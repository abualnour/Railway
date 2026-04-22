from django.contrib import admin

from .models import InAppNotification, NotificationPreference


@admin.register(InAppNotification)
class InAppNotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "category", "level", "is_read", "email_sent", "created_at")
    list_filter = ("category", "level", "is_read", "email_sent", "created_at")
    search_fields = ("recipient__email", "title", "body")


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "payroll_management_in_app_enabled",
        "payroll_management_email_enabled",
        "payroll_employee_in_app_enabled",
        "payroll_employee_email_enabled",
        "payroll_employee_include_pdf_link",
        "email_enabled",
        "updated_at",
    )
    list_filter = (
        "payroll_management_in_app_enabled",
        "payroll_management_email_enabled",
        "payroll_employee_in_app_enabled",
        "payroll_employee_email_enabled",
        "payroll_employee_include_pdf_link",
        "email_enabled",
    )
    search_fields = ("user__email",)
