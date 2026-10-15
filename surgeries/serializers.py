from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from patients.models import Patient
from patients.serializers import PatientInputSerializer, PatientOutputSerializer
from .models import Surgery, SurgeryLensCheck


class SurgeryLensCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = SurgeryLensCheck
        fields = ['id', 'field', 'value', 'checked_by', 'checked_at']
        read_only_fields = fields


class SurgeryOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)
    lens_checks = SurgeryLensCheckSerializer(many=True, read_only=True)

    class Meta:
        model = Surgery
        fields = [
            'id', 'patient', 'hospital', 'surgery_type', 'eye', 'scheduled_at',
            'insurer', 'iol_model', 'iol_power', 'anesthesia', 'amount', 'notes',
            'status', 'lens_ordered', 'lens_received', 'lens_verified',
            'documentation_ready', 'created_at', 'updated_at', 'deleted_at',
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
        fields = SurgeryOutputSerializer.Meta.fields + ['patient_id']
        read_only_fields = ['id', 'created_at', 'updated_at', 'deleted_at', 'deleted_by', 'lens_checks']

    def validate(self, attrs):
        if self.instance is None:
            if ('patient_id' in attrs) == ('patient' in attrs):
                raise serializers.ValidationError('Provide exactly one of patient_id or patient.')
        elif 'patient' in attrs:
            raise serializers.ValidationError({'patient': 'Use patient_id to change the patient.'})
        self.validate_lens_state(attrs, self.instance)
        return attrs

    @staticmethod
    def validate_lens_state(attrs, instance):
        received = attrs.get('lens_received', getattr(instance, 'lens_received', False))
        verified = attrs.get('lens_verified', getattr(instance, 'lens_verified', False))
        if verified and not received:
            raise serializers.ValidationError({'lens_verified': 'The lens must be received before verification.'})

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
        # Lock and revalidate the current state to avoid conflicting concurrent checks.
        instance = Surgery.objects.select_for_update().filter(pk=instance.pk, deleted_at__isnull=True).first()
        if instance is None:
            raise NotFound('Surgery not found.')
        self.validate_lens_state(validated_data, instance)
        previous = {field: getattr(instance, field) for field in ('lens_ordered', 'lens_received', 'lens_verified')}
        if 'patient_id' in validated_data:
            validated_data['patient'] = validated_data.pop('patient_id')
        surgery = super().update(instance, validated_data)
        surgery.record_lens_changes(previous, self.context['request'].user)
        return surgery

    def to_representation(self, instance):
        return SurgeryOutputSerializer(instance, context=self.context).data
