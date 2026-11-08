from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from patients.models import Patient
from patients.serializers import PatientOutputSerializer
from .models import LensOrder


class LensOrderOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)
    eye_label = serializers.CharField(source='get_eye_display', read_only=True)
    lens_type_label = serializers.CharField(source='get_lens_type_display', read_only=True)
    format_label = serializers.CharField(source='get_format_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    delivery_type_label = serializers.CharField(source='get_delivery_type_display', read_only=True)

    class Meta:
        model = LensOrder
        fields = [
            'id', 'patient', 'eye', 'laboratory', 'lens_type', 'right_eye_parameters',
            'left_eye_parameters', 'format', 'status', 'delivery_type', 'appointment_date',
            'notes', 'ordered_at', 'received_at', 'notified_at', 'delivered_at',
            'created_at', 'updated_at', 'deleted_at', 'deleted_by',
            'eye_label', 'lens_type_label', 'format_label', 'status_label', 'delivery_type_label',
        ]
        read_only_fields = fields


class LensOrderInputSerializer(serializers.ModelSerializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        source='patient', queryset=Patient.objects.all(), write_only=True,
    )

    class Meta:
        model = LensOrder
        fields = [
            'patient_id', 'eye', 'laboratory', 'lens_type', 'right_eye_parameters',
            'left_eye_parameters', 'format', 'status', 'delivery_type', 'appointment_date', 'notes',
        ]

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = LensOrder.objects.select_for_update().filter(pk=instance.pk, deleted_at__isnull=True).first()
        if instance is None:
            raise NotFound('Pedido no encontrado.')
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        return LensOrderOutputSerializer(instance, context=self.context).data
