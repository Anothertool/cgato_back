from django.db import IntegrityError, transaction
from rest_framework import serializers

from .models import Patient


class PatientOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = ['id', 'first_name', 'last_name', 'phone', 'clinical_reference', 'patient_source', 'created_at', 'updated_at']
        read_only_fields = fields


class PatientInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = PatientOutputSerializer.Meta.fields
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_clinical_reference(self, value):
        return value or None

    def create(self, validated_data):
        try:
            with transaction.atomic():
                return super().create(validated_data)
        except IntegrityError:
            raise serializers.ValidationError({'clinical_reference': 'This reference is already in use.'}) from None

    def update(self, instance, validated_data):
        try:
            with transaction.atomic():
                return super().update(instance, validated_data)
        except IntegrityError:
            raise serializers.ValidationError({'clinical_reference': 'This reference is already in use.'}) from None

    def to_representation(self, instance):
        return PatientOutputSerializer(instance, context=self.context).data
