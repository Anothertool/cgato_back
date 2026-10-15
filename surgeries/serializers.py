from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from patients.models import Patient
from patients.serializers import PatientInputSerializer, PatientOutputSerializer
from .choices import BudgetStatusChoices
from .models import Surgery, SurgeryLensCheck


class SurgeryLensCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurgeryLensCheck
        fields = ['id', 'field', 'value', 'checked_by', 'checked_at']
        read_only_fields = fields


class SurgeryOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)
    lens_checks = SurgeryLensCheckSerializer(many=True, read_only=True)
    surgery_type_label = serializers.CharField(source='get_surgery_type_display', read_only=True)
    eye_label = serializers.CharField(source='get_eye_display', read_only=True)
    insurer_label = serializers.CharField(source='get_insurer_display', read_only=True)
    iol_model_label = serializers.CharField(source='get_iol_model_display', read_only=True)
    budget_status_label = serializers.CharField(source='get_budget_status_display', read_only=True)
    display_status = serializers.CharField(read_only=True)
    payment_status = serializers.CharField(read_only=True)
    amount_due = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    payment_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = Surgery
        fields = [
            'id', 'patient', 'surgery_type', 'eye', 'scheduled_at',
            'insurer', 'iol_model', 'iol_power', 'anesthesia', 'amount', 'notes',
            'operating_room_cost', 'first_consultation_at',
            'amount_paid', 'payment_status', 'amount_due', 'payment_percentage',
            'budget_status', 'quoted_at', 'accepted_at', 'lost_at', 'completed_at',
            'cancelled_at', 'display_status', 'surgery_type_label', 'eye_label',
            'insurer_label', 'iol_model_label', 'budget_status_label',
            'lens_ordered', 'lens_verified', 'eyes_verified',
            'informed_consent_signed', 'blood_test_done', 'anesthetist_appointment',
            'created_at', 'updated_at', 'deleted_at',
            'deleted_by', 'lens_checks',
        ]
        read_only_fields = fields


class SurgeryInputSerializer(serializers.ModelSerializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        queryset=Patient.objects.all(), required=False, write_only=True,
        error_messages={
            'does_not_exist': 'Patient not found.',
            'incorrect_type': 'A valid patient ID is required.',
        },
    )
    patient = PatientInputSerializer(required=False, write_only=True)

    class Meta:
        model = Surgery
        fields = [field for field in SurgeryOutputSerializer.Meta.fields if not field.endswith('_label') and field != 'display_status'] + ['patient_id']
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'deleted_at', 'deleted_by', 'lens_checks',
            'quoted_at', 'accepted_at', 'lost_at', 'completed_at', 'cancelled_at',
            'payment_status', 'amount_due', 'payment_percentage',
        ]
        extra_kwargs = {
            'budget_status': {'allow_blank': False},
            'insurer': {'required': False, 'allow_blank': True, 'allow_null': True},
        }

    def validate_insurer(self, value):
        return value or ''

    def validate(self, attrs):
        if self.instance is None:
            if ('patient_id' in attrs) == ('patient' in attrs):
                raise serializers.ValidationError('Provide exactly one of patient_id or patient.')
        elif 'patient' in attrs:
            raise serializers.ValidationError({'patient': 'Use patient_id to change the patient.'})
        self.validate_execution_state(attrs, self.instance)
        self.validate_payment(attrs, self.instance)
        return attrs

    @staticmethod
    def validate_payment(attrs, instance):
        amount = attrs.get('amount', getattr(instance, 'amount', None))
        amount_paid = attrs.get('amount_paid', getattr(instance, 'amount_paid', None))
        if amount is not None and amount_paid is not None and amount_paid > amount:
            raise serializers.ValidationError({'amount_paid': 'Amount paid cannot exceed the surgery amount.'})

    @staticmethod
    def validate_execution_state(attrs, instance):
        if instance is not None and instance.completed_at is not None:
            if attrs.get('scheduled_at', instance.scheduled_at) is None:
                raise serializers.ValidationError({'scheduled_at': 'A completed surgery must retain a scheduled date.'})
            if attrs.get('budget_status', instance.budget_status) == BudgetStatusChoices.LOST:
                raise serializers.ValidationError({'budget_status': 'A completed surgery cannot have a lost budget.'})

    @transaction.atomic
    def create(self, validated_data):
        patient = validated_data.pop('patient_id', None)
        if patient is None:
            patient_data = validated_data.pop('patient')
            patient = PatientInputSerializer(context=self.context).create(patient_data)
        surgery = Surgery.objects.create(patient=patient, **validated_data)
        surgery.record_lens_changes({}, self.context['request'].user)
        return surgery

    @transaction.atomic
    def update(self, instance, validated_data):
        # Lock and revalidate the current state before updating.
        instance = Surgery.objects.select_for_update().filter(pk=instance.pk, deleted_at__isnull=True).first()
        if instance is None:
            raise NotFound('Surgery not found.')
        self.validate_execution_state(validated_data, instance)
        self.validate_payment(validated_data, instance)
        previous = {field: getattr(instance, field) for field in ('lens_ordered', 'lens_verified')}
        if 'patient_id' in validated_data:
            validated_data['patient'] = validated_data.pop('patient_id')
        surgery = super().update(instance, validated_data)
        surgery.record_lens_changes(previous, self.context['request'].user)
        return surgery

    def to_representation(self, instance):
        return SurgeryOutputSerializer(instance, context=self.context).data
