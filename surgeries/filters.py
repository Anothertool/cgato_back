from django_filters import rest_framework as filters

from .models import Surgery


class SurgeryFilter(filters.FilterSet):
    patient_id = filters.UUIDFilter(field_name='patient_id')

    class Meta:
        model = Surgery
        fields = {
            'status': ['exact'],
            'hospital': ['exact'],
            'eye': ['exact'],
            'insurer': ['exact'],
            'scheduled_at': ['gte', 'lte'],
        }
