import uuid
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from .choices import (
    BudgetStatusChoices, EyeChoices, InsurerChoices, IOLModelChoices,
    LensCheckFieldChoices, SurgeryTypeChoices,
)


class Surgery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='surgeries')
    surgery_type = models.CharField(max_length=255, choices=SurgeryTypeChoices.choices, blank=True)
    eye = models.CharField(max_length=5, choices=EyeChoices.choices, blank=True)
    scheduled_at = models.DateTimeField(db_index=True, null=True, blank=True)
    insurer = models.CharField(max_length=255, choices=InsurerChoices.choices, blank=True)
    iol_model = models.CharField(max_length=255, choices=IOLModelChoices.choices, blank=True)
    iol_power = models.DecimalField(max_digits=7, decimal_places=2, blank=True, null=True)
    anesthesia = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    
    #Payments
    amount = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    operating_room_cost = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    amount_paid = models.DecimalField(
        max_digits=12, decimal_places=2, blank=True, null=True,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    
    #Sales Process
    first_consultation_at = models.DateField(blank=True, null=True)
    budget_status = models.CharField(max_length=10, choices=BudgetStatusChoices.choices, default=BudgetStatusChoices.QUOTED, blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True, editable=False)
    accepted_at = models.DateTimeField(null=True, blank=True, editable=False)
    lost_at = models.DateTimeField(null=True, blank=True, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    
    #Checklist
    lens_ordered = models.BooleanField('Lentes pedidas', default=False)
    lens_verified = models.BooleanField('Lentes comprobadas', default=False)
    eyes_verified = models.BooleanField('Ojos a operar comprobados', default=False)
    informed_consent_signed = models.BooleanField('Consentimiento informado firmado', default=False)
    blood_test_done = models.BooleanField('Analítica realizada', default=False)
    anesthetist_appointment = models.BooleanField('Cita con anestesista concertada', default=False)
    
    #Timestamps
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
            models.CheckConstraint(condition=models.Q(amount_paid__gte=0) | models.Q(amount_paid__isnull=True), name='surgery_amount_paid_nonnegative'),
            models.CheckConstraint(condition=models.Q(amount_paid__lte=models.F('amount')) | models.Q(amount__isnull=True) | models.Q(amount_paid__isnull=True), name='surgery_amount_paid_lte_amount'),
            models.CheckConstraint(condition=models.Q(amount__gte=0) | models.Q(amount__isnull=True), name='surgery_amount_nonnegative'),
            models.CheckConstraint(condition=models.Q(operating_room_cost__gte=0) | models.Q(operating_room_cost__isnull=True), name='surgery_operating_room_cost_nonnegative'),
            models.CheckConstraint(condition=models.Q(completed_at__isnull=True) | models.Q(cancelled_at__isnull=True), name='surgery_execution_dates_exclusive'),
        ]

    @property
    def payment_status(self):
        if self.amount is None or self.amount_paid is None:
            return 'UNKNOWN'
        if self.amount_paid == self.amount:
            return 'PAID'
        if self.amount_paid == 0:
            return 'PENDING'
        return 'PARTIAL'

    @property
    def amount_due(self):
        if self.amount is None or self.amount_paid is None:
            return None
        return self.amount - self.amount_paid

    @property
    def payment_percentage(self):
        if self.amount is None or self.amount_paid is None:
            return None
        if self.amount == 0:
            return Decimal('100.00')
        return (self.amount_paid / self.amount * 100).quantize(Decimal('0.01'))

    @property
    def display_status(self):
        if self.budget_status == BudgetStatusChoices.LOST:
            return 'LOST'
        if self.completed_at is not None:
            return 'COMPLETED'
        if self.cancelled_at is not None:
            return 'CANCELLED'
        if self.scheduled_at is not None:
            return 'SCHEDULED' if self.scheduled_at > timezone.now() else 'AWAITING_CONFIRMATION'
        return self.budget_status

    def save(self, *args, **kwargs):
        timestamp_field = {
            BudgetStatusChoices.QUOTED: 'quoted_at',
            BudgetStatusChoices.ACCEPTED: 'accepted_at',
            BudgetStatusChoices.LOST: 'lost_at',
        }.get(self.budget_status)
        update_fields = kwargs.get('update_fields')
        if timestamp_field and getattr(self, timestamp_field) is None and (
            update_fields is None or 'budget_status' in update_fields
        ):
            setattr(self, timestamp_field, timezone.now())
            if update_fields is not None:
                kwargs['update_fields'] = set(update_fields) | {timestamp_field}
        super().save(*args, **kwargs)

    def record_lens_changes(self, previous, user):
        user = user if user.is_authenticated else None
        for field in ('lens_ordered', 'lens_verified'):
            value = getattr(self, field)
            if value != previous.get(field, False):
                SurgeryLensCheck.objects.create(surgery=self, field=field, value=value, checked_by=user)

    def clean(self):
        super().clean()
        if self.amount is not None and self.amount_paid is not None and self.amount_paid > self.amount:
            raise ValidationError({'amount_paid': 'Amount paid cannot exceed the surgery amount.'})
        if self.completed_at is not None:
            if self.cancelled_at is not None:
                raise ValidationError({'completed_at': 'A completed surgery cannot be cancelled.'})
            if self.scheduled_at is None or self.budget_status == BudgetStatusChoices.LOST:
                raise ValidationError({'completed_at': 'Completion requires a scheduled date and a budget that is not lost.'})

    def soft_delete(self, user):
        self.deleted_at = timezone.now()
        self.deleted_by = user if user.is_authenticated else None
        self.save(update_fields=['deleted_at', 'deleted_by', 'updated_at'])

    def __str__(self):
        return str(self.pk)


class SurgeryLensCheck(models.Model):
    surgery = models.ForeignKey(Surgery, on_delete=models.PROTECT, related_name='lens_checks')
    field = models.CharField(max_length=20, choices=LensCheckFieldChoices.choices)
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
