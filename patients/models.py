import uuid

from django.db import models

from .choices import PatientSourceChoices


class Patient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    clinical_reference = models.CharField(max_length=100, blank=True, null=True, unique=True)
    patient_source = models.CharField(max_length=20, choices=PatientSourceChoices.choices, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['first_name', 'last_name', 'id']

    def save(self, *args, **kwargs):
        self.clinical_reference = (self.clinical_reference or '').strip() or None
        super().save(*args, **kwargs)

    def __str__(self):
        return str(self.pk)
