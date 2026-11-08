"""Limpiar nombres existentes desde ``python manage.py shell``.

from patients.utils.format_names import format_patient_names
format_patient_names()
format_patient_names(dry_run=False)
"""

from django.db import transaction

from ..models import Patient
from ..names import normalize_patient_name


def format_patient_names(*, dry_run=True):
    """Devuelve el número de pacientes cuyos nombres cambian."""
    changed = 0
    with transaction.atomic():
        patients = Patient.objects.only('first_name', 'last_name', 'clinical_reference').order_by('pk')
        if not dry_run:
            patients = patients.select_for_update()
        for patient in patients.iterator():
            fields = []
            for field in ('first_name', 'last_name'):
                current = getattr(patient, field)
                formatted = normalize_patient_name(current, remove_number_prefix=True)
                if formatted != current:
                    setattr(patient, field, formatted)
                    fields.append(field)
            if fields:
                changed += 1
                if not dry_run:
                    patient.save(update_fields=fields)
    return changed
