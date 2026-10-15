from django.contrib import admin

from .models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ['id', 'first_name', 'last_name', 'clinical_reference', 'created_at']
    search_fields = ['first_name', 'last_name', 'clinical_reference']
    readonly_fields = ['id', 'created_at', 'updated_at']
