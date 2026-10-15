from django.contrib import admin

from .models import Surgery, SurgeryLensCheck


class SurgeryLensCheckInline(admin.TabularInline):
    model = SurgeryLensCheck
    fields = ['field', 'value', 'checked_by', 'checked_at']
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Surgery)
class SurgeryAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient', 'hospital', 'surgery_type', 'scheduled_at', 'status', 'deleted_at']
    list_filter = ['status', 'eye', 'hospital']
    readonly_fields = ['id', 'created_at', 'updated_at', 'deleted_at', 'deleted_by']
    autocomplete_fields = ['patient']
    inlines = [SurgeryLensCheckInline]

    def save_model(self, request, obj, form, change):
        previous = {}
        if change:
            current = Surgery.objects.select_for_update().get(pk=obj.pk)
            previous = {field: getattr(current, field) for field in ('lens_ordered', 'lens_received', 'lens_verified')}
        super().save_model(request, obj, form, change)
        obj.record_lens_changes(previous, request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.deleted_at is not None:
            return False
        return super().has_change_permission(request, obj)


@admin.register(SurgeryLensCheck)
class SurgeryLensCheckAdmin(admin.ModelAdmin):
    list_display = ['surgery', 'field', 'value', 'checked_by', 'checked_at']
    readonly_fields = ['surgery', 'field', 'value', 'checked_by', 'checked_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
