from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .filters import SurgeryFilter
from .choices import BudgetStatusChoices
from .models import Surgery
from .serializers import SurgeryInputSerializer, SurgeryOutputSerializer


class SurgeryViewSet(viewsets.ModelViewSet):
    queryset = Surgery.objects.filter(deleted_at__isnull=True).select_related('patient').prefetch_related('lens_checks').order_by(
        F('scheduled_at').desc(nulls_last=True), '-created_at', 'id',
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SurgeryFilter
    search_fields = ['patient__first_name', 'patient__last_name', 'patient__clinical_reference', 'notes']
    ordering_fields = ['scheduled_at', 'created_at', 'updated_at', 'id']
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return SurgeryInputSerializer
        return SurgeryOutputSerializer

    def get_locked_surgery(self):
        surgery = get_object_or_404(
            Surgery.objects.select_for_update().filter(deleted_at__isnull=True),
            pk=self.kwargs['pk'],
        )
        self.check_object_permissions(self.request, surgery)
        return surgery

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def complete(self, request, pk=None):
        surgery = self.get_locked_surgery()
        if surgery.cancelled_at is not None:
            raise serializers.ValidationError('Reopen the cancelled surgery before completing it.')
        if surgery.scheduled_at is None or surgery.budget_status == BudgetStatusChoices.LOST:
            raise serializers.ValidationError('Completion requires a scheduled date and a budget that is not lost.')
        if surgery.completed_at is None:
            surgery.completed_at = timezone.now()
            surgery.save(update_fields=['completed_at', 'updated_at'])
        return Response(SurgeryOutputSerializer(surgery, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def cancel(self, request, pk=None):
        surgery = self.get_locked_surgery()
        if surgery.completed_at is not None:
            raise serializers.ValidationError('A completed surgery cannot be cancelled.')
        if surgery.cancelled_at is None:
            surgery.cancelled_at = timezone.now()
            surgery.save(update_fields=['cancelled_at', 'updated_at'])
        return Response(SurgeryOutputSerializer(surgery, context=self.get_serializer_context()).data)

    @action(detail=True, methods=['post'])
    @transaction.atomic
    def reopen(self, request, pk=None):
        surgery = self.get_locked_surgery()
        if surgery.completed_at is not None:
            raise serializers.ValidationError('A completed surgery cannot be reopened.')
        if surgery.cancelled_at is not None:
            surgery.cancelled_at = None
            surgery.save(update_fields=['cancelled_at', 'updated_at'])
        return Response(SurgeryOutputSerializer(surgery, context=self.get_serializer_context()).data)

    @transaction.atomic
    def perform_destroy(self, instance):
        surgery = Surgery.objects.select_for_update().get(pk=instance.pk)
        if surgery.deleted_at is None:
            surgery.soft_delete(self.request.user)
