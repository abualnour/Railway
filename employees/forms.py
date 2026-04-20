import re
from datetime import timedelta
from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from organization.models import Branch, Company, Department, JobTitle, Section

from .models import (
    BranchWeeklyScheduleTheme,
    BranchWeeklyDutyOption,
    BranchWeeklyScheduleEntry,
    BranchWeeklyPendingOff,
    Employee,
    EmployeeActionRecord,
    EmployeeAttendanceCorrection,
    EmployeeAttendanceEvent,
    EmployeeAttendanceLedger,
    EmployeeDocument,
    EmployeeHistory,
    EmployeeLeave,
    EmployeeRequiredSubmission,
    EmployeeDocumentRequest,
)

UserModel = get_user_model()


def infer_employee_account_role(job_title):
    title_name = ((getattr(job_title, "name", "") or "").strip())
    if not title_name:
        return "employee"

    if re.search(r"(?i)\boperations?\s*manager\b", title_name) or re.search(r"(?i)\boperation\s*manager\b", title_name):
        return "operations_manager"

    if (
        re.search(r"(?i)\bsupervisor\b", title_name)
    ):
        return "supervisor"

    return "employee"


def should_account_have_staff_access(role_value):
    # Business roles should use the HR-system permission layer, not Django admin-panel access.
    return False


