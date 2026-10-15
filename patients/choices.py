from django.db import models


class PatientSourceChoices(models.TextChoices):
    SOCIAL_MEDIA = 'SOCIAL_MEDIA', 'Redes sociales'
    INSURER = 'INSURER', 'Aseguradora'
    CONSULTATION = 'CONSULTATION', 'Consulta en la clínica'
    REFERRAL = 'REFERRAL', 'Recomendación'
    WEB = 'WEB', 'Web / Google'
    OTHER = 'OTHER', 'Otros'
    UNKNOWN = 'UNKNOWN', 'Desconocido'
