from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from cash.models import CashEntry
from .filters import SurgeryFilter
from .choices import BudgetStatusChoices
from .models import Surgery
from .serializers import (
    SurgeryAvailabilityQuerySerializer, SurgeryCalendarSerializer,
    SurgeryDetailSerializer, SurgeryInputSerializer, SurgeryOptionSerializer, SurgeryOutputSerializer,
)


class SurgeryViewSet(viewsets.ModelViewSet):
    queryset = Surgery.objects.filter(deleted_at__isnull=True).select_related('patient').annotate(
        _amount_paid=Sum('cash_entries__amount', default=Decimal('0.00')),
    ).prefetch_related('lens_checks').order_by(
        F('scheduled_at').desc(nulls_last=True), '-created_at', 'id',
    )
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SurgeryFilter
    search_fields = ['patient__first_name', 'patient__last_name', 'patient__clinical_reference', 'notes']
    ordering_fields = ['created_at','scheduled_at','updated_at', 'id']
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def paginate_queryset(self, queryset):
        if self.action == 'list' and self.request.query_params.get('view') == 'calendar':
            return None
        return super().paginate_queryset(queryset)

    def get_queryset(self):
        if self.action == 'list' and self.request.query_params.get('view') == 'calendar':
            return Surgery.objects.filter(deleted_at__isnull=True).select_related('patient').only(
                'id', 'patient_id', 'patient__first_name', 'patient__last_name', 'scheduled_at',
            ).annotate(
                has_payment=Exists(CashEntry.objects.filter(surgery_id=OuterRef('pk'))),
            ).order_by(F('scheduled_at').desc(nulls_last=True), '-created_at', 'id')
        queryset = super().get_queryset()
        if self.action == 'retrieve':
            return queryset.prefetch_related('cash_entries')
        return queryset

    def get_serializer_class(self):
        if self.action == 'list' and self.request.query_params.get('view') == 'calendar':
            return SurgeryCalendarSerializer
        if self.action == 'retrieve':
            return SurgeryDetailSerializer
        if self.action == 'cash_options':
            return SurgeryOptionSerializer
        if self.action in ('create', 'update', 'partial_update'):
            return SurgeryInputSerializer
        return SurgeryOutputSerializer

    @action(detail=False, methods=['get'])
    def availability(self, request):
        query = SurgeryAvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = query.validated_data['start']
        end = query.validated_data['end']
        tz = timezone.get_current_timezone()
        occupied_by_date = dict(
            Surgery.objects.filter(
                deleted_at__isnull=True,
                cancelled_at__isnull=True,
                scheduled_at__gte=timezone.make_aware(datetime.combine(start, time.min), tz),
                scheduled_at__lt=timezone.make_aware(datetime.combine(end, time.min), tz),
            ).exclude(budget_status=BudgetStatusChoices.LOST).order_by().annotate(
                date=TruncDate('scheduled_at', tzinfo=tz),
            ).values('date').annotate(
                occupied=Count('id'),
            ).values_list('date', 'occupied')
        )
        days = []
        date = start
        capacities = {0: 7, 3: 7}
        while date < end:
            capacity = capacities.get(date.weekday())
            if capacity is not None:
                occupied = occupied_by_date.get(date, 0)
                available = max(capacity - occupied, 0)
                status = 'FULL' if available == 0 else 'LIMITED' if available <= 2 else 'AVAILABLE'
                days.append({
                    'date': date.isoformat(),
                    'capacity': capacity,
                    'occupied': occupied,
                    'available': available,
                    'status': status,
                })
            date += timedelta(days=1)
        return Response({'days': days})

    @action(detail=False, methods=['get'], url_path='options')
    def cash_options(self, request):
        queryset = self.filter_queryset(self.get_queryset()).prefetch_related(None)
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

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
