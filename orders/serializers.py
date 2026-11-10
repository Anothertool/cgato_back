from django.db import transaction
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from patients.models import Patient
from patients.serializers import PatientOutputSerializer
from surgeries.models import Surgery

from .choices import LensTypeChoices, StatusChoices
from .models import LensOrder


class LensOrderOutputSerializer(serializers.ModelSerializer):
    patient = PatientOutputSerializer(read_only=True)
    eye_label = serializers.CharField(source='get_eye_display', read_only=True)
    laboratory_label = serializers.CharField(source='get_laboratory_display', read_only=True)
    lens_type_label = serializers.CharField(source='get_lens_type_display', read_only=True)
    format_label = serializers.CharField(source='get_format_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    delivery_type_label = serializers.CharField(source='get_delivery_type_display', read_only=True)

    class Meta:
        model = LensOrder
        fields = [
            'id', 'patient', 'surgery_id', 'eye', 'laboratory', 'lens_type', 'right_eye_parameters',
            'left_eye_parameters', 'format', 'status', 'delivery_type', 'appointment_date',
            'notes', 'ordered_at', 'received_at', 'notified_at', 'delivered_at',
            'created_at', 'updated_at', 'deleted_at', 'deleted_by',
            'eye_label', 'laboratory_label', 'lens_type_label', 'format_label', 'status_label', 'delivery_type_label',
        ]
        read_only_fields = fields


class LensOrderInputSerializer(serializers.ModelSerializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        source='patient', queryset=Patient.objects.all(), write_only=True,
    )
    surgery_id = serializers.PrimaryKeyRelatedField(
        source='surgery', queryset=Surgery.objects.filter(deleted_at__isnull=True),
        required=False, allow_null=True, write_only=True,
    )

    class Meta:
        model = LensOrder
        fields = [
            'patient_id', 'surgery_id', 'eye', 'laboratory', 'lens_type', 'right_eye_parameters',
            'left_eye_parameters', 'format', 'status', 'delivery_type', 'appointment_date', 'notes',
        ]

    def sync_surgery_checklist(self, order):
        if order.surgery_id is None:
            return
        if order.lens_type != LensTypeChoices.LIO:
            raise serializers.ValidationError({'surgery_id': 'Solo los pedidos LIO pueden vincularse a una cirugía.'})
        surgery = Surgery.objects.select_for_update().filter(
            pk=order.surgery_id, patient_id=order.patient_id, deleted_at__isnull=True,
        ).first()
        if surgery is None:
            raise serializers.ValidationError({'surgery_id': 'Selecciona una cirugía activa del mismo paciente.'})
        if order.status == StatusChoices.PENDING:
            return

        previous = {'lens_ordered': surgery.lens_ordered, 'lens_verified': surgery.lens_verified}
        surgery.lens_ordered = True
        if order.status in (StatusChoices.RECEIVED, StatusChoices.NOTIFIED, StatusChoices.DELIVERED):
            surgery.lens_verified = True
        changed = [field for field, value in previous.items() if getattr(surgery, field) != value]
        if changed:
            surgery.save(update_fields=[*changed, 'updated_at'])
            surgery.record_lens_changes(previous, self.context['request'].user)

    @transaction.atomic
    def create(self, validated_data):
        order = super().create(validated_data)
        self.sync_surgery_checklist(order)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = LensOrder.objects.select_for_update().filter(pk=instance.pk, deleted_at__isnull=True).first()
        if instance is None:
            raise NotFound('Pedido no encontrado.')
        previous = (instance.surgery_id, instance.patient_id, instance.lens_type, instance.status)
        order = super().update(instance, validated_data)
        if previous != (order.surgery_id, order.patient_id, order.lens_type, order.status):
            self.sync_surgery_checklist(order)
        return order

    def to_representation(self, instance):
        return LensOrderOutputSerializer(instance, context=self.context).data
