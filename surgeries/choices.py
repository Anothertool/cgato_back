from django.db import models


class SurgeryTypeChoices(models.TextChoices):
    FACO_INSTENT = 'FACO_INSTENT', 'Faco + Instent'
    FACO = 'FACO', 'Faco'
    FEPNP = 'FEPNP', 'FEPNP'
    FACO_PRESERFLO = 'FACO_PRESERFLO', 'Faco + Preserflo'
    BLEPHAROPLASTY = 'BLEPHAROPLASTY', 'Blefaroplastia'
    TUMOR = 'TUMOR', 'Tumoración'
    INSTENT = 'INSTENT', 'Instent'
    EPNP = 'EPNP', 'EPNP'
    PRESERFLO = 'PRESERFLO', 'Preserflo'
    ICL = 'ICL', 'ICL'
    PRK = 'PRK', 'PRK'
    LASIK = 'LASIK', 'LASIK'
    PTOSIS = 'PTOSIS', 'Ptosis'
    CHALAZION = 'CHALAZION', 'Chalazión'
    CONJUNCTIVOCHALASIS_PUNCTOPLASTY = 'CONJUNCTIVOCHALASIS_PUNCTOPLASTY', 'Conjuntivochalasis + puntoplastia'
    ANTI_VEGF_INJECTION = 'ANTI_VEGF_INJECTION', 'Inyección intravítrea anti-VEGF'
    OTHER = 'OTHER', 'Otros'


class InsurerChoices(models.TextChoices):
    CASER = 'CASER', 'Caser'
    ADESLAS = 'ADESLAS', 'Adeslas'
    CIGNA = 'CIGNA', 'Cigna'
    DKV = 'DKV', 'DKV'
    DIVINA_PASTORA = 'DIVINA_PASTORA', 'Divina Pastora'
    PRIVATE = 'PRIVATE', 'Privado'
    AEGON = 'AEGON', 'Aegon'
    OTHER = 'OTHER', 'Otros'


class IOLModelChoices(models.TextChoices):
    PURE_DEN00V = 'PURE_DEN00V', 'PURE DEN00V'
    PURE_TORICA_DET = 'PURE_TORICA_DET', 'PURE + TORICA DET'
    MULTI_DRN00V = 'MULTI_DRN00V', 'MULTI DRN00V'
    MULTI_TORICA_DRT = 'MULTI_TORICA_DRT', 'MULTI + TORICA DRT'
    HOYA_XY1 = 'HOYA_XY1', 'HOYA XY1'
    OTHER = 'OTHER', 'Otros'


class EyeChoices(models.TextChoices):
    RIGHT = 'RIGHT', 'Derecho'
    LEFT = 'LEFT', 'Izquierdo'
    BOTH = 'BOTH', 'Ambos'


class BudgetStatusChoices(models.TextChoices):
    QUOTED = 'QUOTED', 'Presupuestado'
    ACCEPTED = 'ACCEPTED', 'Aceptado'
    LOST = 'LOST', 'Perdido'


class LensCheckFieldChoices(models.TextChoices):
    LENS_ORDERED = 'lens_ordered', 'Lens ordered'
    # Kept for existing history entries; no longer a checklist field.
    LENS_RECEIVED = 'lens_received', 'Lens received'
    LENS_VERIFIED = 'lens_verified', 'Lens verified'
