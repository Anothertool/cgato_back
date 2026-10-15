from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets

from .filters import SurgeryFilter
from .models import Surgery
from .serializers import SurgeryInputSerializer, SurgeryOutputSerializer


class SurgeryViewSet(viewsets.ModelViewSet):
    queryset = Surgery.objects.filter(deleted_at__isnull=True).select_related('patient').prefetch_related('lens_checks')
    filter_backends = [DjangoFilterBackend]
    filterset_class = SurgeryFilter
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return SurgeryInputSerializer
        return SurgeryOutputSerializer

    @transaction.atomic
    def perform_destroy(self, instance):
        surgery = Surgery.objects.select_for_update().get(pk=instance.pk)
        if surgery.deleted_at is None:
            surgery.soft_delete(self.request.user)
