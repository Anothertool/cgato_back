import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class Surgery(models.Model):
    class Eye(models.TextChoices):
        RIGHT = 'RIGHT', 'Right'
        LEFT = 'LEFT', 'Left'
        BOTH = 'BOTH', 'Both'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PREPARING = 'PREPARING', 'Preparing'
        READY = 'READY', 'Ready'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='surgeries')
    hospital = models.CharField(max_length=255)
    surgery_type = models.CharField(max_length=255)
    eye = models.CharField(max_length=5, choices=Eye.choices)
    scheduled_at = models.DateTimeField(db_index=True)
    insurer = models.CharField(max_length=255, blank=True)
    iol_model = models.CharField(max_length=255, blank=True)
    iol_power = models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)
    anesthesia = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    lens_ordered = models.BooleanField(default=False)
    lens_received = models.BooleanField(default=False)
    lens_verified = models.BooleanField(default=False)
    documentation_ready = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(blank=True, null=True, editable=False)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='+', blank=True, null=True, editable=False,
    )

    class Meta:
        ordering = ['scheduled_at', 'id']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=0) | models.Q(amount__isnull=True), name='surgery_amount_nonnegative'),
            models.CheckConstraint(condition=models.Q(lens_verified=False) | models.Q(lens_received=True), name='surgery_verified_requires_received'),
        ]

    def record_lens_changes(self, previous, user):
        user = user if user.is_authenticated else None
        for field in ('lens_ordered', 'lens_received', 'lens_verified'):
            value = getattr(self, field)
            if value != previous.get(field, False):
                SurgeryLensCheck.objects.create(surgery=self, field=field, value=value, checked_by=user)

    def clean(self):
        super().clean()
        if self.lens_verified and not self.lens_received:
            raise ValidationError({'lens_verified': 'The lens must be received before verification.'})

    def soft_delete(self, user):
        self.deleted_at = timezone.now()
        self.deleted_by = user if user.is_authenticated else None
        self.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])

    def __str__(self):
        return str(self.pk)


class SurgeryLensCheck(models.Model):
    surgery = models.ForeignKey(Surgery, on_delete=models.PROTECT, related_name='lens_checks')
    field = models.CharField(max_length=20, choices=[
        ('lens_ordered', 'Lens ordered'),
        ('lens_received', 'Lens received'),
        ('lens_verified', 'Lens verified'),
    ])
    value = models.BooleanField()
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='+', blank=True, null=True,
    )
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['checked_at', 'id']

    def __str__(self):
        return str(self.pk)
