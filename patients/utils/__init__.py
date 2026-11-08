"""Importar un año de pacientes desde ``python manage.py shell``.

    from patients.utils import import_patients
    import_patients(dry_run=True)
    import_patients()

Para simular todos los archivos anuales de patients/dataset:

from patients.utils import import_all_patients
import_all_patients(dry_run=True)

import_patients lee por defecto patients/dataset/2026.xlsx.
Nº Poliza se utiliza como clinical_reference; N.Orden no se importa.
Se prefiere Móvil a Teléfono y se conserva su texto, incluidos prefijos.
Procedencia se traduce a PatientSourceChoices; un vacío permanece como None.
Compañía, Sexo y E-Mail no tienen campo en Patient y no se importan.
La fecha de alta se conserva en created_at para pacientes nuevos, a medianoche
en Europe/Madrid. En pacientes existentes solo se completan campos vacíos;
no se cambia su fecha ni se sobrescriben datos ya informados.
Los nombres existentes se conservan, incluso si el nombre completo está
guardado en first_name por una importación anterior.
Se reutiliza por referencia o por nombre completo único entre pacientes de BD
sin referencia. Dos referencias distintas identifican pacientes distintos,
aunque sus nombres normalizados coincidan.
Las diferencias de procedencia se contabilizan sin sobrescribir el dato de BD.
Las filas inválidas o con identidad ambigua se omiten y se incluyen en issues.
dry_run ejecuta la misma importación y revierte todos sus cambios.
"""

from copy import copy
from datetime import date, datetime, time
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DataError, IntegrityError, transaction
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel

from ..choices import PatientSourceChoices
from ..models import Patient


DEFAULT_PATH = Path(settings.BASE_DIR) / 'patients' / 'dataset' / '2026.xlsx'
REQUIRED_COLUMNS = {
    'no poliza', 'nombre', 'apellidos', 'fecha de alta',
    'procedencia', 'telefono', 'movil',
}
SOURCE_MAP = {
    'referido': PatientSourceChoices.REFERRAL,
    'cuadro medico': PatientSourceChoices.INSURER,
    'google': PatientSourceChoices.WEB,
    'pagina web': PatientSourceChoices.WEB,
    'rr ss': PatientSourceChoices.SOCIAL_MEDIA,
}


def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize(value):
    value = unicodedata.normalize('NFKD', _text(value).casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^\w\s]', ' ', value).split())


def _registration_date(value, epoch, year):
    if isinstance(value, bool):
        raise ValueError('Fecha de alta inválida.')
    if isinstance(value, (int, float)):
        value = from_excel(value, epoch=epoch)
    if isinstance(value, str):
        value = datetime.strptime(value.strip(), '%d-%m-%Y')
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date) or value.year != year:
        raise ValueError(f'La fecha de alta debe pertenecer a {year}.')
    return timezone.make_aware(datetime.combine(value, time.min), ZoneInfo('Europe/Madrid'))


