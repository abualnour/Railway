from django import forms

from .models import NotificationPreference


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            "payroll_management_in_app_enabled",
            "payroll_management_email_enabled",
            "payroll_employee_in_app_enabled",
            "payroll_employee_email_enabled",
            "payroll_employee_include_pdf_link",
            "email_enabled",
            "request_in_app_enabled",
            "operations_in_app_enabled",
            "schedule_in_app_enabled",
            "employee_in_app_enabled",
            "hr_in_app_enabled",
            "contract_in_app_enabled",
            "calendar_in_app_enabled",
        ]
        labels = {
            "payroll_management_in_app_enabled": "In-app workflow alerts",
            "payroll_management_email_enabled": "Email workflow alerts",
            "payroll_employee_in_app_enabled": "In-app payslip delivery alerts",
            "payroll_employee_email_enabled": "Email payslip delivery alerts",
            "payroll_employee_include_pdf_link": "Include direct PDF link",
            "email_enabled": "Email notifications for in-app alerts",
            "request_in_app_enabled": "Requests and approvals",
            "operations_in_app_enabled": "Branch operations and tasks",
            "schedule_in_app_enabled": "Schedule updates",
            "employee_in_app_enabled": "Employee status and attendance",
            "hr_in_app_enabled": "HR announcements and policies",
            "contract_in_app_enabled": "Contract reminders and expiries",
            "calendar_in_app_enabled": "Calendar and holiday updates",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-check-input".strip()
