from django.db import models


class EyeChoices(models.TextChoices):
    RIGHT = 'RIGHT', 'Derecho'
    LEFT = 'LEFT', 'Izquierdo'
    BOTH = 'BOTH', 'Ambos'


class LaboratoryChoices(models.TextChoices):
    TIEDRA = 'TIEDRA', 'TIEDRA'
    MENICOM = 'MENICOM', 'MENICOM'
    MARKENOVI = 'MARKENOVI', 'MARKENOVI'


class StatusChoices(models.TextChoices):
    PENDING = 'pending', 'Pendiente'
    ORDERED = 'ordered', 'Pedida'
    RECEIVED = 'received', 'Recibida'
    NOTIFIED = 'notified', 'Avisado / Citado'
    DELIVERED = 'delivered', 'Entregada'


class DeliveryTypeChoices(models.TextChoices):
    PICKUP = 'pickup', 'Recogida'
    APPOINTMENT = 'appointment', 'Cita'
