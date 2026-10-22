"""Importación de movimientos, sin usar proformas ni presupuestos como cobros.

Columnas del Excel histórico: external_id, patient_name, date, amount,
payment_method e invoice_number (opcional). payment_method_original, si está
presente, permite asignar OTHER a los métodos vacíos en origen.
Los métodos vacíos o desconocidos se guardan como OTHER y los importes negativos
se convierten a su valor absoluto. Las fechas vacías o inválidas se omiten.
Las fechas de 2027 se corrigen a 2026 conservando el día y el mes.
Las demás columnas no se importan ni se utilizan para inferir pagos.
"""

from contextlib import nullcontext
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
import unicodedata

from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from patients.models import Patient
from surgeries.models import Surgery
from .choices import PaymentMethodChoices
from .models import CashEntry


REQUIRED_COLUMNS = {'external_id', 'patient_name', 'date', 'amount', 'payment_method'}
USED_COLUMNS = REQUIRED_COLUMNS | {'invoice_number', 'payment_method_original'}
IMPORT_PREFIX = 'cash-excel:'


def _text(value):
    return '' if value is None else str(value).strip()


def _normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^\w\s]', ' ', value).split())


def _patient_name(value):
    """Sin coma: primer término como nombre y resto como apellidos.

    La coincidencia utiliza siempre el nombre completo, independientemente de
    cómo lo haya separado una importación anterior entre los dos campos.
    """
    name = ' '.join(_text(value).split())
    if ',' in name:
        # El formato explícito «apellidos, nombre» permite conservar ambos.
        last_name, first_name = name.split(',', 1)
        return first_name.strip(), last_name.strip()
    parts = name.split(' ', 1)
    return parts[0], parts[1] if len(parts) == 2 else ''


def _date(value, epoch):
    if isinstance(value, bool):
        raise ValueError('Fecha inválida.')
    if isinstance(value, (int, float)):
        value = from_excel(value, epoch=epoch)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
        try:
            return datetime.strptime(_text(value), fmt).date()
        except ValueError:
            continue
    raise ValueError('Fecha vacía o inválida; se requiere YYYY-MM-DD o DD/MM/YYYY.')


def _amount(value):
    text = _text(value)
    if ',' in text:
        if not re.fullmatch(r'-?(?:\d+|\d{1,3}(?:\.\d{3})+),\d{1,2}', text):
            raise ValueError('Formato de importe inválido.')
        text = text.replace('.', '').replace(',', '.')
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError('Importe vacío o inválido.') from exc
    if not amount.is_finite() or amount == 0:
        raise ValueError('El importe debe ser un número finito distinto de cero.')
    return amount.copy_abs()


def _payment_method(row):
    if 'payment_method_original' in row and not _text(row['payment_method_original']):
        return PaymentMethodChoices.OTHER
    value = _normalize(_text(row['payment_method']))
    if not value:
        return PaymentMethodChoices.OTHER
    aliases = {
        _normalize(alias): method
        for method, label in PaymentMethodChoices.choices
        for alias in (method, label)
    }
    aliases.update({
        'metalico': PaymentMethodChoices.CASH,
        'tpv': PaymentMethodChoices.CARD,
    })
    return aliases.get(value, PaymentMethodChoices.OTHER)


def _headers(cells):
    names = [_text(cell.value) for cell in cells]
    duplicates = {name for name in names if name and names.count(name) > 1}
    if duplicates:
        raise ValueError(f'Encabezados duplicados: {", ".join(sorted(duplicates))}.')
    missing = REQUIRED_COLUMNS - set(names)
    if missing:
        raise ValueError(f'Faltan columnas: {", ".join(sorted(missing))}.')
    return {index: name for index, name in enumerate(names) if name in USED_COLUMNS}


