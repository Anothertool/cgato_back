import uuid
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from .choices import InvoiceStatusChoices, PaymentMethodChoices


class CashEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, null=True, blank=True,
        related_name='cash_entries',
    )
    date = models.DateField(db_index=True)
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    payment_method = models.CharField(max_length=20, choices=PaymentMethodChoices.choices)
    invoice_number = models.CharField(max_length=100, blank=True, default='')
    invoice_status = models.CharField(
        max_length=20, choices=InvoiceStatusChoices.choices,
        default=InvoiceStatusChoices.PENDING,
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at', 'id']
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gte=Decimal('0.01')), name='cash_entry_amount_positive'),
        ]

    def __str__(self):
        return str(self.pk)
