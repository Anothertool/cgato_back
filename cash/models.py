import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from .choices import InvoiceStatusChoices, PaymentMethodChoices


class CashEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, null=True, blank=True,
        related_name='cash_entries',
    )
    surgery = models.ForeignKey(
        'surgeries.Surgery', on_delete=models.PROTECT, null=True, blank=True,
        related_name='cash_entries',
    )
    date = models.DateField(db_index=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    payment_method = models.CharField(max_length=20, choices=PaymentMethodChoices.choices)
    invoice_number = models.CharField(max_length=100, blank=True, default='')
    import_reference = models.CharField(
        max_length=255, unique=True, null=True, blank=True, editable=False,
    )
    invoice_status = models.CharField(
        max_length=20, choices=InvoiceStatusChoices.choices,
        default=InvoiceStatusChoices.PENDING,
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at', 'id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(patient__isnull=True) | models.Q(surgery__isnull=True),
                name='cash_entry_patient_or_surgery',
            ),
            models.CheckConstraint(condition=models.Q(amount__gte=Decimal('0.01')), name='cash_entry_amount_positive'),
        ]

    def clean(self):
        super().clean()
        if self.patient_id is not None and self.surgery_id is not None:
            raise ValidationError('Provide either a patient or a surgery, not both.')
        if self.surgery_id is not None and self.amount is not None:
            total = self.surgery.cash_entries.exclude(pk=self.pk).aggregate(
                total=models.Sum('amount', default=Decimal('0.00')),
            )['total']
            if self.surgery.amount is not None and total + self.amount > self.surgery.amount:
                raise ValidationError({'amount': 'Total payments cannot exceed the surgery amount.'})

    def __str__(self):
        return str(self.pk)