def import_cash(path, *, dry_run=False, report=None):
    """Devuelve contadores y errores por fila; dry_run revierte la simulación.

    Cada fila se valida y guarda dentro de su propia transacción. Una referencia
    de origen identifica el movimiento, independientemente de nombre de archivo,
    orden, paciente, fecha e importe. Nunca se actualizan movimientos existentes.
    """
    summary = dict.fromkeys((
        'cash_created', 'patients_created', 'with_surgery', 'without_surgery',
        'duplicates', 'errors',
    ), 0)
    summary['issues'] = []
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError('El archivo debe contener una única hoja de cobros.')
        rows = enumerate(workbook.active.iter_rows(), start=1)
        for _, cells in rows:
            if any(_text(cell.value) for cell in cells):
                columns = _headers(cells)
                break
        else:
            raise ValueError('La hoja está vacía.')

        patients = {}
        for patient in Patient.objects.all().only('id', 'first_name', 'last_name'):
            name = _patient_name(f'{patient.first_name} {patient.last_name}')
            key = _normalize(' '.join(name))
            patients.setdefault(key, []).append(patient)

        # Una transacción exterior solo en simulación permite reproducir también
        # duplicados, pacientes y totales acumulados entre filas antes del rollback.
        with transaction.atomic() if dry_run else nullcontext():
            for row_number, cells in rows:
                if not any(_text(cell.value) for cell in cells):
                    continue
                reference = None
                try:
                    with transaction.atomic():
                        row = {name: cells[index].value if index < len(cells) else None
                               for index, name in columns.items()}
                        source_id = _text(row['external_id'])
                        if not source_id:
                            raise ValueError('external_id vacío; no se puede garantizar la idempotencia.')
                        reference = f'{IMPORT_PREFIX}{source_id}'
                        CashEntry._meta.get_field('import_reference').clean(reference, None)
                        if CashEntry.objects.filter(import_reference=reference).exists():
                            summary['duplicates'] += 1
                            continue
                        if any(index < len(cells) and cells[index].data_type in ('f', 'e')
                               for index in columns):
                            raise ValueError('Las columnas utilizadas contienen una fórmula o un error de Excel; sustituir por valores.')

                        payment_date = _date(row['date'], workbook.epoch)
                        if payment_date.year == 2027:
                            payment_date = payment_date.replace(year=2026)
                        amount = _amount(row['amount'])
                        method = _payment_method(row)
                        first_name, last_name = _patient_name(row['patient_name'])
                        key = _normalize(f'{first_name} {last_name}')
                        if not key or not first_name:
                            raise ValueError('Nombre de paciente vacío o inválido.')
                        matches = patients.get(key, [])
                        if len(matches) > 1:
                            raise ValueError('Varios pacientes coinciden con el nombre normalizado; requiere revisión.')
                        created_patient = not matches
                        if created_patient:
                            patient = Patient(first_name=first_name, last_name=last_name)
                            patient.full_clean()
                            patient.save()
                        else:
                            patient = matches[0]

                        surgeries = list(Surgery.objects.select_for_update().filter(
                            patient=patient, deleted_at__isnull=True,
                        )[:2])
                        # El archivo solo aporta fecha de cobro, sin identificador
                        # ni fecha de cirugía fiables. Con varias no hay evidencia
                        # suficiente para asociar una, ni siquiera por cercanía.
                        surgery = surgeries[0] if len(surgeries) == 1 else None
                        entry = CashEntry(
                            patient=None if surgery else patient,
                            surgery=surgery,
                            date=payment_date,
                            amount=amount,
                            payment_method=method,
                            invoice_number=_text(row.get('invoice_number')),
                            import_reference=reference,
                        )
                        entry.full_clean()
                        entry.save()
                    # Incorporar al índice solo tras el éxito de la fila completa.
                    if created_patient:
                        patients.setdefault(key, []).append(patient)
                        summary['patients_created'] += 1
                    summary['cash_created'] += 1
                    summary['with_surgery' if surgery else 'without_surgery'] += 1
                except (ValueError, ValidationError, IntegrityError, DataError, OverflowError) as exc:
                    # La restricción única también protege ejecuciones concurrentes.
                    if isinstance(exc, (IntegrityError, ValidationError)) and reference and CashEntry.objects.filter(import_reference=reference).exists():
                        summary['duplicates'] += 1
                        continue
                    summary['errors'] += 1
                    message = f'Fila {row_number}: {exc}'
                    summary['issues'].append(message)
                    if report is not None:
                        report(message)
            if dry_run:
                transaction.set_rollback(True)
    finally:
        workbook.close()
    return summary
