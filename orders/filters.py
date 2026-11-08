from django_filters import rest_framework as filters

from .models import LensOrder


class LensOrderFilter(filters.FilterSet):
    laboratory = filters.CharFilter(lookup_expr='iexact')

    class Meta:
        model = LensOrder
        fields = ['status', 'laboratory']
