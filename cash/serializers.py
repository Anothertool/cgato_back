from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from rest_framework import serializers

from patients.models import Patient
from patients.serializers import PatientOutputSerializer
from surgeries.models import Surgery
from surgeries.serializers import SurgeryOptionSerializer
from .choices import InvoiceStatusChoices, PaymentMethodChoices
from .models import CashEntry


class CashEntryOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)
    surgery = SurgeryOptionSerializer(read_only=True)
    surgery_id = serializers.PrimaryKeyRelatedField(
        source='surgery', read_only=True, pk_field=serializers.UUIDField(),
    )

    class Meta:
        model = CashEntry
        fields = [
            'id', 'patient', 'surgery_id', 'surgery', 'date', 'amount', 'payment_method',
            'invoice_number', 'invoice_status', 'notes', 'created_at',
        ]
        read_only_fields = fields


class CashEntryInputSerializer(serializers.ModelSerializer):
    surgery_id = serializers.PrimaryKeyRelatedField(
        source='surgery', queryset=Surgery.objects.filter(deleted_at__isnull=True),
        required=False, allow_null=True, write_only=True,
    )
    patient_id = serializers.PrimaryKeyRelatedField(
        source='patient', queryset=Patient.objects.all(),
        required=False, allow_null=True, write_only=True,
    )

    class Meta:
        model = CashEntry
        fields = [field for field in CashEntryOutputSerializer.Meta.fields if field not in ('patient', 'surgery')] + ['patient_id']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        patient = attrs.get('patient', getattr(self.instance, 'patient', None))
        surgery = attrs.get('surgery', getattr(self.instance, 'surgery', None))
        if patient is not None and surgery is not None:
            raise serializers.ValidationError('Provide either patient_id or surgery_id, not both.')
        return attrs

    def validate_surgery_payment(self, validated_data, instance=None):
        surgery = validated_data.get('surgery', getattr(instance, 'surgery', None))
        if surgery is None:
            return
        surgery = Surgery.objects.select_for_update().get(pk=surgery.pk)
        if surgery.deleted_at is not None:
            raise serializers.ValidationError({'surgery_id': 'Cirugía no encontrada.'})
        entries = surgery.cash_entries.all()
        if instance is not None:
            entries = entries.exclude(pk=instance.pk)
        total = entries.aggregate(total=Sum('amount', default=Decimal('0.00')))['total']
        amount = validated_data.get('amount', getattr(instance, 'amount', Decimal('0.00')))
        if surgery.amount is not None and total + amount > surgery.amount:
            raise serializers.ValidationError({'amount': 'El importe total de los pagos no puede superar el importe de la cirugía.'})

    @transaction.atomic
    def create(self, validated_data):
        self.validate_surgery_payment(validated_data)
        return super().create(validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = CashEntry.objects.select_for_update().get(pk=instance.pk)
        self.instance = instance
        self.validate(validated_data)
        self.validate_surgery_payment(validated_data, instance)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        return CashEntryOutputSerializer(instance, context=self.context).data


class CashQuerySerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True)
    date = serializers.DateField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethodChoices.choices, required=False)
    invoice_status = serializers.ChoiceField(choices=InvoiceStatusChoices.choices, required=False)
    patient_id = serializers.UUIDField(required=False)
    surgery_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if 'date' in attrs and ('date_from' in attrs or 'date_to' in attrs):
            raise serializers.ValidationError('Use date or date_from/date_to, not both.')
        if 'date_from' in attrs and 'date_to' in attrs and attrs['date_from'] > attrs['date_to']:
            raise serializers.ValidationError({'date_to': 'Must be on or after date_from.'})
        return attrs


class CashSummarySerializer(serializers.Serializer):
    date = serializers.DateField()
    week_start = serializers.DateField()
    week_end = serializers.DateField()
    month_start = serializers.DateField()
    month_end = serializers.DateField()
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    total = serializers.DecimalField(max_digits=24, decimal_places=2)
    entries_count = serializers.IntegerField()
    by_payment_method = serializers.DictField(
        child=serializers.DecimalField(max_digits=24, decimal_places=2),
    )
    total_today = serializers.DecimalField(max_digits=24, decimal_places=2)
    total_week = serializers.DecimalField(max_digits=24, decimal_places=2)
    total_month = serializers.DecimalField(max_digits=24, decimal_places=2)
    cash_today = serializers.DecimalField(max_digits=24, decimal_places=2)