class EmployeeForm(forms.ModelForm):
    login_email = forms.EmailField(
        required=False,
        label="Login Email",
        help_text="This email will be used as the employee login account.",
    )
    password1 = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label="Password",
        help_text="Set a password for first-time login or enter a new password to reset it.",
    )
    password2 = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        label="Confirm Password",
        help_text="Enter the same password again for confirmation.",
    )
    login_is_active = forms.BooleanField(
        required=False,
        initial=True,
        label="Login account is active",
        help_text="Turn this off to block this linked account from signing in.",
    )

    class Meta:
        model = Employee
        fields = [
            "full_name",
            "photo",
            "email",
            "phone",
            "birth_date",
            "marital_status",
            "nationality",
            "company",
            "department",
            "branch",
            "section",
            "job_title",
            "hire_date",
            "passport_reference_number",
            "passport_issue_date",
            "passport_expiry_date",
            "civil_id_reference_number",
            "civil_id_issue_date",
            "civil_id_expiry_date",
            "salary",
            "is_active",
            "notes",
        ]
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "hire_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "passport_issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "passport_expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "civil_id_issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "civil_id_expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for date_field_name in [
            "birth_date",
            "hire_date",
            "passport_issue_date",
            "passport_expiry_date",
            "civil_id_issue_date",
            "civil_id_expiry_date",
        ]:
            if date_field_name in self.fields:
                self.fields[date_field_name].input_formats = ["%Y-%m-%d"]

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.FileInput):
                widget.attrs["class"] = "form-control"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["section"].queryset = Section.objects.none()
        self.fields["job_title"].queryset = JobTitle.objects.none()

        self.account_history_messages = []
        self.saved_user_account = None
        self.account_save_action = None

        linked_user = getattr(self.instance, "user", None) if self.instance and self.instance.pk else None
        self._original_user_data = {
            "email": getattr(linked_user, "email", "") if linked_user else "",
            "is_active": getattr(linked_user, "is_active", True) if linked_user else True,
            "role": getattr(linked_user, "role", "") if linked_user else "",
        }

        if linked_user:
            self.fields["login_email"].initial = getattr(linked_user, "email", "")
            self.fields["login_is_active"].initial = getattr(linked_user, "is_active", True)

        department_id = None
        section_id = None

        if self.is_bound:
            department_id = self.data.get("department") or None
            section_id = self.data.get("section") or None
        elif self.instance.pk:
            department_id = self.instance.department_id
            section_id = self.instance.section_id

        if department_id:
            self.fields["section"].queryset = (
                Section.objects.filter(department_id=department_id, is_active=True).order_by("name")
            )

            job_titles_qs = JobTitle.objects.filter(
                department_id=department_id,
                is_active=True,
            )

            if section_id:
                job_titles_qs = job_titles_qs.filter(
                    Q(section_id=section_id) | Q(section__isnull=True)
                )
            else:
                job_titles_qs = job_titles_qs.filter(section__isnull=True)

            self.fields["job_title"].queryset = job_titles_qs.order_by("name")

    def _user_has_real_field(self, user, field_name):
        if not hasattr(user, "_meta"):
            return False
        try:
            user._meta.get_field(field_name)
            return True
        except Exception:
            return False


    def clean_login_email(self):
        login_email = (self.cleaned_data.get("login_email") or "").strip().lower()
        return login_email

    def _wants_login_account(self, cleaned_data):
        existing_user = getattr(self.instance, "user", None)
        login_email = cleaned_data.get("login_email")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")
        return bool(existing_user or login_email or password1 or password2)

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        section = cleaned_data.get("section")
        job_title = cleaned_data.get("job_title")
        login_email = cleaned_data.get("login_email")
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if section and department and section.department_id != department.id:
            self.add_error("section", "Selected section must belong to the selected department.")

        if job_title and department and job_title.department_id and job_title.department_id != department.id:
            self.add_error("job_title", "Selected job title must belong to the selected department.")

        if job_title and job_title.section_id:
            if not section:
                self.add_error("section", "A section is required for the selected job title.")
            elif section.id != job_title.section_id:
                self.add_error("job_title", "Selected job title must match the selected section.")

        birth_date = cleaned_data.get("birth_date")
        passport_issue_date = cleaned_data.get("passport_issue_date")
        passport_expiry_date = cleaned_data.get("passport_expiry_date")
        civil_id_issue_date = cleaned_data.get("civil_id_issue_date")
        civil_id_expiry_date = cleaned_data.get("civil_id_expiry_date")

        if birth_date and birth_date > timezone.localdate():
            self.add_error("birth_date", "Birth date cannot be in the future.")

        if passport_issue_date and passport_expiry_date and passport_issue_date > passport_expiry_date:
            self.add_error("passport_expiry_date", "Passport expiry date must be on or after the passport issue date.")

        if civil_id_issue_date and civil_id_expiry_date and civil_id_issue_date > civil_id_expiry_date:
            self.add_error("civil_id_expiry_date", "Civil ID expiry date must be on or after the Civil ID issue date.")

        if self._wants_login_account(cleaned_data):
            if not login_email:
                self.add_error("login_email", "Login email is required when creating or updating a login account.")

            existing_user_qs = UserModel.objects.filter(email__iexact=login_email)
            existing_linked_user = getattr(self.instance, "user", None)

            if existing_linked_user:
                existing_user_qs = existing_user_qs.exclude(pk=existing_linked_user.pk)

            if login_email and existing_user_qs.exists():
                self.add_error("login_email", "This login email is already used by another account.")

            if password1 or password2:
                if password1 != password2:
                    self.add_error("password2", "Password confirmation does not match.")
                elif len(password1) < 8:
                    self.add_error("password1", "Password must be at least 8 characters.")

        return cleaned_data

    def save(self, commit=True):
        employee = super().save(commit=False)

        cleaned_data = getattr(self, "cleaned_data", {})
        login_email = cleaned_data.get("login_email")
        password1 = cleaned_data.get("password1")
        login_is_active = cleaned_data.get("login_is_active", True)

        wants_login_account = self._wants_login_account(cleaned_data)
        linked_user = getattr(employee, "user", None)
        inferred_role = infer_employee_account_role(cleaned_data.get("job_title") or getattr(employee, "job_title", None))
        staff_access_flag = should_account_have_staff_access(inferred_role)

        if wants_login_account:
            if linked_user:
                user = linked_user
                self.account_save_action = "updated"
            else:
                create_kwargs = {
                    "email": login_email or "",
                    "password": password1,
                    "is_active": login_is_active,
                }
                if self._user_has_real_field(UserModel, "role"):
                    create_kwargs["role"] = inferred_role
                if self._user_has_real_field(UserModel, "is_staff"):
                    create_kwargs["is_staff"] = staff_access_flag
                user = UserModel.objects.create_user(**create_kwargs)
                self.account_save_action = "created"

            if self._user_has_real_field(user, "email"):
                user.email = login_email or ""

            if self._user_has_real_field(user, "is_active"):
                user.is_active = login_is_active

            if self._user_has_real_field(user, "role"):
                user.role = inferred_role

            if self._user_has_real_field(user, "is_staff") and not getattr(user, "is_superuser", False):
                user.is_staff = staff_access_flag

            if password1:
                user.set_password(password1)

            user.save()
            employee.user = user
            self.saved_user_account = user

            if self.account_save_action == "created":
                self.account_history_messages.append("Employee login account created.")
            else:
                self.account_history_messages.append("Employee login account updated.")

            if inferred_role == "operations_manager":
                self.account_history_messages.append("Linked login account role synced as Operations Manager.")
            elif inferred_role == "supervisor":
                self.account_history_messages.append("Linked login account role synced as Supervisor.")
            else:
                self.account_history_messages.append("Linked login account role synced as Employee.")

        if commit:
            employee.save()
            self.save_m2m()

        return employee


class EmployeeTransferForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "company",
            "department",
            "branch",
            "section",
            "job_title",
            "notes",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["section"].queryset = Section.objects.none()
        self.fields["job_title"].queryset = JobTitle.objects.none()

        department_id = None
        section_id = None

        if self.is_bound:
            department_id = self.data.get("department") or None
            section_id = self.data.get("section") or None
        elif self.instance.pk:
            department_id = self.instance.department_id
            section_id = self.instance.section_id

        if department_id:
            self.fields["section"].queryset = (
                Section.objects.filter(department_id=department_id, is_active=True).order_by("name")
            )

            job_titles_qs = JobTitle.objects.filter(
                department_id=department_id,
                is_active=True,
            )

            if section_id:
                job_titles_qs = job_titles_qs.filter(
                    Q(section_id=section_id) | Q(section__isnull=True)
                )
            else:
                job_titles_qs = job_titles_qs.filter(section__isnull=True)

            self.fields["job_title"].queryset = job_titles_qs.order_by("name")

        self.fields["notes"].required = False
        self.fields["notes"].widget = forms.Textarea(
            attrs={
                "rows": 4,
                "class": "form-control",
                "placeholder": "Optional transfer note or movement explanation...",
            }
        )

    def clean(self):
        cleaned_data = super().clean()

        department = cleaned_data.get("department")
        section = cleaned_data.get("section")
        job_title = cleaned_data.get("job_title")

        if section and department and section.department_id != department.id:
            self.add_error("section", "Selected section must belong to the selected department.")

        if job_title and department and job_title.department_id and job_title.department_id != department.id:
            self.add_error("job_title", "Selected job title must belong to the selected department.")

        if job_title and job_title.section_id:
            if not section:
                self.add_error("section", "A section is required for the selected job title.")
            elif section.id != job_title.section_id:
                self.add_error("job_title", "Selected job title must match the selected section.")

        return cleaned_data


class EmployeeDocumentForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocument
        fields = [
            "title",
            "document_type",
            "reference_number",
            "is_required",
            "file",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Optional document description or compliance note...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["title"].required = False
        self.fields["reference_number"].required = False
        self.fields["description"].required = False

    def clean_title(self):
        title = self.cleaned_data.get("title", "")
        return title.strip()

    def clean_reference_number(self):
        reference_number = self.cleaned_data.get("reference_number", "")
        return reference_number.strip()


class EmployeeRequiredSubmissionCreateForm(forms.ModelForm):
    class Meta:
        model = EmployeeRequiredSubmission
        fields = [
            "title",
            "request_type",
            "priority",
            "due_date",
            "instructions",
        ]
        widgets = {
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "instructions": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Explain what is missing, what should be uploaded, and any compliance note or deadline...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["instructions"].required = False

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Request title is required.")
        return title

    def clean_instructions(self):
        return (self.cleaned_data.get("instructions") or "").strip()


class EmployeeRequiredSubmissionResponseForm(forms.ModelForm):
    class Meta:
        model = EmployeeRequiredSubmission
        fields = [
            "response_file",
            "response_reference_number",
            "response_issue_date",
            "response_expiry_date",
            "employee_note",
        ]
        widgets = {
            "response_issue_date": forms.DateInput(attrs={"type": "date"}),
            "response_expiry_date": forms.DateInput(attrs={"type": "date"}),
            "employee_note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Add any note for management about this submitted file...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["response_reference_number"].required = False
        self.fields["employee_note"].required = False

    def clean_employee_note(self):
        return (self.cleaned_data.get("employee_note") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        response_file = cleaned_data.get("response_file")
        issue_date = cleaned_data.get("response_issue_date")
        expiry_date = cleaned_data.get("response_expiry_date")

        if not response_file and not getattr(self.instance, "response_file", None):
            self.add_error("response_file", "Please upload the requested file before submitting.")

        if issue_date and expiry_date and expiry_date < issue_date:
            self.add_error("response_expiry_date", "Response expiry date cannot be earlier than response issue date.")

        return cleaned_data




class EmployeeDocumentRequestCreateForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocumentRequest
        fields = [
            "title",
            "request_type",
            "priority",
            "needed_by_date",
            "request_note",
        ]
        widgets = {
            "needed_by_date": forms.DateInput(attrs={"type": "date"}),
            "request_note": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Explain what you need from HR or management and add any purpose, embassy, bank, or official use note...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["request_note"].required = False

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Request title is required.")
        return title

    def clean_request_note(self):
        return (self.cleaned_data.get("request_note") or "").strip()


class EmployeeDocumentRequestReviewForm(forms.ModelForm):
    class Meta:
        model = EmployeeDocumentRequest
        fields = [
            "status",
            "management_note",
            "response_file",
        ]
        widgets = {
            "management_note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Add a review note, completion note, or rejection reason for the employee...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (EmployeeDocumentRequest.STATUS_APPROVED, "Approved / In Progress"),
            (EmployeeDocumentRequest.STATUS_COMPLETED, "Completed With File"),
            (EmployeeDocumentRequest.STATUS_REJECTED, "Rejected"),
            (EmployeeDocumentRequest.STATUS_CANCELLED, "Cancelled"),
        ]
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["management_note"].required = False
        self.fields["response_file"].required = False

    def clean_management_note(self):
        return (self.cleaned_data.get("management_note") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get("status")
        response_file = cleaned_data.get("response_file")

        if status == EmployeeDocumentRequest.STATUS_COMPLETED and not response_file and not getattr(self.instance, "response_file", None):
            self.add_error("response_file", "A reply file is required when completing the employee document request.")

        return cleaned_data

class EmployeeRequiredSubmissionReviewForm(forms.ModelForm):
    class Meta:
        model = EmployeeRequiredSubmission
        fields = ["status", "review_note"]
        widgets = {
            "review_note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Optional manager review note, correction note, or completion note...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (EmployeeRequiredSubmission.STATUS_COMPLETED, "Completed"),
            (EmployeeRequiredSubmission.STATUS_NEEDS_CORRECTION, "Needs Correction"),
            (EmployeeRequiredSubmission.STATUS_CANCELLED, "Cancelled"),
        ]
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["review_note"].required = False

    def clean_review_note(self):
        return (self.cleaned_data.get("review_note") or "").strip()


class EmployeeActionRecordForm(forms.ModelForm):
    class Meta:
        model = EmployeeActionRecord
        fields = [
            "action_type",
            "action_date",
            "title",
            "description",
            "status",
            "severity",
        ]
        widgets = {
            "action_date": forms.DateInput(attrs={"type": "date"}),
            "title": forms.TextInput(
                attrs={
                    "placeholder": "Example: Unapproved absence, late opening, written warning, appreciation memo"
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Record the full attendance, incident, or discipline details here.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["description"].required = False

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Record title is required.")
        return title

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()


class EmployeeAttendanceLedgerForm(forms.ModelForm):
    class Meta:
        model = EmployeeAttendanceLedger
        fields = [
            "attendance_date",
            "day_status",
            "shift",
            "clock_in_time",
            "clock_out_time",
            "scheduled_hours",
            "notes",
        ]
        widgets = {
            "attendance_date": forms.DateInput(attrs={"type": "date"}),
            "clock_in_time": forms.TimeInput(attrs={"type": "time"}),
            "clock_out_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Optional attendance note, audit note, or daily exception detail.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        self.employee = kwargs.pop("employee", None)
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["clock_in_time"].required = False
        self.fields["clock_out_time"].required = False
        self.fields["notes"].required = False
        self.fields["scheduled_hours"].required = False
        self.fields["shift"].required = False

        self.fields["scheduled_hours"].initial = "8.00"

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned_data = super().clean()

        attendance_date = cleaned_data.get("attendance_date")
        day_status = cleaned_data.get("day_status")
        shift = cleaned_data.get("shift")
        clock_in_time = cleaned_data.get("clock_in_time")
        clock_out_time = cleaned_data.get("clock_out_time")
        scheduled_hours = cleaned_data.get("scheduled_hours")

        zero_work_statuses = {
            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
            EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF,
            EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY,
        }

        if not attendance_date:
            self.add_error("attendance_date", "Attendance date is required.")

        if self.employee and attendance_date:
            duplicate_qs = EmployeeAttendanceLedger.objects.filter(
                employee=self.employee,
                attendance_date=attendance_date,
            )

            if self.instance and self.instance.pk:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)

            if duplicate_qs.exists():
                self.add_error(
                    "attendance_date",
                    "An attendance ledger entry already exists for this employee on the selected date.",
                )

            if self.employee.hire_date and attendance_date < self.employee.hire_date:
                self.add_error(
                    "attendance_date",
                    "Attendance date cannot be earlier than the employee hire date.",
                )

        if day_status in zero_work_statuses:
            if shift:
                self.add_error("shift", "Shift is only allowed for working attendance days.")
            if clock_in_time or clock_out_time:
                self.add_error("clock_in_time", "Clock times are only allowed for working attendance days.")
        else:
            if not shift:
                self.add_error("shift", "Shift selection is required for working attendance days.")
            if not clock_in_time:
                self.add_error("clock_in_time", "Clock-in time is required for working attendance days.")
            if not clock_out_time:
                self.add_error("clock_out_time", "Clock-out time is required for working attendance days.")

            if clock_in_time and clock_out_time:
                temp_entry = EmployeeAttendanceLedger(
                    employee=self.employee,
                    attendance_date=attendance_date,
                    day_status=day_status,
                    shift=shift,
                    clock_in_time=clock_in_time,
                    clock_out_time=clock_out_time,
                    scheduled_hours=scheduled_hours or Decimal("0.00"),
                )
                normalized_clock_in, normalized_clock_out = temp_entry.get_attendance_window()
                if not normalized_clock_in or not normalized_clock_out or normalized_clock_out <= normalized_clock_in:
                    self.add_error("clock_out_time", "Clock-out time must be later than clock-in time for the selected shift.")

        if scheduled_hours in [None, ""]:
            self.add_error("scheduled_hours", "Scheduled hours are required.")
        elif scheduled_hours <= 0:
            self.add_error("scheduled_hours", "Scheduled hours must be greater than zero.")

        if scheduled_hours is not None and scheduled_hours < 0:
            self.add_error("scheduled_hours", "Scheduled hours cannot be negative.")

        return cleaned_data


class EmployeeAttendanceCorrectionForm(forms.ModelForm):
    class Meta:
        model = EmployeeAttendanceCorrection
        fields = [
            "requested_day_status",
            "requested_clock_in_time",
            "requested_clock_out_time",
            "requested_scheduled_hours",
            "requested_late_minutes",
            "requested_early_departure_minutes",
            "requested_overtime_minutes",
            "requested_notes",
            "request_reason",
        ]
        widgets = {
            "requested_clock_in_time": forms.TimeInput(attrs={"type": "time"}),
            "requested_clock_out_time": forms.TimeInput(attrs={"type": "time"}),
            "requested_notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional correction note for the final attendance row."}
            ),
            "request_reason": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Why should this attendance row be corrected?"}
            ),
        }

    def __init__(self, *args, **kwargs):
        self.attendance_entry = kwargs.pop("attendance_entry", None)
        super().__init__(*args, **kwargs)

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["requested_clock_in_time"].required = False
        self.fields["requested_clock_out_time"].required = False
        self.fields["requested_notes"].required = False
        self.fields["requested_scheduled_hours"].required = False
        self.fields["requested_late_minutes"].required = False
        self.fields["requested_early_departure_minutes"].required = False
        self.fields["requested_overtime_minutes"].required = False

        self.fields["requested_scheduled_hours"].initial = "8.00"
        self.fields["requested_late_minutes"].initial = 0
        self.fields["requested_early_departure_minutes"].initial = 0
        self.fields["requested_overtime_minutes"].initial = 0

    def clean_requested_notes(self):
        return (self.cleaned_data.get("requested_notes") or "").strip()

    def clean_request_reason(self):
        value = (self.cleaned_data.get("request_reason") or "").strip()
        if not value:
            raise forms.ValidationError("Correction reason is required.")
        return value

    def clean(self):
        cleaned_data = super().clean()

        day_status = cleaned_data.get("requested_day_status")
        clock_in_time = cleaned_data.get("requested_clock_in_time")
        clock_out_time = cleaned_data.get("requested_clock_out_time")
        scheduled_hours = cleaned_data.get("requested_scheduled_hours")
        late_minutes = cleaned_data.get("requested_late_minutes")
        early_departure_minutes = cleaned_data.get("requested_early_departure_minutes")
        overtime_minutes = cleaned_data.get("requested_overtime_minutes")

        zero_work_statuses = {
            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
            EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF,
            EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY,
        }

        if clock_in_time and clock_out_time and clock_out_time <= clock_in_time:
            self.add_error("requested_clock_out_time", "Clock-out time must be later than clock-in time.")

        if (clock_in_time and not clock_out_time) or (clock_out_time and not clock_in_time):
            missing_field = "requested_clock_out_time" if clock_in_time and not clock_out_time else "requested_clock_in_time"
            self.add_error(missing_field, "Both clock-in and clock-out times are required when correcting a working-day time window.")

        if day_status in zero_work_statuses and (clock_in_time or clock_out_time):
            self.add_error("requested_clock_in_time", "Clock times are only allowed for real attendance days.")

        if day_status in zero_work_statuses:
            if late_minutes not in [None, 0]:
                self.add_error("requested_late_minutes", "Late minutes must be zero for non-working attendance statuses.")
            if early_departure_minutes not in [None, 0]:
                self.add_error(
                    "requested_early_departure_minutes",
                    "Early departure minutes must be zero for non-working attendance statuses.",
                )

        if day_status not in zero_work_statuses and scheduled_hours in [None, ""]:
            self.add_error("requested_scheduled_hours", "Scheduled hours are required for working attendance days.")
        elif scheduled_hours is not None and scheduled_hours <= 0 and day_status not in zero_work_statuses:
            self.add_error("requested_scheduled_hours", "Scheduled hours must be greater than zero for working attendance days.")

        if scheduled_hours is not None and scheduled_hours < 0:
            self.add_error("requested_scheduled_hours", "Scheduled hours cannot be negative.")

        if late_minutes is not None and late_minutes < 0:
            self.add_error("requested_late_minutes", "Late minutes cannot be negative.")

        if early_departure_minutes is not None and early_departure_minutes < 0:
            self.add_error("requested_early_departure_minutes", "Early departure minutes cannot be negative.")

        if overtime_minutes is not None and overtime_minutes < 0:
            self.add_error("requested_overtime_minutes", "Overtime minutes cannot be negative.")

        if self.attendance_entry and self.attendance_entry.employee.hire_date:
            attendance_date = self.attendance_entry.attendance_date
            if attendance_date < self.attendance_entry.employee.hire_date:
                self.add_error("requested_day_status", "Attendance date cannot be earlier than the employee hire date.")

        if self.attendance_entry and not self.errors:
            comparison_fields = [
                "requested_day_status",
                "requested_clock_in_time",
                "requested_clock_out_time",
                "requested_scheduled_hours",
                "requested_late_minutes",
                "requested_early_departure_minutes",
                "requested_overtime_minutes",
                "requested_notes",
            ]
            unchanged = all(
                cleaned_data.get(field_name) == getattr(self.attendance_entry, field_name.replace("requested_", ""))
                for field_name in comparison_fields
            )
            if unchanged:
                raise forms.ValidationError(
                    "Update at least one attendance value before submitting a correction request."
                )

        return cleaned_data


class EmployeeSelfServiceAttendanceForm(forms.Form):
    shift = forms.ChoiceField(
        choices=EmployeeAttendanceLedger.SHIFT_CHOICES,
        label="Shift",
    )
    latitude = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        label="Latitude",
        widget=forms.HiddenInput(),
    )
    longitude = forms.DecimalField(
        required=False,
        max_digits=9,
        decimal_places=6,
        label="Longitude",
        widget=forms.HiddenInput(),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Optional duty note for today."}),
        label="Notes",
    )

    def __init__(self, *args, **kwargs):
        shift_choices = kwargs.pop("shift_choices", None)
        shift_locked = kwargs.pop("shift_locked", False)
        super().__init__(*args, **kwargs)
        if shift_choices:
            self.fields["shift"].choices = shift_choices
        if shift_locked:
            self.fields["shift"].help_text = "This attendance shift is controlled by today's assigned duty."
            self.fields["shift"].disabled = True
        for field_name, field in self.fields.items():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if not isinstance(widget, forms.HiddenInput):
                field.widget.attrs["class"] = f"{existing} form-control".strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get("latitude")
        longitude = cleaned_data.get("longitude")

        if (latitude is None) != (longitude is None):
            raise forms.ValidationError("Both latitude and longitude are required when capturing live device location.")

        if latitude is None or longitude is None:
            raise forms.ValidationError("Use your live device location before saving attendance.")

        return cleaned_data


class EmployeeHistoryForm(forms.ModelForm):
    class Meta:
        model = EmployeeHistory
        fields = ["event_type", "title", "description", "event_date"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "event_date": forms.DateInput(attrs={"type": "date"}),
            "title": forms.TextInput(
                attrs={"placeholder": "Example: Verbal warning, onboarding completed, file corrected"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Timeline title is required.")
        return title


class EmployeeLeaveForm(forms.ModelForm):
    class Meta:
        model = EmployeeLeave
        fields = [
            "leave_type",
            "start_date",
            "end_date",
            "reason",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Optional reason or note for this leave request...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["reason"].required = False

    def clean_reason(self):
        return (self.cleaned_data.get("reason") or "").strip()

    def clean(self):
        cleaned_data = super().clean()

        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be earlier than start date.")

        return cleaned_data


class EmployeeSelfServiceLeaveRequestForm(EmployeeLeaveForm):
    attachment_title = forms.CharField(
        required=False,
        max_length=255,
        label="Attachment Title",
    )
    attachment_document_type = forms.ChoiceField(
        required=False,
        choices=EmployeeDocument.DOCUMENT_TYPE_CHOICES,
        initial=EmployeeDocument.DOCUMENT_TYPE_OTHER,
        label="Attachment Type",
    )
    attachment_reference_number = forms.CharField(
        required=False,
        max_length=120,
        label="Reference Number",
    )
    attachment_issue_date = forms.DateField(
        required=False,
        label="Attachment Issue Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    attachment_expiry_date = forms.DateField(
        required=False,
        label="Attachment Expiry Date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    attachment_description = forms.CharField(
        required=False,
        label="Attachment Description",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Optional supporting document note or explanation...",
            }
        ),
    )
    attachment_file = forms.FileField(
        required=False,
        label="Supporting Document",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        attachment_fields = [
            "attachment_title",
            "attachment_document_type",
            "attachment_reference_number",
            "attachment_issue_date",
            "attachment_expiry_date",
            "attachment_description",
            "attachment_file",
        ]

        for field_name in attachment_fields:
            field = self.fields[field_name]
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["attachment_title"].widget.attrs.setdefault(
            "placeholder",
            "Example: Sick leave medical certificate",
        )
        self.fields["attachment_reference_number"].widget.attrs.setdefault(
            "placeholder",
            "Optional document reference number",
        )

    def clean_attachment_title(self):
        return (self.cleaned_data.get("attachment_title") or "").strip()

    def clean_attachment_reference_number(self):
        return (self.cleaned_data.get("attachment_reference_number") or "").strip()

    def clean_attachment_description(self):
        return (self.cleaned_data.get("attachment_description") or "").strip()

    def clean_attachment_issue_date(self):
        return self.cleaned_data.get("attachment_issue_date")

    def clean_attachment_expiry_date(self):
        return self.cleaned_data.get("attachment_expiry_date")

    def clean(self):
        cleaned_data = super().clean()

        attachment_file = cleaned_data.get("attachment_file")
        attachment_title = cleaned_data.get("attachment_title")
        attachment_reference_number = cleaned_data.get("attachment_reference_number")
        attachment_description = cleaned_data.get("attachment_description")
        attachment_document_type = cleaned_data.get("attachment_document_type")
        attachment_issue_date = cleaned_data.get("attachment_issue_date")
        attachment_expiry_date = cleaned_data.get("attachment_expiry_date")

        has_attachment_metadata = any(
            [
                attachment_title,
                attachment_reference_number,
                attachment_description,
                attachment_issue_date,
                attachment_expiry_date,
                attachment_document_type
                and attachment_document_type != EmployeeDocument.DOCUMENT_TYPE_OTHER,
            ]
        )

        if has_attachment_metadata and not attachment_file:
            self.add_error(
                "attachment_file",
                "Please upload the supporting document file or remove the attachment details.",
            )

        if attachment_issue_date and attachment_expiry_date and attachment_expiry_date < attachment_issue_date:
            self.add_error(
                "attachment_expiry_date",
                "Attachment expiry date cannot be earlier than the attachment issue date.",
            )

        return cleaned_data


class BranchWeeklyScheduleEntryForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyScheduleEntry
        fields = [
            "employee",
            "schedule_date",
            "duty_option",
            "title",
            "order_note",
            "status",
        ]
        widgets = {
            "schedule_date": forms.DateInput(attrs={"type": "date"}),
            "order_note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Add the weekly schedule details, branch orders, or follow-up note for the team member.",
                }
            ),
        }

    def __init__(self, *args, branch=None, week_start=None, **kwargs):
        self.branch = branch
        self.week_start = week_start
        super().__init__(*args, **kwargs)

        if self.branch is not None:
            self.fields["employee"].queryset = (
                Employee.objects.select_related("job_title", "section")
                .filter(branch=self.branch, is_active=True)
                .order_by("full_name", "employee_id")
            )
            self.fields["duty_option"].queryset = (
                BranchWeeklyDutyOption.objects.filter(branch=self.branch, is_active=True).order_by("display_order", "label")
            )
            self.fields["duty_option"].label_from_instance = lambda option: option.preview_label
        else:
            self.fields["employee"].queryset = Employee.objects.none()
            self.fields["duty_option"].queryset = BranchWeeklyDutyOption.objects.none()

        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

        self.fields["order_note"].required = False
        self.fields["title"].required = False
        self.fields["duty_option"].label = "Duty Option"
        self.fields["title"].label = "Custom Label"
        self.fields["order_note"].label = "Orders / Notes"
        self.fields["title"].widget.attrs.setdefault(
            "placeholder",
            "Only needed when using a custom duty label",
        )

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean_order_note(self):
        return (self.cleaned_data.get("order_note") or "").strip()

    def clean(self):
        cleaned_data = super().clean()

        employee = cleaned_data.get("employee")
        schedule_date = cleaned_data.get("schedule_date")
        duty_option = cleaned_data.get("duty_option")
        title = cleaned_data.get("title")

        if self.branch is not None and employee and employee.branch_id != self.branch.id:
            self.add_error("employee", "Selected employee must belong to this branch.")

        if self.week_start and schedule_date:
            week_end = self.week_start + timedelta(days=6)
            if schedule_date < self.week_start or schedule_date > week_end:
                self.add_error(
                    "schedule_date",
                    "Schedule date must stay inside the selected branch week.",
                )

        if not duty_option:
            self.add_error("duty_option", "Please select a duty option from the list.")
        elif duty_option.branch_id != self.branch.id:
            self.add_error("duty_option", "Selected duty option must belong to this branch.")

        if duty_option and duty_option.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM and not title:
            self.add_error("title", "Custom duty needs a short label.")

        return cleaned_data


class BranchWeeklyDutyOptionForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyDutyOption
        fields = [
            "label",
            "duty_type",
            "default_start_time",
            "default_end_time",
            "background_color",
            "text_color",
            "display_order",
            "is_active",
        ]
        widgets = {
            "default_start_time": forms.TimeInput(attrs={"type": "time"}),
            "default_end_time": forms.TimeInput(attrs={"type": "time"}),
            "background_color": forms.TextInput(attrs={"type": "color"}),
            "text_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()
        self.fields["label"].widget.attrs.setdefault("placeholder", "Example: 2 pm to 10 pm")
        self.fields["background_color"].widget.attrs.setdefault("value", "#2563eb")
        self.fields["text_color"].widget.attrs.setdefault("value", "#f8fafc")

    def clean_label(self):
        label = (self.cleaned_data.get("label") or "").strip()
        if not label:
            raise forms.ValidationError("Duty option label is required.")
        return label


class BranchWeeklyDutyOptionStyleForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyDutyOption
        fields = ["background_color", "text_color"]
        widgets = {
            "background_color": forms.TextInput(attrs={"type": "color"}),
            "text_color": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()


class BranchWeeklyDutyOptionTimingForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyDutyOption
        fields = ["default_start_time", "default_end_time"]
        widgets = {
            "default_start_time": forms.TimeInput(attrs={"type": "time"}),
            "default_end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()


class BranchWeeklyScheduleThemeForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyScheduleTheme
        fields = [
            "employee_column_bg",
            "employee_column_text",
            "job_title_column_bg",
            "job_title_column_text",
            "pending_off_column_bg",
            "pending_off_column_text",
            "day_header_bg",
            "day_header_text",
        ]
        widgets = {
            "employee_column_bg": forms.TextInput(attrs={"type": "color"}),
            "employee_column_text": forms.TextInput(attrs={"type": "color"}),
            "job_title_column_bg": forms.TextInput(attrs={"type": "color"}),
            "job_title_column_text": forms.TextInput(attrs={"type": "color"}),
            "pending_off_column_bg": forms.TextInput(attrs={"type": "color"}),
            "pending_off_column_text": forms.TextInput(attrs={"type": "color"}),
            "day_header_bg": forms.TextInput(attrs={"type": "color"}),
            "day_header_text": forms.TextInput(attrs={"type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()


class BranchWeeklyPendingOffForm(forms.ModelForm):
    class Meta:
        model = BranchWeeklyPendingOff
        fields = ["employee", "pending_off_count"]

    def __init__(self, *args, branch=None, **kwargs):
        self.branch = branch
        super().__init__(*args, **kwargs)
        if self.branch is not None:
            self.fields["employee"].queryset = (
                Employee.objects.filter(branch=self.branch, is_active=True)
                .select_related("job_title")
                .order_by("full_name", "employee_id")
            )
        else:
            self.fields["employee"].queryset = Employee.objects.none()

        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

    def clean(self):
        cleaned_data = super().clean()
        employee = cleaned_data.get("employee")
        if self.branch is not None and employee and employee.branch_id != self.branch.id:
            self.add_error("employee", "Selected employee must belong to this branch.")
        return cleaned_data


class BranchWeeklyScheduleImportForm(forms.Form):
    import_file = forms.FileField(
        label="Google Sheet / Excel File",
        help_text="Upload an .xlsx or .csv file exported from Google Sheets or Excel.",
    )
    replace_existing = forms.BooleanField(
        required=False,
        initial=True,
        label="Replace current week entries before import",
        help_text="Keep this checked for a full week replacement. If unchecked, the import only updates non-empty cells and leaves the current sheet in place.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

    def clean_import_file(self):
        uploaded_file = self.cleaned_data.get("import_file")
        if not uploaded_file:
            return uploaded_file

        filename = (uploaded_file.name or "").lower()
        if not (filename.endswith(".xlsx") or filename.endswith(".csv")):
            raise forms.ValidationError("Only .xlsx and .csv files are supported for schedule import.")
        return uploaded_file


class AttendanceFilterForm(forms.Form):
    FILTER_THIS_MONTH = "this_month"
    FILTER_LAST_MONTH = "last_month"
    FILTER_CUSTOM = "custom"
    FILTER_ALL = "all"

    FILTER_CHOICES = [
        (FILTER_THIS_MONTH, "This Month"),
        (FILTER_LAST_MONTH, "Last Month"),
        (FILTER_CUSTOM, "Custom Range"),
        (FILTER_ALL, "All Records"),
    ]

    filter_type = forms.ChoiceField(
        choices=FILTER_CHOICES,
        required=False,
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["filter_type"].initial = self.FILTER_THIS_MONTH

        for field in self.fields.values():
            existing = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing} form-control".strip()

    def clean(self):
        cleaned_data = super().clean()
        filter_type = cleaned_data.get("filter_type") or self.FILTER_THIS_MONTH
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if filter_type == self.FILTER_CUSTOM:
            if not start_date:
                self.add_error("start_date", "Start date is required for a custom attendance range.")
            if not end_date:
                self.add_error("end_date", "End date is required for a custom attendance range.")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be earlier than start date.")

        return cleaned_data

    @staticmethod
    def default_initial():
        today = timezone.localdate()
        return {
            "filter_type": AttendanceFilterForm.FILTER_THIS_MONTH,
            "start_date": today.replace(day=1),
            "end_date": today,
        }


class AttendanceManagementFilterForm(forms.Form):
    search = forms.CharField(
        required=False,
        label="Search",
    )
    employee = forms.ModelChoiceField(
        required=False,
        queryset=Employee.objects.none(),
        label="Employee",
        empty_label="All Employees",
    )
    company = forms.ModelChoiceField(
        required=False,
        queryset=Company.objects.none(),
        label="Company",
        empty_label="All Companies",
    )
    branch = forms.ModelChoiceField(
        required=False,
        queryset=Branch.objects.none(),
        label="Branch",
        empty_label="All Branches",
    )
    department = forms.ModelChoiceField(
        required=False,
        queryset=Department.objects.none(),
        label="Department",
        empty_label="All Departments",
    )
    section = forms.ModelChoiceField(
        required=False,
        queryset=Section.objects.none(),
        label="Section",
        empty_label="All Sections",
    )
    day_status = forms.ChoiceField(
        required=False,
        label="Day Status",
        choices=[("", "All Statuses")] + list(EmployeeAttendanceLedger.DAY_STATUS_CHOICES),
    )
    filter_type = forms.ChoiceField(
        required=False,
        choices=AttendanceFilterForm.FILTER_CHOICES,
        label="Range",
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Start Date",
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="End Date",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["employee"].queryset = Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        ).order_by("full_name", "employee_id")
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
        self.fields["section"].queryset = Section.objects.filter(is_active=True).order_by("name")
        self.fields["filter_type"].initial = AttendanceFilterForm.FILTER_THIS_MONTH

        self.fields["search"].widget.attrs.setdefault(
            "placeholder",
            "Search by employee, ID, email, notes, or document source",
        )

        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

    def clean_search(self):
        return (self.cleaned_data.get("search") or "").strip()

    def clean(self):
        cleaned_data = super().clean()
        filter_type = cleaned_data.get("filter_type") or AttendanceFilterForm.FILTER_THIS_MONTH
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if filter_type == AttendanceFilterForm.FILTER_CUSTOM:
            if not start_date:
                self.add_error("start_date", "Start date is required for a custom attendance range.")
            if not end_date:
                self.add_error("end_date", "End date is required for a custom attendance range.")

        if start_date and end_date and end_date < start_date:
            self.add_error("end_date", "End date cannot be earlier than start date.")

        return cleaned_data

    @staticmethod
    def default_initial():
        initial = AttendanceFilterForm.default_initial()
        initial.update(
            {
                "search": "",
                "employee": None,
                "company": None,
                "branch": None,
                "department": None,
                "section": None,
                "day_status": "",
            }
        )
        return initial
