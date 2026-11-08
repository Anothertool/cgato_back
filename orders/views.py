from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets

from .filters import LensOrderFilter
from .models import LensOrder
from .serializers import LensOrderInputSerializer, LensOrderOutputSerializer


class LensOrderViewSet(viewsets.ModelViewSet):
    queryset = LensOrder.objects.filter(deleted_at__isnull=True).select_related('patient').order_by('-created_at', 'id')
    filter_backends = [DjangoFilterBackend]
    filterset_class = LensOrderFilter
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('create', 'partial_update'):
            return LensOrderInputSerializer
        return LensOrderOutputSerializer

    def perform_destroy(self, instance):
        user = self.request.user
        now = timezone.now()
        LensOrder.objects.filter(pk=instance.pk, deleted_at__isnull=True).update(
            deleted_at=now, updated_at=now, deleted_by=user if user.is_authenticated else None,
        )
