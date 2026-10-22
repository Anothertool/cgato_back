from django.contrib import admin

from .models import CashEntry


@admin.register(CashEntry)
class CashEntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'date', 'patient', 'surgery', 'amount', 'payment_method', 'invoice_status']
    list_filter = ['payment_method', 'invoice_status', 'date']
    search_fields = ['invoice_number', 'patient__first_name', 'patient__last_name']
    readonly_fields = ['id', 'created_at']
