import csv
import re
import unicodedata
import uuid
from collections import defaultdict
from contextlib import nullcontext
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from patients.models import Patient
from .choices import (
    DeliveryTypeChoices, EyeChoices, FormatChoices, LaboratoryChoices, LensTypeChoices, StatusChoices,
)
from .models import LensOrder


"""
from orders.utils import import_lens_orders

preview = import_lens_orders(dry_run=True)
print(preview["created"])
print(*preview["errors"], sep="\n")
print(*preview["warnings"], sep="\n")

# Tras revisar la simulación
result = import_lens_orders()
"""


DEFAULT_CSV = Path(__file__).with_name('pedidosLC.csv')
REQUIRED_COLUMNS = {'Card ID', 'Card Name', 'Card Description', 'Labels', 'List Name'}
STATUSES = {
    'pendientes': StatusChoices.PENDING,
    'pedidas': StatusChoices.ORDERED,
    'recibidas': StatusChoices.RECEIVED,
    'avisados': StatusChoices.NOTIFIED,
    'citados': StatusChoices.NOTIFIED,
    'avisados citados': StatusChoices.NOTIFIED,
    'entregadas': StatusChoices.DELIVERED,
    'enviadas entregadas': StatusChoices.DELIVERED,
}
DESCRIPTION_FIELD = re.compile(
    r'^\s*\*{0,2}\s*(c[oó]digo paciente|ojo|laboratorio|tipo de lente|'
    r'par[aá]metros\s+o[di]|formato|formao)\s*'
    r'(?:\*{1,2}\s*:?|:\s*\*{0,2})\s*(.*?)\s*\*{0,2}\s*$',
    re.IGNORECASE,
)
LABORATORIES = {
    'tiedra': LaboratoryChoices.TIEDRA,
    'menicon': LaboratoryChoices.MENICOM,
    'markenovi': LaboratoryChoices.MARKENOVI,
    'markennovy': LaboratoryChoices.MARKENOVI,
    'marknnovy': LaboratoryChoices.MARKENOVI,
}
DELIVERY_TYPES = {
    'citar': DeliveryTypeChoices.APPOINTMENT,
    'recoger': DeliveryTypeChoices.PICKUP,
}
ORTHO_K = r'\b(?:otk|orto\s*k|ortho\s*k|z night|z junior|bloom night)\b'
RGP = r'\b(?:rpg|rgp|rose k2?)\b'
SOFT = r'\b(?:blandas?|soft|clear|lear|claear|ckear|xtensa|mylo|maylo|one day|flat pack|diarias?|mensual)\b'
TEMPLATE_FORMATS = {'otk lc o blister', 'otk blister o cajas', 'caja blister', 'o blister'}
FORMATS = {FormatChoices.BOX: r'\bcajas?\b', FormatChoices.BLISTER: r'\bblisters?\b'}
STOCK_TITLES = {'lentillas', 'pedir menicare bloom y progent', 'bloom progent', 'pedir spray clean lc otk'}
PATIENT_ALIASES = {
    'alejandro frenandez adreu': 'Alejandro Fernandez Andreu',
    'cement lamarque': 'Clement Lamarque',
    'elena de prado bid': 'Elena de Prado Dib',
    'javier garcia monterubio': 'Javier Garcia Monterrubio',
    'rafael cosio fdez': 'Rafael Cosio Fernandez',
}
NON_FORMAT_VALUES = {'lc', 'lente', 'lentes', 'cambio de lente', 'lente definitiva'}


def _normalize(value):
    value = unicodedata.normalize('NFKD', value.casefold())
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


def _patient_key(name):
    return _normalize(PATIENT_ALIASES.get(_normalize(name), name))


def _description_fields(description):
    fields = {}
    current = None
    for line in description.splitlines():
        match = DESCRIPTION_FIELD.match(line)
        if match:
            current = _normalize(match[1])
            if current == 'formao':
                current = 'formato'
            fields[current] = [match[2].strip()]
        elif line.lstrip().startswith('**'):
            current = None
        elif current in ('parametros od', 'parametros oi') and line.strip():
            fields[current].append(line.strip())
    return {key: '\n'.join(lines).strip() for key, lines in fields.items()}


