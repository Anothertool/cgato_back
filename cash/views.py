from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.response import Response

from .choices import PaymentMethodChoices
from .models import CashEntry
from .serializers import (
    CashEntryInputSerializer, CashEntryOutputSerializer,
    CashQuerySerializer, CashSummarySerializer,
)


def filter_entries(queryset, params, include_dates=True):
    for field in ('payment_method', 'invoice_status', 'patient_id'):
        if field in params:
            queryset = queryset.filter(**{field: params[field]})
    if include_dates:
        for param, lookup in (('date', 'date'), ('date_from', 'date__gte'), ('date_to', 'date__lte')):
            if param in params:
                queryset = queryset.filter(**{lookup: params[param]})
    return queryset


def query_params(request):
    serializer = CashQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


class CashEntryViewSet(viewsets.ModelViewSet):
    queryset = CashEntry.objects.select_related('patient')
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return CashEntryInputSerializer
        return CashEntryOutputSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.action == 'list':
            queryset = filter_entries(queryset, query_params(self.request))
        return queryset


class CashSummaryViewSet(viewsets.ViewSet):
    http_method_names = ['get', 'head', 'options']
    serializer_class = CashSummarySerializer

    def list(self, request):
        params = query_params(request)
        anchor = params.get('date', timezone.localdate())
        week_start = anchor - timedelta(days=anchor.weekday())
        week_end = week_start + timedelta(days=min(6, (date.max - week_start).days))
        base = filter_entries(CashEntry.objects.all(), params, include_dates=False)
        period_params = params.copy()
        if not any(field in params for field in ('date', 'date_from', 'date_to')):
            period_params['date'] = anchor
        period = filter_entries(base, period_params)
        amounts = {method: Decimal('0.00') for method in PaymentMethodChoices.values}
        for row in period.order_by().values('payment_method').annotate(total=Sum('amount')):
            amounts[row['payment_method']] = row['total']
        cards = base.aggregate(
            total_today=Sum('amount', filter=Q(date=anchor), default=Decimal('0.00')),
            total_week=Sum('amount', filter=Q(date__range=(week_start, week_end)), default=Decimal('0.00')),
            cash_today=Sum('amount', filter=Q(date=anchor, payment_method=PaymentMethodChoices.CASH), default=Decimal('0.00')),
        )
        summary = {
            'date': anchor, 'week_start': week_start, 'week_end': week_end,
            'date_from': period_params.get('date', params.get('date_from')),
            'date_to': period_params.get('date', params.get('date_to')),
            'total': sum(amounts.values(), Decimal('0.00')),
            'entries_count': period.count(),
            'by_payment_method': amounts,
            **cards,
        }
        return Response(CashSummarySerializer(summary).data)
