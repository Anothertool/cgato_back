from django.db.models.deletion import ProtectedError
from rest_framework import filters, serializers, viewsets

from .models import Patient
from .serializers import PatientInputSerializer, PatientOutputSerializer


class PatientViewSet(viewsets.ModelViewSet):
    queryset = Patient.objects.all()
    filter_backends = [filters.SearchFilter]
    search_fields = ['first_name', 'last_name', 'clinical_reference']
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return PatientInputSerializer
        return PatientOutputSerializer

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise serializers.ValidationError('Patients with associated surgeries cannot be deleted.') from None
