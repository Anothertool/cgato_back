from django.db import models


class EyeChoices(models.TextChoices):
    RIGHT = 'RIGHT', 'Derecho'
    LEFT = 'LEFT', 'Izquierdo'
    BOTH = 'BOTH', 'Ambos'


class LaboratoryChoices(models.TextChoices):
    TIEDRA = 'TIEDRA', 'TIEDRA'
    MENICOM = 'MENICOM', 'MENICOM'
    MARKENOVI = 'MARKENOVI', 'MARKENOVI'
    JOHNSON_JOHNSON = 'JOHNSON_JOHNSON', 'Johnson & Johnson'
    BVI = 'BVI', 'BVI'
    HOYA = 'HOYA', 'HOYA'


class LensTypeChoices(models.TextChoices):
    ORTHO_K = 'ortho_k', 'Orto-K'
    RGP = 'rgp', 'RPG'
    SOFT = 'soft', 'Blanda'
    LIO = 'lio', 'LIO'


class FormatChoices(models.TextChoices):
    BLISTER = 'blister', 'Blíster'
    BOX = 'box', 'Caja'


class StatusChoices(models.TextChoices):
    PENDING = 'pending', 'Pendiente'
    ORDERED = 'ordered', 'Pedida'
    RECEIVED = 'received', 'Recibida'
    NOTIFIED = 'notified', 'Avisado / Citado'
    DELIVERED = 'delivered', 'Entregada'


class DeliveryTypeChoices(models.TextChoices):
    PICKUP = 'pickup', 'Recogida'
    APPOINTMENT = 'appointment', 'Cita'
