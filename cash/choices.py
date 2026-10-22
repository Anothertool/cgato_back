from django.db import models


class PaymentMethodChoices(models.TextChoices):
    CASH = 'CASH', 'Efectivo'
    CARD = 'CARD', 'Tarjeta'
    TRANSFER = 'TRANSFER', 'Transferencia'
    OTHER = 'OTHER', 'Otros'


class InvoiceStatusChoices(models.TextChoices):
    PENDING = 'PENDING', 'Pendiente'
    ISSUED = 'ISSUED', 'Emitida, no entregada'
    DELIVERED = 'DELIVERED', 'Emitida y entregada'