def _order_fields(row, warnings):
    fields = _description_fields(row['Card Description'])
    labels = {_normalize(label.split('(', 1)[0]) for label in row['Labels'].split(',')}
    status = STATUSES.get(_normalize(row['List Name']))
    if status is None:
        raise ValueError(f'Lista de Trello desconocida: {row["List Name"]}.')

    eyes = set(_normalize(fields.get('ojo', '')).split()) or labels
    if not eyes & {'od', 'oi', 'i', 'ao', 'odi', 'ambos'}:
        suffix = _normalize(row.get('Card Name', '')).split()[-1:]
        eyes.update(token for token in suffix if token in {'od', 'oi'})
    right = 'od' in eyes
    left = bool(eyes & {'oi', 'i'})
    eye = ''
    if (right and left) or eyes & {'ao', 'odi', 'ambos'}:
        eye = EyeChoices.BOTH
    elif right:
        eye = EyeChoices.RIGHT
    elif left:
        eye = EyeChoices.LEFT
    elif fields.get('ojo'):
        warnings.append('Ojo sin identificar.')

    lab_text = _normalize(fields.get('laboratorio', ''))
    lab_matches = {LABORATORIES[token] for token in lab_text.split() if token in LABORATORIES}
    lab_labels = {LABORATORIES[label] for label in labels if label in LABORATORIES}
    laboratory = _single_choice(
        lab_matches if len(lab_matches) == 1 else (lab_labels & lab_matches or lab_labels or lab_matches),
        'Laboratorio', warnings, has_value=bool(lab_text),
    )
    delivery_type = _single_choice(
        {DELIVERY_TYPES[label] for label in labels if label in DELIVERY_TYPES},
        'Entrega', warnings,
    )

    raw_type = _normalize(fields.get('tipo de lente', ''))
    raw_format = _normalize(fields.get('formato', ''))
    if raw_format in TEMPLATE_FORMATS:
        warnings.append('Formato de plantilla; se deja vacío salvo que figure en el tipo de lente.')
        raw_format = ''
    if raw_format in NON_FORMAT_VALUES:
        raw_format = ''
    lens_type = ''
    if re.search(ORTHO_K, f'{raw_type} {raw_format}') or 'otk' in labels:
        lens_type = LensTypeChoices.ORTHO_K
    elif re.search(RGP, raw_type) or labels & {'rpg', 'rgp', 'rose k'}:
        lens_type = LensTypeChoices.RGP
    elif re.search(SOFT, raw_type) or 'mylo' in labels:
        lens_type = LensTypeChoices.SOFT
    elif raw_type and raw_type != 'urgente' and not any(re.fullmatch(pattern, raw_type) for pattern in FORMATS.values()):
        warnings.append('Tipo de lente sin identificar.')

    formats = {value for value, pattern in FORMATS.items() if re.search(pattern, raw_format)}
    formats = formats or {value for value, pattern in FORMATS.items() if re.search(pattern, raw_type)}
    lens_format = _single_choice(
        formats, 'Formato', warnings, has_value=bool(raw_format and not re.search(ORTHO_K, raw_format)),
    )
    return {
        'status': status,
        'eye': eye,
        'laboratory': laboratory,
        'delivery_type': delivery_type,
        'lens_type': lens_type,
        'format': lens_format,
        'right_eye_parameters': fields.get('parametros od', ''),
        'left_eye_parameters': fields.get('parametros oi', ''),
    }


def _single_choice(matches, field, warnings, *, has_value=False):
    if len(matches) == 1:
        return next(iter(matches))
    if matches or has_value:
        warnings.append(f'{field} ambiguo o sin identificar.')
    return ''


def import_lens_orders(path=DEFAULT_CSV, *, dry_run=False):
    """Importa tarjetas y pacientes faltantes. La simulación revierte todos los cambios."""
    summary = {
        'created': 0, 'patients_created': 0, 'new_patients': [],
        'duplicates': 0, 'skipped': [], 'errors': [], 'warnings': [],
    }
    with open(path, encoding='utf-8-sig', newline='') as source, transaction.atomic() if dry_run else nullcontext():
        reader = csv.DictReader(source, strict=True)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f'Faltan columnas: {", ".join(sorted(missing))}.')

        patients = defaultdict(list)
        for patient_id, first_name, last_name in Patient.objects.values_list('id', 'first_name', 'last_name'):
            patients[_patient_key(f'{first_name} {last_name}')].append(patient_id)

        seen = set()
        for index, row in enumerate(reader, start=1):
            card_id = (row['Card ID'] or '').strip()
            card_name = (row['Card Name'] or '').strip()
            reference = f'Tarjeta {index} ({card_id or "sin ID"}, {card_name})'
            warnings = []
            try:
                if not card_id or any(row[column] is None for column in REQUIRED_COLUMNS):
                    raise ValueError('Tarjeta incompleta.')
                name_key = _normalize(card_name)
                if name_key in STOCK_TITLES:
                    summary['skipped'].append(f'{reference}: Tarjeta sin nombre de paciente.')
                    continue
                # El UUID estable usa la clave primaria para impedir duplicados incluso en paralelo.
                order_id = uuid.uuid5(uuid.NAMESPACE_URL, f'https://trello.com/card/{card_id}')
                if order_id in seen or LensOrder.objects.filter(pk=order_id).exists():
                    summary['duplicates'] += 1
                    continue
                patient_name = re.sub(r'\s+o[di]$', '', card_name, flags=re.IGNORECASE)
                patient_key = _patient_key(patient_name)
                matches = patients[patient_key]
                if len(matches) > 1:
                    raise ValueError('Varios pacientes con ese nombre.')
                values = _order_fields(row, warnings)
                patient_created = False
                with transaction.atomic():
                    if matches:
                        patient_id = matches[0]
                    else:
                        parts = patient_key.split()
                        if len(parts) < 2 or len(parts[-1]) == 1:
                            raise ValueError('Nombre incompleto; indica el nombre completo en el CSV.')
                        display_name = PATIENT_ALIASES.get(_normalize(patient_name), patient_name)
                        first_name, last_name = ' '.join(display_name.split()).split(' ', 1)
                        patient_id = uuid.uuid5(uuid.NAMESPACE_URL, f'urn:cgato:trello-lc:patient:{patient_key}')
                        patient = Patient(id=patient_id, first_name=first_name, last_name=last_name)
                        patient.full_clean(validate_unique=False)
                        _, patient_created = Patient.objects.get_or_create(
                            id=patient_id, defaults={'first_name': first_name, 'last_name': last_name},
                        )
                    values['patient_id'] = patient_id
                    LensOrder(id=order_id, **values).full_clean(validate_unique=False)
                    _, created = LensOrder.objects.get_or_create(id=order_id, defaults=values)
                    if patient_created and not created:
                        transaction.set_rollback(True)
                if created and not matches:
                    matches.append(patient_id)
                    if patient_created:
                        summary['patients_created'] += 1
                        summary['new_patients'].append({'first_name': first_name, 'last_name': last_name})
                seen.add(order_id)
                summary['created' if created else 'duplicates'] += 1
                summary['warnings'].extend(f'{reference}: {warning}' for warning in warnings)
            except (ValueError, ValidationError) as exc:
                summary['errors'].append(f'{reference}: {exc}')
        if dry_run:
            transaction.set_rollback(True)
    return summary
