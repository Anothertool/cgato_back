import uuid

from django.conf import settings
from django.db import models

from .choices import DeliveryTypeChoices, EyeChoices, LaboratoryChoices, StatusChoices


class LensOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, related_name='lens_orders',
    )
    eye = models.CharField(max_length=5, choices=EyeChoices.choices, blank=True)
    laboratory = models.CharField(max_length=150, choices=LaboratoryChoices.choices, blank=True)
    lens_type = models.CharField(max_length=150, blank=True)
    right_eye_parameters = models.TextField(blank=True)
    left_eye_parameters = models.TextField(blank=True)
    format = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    delivery_type = models.CharField(max_length=20, choices=DeliveryTypeChoices.choices, blank=True)
    appointment_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_lens_orders',
    )

    def __str__(self):
        return f'{self.patient} - {self.lens_type}'
