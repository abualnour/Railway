from django import forms

from .models import Employee


class EmployeeAdminActionCenterFilterForm(forms.Form):
    ACTION_DOCUMENT = "document"
    ACTION_LEAVE = "leave"
    ACTION_ACTION_RECORD = "action_record"
    ACTION_ATTENDANCE = "attendance"
    ACTION_HISTORY = "history"

    ACTION_CHOICES = [
        (ACTION_DOCUMENT, "Upload Document"),
        (ACTION_LEAVE, "Create Leave Request"),
        (ACTION_ACTION_RECORD, "Create Attendance / Incident Record"),
        (ACTION_ATTENDANCE, "Add Attendance Ledger Entry"),
        (ACTION_HISTORY, "Add Timeline Entry"),
    ]

    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        required=False,
        empty_label="Select employee",
        label="Employee",
    )
    action_type = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=False,
        label="Action Type",
    )

    def __init__(self, *args, **kwargs):
        employee_queryset = kwargs.pop("employee_queryset", Employee.objects.none())
        super().__init__(*args, **kwargs)

        self.fields["employee"].queryset = employee_queryset
        self.fields["action_type"].initial = self.ACTION_DOCUMENT

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()