def import_patients(path=DEFAULT_PATH, *, dry_run=False, year=2026, verbose=True):
    """Importar un año omitiendo filas inválidas y devolviendo sus motivos en issues."""
    counts = dict(rows=0, patients_created=0, patients_updated=0, patients_skipped=0,
                  source_conflicts=0, patients_invalid=0)
    counts['issues'] = []
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError('El archivo debe contener una única hoja de pacientes.')
        sheet = workbook.active
        rows = sheet.iter_rows()
        headers = [_normalize(cell.value) for cell in next(rows, ())]
        if len(headers) != len(set(headers)):
            raise ValueError('Hay cabeceras duplicadas en el Excel.')
        missing = REQUIRED_COLUMNS - set(headers)
        if missing:
            raise ValueError(f'Faltan columnas: {", ".join(sorted(missing))}.')
        columns = {name: headers.index(name) for name in REQUIRED_COLUMNS}

        with transaction.atomic():
            by_reference = {}
            by_name = {}
            for patient in Patient.objects.select_for_update().all():
                if patient.clinical_reference:
                    by_reference[patient.clinical_reference] = patient
                key = _normalize(f'{patient.first_name} {patient.last_name}')
                by_name.setdefault(key, []).append(patient)
            seen_references = set()

            for number, cells in enumerate(rows, start=2):
                if not any(_text(cell.value) for cell in cells):
                    continue
                counts['rows'] += 1
                try:
                    with transaction.atomic():
                        if any(cells[index].data_type in ('f', 'e') for index in columns.values()):
                            raise ValueError('Las columnas utilizadas deben contener valores, no fórmulas ni errores.')
                        row = {name: cells[index].value for name, index in columns.items()}
                        reference = _text(row['no poliza'])
                        first_name = ' '.join(_text(row['nombre']).split())
                        last_name = ' '.join(_text(row['apellidos']).split())
                        if not reference or not first_name:
                            raise ValueError('Nº Poliza y Nombre son obligatorios.')
                        if reference in seen_references:
                            raise ValueError('Nº Poliza repetido en el Excel.')
                        registered_at = _registration_date(row['fecha de alta'], workbook.epoch, year)
                        source = _normalize(row['procedencia'])
                        if source and source not in SOURCE_MAP:
                            raise ValueError(f'Procedencia desconocida: {_text(row["procedencia"])}.')
                        data = {
                            'first_name': first_name,
                            'last_name': last_name,
                            'clinical_reference': reference,
                            'phone': _text(row['movil']) or _text(row['telefono']),
                            'patient_source': SOURCE_MAP.get(source),
                        }
                        # Validar también campos que no se sobrescribirán en BD.
                        candidate = Patient(**data)
                        candidate.clean_fields()
                        key = _normalize(f'{first_name} {last_name}')
                        patient = by_reference.get(reference)
                        if patient is not None:
                            if _normalize(f'{patient.first_name} {patient.last_name}') != key:
                                raise ValueError('La referencia existente pertenece a un nombre diferente.')
                        else:
                            matches = [match for match in by_name.get(key, [])
                                       if not match.clinical_reference]
                            if len(matches) > 1:
                                raise ValueError('Varios pacientes coinciden por nombre; requiere revisión.')
                            patient = matches[0] if matches else None

                        # Una copia evita alterar los índices si la fila se revierte.
                        patient = copy(patient) if patient is not None else None
                        source_conflict = False
                        if patient is None:
                            patient = candidate
                            patient.full_clean()
                            patient.save(force_insert=True)
                            # auto_now_add sustituye el valor durante save().
                            Patient.objects.filter(pk=patient.pk).update(created_at=registered_at)
                            patient.created_at = registered_at
                            outcome = 'patients_created'
                        else:
                            if data['patient_source'] and patient.patient_source and data['patient_source'] != patient.patient_source:
                                source_conflict = True
                            changed = []
                            for field in ('clinical_reference', 'phone', 'patient_source'):
                                value = data[field]
                                if value and not getattr(patient, field):
                                    setattr(patient, field, value)
                                    changed.append(field)
                            if changed:
                                patient.full_clean()
                                patient.save(update_fields=[*changed, 'updated_at'])
                                outcome = 'patients_updated'
                            else:
                                outcome = 'patients_skipped'
                    # Actualizar índices y contadores solo tras guardar la fila.
                    by_reference[reference] = patient
                    by_name[key] = [match for match in by_name.get(key, [])
                                    if match.pk != patient.pk] + [patient]
                    seen_references.add(reference)
                    counts[outcome] += 1
                    counts['source_conflicts'] += source_conflict
                except (ValueError, ValidationError, IntegrityError, DataError, OverflowError) as exc:
                    counts['patients_invalid'] += 1
                    message = f'{Path(path).name}, {sheet.title}, fila {number}: {exc}'
                    counts['issues'].append(message)
                    print(f'FILA OMITIDA: {message}')

            if dry_run:
                transaction.set_rollback(True)
    finally:
        workbook.close()

    if verbose:
        print('SIMULACIÓN (sin guardar)' if dry_run else 'IMPORTACIÓN COMPLETADA')
        for key, value in counts.items():
            if key != 'issues':
                print(f'{key}: {value}')
    return counts


def import_all_patients(directory=DEFAULT_PATH.parent, *, dry_run=True):
    """Importar YYYY.xlsx en orden de año, dentro de una única transacción.

    La simulación conserva los cambios entre años para detectar coincidencias
    entre archivos y revierte todo al terminar. Las filas inválidas se omiten;
    un error en la estructura de un archivo revierte todos los años.
    Devuelve los contadores por año y el total. Por defecto no guarda cambios.
    """
    paths = sorted(path for path in Path(directory).glob('*.xlsx')
                   if re.fullmatch(r'\d{4}', path.stem))
    if not paths:
        raise ValueError(f'No hay archivos YYYY.xlsx en {directory}.')
    by_year = {}
    totals = {}
    print('SIMULACIÓN DE TODOS LOS AÑOS (sin guardar)' if dry_run
          else 'IMPORTACIÓN DE TODOS LOS AÑOS')
    with transaction.atomic():
        for path in paths:
            try:
                counts = import_patients(path, year=int(path.stem), verbose=False)
            except ValueError as exc:
                raise ValueError(f'{path.name}: {exc}') from exc
            by_year[path.stem] = counts
            for key, value in counts.items():
                if key != 'issues':
                    totals[key] = totals.get(key, 0) + value
            print(f'{path.name}: { {key: value for key, value in counts.items() if key != "issues"} }')
        if dry_run:
            transaction.set_rollback(True)
    print('SIMULACIÓN COMPLETADA (sin guardar)' if dry_run else 'IMPORTACIÓN COMPLETADA')
    print(f'TOTAL: {totals}')
    return {'years': by_year, 'total': totals}
