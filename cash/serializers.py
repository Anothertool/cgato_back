from rest_framework import serializers

from patients.models import Patient
from patients.serializers import PatientOutputSerializer
from .choices import InvoiceStatusChoices, PaymentMethodChoices
from .models import CashEntry


class CashEntryOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)

    class Meta:
        model = CashEntry
        fields = [
            'id', 'patient', 'date', 'amount', 'payment_method',
            'invoice_number', 'invoice_status', 'notes', 'created_at',
        ]
        read_only_fields = fields


class CashEntryInputSerializer(serializers.ModelSerializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        source='patient', queryset=Patient.objects.all(),
        required=False, allow_null=True, write_only=True,
    )

    class Meta:
        model = CashEntry
        fields = [field for field in CashEntryOutputSerializer.Meta.fields if field != 'patient'] + ['patient_id']
        read_only_fields = ['id', 'created_at']

    def to_representation(self, instance):
        return CashEntryOutputSerializer(instance, context=self.context).data


class CashQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    payment_method = serializers.ChoiceField(choices=PaymentMethodChoices.choices, required=False)
    invoice_status = serializers.ChoiceField(choices=InvoiceStatusChoices.choices, required=False)
    patient_id = serializers.UUIDField(required=False)

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
    date_from = serializers.DateField(allow_null=True)
    date_to = serializers.DateField(allow_null=True)
    total = serializers.DecimalField(max_digits=24, decimal_places=2)
    entries_count = serializers.IntegerField()
    by_payment_method = serializers.DictField(
        child=serializers.DecimalField(max_digits=24, decimal_places=2),
    )
    total_today = serializers.DecimalField(max_digits=24, decimal_places=2)
    total_week = serializers.DecimalField(max_digits=24, decimal_places=2)
    cash_today = serializers.DecimalField(max_digits=24, decimal_places=2)
