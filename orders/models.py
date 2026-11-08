import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .choices import (
    DeliveryTypeChoices, EyeChoices, FormatChoices, LaboratoryChoices, LensTypeChoices, StatusChoices,
)


class LensOrder(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, related_name='lens_orders',
    )
    eye = models.CharField(max_length=5, choices=EyeChoices.choices, blank=True)
    laboratory = models.CharField(max_length=150, choices=LaboratoryChoices.choices, blank=True)
    lens_type = models.CharField(max_length=150, choices=LensTypeChoices.choices, blank=True)
    right_eye_parameters = models.TextField(blank=True)
    left_eye_parameters = models.TextField(blank=True)
    format = models.CharField(max_length=100, choices=FormatChoices.choices, blank=True)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    delivery_type = models.CharField(max_length=20, choices=DeliveryTypeChoices.choices, blank=True)
    appointment_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    ordered_at = models.DateTimeField(null=True, blank=True, editable=False)
    received_at = models.DateTimeField(null=True, blank=True, editable=False)
    notified_at = models.DateTimeField(null=True, blank=True, editable=False)
    delivered_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='deleted_lens_orders',
    )

    def save(self, *args, **kwargs):
        timestamp_field = {
            StatusChoices.ORDERED: 'ordered_at',
            StatusChoices.RECEIVED: 'received_at',
            StatusChoices.NOTIFIED: 'notified_at',
            StatusChoices.DELIVERED: 'delivered_at',
        }.get(self.status)
        update_fields = kwargs.get('update_fields')
        if not self._state.adding and timestamp_field and (update_fields is None or 'status' in update_fields):
            previous_status = type(self).objects.using(kwargs.get('using') or self._state.db).filter(
                pk=self.pk,
            ).values_list('status', flat=True).first()
            if previous_status is not None and previous_status != self.status:
                setattr(self, timestamp_field, timezone.now())
                if update_fields is not None:
                    kwargs['update_fields'] = set(update_fields) | {timestamp_field}
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.patient} - {self.lens_type}'
