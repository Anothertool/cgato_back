"""Importar el Excel preparado desde ``python manage.py shell``.

    from utils.import_surgeries import import_surgeries
    import_surgeries(dry_run=True)
    import_surgeries()

Para el segundo archivo preparado:

    from utils.import_surgeries import import_surgeries_excell
    import_surgeries_excell(dry_run=True)
    import_surgeries_excell()

No requiere librerías de Excel. Importa únicamente la hoja Importacion:
Revisar es un subconjunto de ella, no contiene cirugías adicionales.
Los nombres completos se guardan en first_name, sin adivinar apellidos.
Los pacientes se agrupan por patient_key y se reutilizan por nombre normalizado.
Los IDs de Trello producen UUID estables para evitar reimportar cirugías.
Las fechas numéricas de Excel se interpretan en UTC (fechas Due Date de Trello).
Se puede pasar source_timezone='Europe/Madrid' si se han convertido a hora local.
Las cirugías con fecha pasada se completan usando scheduled_at como completed_at.
También se aplica al repetir una importación, sin duplicar pacientes ni cirugías.
Se respetan las cirugías canceladas, eliminadas, perdidas o ya completadas.
Sin fecha programada, historical_completed se conserva únicamente en notes.
La importación completa es atómica. Los demás datos ya importados se conservan.
Columnas opcionales: patient_source, operating_room_cost y first_consultation_at.
Si faltan, quedan vacías. patient_source nunca se deduce de insurer.
first_consultation_at admite fechas ISO (YYYY-MM-DD) o números de fecha Excel.
En pacientes existentes solo se completa patient_source si aún no está informado;
una procedencia contradictoria detiene y revierte la importación.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import posixpath
import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from patients.models import Patient
from patients.choices import PatientSourceChoices
from surgeries.choices import BudgetStatusChoices, InsurerChoices
from surgeries.models import Surgery


NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
DEFAULT_PATH = Path(settings.BASE_DIR) / 'utils' / 'CGato_importacion_preparada.xlsx'
EXCELL_PATH = Path(settings.BASE_DIR) / 'utils' / 'CGato_importacion_preparada_excell.xlsx'
SURGERY_FIELDS = ('surgery_type', 'eye', 'insurer', 'iol_model', 'budget_status', 'anesthesia')
REQUIRED_COLUMNS = {
    'trello_id', 'patient_name', 'patient_key', 'scheduled_at_original',
    'iol_power', 'amount', 'historical_completed', *SURGERY_FIELDS,
    'notes', 'review_reasons', 'trello_url', 'trello_list',
    'surgery_original', 'lio_original', 'amount_original', 'description_original',
}


def _normalize(value):
    value = unicodedata.normalize('NFKD', value.upper())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', re.sub(r'[^A-Z0-9\s]', ' ', value)).strip()


def _read_rows(path):
    """Leer valores por cabecera, incluyendo cadenas compartidas y celdas vacías."""
    with ZipFile(path) as archive:
        def xml(name):
            return ElementTree.fromstring(archive.read(name))

        def text(element):
            return ''.join(node.text or '' for node in element.findall('.//s:t', NS))

        strings = [text(item) for item in xml('xl/sharedStrings.xml')] if 'xl/sharedStrings.xml' in archive.namelist() else []
        workbook = xml('xl/workbook.xml')
        properties = workbook.find('s:workbookPr', NS)
        epoch = datetime(1904, 1, 1) if properties is not None and properties.get('date1904') in ('1', 'true') else datetime(1899, 12, 30)
        sheet = next((item for item in workbook.findall('s:sheets/s:sheet', NS) if item.get('name') == 'Importacion'), None)
        if sheet is None:
            raise ValueError('No existe la hoja Importacion.')
        relation_id = sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        target = next(item.get('Target') for item in xml('xl/_rels/workbook.xml.rels') if item.get('Id') == relation_id)
        sheet_path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))
        headers = None
        rows = []
        for row in xml(sheet_path).findall('s:sheetData/s:row', NS):
            cells = {}
            for cell in row.findall('s:c', NS):
                if cell.find('s:f', NS) is not None:
                    raise ValueError(f'Celda {cell.get("r")}: sustituye la fórmula por su valor antes de importar.')
                value = cell.find('s:v', NS)
                value = value.text or '' if value is not None else text(cell)
                if cell.get('t') == 's':
                    value = strings[int(value)]
                if cell.get('t') == 'e':
                    raise ValueError(f'Celda {cell.get("r")}: error de Excel {value}.')
                cells[re.sub(r'\d', '', cell.get('r'))] = value.strip()
            if not any(cells.values()):
                continue
            if headers is None:
                headers = cells
                missing = REQUIRED_COLUMNS - set(headers.values())
                if missing:
                    raise ValueError(f'Faltan columnas: {", ".join(sorted(missing))}.')
                continue
            rows.append((int(row.get('r')), {header: cells.get(column, '') for column, header in headers.items()}))
        if headers is None:
            raise ValueError('La hoja Importacion está vacía.')
        return rows, epoch


def _scheduled_at(value, epoch, source_timezone):
    if not value:
        return None
    try:
        date = epoch + timedelta(days=float(Decimal(value)))
        date = date + timedelta(microseconds=500000)
        date = date.replace(microsecond=0)
    except ArithmeticError:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if timezone.is_naive(date):
        date = timezone.make_aware(date, source_timezone)
    return date


def _surgery_data(row, epoch, source_timezone):
    historical = row['historical_completed'].upper()
    if historical not in ('', 'YES'):
        raise ValueError('historical_completed debe estar vacío o ser YES.')
    data = {field: row[field] for field in SURGERY_FIELDS}
    for field in ('iol_power', 'amount', 'operating_room_cost'):
        value = row.get(field, '')
        data[field] = Decimal(value.replace(',', '.')) if value else None
    first_consultation = row.get('first_consultation_at', '')
    data['first_consultation_at'] = (
        _scheduled_at(first_consultation, epoch, source_timezone).date()
        if first_consultation else None
    )
    data['scheduled_at'] = _scheduled_at(row['scheduled_at_original'], epoch, source_timezone)
    notes = [row['notes']] if row['notes'] else []
    insurer_mapping = {
        _normalize(alias): value
        for value, label in InsurerChoices.choices
        for alias in (value, label)
    }
    if data['insurer']:
        original = data['insurer']
        data['insurer'] = insurer_mapping.get(_normalize(original), InsurerChoices.OTHER)
        if original != data['insurer']:
            notes.append(f'Aseguradora original: {original}')
    for field, label in (
        ('trello_id', 'Trello ID'), ('trello_url', 'Trello URL'),
        ('trello_list', 'Lista Trello'), ('patient_key', 'Clave de paciente'),
        ('surgery_original', 'Cirugía original'), ('lio_original', 'LIO original'),
        ('amount_original', 'Importe original (no implica cobro)'),
        ('scheduled_at_original', 'Due Date original'), ('review_reasons', 'Pendiente de revisión'),
        ('description_original', 'Descripción original'),
    ):
        if row[field]:
            notes.append(f'{label}: {row[field]}')
    if historical == 'YES':
        notes.append('historical_completed=YES: cirugía hecha según origen; fecha de realización desconocida. completed_at queda vacío.')
    data['notes'] = '\n\n'.join(notes)
    return data


def _complete_past_surgery(surgery, imported_at):
    if (
        surgery.completed_at is not None
        or surgery.cancelled_at is not None
        or surgery.deleted_at is not None
        or surgery.budget_status == BudgetStatusChoices.LOST
        or surgery.scheduled_at is None
        or surgery.scheduled_at > imported_at
    ):
        return False
    surgery.completed_at = surgery.scheduled_at
    surgery.notes = surgery.notes.replace(
        'historical_completed=YES: cirugía hecha según origen; fecha de realización desconocida. completed_at queda vacío.',
        'historical_completed=YES: cirugía hecha según origen.',
    )
    surgery.notes = '\n\n'.join(filter(None, [
        surgery.notes,
        'Importación: completed_at se toma de scheduled_at por ser una fecha pasada.',
    ]))
    return True


def import_surgeries(path=DEFAULT_PATH, *, dry_run=False, source_timezone='UTC'):
    """Crear pacientes/cirugías y devolver contadores; dry_run revierte todo."""
    rows, epoch = _read_rows(Path(path))
    source_timezone = ZoneInfo(source_timezone)
    imported_at = timezone.now()
    counts = dict(rows=len(rows), patients_created=0, patients_reused=0,
                  patients_source_updated=0,
                  surgeries_created=0, surgeries_skipped=0, review_rows=0,
                  surgeries_updated=0, surgeries_completed=0,
                  historical_without_completion_date=0)
    with transaction.atomic():
        patients_by_name = {}
        patients_by_id = {}
        for patient in Patient.objects.all():
            patients_by_id[patient.pk] = patient
            key = _normalize(f'{patient.first_name} {patient.last_name}')
            patients_by_name.setdefault(key, []).append(patient)
        patients_by_key = {}
        seen_ids = set()
        for number, row in rows:
            try:
                trello_id = row['trello_id']
                if not trello_id or not row['patient_name'] or not row['patient_key']:
                    raise ValueError('trello_id, patient_name y patient_key son obligatorios.')
                if trello_id in seen_ids:
                    raise ValueError('trello_id repetido en el Excel.')
                seen_ids.add(trello_id)
                surgery_id = uuid5(NAMESPACE_URL, f'cgato:trello:surgery:{trello_id}')
                existing = Surgery.objects.select_for_update().filter(pk=surgery_id).first()
                if existing is not None:
                    if _complete_past_surgery(existing, imported_at):
                        existing.full_clean()
                        existing.save(update_fields=['completed_at', 'notes', 'updated_at'])
                        counts['surgeries_updated'] += 1
                        counts['surgeries_completed'] += 1
                    else:
                        counts['surgeries_skipped'] += 1
                    continue
                data = _surgery_data(row, epoch, source_timezone)
                patient_source = row.get('patient_source', '') or None
                if patient_source is not None and patient_source not in PatientSourceChoices.values:
                    raise ValueError(f'patient_source no válido: {patient_source}.')
                key = row['patient_key']
                patient = patients_by_key.get(key)
                if patient is None:
                    patient_id = uuid5(NAMESPACE_URL, f'cgato:trello:patient:{key}')
                    imported_patient = patients_by_id.get(patient_id)
                    matches = [imported_patient] if imported_patient else patients_by_name.get(_normalize(key), [])
                    if len(matches) > 1:
                        raise ValueError('Varios pacientes existentes coinciden con patient_key; resuelve la ambigüedad antes de importar.')
                    if matches:
                        patient = matches[0]
                        counts['patients_reused'] += 1
                    else:
                        patient = Patient(
                            id=patient_id,
                            first_name=row['patient_name'],
                            patient_source=patient_source,
                        )
                        patient.full_clean()
                        patient.save(force_insert=True)
                        patients_by_name.setdefault(_normalize(key), []).append(patient)
                        counts['patients_created'] += 1
                    patients_by_key[key] = patient
                if patient_source:
                    if patient.patient_source and patient.patient_source != patient_source:
                        raise ValueError('patient_source contradice la procedencia ya registrada para el paciente.')
                    if not patient.patient_source:
                        patient.patient_source = patient_source
                        patient.full_clean()
                        patient.save(update_fields=['patient_source', 'updated_at'])
                        counts['patients_source_updated'] += 1
                surgery = Surgery(id=surgery_id, patient=patient, **data)
                completed = _complete_past_surgery(surgery, imported_at)
                surgery.full_clean()
                surgery.save(force_insert=True)
                counts['surgeries_created'] += 1
                counts['surgeries_completed'] += completed
                counts['review_rows'] += bool(row['review_reasons'])
                counts['historical_without_completion_date'] += (
                    row['historical_completed'].upper() == 'YES' and surgery.completed_at is None
                )
            except (ValueError, ArithmeticError, ValidationError, IntegrityError) as exc:
                raise ValueError(f'Importacion, fila {number} (Trello {row["trello_id"]}): {exc}') from exc
        if dry_run:
            transaction.set_rollback(True)
    print('SIMULACIÓN (sin guardar)' if dry_run else 'IMPORTACIÓN COMPLETADA')
    for key, value in counts.items():
        print(f'{key}: {value}')
    return counts


def import_surgeries_excell(path=EXCELL_PATH, *, dry_run=False, source_timezone='UTC'):
    """Importar el segundo Excel con las mismas claves estables del anterior."""
    return import_surgeries(path, dry_run=dry_run, source_timezone=source_timezone)
