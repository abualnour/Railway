# Phase 2 Model Quality Replacement Files

## employees/models.py

```python
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from organization.models import Branch, Company, Department, JobTitle, Section


class EmployeeLeaveQuerySet(models.QuerySet):
    def active_statuses(self):
        return self.exclude(status=EmployeeLeave.STATUS_CANCELLED)


def employee_document_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    employee_code = instance.employee.employee_id or f"employee-{instance.employee_id}"
    employee_slug = slugify(instance.employee.full_name) or f"employee-{instance.employee_id}"
    unique_name = uuid4().hex
    return f"employees/documents/{employee_code}-{employee_slug}/{unique_name}{extension}"


def employee_submission_request_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    employee_code = instance.employee.employee_id or f"employee-{instance.employee_id}"
    employee_slug = slugify(instance.employee.full_name) or f"employee-{instance.employee_id}"
    unique_name = uuid4().hex
    return f"employees/submission-requests/{employee_code}-{employee_slug}/{unique_name}{extension}"


def employee_leave_delivery_upload_to(instance, filename):
    return employee_submission_request_upload_to(instance, filename)


def employee_management_request_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    employee_code = instance.employee.employee_id or f"employee-{instance.employee_id}"
    employee_slug = slugify(instance.employee.full_name) or f"employee-{instance.employee_id}"
    unique_name = uuid4().hex
    return f"employees/document-requests/{employee_code}-{employee_slug}/{unique_name}{extension}"


class Employee(models.Model):
    EMPLOYMENT_STATUS_ACTIVE = "active"
    EMPLOYMENT_STATUS_INACTIVE = "inactive"
    EMPLOYMENT_STATUS_ON_LEAVE = "on_leave"
    EMPLOYMENT_STATUS_EMERGENCY_LEAVE = "emergency_leave"
    EMPLOYMENT_STATUS_UNPAID_LEAVE = "unpaid_leave"

    EMPLOYMENT_STATUS_CHOICES = [
        (EMPLOYMENT_STATUS_ACTIVE, "Active"),
        (EMPLOYMENT_STATUS_INACTIVE, "Inactive"),
        (EMPLOYMENT_STATUS_ON_LEAVE, "On Leave"),
        (EMPLOYMENT_STATUS_EMERGENCY_LEAVE, "Emergency Leave"),
        (EMPLOYMENT_STATUS_UNPAID_LEAVE, "Unpaid Leave"),
    ]
    MARITAL_STATUS_SINGLE = "single"
    MARITAL_STATUS_MARRIED = "married"
    MARITAL_STATUS_DIVORCED = "divorced"
    MARITAL_STATUS_WIDOWED = "widowed"

    MARITAL_STATUS_CHOICES = [
        (MARITAL_STATUS_SINGLE, "Single"),
        (MARITAL_STATUS_MARRIED, "Married"),
        (MARITAL_STATUS_DIVORCED, "Divorced"),
        (MARITAL_STATUS_WIDOWED, "Widowed"),
    ]
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="employee_profile",
        null=True,
        blank=True,
    )
    employee_id = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    photo = models.ImageField(
        upload_to="employees/photos/",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="employees",
        null=True,
        blank=True,
    )
    job_title = models.ForeignKey(
        JobTitle,
        on_delete=models.PROTECT,
        related_name="employees",
    )

    hire_date = models.DateField(null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    marital_status = models.CharField(
        max_length=20,
        choices=MARITAL_STATUS_CHOICES,
        blank=True,
        default="",
    )
    nationality = models.CharField(max_length=100, blank=True, default="")
    passport_reference_number = models.CharField(max_length=100, blank=True, default="")
    passport_issue_date = models.DateField(null=True, blank=True)
    passport_expiry_date = models.DateField(null=True, blank=True)
    civil_id_reference_number = models.CharField(max_length=100, blank=True, default="")
    civil_id_issue_date = models.DateField(null=True, blank=True)
    civil_id_expiry_date = models.DateField(null=True, blank=True)
    is_kuwaiti_national = models.BooleanField(default=False)
    pifss_registration_number = models.CharField(max_length=50, blank=True)
    salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    notes = models.TextField(blank=True)
    employment_status = models.CharField(
        max_length=30,
        choices=EMPLOYMENT_STATUS_CHOICES,
        default=EMPLOYMENT_STATUS_ACTIVE,
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_id", "full_name"]
        indexes = [
            models.Index(fields=["company", "is_active", "employment_status"]),
            models.Index(fields=["branch", "is_active", "full_name"]),
            models.Index(fields=["department", "is_active", "full_name"]),
        ]
        verbose_name = "Employee"
        verbose_name_plural = "Employees"

    def __str__(self):
        return f"{self.employee_id} - {self.full_name}"

    def clean(self):
        errors = {}

        # Shared company assignment rule:
        # the employee's company can be selected independently from the
        # structural company that owns the department or branch record.
        # Department and branch still remain real organization records,
        # but employee assignment is allowed to reuse them across companies.

        if self.section_id and self.department_id:
            if self.section.department_id != self.department_id:
                errors["section"] = "Selected section must belong to the selected department."

        if self.job_title_id and self.department_id:
            if self.job_title.department_id != self.department_id:
                errors["job_title"] = "Selected job title must belong to the selected department."

        if self.job_title_id and self.job_title.section_id:
            if not self.section_id:
                errors["section"] = "This job title requires selecting its matching section."
            elif self.job_title.section_id != self.section_id:
                errors["job_title"] = "Selected job title does not belong to the selected section."

        if self.birth_date and self.birth_date > timezone.localdate():
            errors["birth_date"] = "Birth date cannot be in the future."

        if self.passport_issue_date and self.passport_expiry_date:
            if self.passport_issue_date > self.passport_expiry_date:
                errors["passport_expiry_date"] = "Passport expiry date must be on or after the passport issue date."

        if self.civil_id_issue_date and self.civil_id_expiry_date:
            if self.civil_id_issue_date > self.civil_id_expiry_date:
                errors["civil_id_expiry_date"] = "Civil ID expiry date must be on or after the Civil ID issue date."

        if self.is_kuwaiti_national and not (self.pifss_registration_number or "").strip():
            errors["pifss_registration_number"] = "PIFSS registration number is required for Kuwaiti nationals."

        if self.user_id:
            existing_employee = Employee.objects.filter(user_id=self.user_id)
            if self.pk:
                existing_employee = existing_employee.exclude(pk=self.pk)
            if existing_employee.exists():
                errors["user"] = "This user is already linked to another employee profile."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def generate_next_employee_id(cls):
        last_emp = (
            cls.objects.filter(employee_id__regex=r"^EMP[0-9]+$")
            .order_by("-id")
            .first()
        )

        if not last_emp:
            return "EMP001"

        try:
            last_number = int(last_emp.employee_id.replace("EMP", ""))
        except (TypeError, ValueError):
            last_number = 0

        next_number = last_number + 1
        return f"EMP{next_number:03d}"

    def save(self, *args, **kwargs):
        if not self.employee_id:
            candidate = self.generate_next_employee_id()

            while Employee.objects.filter(employee_id=candidate).exists():
                try:
                    number = int(candidate.replace("EMP", ""))
                except (TypeError, ValueError):
                    number = 0
                candidate = f"EMP{number + 1:03d}"

            self.employee_id = candidate

        self.pifss_registration_number = (self.pifss_registration_number or "").strip()

        if self.employment_status == self.EMPLOYMENT_STATUS_INACTIVE:
            self.is_active = False

        super().save(*args, **kwargs)

    @property
    def employment_status_badge_class(self):
        mapping = {
            self.EMPLOYMENT_STATUS_ACTIVE: "badge-success",
            self.EMPLOYMENT_STATUS_INACTIVE: "badge-danger",
            self.EMPLOYMENT_STATUS_ON_LEAVE: "badge-primary",
            self.EMPLOYMENT_STATUS_EMERGENCY_LEAVE: "badge-warning",
            self.EMPLOYMENT_STATUS_UNPAID_LEAVE: "badge-danger",
        }
        return mapping.get(self.employment_status, "badge")

    @property
    def operational_status_label(self):
        return "Operationally Active" if self.is_active else "Operationally Inactive"

    @property
    def age(self):
        if not self.birth_date:
            return None

        today = timezone.localdate()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return max(years, 0)

    @property
    def working_time_summary(self):
        return build_employee_working_time_summary(self)

    def calculate_end_of_service_gratuity(self, final_salary):
        if final_salary in [None, ""]:
            return Decimal("0.00")

        final_salary = Decimal(final_salary)
        if final_salary <= Decimal("0.00") or not self.hire_date:
            return Decimal("0.00")

        today = timezone.localdate()
        completed_service_years = today.year - self.hire_date.year
        if (today.month, today.day) < (self.hire_date.month, self.hire_date.day):
            completed_service_years -= 1
        completed_service_years = max(completed_service_years, 0)

        if completed_service_years < 5:
            gratuity_amount = final_salary * Decimal(completed_service_years) * (Decimal("15") / Decimal("30"))
        else:
            gratuity_amount = final_salary * Decimal(completed_service_years)

        return gratuity_amount.quantize(Decimal("0.01"))


WORKING_HOURS_PER_DAY = Decimal("8.00")
WEEKLY_OFF_WEEKDAYS = {4}  # Company policy default: Friday only
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class EmployeeWorkingTimeSummary:
    scheduled_working_days: int
    service_days: int
    completed_service_years: int
    completed_service_months_remainder: int
    service_duration_display: str
    annual_leave_entitlement_days: int
    annual_leave_taken_days: int
    annual_leave_balance_days: int
    approved_future_annual_leave_days: int
    annual_leave_available_after_planning_days: int
    approved_leave_days: int
    pending_leave_days: int
    rejected_leave_requests: int
    cancelled_leave_requests: int
    unpaid_leave_days: int
    annual_leave_days: int
    sick_leave_days: int
    maternity_leave_days: int
    paternity_leave_days: int
    hajj_leave_days: int
    lieu_leave_days: int
    emergency_leave_days: int
    other_leave_days: int
    absence_days: int
    punctuality_deduction_hours: Decimal
    total_working_days: int
    total_working_hours: Decimal


def iterate_dates(start_date, end_date):
    current_date = start_date
    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def count_policy_working_days(start_date, end_date):
    if not start_date or not end_date or start_date > end_date:
        return 0
    try:
        from workcalendar.services import count_working_days

        return count_working_days(start_date, end_date)
    except Exception:
        working_days = 0
        for current_date in iterate_dates(start_date, end_date):
            if current_date.weekday() not in WEEKLY_OFF_WEEKDAYS:
                working_days += 1
        return working_days


def is_policy_working_day(value):
    if not value:
        return False
    try:
        from workcalendar.services import is_working_day

        return is_working_day(value)
    except Exception:
        return value.weekday() not in WEEKLY_OFF_WEEKDAYS


def is_policy_weekly_off_day(value):
    if not value:
        return False
    try:
        from workcalendar.services import is_weekly_off_day

        return is_weekly_off_day(value)
    except Exception:
        return value.weekday() in WEEKLY_OFF_WEEKDAYS


def is_policy_holiday(value):
    if not value:
        return False
    try:
        from workcalendar.services import is_public_holiday

        return is_public_holiday(value)
    except Exception:
        return False


def get_lateness_deduction_hours(action_record):
    mapping = {
        EmployeeActionRecord.SEVERITY_LOW: Decimal("0.25"),
        EmployeeActionRecord.SEVERITY_MEDIUM: Decimal("0.50"),
        EmployeeActionRecord.SEVERITY_HIGH: Decimal("1.00"),
        EmployeeActionRecord.SEVERITY_CRITICAL: Decimal("2.00"),
    }
    return mapping.get(action_record.severity, Decimal("0.00"))


def minutes_to_hours_decimal(minutes):
    if not minutes:
        return Decimal("0.00")
    return (Decimal(minutes) / Decimal("60")).quantize(Decimal("0.01"))


def format_minutes_as_hours_minutes(minutes):
    total_minutes = int(minutes or 0)
    hours, remainder = divmod(total_minutes, 60)
    return f"{hours}h {remainder}m"


def format_decimal_hours_as_hours_minutes(decimal_hours):
    if decimal_hours in [None, ""]:
        return "0h 0m"

    total_minutes = int(
        (
            Decimal(decimal_hours) * Decimal("60")
        ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    return format_minutes_as_hours_minutes(total_minutes)


def combine_date_and_time(target_date, target_time):
    if not target_date or not target_time:
        return None
    return datetime.combine(target_date, target_time)


def decimal_hours_from_datetimes(start_dt, end_dt):
    if not start_dt or not end_dt or end_dt <= start_dt:
        return Decimal("0.00")
    total_seconds = Decimal((end_dt - start_dt).total_seconds())
    total_minutes = (total_seconds / Decimal("60")).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP,
    )
    total_hours = total_minutes / Decimal("60")
    return total_hours.quantize(Decimal("0.01"))


def get_employee_approved_leave_dates(employee, as_of_date):
    covered_dates = set()

    approved_leaves = employee.leave_records.filter(status=EmployeeLeave.STATUS_APPROVED)
    for leave_record in approved_leaves:
        if not leave_record.start_date or not leave_record.end_date:
            continue

        leave_start = max(employee.hire_date, leave_record.start_date)
        leave_end = min(as_of_date, leave_record.end_date)

        if leave_start > leave_end:
            continue

        for current_date in iterate_dates(leave_start, leave_end):
            if is_policy_working_day(current_date):
                covered_dates.add(current_date)

    return covered_dates


class EmployeeLeave(models.Model):
    LEAVE_TYPE_ANNUAL = "annual"
    LEAVE_TYPE_SICK = "sick"
    LEAVE_TYPE_UNPAID = "unpaid"
    LEAVE_TYPE_MATERNITY = "maternity"
    LEAVE_TYPE_PATERNITY = "paternity"
    LEAVE_TYPE_HAJJ = "hajj"
    LEAVE_TYPE_LIEU = "lieu"
    LEAVE_TYPE_EMERGENCY = "emergency"
    LEAVE_TYPE_OTHER = "other"

    LEAVE_TYPE_CHOICES = [
        (LEAVE_TYPE_ANNUAL, "Annual Leave"),
        (LEAVE_TYPE_SICK, "Sick Leave"),
        (LEAVE_TYPE_UNPAID, "Unpaid Leave"),
        (LEAVE_TYPE_MATERNITY, "Maternity Leave"),
        (LEAVE_TYPE_PATERNITY, "Paternity Leave"),
        (LEAVE_TYPE_HAJJ, "Hajj Leave"),
        (LEAVE_TYPE_LIEU, "Lieu Leave"),
        (LEAVE_TYPE_EMERGENCY, "Emergency Leave"),
        (LEAVE_TYPE_OTHER, "Other"),
    ]

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    STAGE_SUPERVISOR_REVIEW = "supervisor_review"
    STAGE_OPERATIONS_REVIEW = "operations_review"
    STAGE_HR_REVIEW = "hr_review"
    STAGE_FINAL_APPROVED = "final_approved"
    STAGE_FINAL_REJECTED = "final_rejected"
    STAGE_CANCELLED = "cancelled"

    STAGE_CHOICES = [
        (STAGE_SUPERVISOR_REVIEW, "Supervisor Review"),
        (STAGE_OPERATIONS_REVIEW, "Operations Review"),
        (STAGE_HR_REVIEW, "HR Review"),
        (STAGE_FINAL_APPROVED, "Final Approved"),
        (STAGE_FINAL_REJECTED, "Final Rejected"),
        (STAGE_CANCELLED, "Cancelled"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_records",
    )
    leave_type = models.CharField(
        max_length=20,
        choices=LEAVE_TYPE_CHOICES,
        default=LEAVE_TYPE_ANNUAL,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    reason = models.TextField(blank=True)
    approval_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    current_stage = models.CharField(
        max_length=30,
        choices=STAGE_CHOICES,
        default=STAGE_SUPERVISOR_REVIEW,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_employee_leaves",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_employee_leaves",
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_employee_leaves",
        null=True,
        blank=True,
    )
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="rejected_employee_leaves",
        null=True,
        blank=True,
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_employee_leaves",
        null=True,
        blank=True,
    )
    supervisor_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="supervisor_reviewed_employee_leaves",
        null=True,
        blank=True,
    )
    operations_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="operations_reviewed_employee_leaves",
        null=True,
        blank=True,
    )
    hr_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="hr_reviewed_employee_leaves",
        null=True,
        blank=True,
    )

    supervisor_review_note = models.TextField(blank=True)
    operations_review_note = models.TextField(blank=True)
    hr_review_note = models.TextField(blank=True)

    supervisor_reviewed_at = models.DateTimeField(null=True, blank=True)
    operations_reviewed_at = models.DateTimeField(null=True, blank=True)
    hr_reviewed_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)

    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = EmployeeLeaveQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "status", "-start_date"]),
            models.Index(fields=["status", "current_stage", "-created_at"]),
            models.Index(fields=["leave_type", "status", "start_date"]),
        ]
        verbose_name = "Employee Leave"
        verbose_name_plural = "Employee Leaves"

    def __str__(self):
        return f"{self.employee.full_name} - {self.get_leave_type_display()} ({self.start_date} to {self.end_date})"

    def clean(self):
        errors = {}

        if self.start_date and self.end_date and self.end_date < self.start_date:
            errors["end_date"] = "End date cannot be earlier than start date."

        if self.status == self.STATUS_PENDING and self.current_stage not in {
            self.STAGE_SUPERVISOR_REVIEW,
            self.STAGE_OPERATIONS_REVIEW,
            self.STAGE_HR_REVIEW,
        }:
            errors["current_stage"] = "Pending leave requests must stay in a valid approval stage."

        if self.status == self.STATUS_APPROVED:
            if not self.approved_by_id:
                errors["approved_by"] = "Approved by is required when the leave is approved."
            if self.current_stage != self.STAGE_FINAL_APPROVED:
                errors["current_stage"] = "Approved leave requests must be marked as Final Approved."

        if self.status == self.STATUS_REJECTED:
            if not self.rejected_by_id:
                errors["rejected_by"] = "Rejected by is required when the leave is rejected."
            if self.current_stage != self.STAGE_FINAL_REJECTED:
                errors["current_stage"] = "Rejected leave requests must be marked as Final Rejected."

        if self.status == self.STATUS_CANCELLED:
            if not self.cancelled_by_id:
                errors["cancelled_by"] = "Cancelled by is required when the leave is cancelled."
            if self.current_stage != self.STAGE_CANCELLED:
                errors["current_stage"] = "Cancelled leave requests must be marked as Cancelled."

        if errors:
            raise ValidationError(errors)

    def calculate_total_days(self):
        if not self.start_date or not self.end_date:
            return 0
        return count_policy_working_days(self.start_date, self.end_date)

    def save(self, *args, **kwargs):
        if self.status == self.STATUS_PENDING and not self.current_stage:
            self.current_stage = self.STAGE_SUPERVISOR_REVIEW
        self.full_clean()
        self.total_days = self.calculate_total_days()
        super().save(*args, **kwargs)

    @property
    def can_approve(self):
        return self.status == self.STATUS_PENDING and self.current_stage in {
            self.STAGE_SUPERVISOR_REVIEW,
            self.STAGE_OPERATIONS_REVIEW,
            self.STAGE_HR_REVIEW,
        }

    @property
    def can_reject(self):
        return self.status == self.STATUS_PENDING and self.current_stage in {
            self.STAGE_SUPERVISOR_REVIEW,
            self.STAGE_OPERATIONS_REVIEW,
            self.STAGE_HR_REVIEW,
        }

    @property
    def can_cancel(self):
        return self.status in [self.STATUS_PENDING, self.STATUS_APPROVED]

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_PENDING: "badge-warning",
            self.STATUS_APPROVED: "badge-success",
            self.STATUS_REJECTED: "badge-danger",
            self.STATUS_CANCELLED: "badge",
        }
        return mapping.get(self.status, "badge")

    @property
    def current_stage_badge_class(self):
        mapping = {
            self.STAGE_SUPERVISOR_REVIEW: "badge-warning",
            self.STAGE_OPERATIONS_REVIEW: "badge-primary",
            self.STAGE_HR_REVIEW: "badge-primary",
            self.STAGE_FINAL_APPROVED: "badge-success",
            self.STAGE_FINAL_REJECTED: "badge-danger",
            self.STAGE_CANCELLED: "badge",
        }
        return mapping.get(self.current_stage, "badge")

    @property
    def current_stage_actor_label(self):
        mapping = {
            self.STAGE_SUPERVISOR_REVIEW: "Supervisor",
            self.STAGE_OPERATIONS_REVIEW: "Operations",
            self.STAGE_HR_REVIEW: "HR",
            self.STAGE_FINAL_APPROVED: "Approved",
            self.STAGE_FINAL_REJECTED: "Rejected",
            self.STAGE_CANCELLED: "Cancelled",
        }
        return mapping.get(self.current_stage, self.get_current_stage_display())

    @property
    def workflow_step_summary(self):
        return [
            {
                "label": "Supervisor Review",
                "is_complete": bool(self.supervisor_reviewed_at),
                "actor": self.supervisor_reviewed_by,
                "acted_at": self.supervisor_reviewed_at,
                "note": self.supervisor_review_note,
            },
            {
                "label": "Operations Review",
                "is_complete": bool(self.operations_reviewed_at),
                "actor": self.operations_reviewed_by,
                "acted_at": self.operations_reviewed_at,
                "note": self.operations_review_note,
            },
            {
                "label": "HR Review",
                "is_complete": bool(self.hr_reviewed_at),
                "actor": self.hr_reviewed_by,
                "acted_at": self.hr_reviewed_at,
                "note": self.hr_review_note,
            },
        ]


class EmployeeContract(models.Model):
    CONTRACT_TYPE_PERMANENT = "permanent"
    CONTRACT_TYPE_FIXED_TERM = "fixed_term"
    CONTRACT_TYPE_PROBATION = "probation"

    CONTRACT_TYPE_CHOICES = [
        (CONTRACT_TYPE_PERMANENT, "Permanent"),
        (CONTRACT_TYPE_FIXED_TERM, "Fixed Term"),
        (CONTRACT_TYPE_PROBATION, "Probation"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="contracts",
    )
    contract_type = models.CharField(
        max_length=20,
        choices=CONTRACT_TYPE_CHOICES,
        default=CONTRACT_TYPE_PERMANENT,
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-start_date", "-id"]
        indexes = [
            models.Index(fields=["employee", "is_active", "-start_date"]),
            models.Index(fields=["end_date", "is_active"]),
        ]
        verbose_name = "Employee Contract"
        verbose_name_plural = "Employee Contracts"

    def __str__(self):
        return f"{self.employee.full_name} | {self.get_contract_type_display()} | {self.start_date}"

    def clean(self):
        errors = {}

        if self.end_date and self.start_date and self.end_date <= self.start_date:
            errors["end_date"] = "End date must be after the start date."

        if self.probation_end_date and self.end_date and self.probation_end_date > self.end_date:
            errors["probation_end_date"] = "Probation end date must be on or before the contract end date."

        if errors:
            raise ValidationError(errors)

    @property
    def days_until_expiry(self):
        if not self.end_date:
            return None
        return (self.end_date - timezone.localdate()).days

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class OvertimeRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="overtime_requests",
    )
    date = models.DateField()
    hours_requested = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_overtime_requests",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "status", "-date"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        verbose_name = "Overtime Request"
        verbose_name_plural = "Overtime Requests"

    def __str__(self):
        return f"{self.employee.full_name} | {self.date} | {self.hours_requested} hour(s)"

    def clean(self):
        errors = {}

        if self.hours_requested is None or self.hours_requested <= Decimal("0.00"):
            errors["hours_requested"] = "Requested hours must be greater than zero."

        if not (self.reason or "").strip():
            errors["reason"] = "Reason is required for overtime requests."

        if self.status == self.STATUS_PENDING:
            if self.reviewed_by_id:
                errors["reviewed_by"] = "Pending overtime requests cannot have a reviewer yet."
            if self.reviewed_at:
                errors["reviewed_at"] = "Pending overtime requests cannot have a review timestamp yet."
        else:
            if not self.reviewed_by_id:
                errors["reviewed_by"] = "Reviewed by is required when the request is approved or rejected."
            if not self.reviewed_at:
                errors["reviewed_at"] = "Reviewed at is required when the request is approved or rejected."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.reason = (self.reason or "").strip()
        self.review_note = (self.review_note or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_PENDING: "badge-warning",
            self.STATUS_APPROVED: "badge-success",
            self.STATUS_REJECTED: "badge-danger",
        }
        return mapping.get(self.status, "badge")


class EmployeeActionRecord(models.Model):
    ACTION_TYPE_ABSENCE = "absence"
    ACTION_TYPE_LATENESS = "lateness"
    ACTION_TYPE_WARNING = "warning"
    ACTION_TYPE_MEMO = "memo"
    ACTION_TYPE_DISCIPLINARY = "disciplinary_action"
    ACTION_TYPE_COMMENDATION = "commendation"
    ACTION_TYPE_OTHER = "other"

    ACTION_TYPE_CHOICES = [
        (ACTION_TYPE_ABSENCE, "Absence"),
        (ACTION_TYPE_LATENESS, "Lateness"),
        (ACTION_TYPE_WARNING, "Warning"),
        (ACTION_TYPE_MEMO, "Memo"),
        (ACTION_TYPE_DISCIPLINARY, "Disciplinary Action"),
        (ACTION_TYPE_COMMENDATION, "Commendation"),
        (ACTION_TYPE_OTHER, "Other"),
    ]

    STATUS_OPEN = "open"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
    ]

    SEVERITY_LOW = "low"
    SEVERITY_MEDIUM = "medium"
    SEVERITY_HIGH = "high"
    SEVERITY_CRITICAL = "critical"

    SEVERITY_CHOICES = [
        (SEVERITY_LOW, "Low"),
        (SEVERITY_MEDIUM, "Medium"),
        (SEVERITY_HIGH, "High"),
        (SEVERITY_CRITICAL, "Critical"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="action_records",
    )
    action_type = models.CharField(
        max_length=30,
        choices=ACTION_TYPE_CHOICES,
        default=ACTION_TYPE_MEMO,
    )
    action_date = models.DateField(default=timezone.localdate)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_OPEN,
    )
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default=SEVERITY_MEDIUM,
    )
    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-action_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "status", "-action_date"]),
            models.Index(fields=["action_type", "severity", "-action_date"]),
        ]
        verbose_name = "Employee Action Record"
        verbose_name_plural = "Employee Action Records"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    def clean(self):
        errors = {}

        if not (self.title or "").strip():
            errors["title"] = "Title is required."

        if errors:
            raise ValidationError(errors)

    @property
    def action_type_badge_class(self):
        mapping = {
            self.ACTION_TYPE_ABSENCE: "badge-danger",
            self.ACTION_TYPE_LATENESS: "badge-warning",
            self.ACTION_TYPE_WARNING: "badge-danger",
            self.ACTION_TYPE_MEMO: "badge",
            self.ACTION_TYPE_DISCIPLINARY: "badge-danger",
            self.ACTION_TYPE_COMMENDATION: "badge-success",
            self.ACTION_TYPE_OTHER: "badge-primary",
        }
        return mapping.get(self.action_type, "badge")

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_OPEN: "badge-warning",
            self.STATUS_UNDER_REVIEW: "badge-primary",
            self.STATUS_RESOLVED: "badge-success",
            self.STATUS_CLOSED: "badge",
        }
        return mapping.get(self.status, "badge")

    @property
    def severity_badge_class(self):
        mapping = {
            self.SEVERITY_LOW: "badge",
            self.SEVERITY_MEDIUM: "badge-primary",
            self.SEVERITY_HIGH: "badge-warning",
            self.SEVERITY_CRITICAL: "badge-danger",
        }
        return mapping.get(self.severity, "badge")

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.full_clean()
        super().save(*args, **kwargs)


class EmployeeAttendanceLedger(models.Model):
    DAY_STATUS_PRESENT = "present"
    DAY_STATUS_ABSENT = "absent"
    DAY_STATUS_WEEKLY_OFF = "weekly_off"
    DAY_STATUS_PAID_LEAVE = "paid_leave"
    DAY_STATUS_UNPAID_LEAVE = "unpaid_leave"
    DAY_STATUS_SICK_LEAVE = "sick_leave"
    DAY_STATUS_HOLIDAY = "holiday"
    DAY_STATUS_OTHER = "other"

    DAY_STATUS_CHOICES = [
        (DAY_STATUS_PRESENT, "Present"),
        (DAY_STATUS_ABSENT, "Absent"),
        (DAY_STATUS_WEEKLY_OFF, "Weekly Off"),
        (DAY_STATUS_PAID_LEAVE, "Paid Leave"),
        (DAY_STATUS_UNPAID_LEAVE, "Unpaid Leave"),
        (DAY_STATUS_SICK_LEAVE, "Sick Leave"),
        (DAY_STATUS_HOLIDAY, "Holiday"),
        (DAY_STATUS_OTHER, "Other"),
    ]

    SHIFT_MORNING = "morning"
    SHIFT_MIDDLE = "middle"
    SHIFT_NIGHT = "night"
    SHIFT_NINE_TO_FIVE = "nine_to_five"
    SHIFT_TWELVE_TO_EIGHT = "twelve_to_eight"
    SHIFT_ONE_TO_NINE = "one_to_nine"
    SHIFT_TWO_TO_TEN = "two_to_ten"
    SHIFT_THREE_TO_ELEVEN = "three_to_eleven"
    SHIFT_FOUR_TO_MIDNIGHT = "four_to_midnight"
    SHIFT_MORNING_STANDARD = "morning_standard"
    SHIFT_MIDDLE_STANDARD = "middle_standard"
    SHIFT_EVENING_STANDARD = "evening_standard"

    SHIFT_CHOICES = [
        (SHIFT_MORNING, "Morning Shift"),
        (SHIFT_MIDDLE, "Middle Shift"),
        (SHIFT_NIGHT, "Night Shift"),
        (SHIFT_NINE_TO_FIVE, "9 am to 5 pm"),
        (SHIFT_TWELVE_TO_EIGHT, "12 pm to 8 pm"),
        (SHIFT_ONE_TO_NINE, "1 pm to 9 pm"),
        (SHIFT_TWO_TO_TEN, "2 pm to 10 pm"),
        (SHIFT_THREE_TO_ELEVEN, "3 pm to 11 pm"),
        (SHIFT_FOUR_TO_MIDNIGHT, "4 pm to 12 am"),
        (SHIFT_MORNING_STANDARD, "Morning shift"),
        (SHIFT_MIDDLE_STANDARD, "Middle shift"),
        (SHIFT_EVENING_STANDARD, "Evening shift"),
    ]

    SOURCE_MANUAL = "manual"
    SOURCE_LEAVE = "leave"
    SOURCE_ACTION = "action"
    SOURCE_SYSTEM = "system"

    SOURCE_CHOICES = [
        (SOURCE_MANUAL, "Manual"),
        (SOURCE_LEAVE, "Leave Workflow"),
        (SOURCE_ACTION, "Action Record"),
        (SOURCE_SYSTEM, "System"),
    ]

    SHIFT_TIME_MAP = {
        SHIFT_MORNING: ("09:00", "17:00"),
        SHIFT_MIDDLE: ("13:00", "21:00"),
        SHIFT_NIGHT: ("22:00", "06:00"),
        SHIFT_NINE_TO_FIVE: ("09:00", "17:00"),
        SHIFT_TWELVE_TO_EIGHT: ("12:00", "20:00"),
        SHIFT_ONE_TO_NINE: ("13:00", "21:00"),
        SHIFT_TWO_TO_TEN: ("14:00", "22:00"),
        SHIFT_THREE_TO_ELEVEN: ("15:00", "23:00"),
        SHIFT_FOUR_TO_MIDNIGHT: ("16:00", "00:00"),
        SHIFT_MORNING_STANDARD: ("09:00", "17:00"),
        SHIFT_MIDDLE_STANDARD: ("13:00", "21:00"),
        SHIFT_EVENING_STANDARD: ("15:00", "23:00"),
    }

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_ledgers",
    )
    attendance_date = models.DateField()
    day_status = models.CharField(
        max_length=20,
        choices=DAY_STATUS_CHOICES,
        default=DAY_STATUS_PRESENT,
    )
    shift = models.CharField(
        max_length=20,
        choices=SHIFT_CHOICES,
        null=True,
        blank=True,
    )
    clock_in_time = models.TimeField(null=True, blank=True)
    clock_out_time = models.TimeField(null=True, blank=True)
    scheduled_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=WORKING_HOURS_PER_DAY,
    )
    worked_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    late_minutes = models.PositiveIntegerField(default=0)
    early_departure_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_location_label = models.CharField(max_length=255, blank=True, default="")
    check_out_location_label = models.CharField(max_length=255, blank=True, default="")
    check_in_address = models.TextField(blank=True, default="")
    check_out_address = models.TextField(blank=True, default="")
    is_paid_day = models.BooleanField(default=True)
    source = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
    )
    notes = models.TextField(blank=True)

    linked_leave = models.ForeignKey(
        "EmployeeLeave",
        on_delete=models.SET_NULL,
        related_name="attendance_ledger_entries",
        null=True,
        blank=True,
    )
    linked_action_record = models.ForeignKey(
        "EmployeeActionRecord",
        on_delete=models.SET_NULL,
        related_name="attendance_ledger_entries",
        null=True,
        blank=True,
    )

    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attendance_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "-attendance_date"]),
            models.Index(fields=["day_status", "-attendance_date"]),
            models.Index(fields=["source", "-attendance_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "attendance_date"],
                name="unique_employee_attendance_date",
            )
        ]
        verbose_name = "Employee Attendance Ledger"
        verbose_name_plural = "Employee Attendance Ledgers"

    def __str__(self):
        return f"{self.employee.full_name} - {self.attendance_date} - {self.get_day_status_display()}"

    @classmethod
    def get_shift_time_map(cls):
        return {
            cls.SHIFT_MORNING: {"label": "Morning Shift", "start": "09:00", "end": "17:00"},
            cls.SHIFT_MIDDLE: {"label": "Middle Shift", "start": "13:00", "end": "21:00"},
            cls.SHIFT_NIGHT: {"label": "Night Shift", "start": "22:00", "end": "06:00"},
            cls.SHIFT_NINE_TO_FIVE: {"label": "9 am to 5 pm", "start": "09:00", "end": "17:00"},
            cls.SHIFT_TWELVE_TO_EIGHT: {"label": "12 pm to 8 pm", "start": "12:00", "end": "20:00"},
            cls.SHIFT_ONE_TO_NINE: {"label": "1 pm to 9 pm", "start": "13:00", "end": "21:00"},
            cls.SHIFT_TWO_TO_TEN: {"label": "2 pm to 10 pm", "start": "14:00", "end": "22:00"},
            cls.SHIFT_THREE_TO_ELEVEN: {"label": "3 pm to 11 pm", "start": "15:00", "end": "23:00"},
            cls.SHIFT_FOUR_TO_MIDNIGHT: {"label": "4 pm to 12 am", "start": "16:00", "end": "00:00"},
            cls.SHIFT_MORNING_STANDARD: {"label": "Morning shift", "start": "09:00", "end": "17:00"},
            cls.SHIFT_MIDDLE_STANDARD: {"label": "Middle shift", "start": "13:00", "end": "21:00"},
            cls.SHIFT_EVENING_STANDARD: {"label": "Evening shift", "start": "15:00", "end": "23:00"},
        }

    def get_shift_window(self):
        shift_map = self.get_shift_time_map()
        shift_config = shift_map.get(self.shift)
        if not shift_config or not self.attendance_date:
            return None, None

        start_hour, start_minute = [int(part) for part in shift_config["start"].split(":")]
        end_hour, end_minute = [int(part) for part in shift_config["end"].split(":")]

        shift_start_dt = datetime.combine(
            self.attendance_date,
            datetime.min.time().replace(hour=start_hour, minute=start_minute),
        )
        shift_end_dt = datetime.combine(
            self.attendance_date,
            datetime.min.time().replace(hour=end_hour, minute=end_minute),
        )

        if shift_end_dt <= shift_start_dt:
            shift_end_dt += timedelta(days=1)

        return shift_start_dt, shift_end_dt

    def get_attendance_window(self):
        if not self.attendance_date or not self.clock_in_time or not self.clock_out_time:
            return None, None

        shift_start_dt, shift_end_dt = self.get_shift_window()

        clock_in_dt = combine_date_and_time(self.attendance_date, self.clock_in_time)
        clock_out_dt = combine_date_and_time(self.attendance_date, self.clock_out_time)

        if not clock_in_dt or not clock_out_dt:
            return None, None

        if shift_start_dt and shift_end_dt and shift_end_dt.date() > shift_start_dt.date():
            if clock_in_dt < shift_start_dt:
                clock_in_dt += timedelta(days=1)
            if clock_out_dt <= shift_start_dt:
                clock_out_dt += timedelta(days=1)
        elif clock_out_dt <= clock_in_dt:
            return None, None

        return clock_in_dt, clock_out_dt

    def clean(self):
        errors = {}

        zero_work_statuses = {
            self.DAY_STATUS_ABSENT,
            self.DAY_STATUS_WEEKLY_OFF,
            self.DAY_STATUS_PAID_LEAVE,
            self.DAY_STATUS_UNPAID_LEAVE,
            self.DAY_STATUS_SICK_LEAVE,
            self.DAY_STATUS_HOLIDAY,
        }

        if self.attendance_date and self.employee_id:
            existing = EmployeeAttendanceLedger.objects.filter(
                employee_id=self.employee_id,
                attendance_date=self.attendance_date,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                errors["attendance_date"] = "An attendance entry already exists for this employee on this date."

            if self.employee.hire_date and self.attendance_date < self.employee.hire_date:
                errors["attendance_date"] = "Attendance date cannot be earlier than the employee hire date."

        if self.day_status in zero_work_statuses:
            if self.shift:
                errors["shift"] = "Shift is only allowed for working attendance days."
            if self.clock_in_time or self.clock_out_time:
                errors["clock_in_time"] = "Clock times are only allowed for working attendance days."
            if self.late_minutes:
                errors["late_minutes"] = "Late minutes must be zero for non-working statuses."
            if self.early_departure_minutes:
                errors["early_departure_minutes"] = "Early departure minutes must be zero for non-working statuses."
            if self.overtime_minutes:
                errors["overtime_minutes"] = "Overtime minutes must be zero for non-working statuses."
        else:
            if not self.shift:
                errors["shift"] = "Shift selection is required for working attendance days."
            if not self.clock_in_time:
                errors["clock_in_time"] = "Clock-in time is required for working attendance days."
            if not self.clock_out_time:
                errors["clock_out_time"] = "Clock-out time is required for working attendance days."

            if self.shift and self.clock_in_time and self.clock_out_time:
                clock_in_dt, clock_out_dt = self.get_attendance_window()
                if not clock_in_dt or not clock_out_dt or clock_out_dt <= clock_in_dt:
                    errors["clock_out_time"] = "Clock-out time must be later than clock-in time for the selected shift."

        if self.scheduled_hours is None or self.scheduled_hours <= 0:
            errors["scheduled_hours"] = "Scheduled hours must be greater than zero."

        if self.scheduled_hours is not None and self.scheduled_hours < 0:
            errors["scheduled_hours"] = "Scheduled hours cannot be negative."

        if self.late_minutes is not None and self.late_minutes < 0:
            errors["late_minutes"] = "Late minutes cannot be negative."

        if self.early_departure_minutes is not None and self.early_departure_minutes < 0:
            errors["early_departure_minutes"] = "Early departure minutes cannot be negative."

        if self.overtime_minutes is not None and self.overtime_minutes < 0:
            errors["overtime_minutes"] = "Overtime minutes cannot be negative."

        if errors:
            raise ValidationError(errors)

    def calculate_worked_hours(self):
        zero_work_statuses = {
            self.DAY_STATUS_ABSENT,
            self.DAY_STATUS_WEEKLY_OFF,
            self.DAY_STATUS_PAID_LEAVE,
            self.DAY_STATUS_UNPAID_LEAVE,
            self.DAY_STATUS_SICK_LEAVE,
            self.DAY_STATUS_HOLIDAY,
        }

        if self.day_status in zero_work_statuses:
            return Decimal("0.00")

        clock_in_dt, clock_out_dt = self.get_attendance_window()
        if clock_in_dt and clock_out_dt and clock_out_dt > clock_in_dt:
            return decimal_hours_from_datetimes(clock_in_dt, clock_out_dt)

        return Decimal("0.00")

    def calculate_late_minutes(self):
        shift_start_dt, shift_end_dt = self.get_shift_window()
        clock_in_dt, _ = self.get_attendance_window()

        if not shift_start_dt or not shift_end_dt or not clock_in_dt:
            return 0

        if clock_in_dt <= shift_start_dt:
            return 0

        return int((clock_in_dt - shift_start_dt).total_seconds() // 60)

    def calculate_early_departure_minutes(self):
        shift_start_dt, shift_end_dt = self.get_shift_window()
        _, clock_out_dt = self.get_attendance_window()

        if not shift_start_dt or not shift_end_dt or not clock_out_dt:
            return 0

        if clock_out_dt >= shift_end_dt:
            return 0

        return int((shift_end_dt - clock_out_dt).total_seconds() // 60)

    def calculate_overtime_minutes(self):
        shift_start_dt, shift_end_dt = self.get_shift_window()
        _, clock_out_dt = self.get_attendance_window()

        if not shift_start_dt or not shift_end_dt or not clock_out_dt:
            return 0

        if clock_out_dt <= shift_end_dt:
            return 0

        return int((clock_out_dt - shift_end_dt).total_seconds() // 60)

    @property
    def worked_hours_display(self):
        return format_decimal_hours_as_hours_minutes(self.worked_hours)

    @property
    def scheduled_hours_display(self):
        return format_decimal_hours_as_hours_minutes(self.scheduled_hours)

    @property
    def late_minutes_display(self):
        return format_minutes_as_hours_minutes(self.late_minutes)

    @property
    def early_departure_minutes_display(self):
        return format_minutes_as_hours_minutes(self.early_departure_minutes)

    @property
    def overtime_minutes_display(self):
        return format_minutes_as_hours_minutes(self.overtime_minutes)

    @property
    def notes_preview(self):
        note = " ".join((self.notes or "").split())
        if not note:
            return "No notes"
        if len(note) <= 120:
            return note
        return f"{note[:117].rstrip()}..."

    def save(self, *args, **kwargs):
        zero_work_statuses = {
            self.DAY_STATUS_ABSENT,
            self.DAY_STATUS_WEEKLY_OFF,
            self.DAY_STATUS_PAID_LEAVE,
            self.DAY_STATUS_UNPAID_LEAVE,
            self.DAY_STATUS_SICK_LEAVE,
            self.DAY_STATUS_HOLIDAY,
        }

        if self.day_status in zero_work_statuses:
            self.shift = None
            self.clock_in_time = None
            self.clock_out_time = None
            self.late_minutes = 0
            self.early_departure_minutes = 0
            self.overtime_minutes = 0
            self.is_paid_day = self.day_status not in {
                self.DAY_STATUS_ABSENT,
                self.DAY_STATUS_UNPAID_LEAVE,
            }
        else:
            self.late_minutes = self.calculate_late_minutes()
            self.early_departure_minutes = self.calculate_early_departure_minutes()
            self.overtime_minutes = self.calculate_overtime_minutes()
            self.is_paid_day = True

        self.notes = (self.notes or "").strip()
        self.worked_hours = self.calculate_worked_hours()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def shift_label(self):
        return dict(self.SHIFT_CHOICES).get(self.shift, "—")

    @property
    def day_status_badge_class(self):
        mapping = {
            self.DAY_STATUS_PRESENT: "badge-success",
            self.DAY_STATUS_ABSENT: "badge-danger",
            self.DAY_STATUS_WEEKLY_OFF: "badge",
            self.DAY_STATUS_PAID_LEAVE: "badge-primary",
            self.DAY_STATUS_UNPAID_LEAVE: "badge-danger",
            self.DAY_STATUS_SICK_LEAVE: "badge-warning",
            self.DAY_STATUS_HOLIDAY: "badge",
            self.DAY_STATUS_OTHER: "badge-light",
        }
        return mapping.get(self.day_status, "badge")

    @property
    def source_badge_class(self):
        mapping = {
            self.SOURCE_MANUAL: "badge",
            self.SOURCE_LEAVE: "badge-primary",
            self.SOURCE_ACTION: "badge-warning",
            self.SOURCE_SYSTEM: "badge-light",
        }
        return mapping.get(self.source, "badge")

    @property
    def attendance_rule_label(self):
        if self.day_status == self.DAY_STATUS_PRESENT:
            return "Working Day"
        if self.day_status == self.DAY_STATUS_WEEKLY_OFF:
            return "Weekly Off Rule"
        if self.day_status == self.DAY_STATUS_HOLIDAY:
            return "Holiday Rule"
        if self.day_status in {self.DAY_STATUS_PAID_LEAVE, self.DAY_STATUS_SICK_LEAVE}:
            return "Paid Leave Rule"
        if self.day_status == self.DAY_STATUS_UNPAID_LEAVE:
            return "Unpaid Leave Rule"
        if self.day_status == self.DAY_STATUS_ABSENT:
            return "Absence Rule"
        return "Custom Rule"

    @property
    def attendance_rule_badge_class(self):
        if self.day_status == self.DAY_STATUS_PRESENT:
            return "badge-success"
        if self.day_status in {self.DAY_STATUS_PAID_LEAVE, self.DAY_STATUS_SICK_LEAVE}:
            return "badge-primary"
        if self.day_status in {self.DAY_STATUS_ABSENT, self.DAY_STATUS_UNPAID_LEAVE}:
            return "badge-danger"
        if self.day_status in {self.DAY_STATUS_WEEKLY_OFF, self.DAY_STATUS_HOLIDAY}:
            return "badge"
        return "badge-light"

    @classmethod
    def get_split_status_badge_class(cls, status_label):
        mapping = {
            "On Time": "badge-success",
            "Checked In": "badge-success",
            "Checked Out": "badge-success",
            "Late": "badge-warning",
            "Early Check-Out": "badge-warning",
            "Pending Check-Out": "badge-light",
            "Missing": "badge-danger",
            "Not Checked Out": "badge-danger",
            "Not Required": "badge",
            "Overtime": "badge-primary",
        }
        return mapping.get(status_label, "badge")

    @classmethod
    def resolve_check_in_status(cls, *, day_status, attendance_date, shift, clock_in_time):
        non_working_statuses = {
            cls.DAY_STATUS_WEEKLY_OFF,
            cls.DAY_STATUS_PAID_LEAVE,
            cls.DAY_STATUS_UNPAID_LEAVE,
            cls.DAY_STATUS_SICK_LEAVE,
            cls.DAY_STATUS_HOLIDAY,
        }

        if day_status in non_working_statuses:
            return "Not Required"

        if day_status == cls.DAY_STATUS_ABSENT:
            return "Missing"

        if not clock_in_time:
            return "Missing"

        temp_entry = cls(attendance_date=attendance_date, shift=shift)
        shift_start_dt, _shift_end_dt = temp_entry.get_shift_window()
        clock_in_dt = combine_date_and_time(attendance_date, clock_in_time)

        if shift_start_dt and clock_in_dt:
            if clock_in_dt <= shift_start_dt:
                return "On Time"
            return "Late"

        return "Checked In"

    @classmethod
    def resolve_check_out_status(
        cls,
        *,
        day_status,
        attendance_date,
        shift,
        clock_in_time,
        clock_out_time,
        early_departure_minutes=0,
        overtime_minutes=0,
    ):
        non_working_statuses = {
            cls.DAY_STATUS_WEEKLY_OFF,
            cls.DAY_STATUS_PAID_LEAVE,
            cls.DAY_STATUS_UNPAID_LEAVE,
            cls.DAY_STATUS_SICK_LEAVE,
            cls.DAY_STATUS_HOLIDAY,
        }

        if day_status in non_working_statuses:
            return "Not Required"

        if not clock_out_time:
            if day_status == cls.DAY_STATUS_ABSENT:
                return "Not Checked Out"
            if clock_in_time:
                return "Pending Check-Out"
            return "Not Checked Out"

        if early_departure_minutes:
            return "Early Check-Out"

        if overtime_minutes:
            return "Overtime"

        temp_entry = cls(attendance_date=attendance_date, shift=shift)
        _shift_start_dt, shift_end_dt = temp_entry.get_shift_window()
        clock_out_dt = combine_date_and_time(attendance_date, clock_out_time)

        if shift_end_dt and clock_out_dt:
            if shift_end_dt.date() > attendance_date and clock_out_dt <= shift_end_dt - timedelta(days=1):
                clock_out_dt += timedelta(days=1)
            if clock_out_dt < shift_end_dt:
                return "Early Check-Out"

        return "Checked Out"

    @property
    def check_in_status_label(self):
        return self.resolve_check_in_status(
            day_status=self.day_status,
            attendance_date=self.attendance_date,
            shift=self.shift,
            clock_in_time=self.clock_in_time,
        )

    @property
    def check_in_status_badge_class(self):
        return self.get_split_status_badge_class(self.check_in_status_label)

    @property
    def check_out_status_label(self):
        return self.resolve_check_out_status(
            day_status=self.day_status,
            attendance_date=self.attendance_date,
            shift=self.shift,
            clock_in_time=self.clock_in_time,
            clock_out_time=self.clock_out_time,
            early_departure_minutes=self.early_departure_minutes,
            overtime_minutes=self.overtime_minutes,
        )

    @property
    def check_out_status_badge_class(self):
        return self.get_split_status_badge_class(self.check_out_status_label)

    @property
    def is_correction_available(self):
        return True


class EmployeeAttendanceCorrection(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPLIED = "applied"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_REJECTED, "Rejected"),
    ]

    linked_attendance = models.ForeignKey(
        EmployeeAttendanceLedger,
        on_delete=models.CASCADE,
        related_name="correction_requests",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_corrections",
    )
    requested_day_status = models.CharField(
        max_length=20,
        choices=EmployeeAttendanceLedger.DAY_STATUS_CHOICES,
        default=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
    )
    requested_clock_in_time = models.TimeField(null=True, blank=True)
    requested_clock_out_time = models.TimeField(null=True, blank=True)
    requested_scheduled_hours = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=WORKING_HOURS_PER_DAY,
    )
    requested_late_minutes = models.PositiveIntegerField(default=0)
    requested_early_departure_minutes = models.PositiveIntegerField(default=0)
    requested_overtime_minutes = models.PositiveIntegerField(default=0)
    requested_notes = models.TextField(blank=True)
    request_reason = models.TextField()
    review_notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="requested_attendance_corrections",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_attendance_corrections",
        null=True,
        blank=True,
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.employee.full_name} - {self.linked_attendance.attendance_date} correction"

    def clean(self):
        errors = {}
        zero_work_statuses = {
            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
            EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF,
            EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY,
        }

        if self.linked_attendance_id:
            if self.employee_id and self.employee_id != self.linked_attendance.employee_id:
                errors["employee"] = "Correction employee must match the linked attendance employee."
            if self.status == self.STATUS_PENDING:
                sibling_qs = EmployeeAttendanceCorrection.objects.filter(
                    linked_attendance_id=self.linked_attendance_id,
                    status=self.STATUS_PENDING,
                )
                if self.pk:
                    sibling_qs = sibling_qs.exclude(pk=self.pk)
                if sibling_qs.exists():
                    errors["status"] = "A pending correction already exists for this attendance record."

        if not (self.request_reason or "").strip():
            errors["request_reason"] = "Correction reason is required."

        if self.requested_clock_in_time and self.requested_clock_out_time:
            if self.requested_clock_out_time <= self.requested_clock_in_time:
                errors["requested_clock_out_time"] = "Clock-out time must be later than clock-in time."

        if self.requested_day_status in zero_work_statuses and (
            self.requested_clock_in_time or self.requested_clock_out_time
        ):
            errors["requested_clock_in_time"] = "Clock times are only allowed for present working days."

        if self.requested_day_status in zero_work_statuses:
            if self.requested_late_minutes:
                errors["requested_late_minutes"] = "Late minutes must be zero for non-working statuses."
            if self.requested_early_departure_minutes:
                errors["requested_early_departure_minutes"] = "Early departure minutes must be zero for non-working statuses."

        if self.requested_scheduled_hours is not None and self.requested_scheduled_hours < 0:
            errors["requested_scheduled_hours"] = "Scheduled hours cannot be negative."

        if self.requested_overtime_minutes is not None and self.requested_overtime_minutes < 0:
            errors["requested_overtime_minutes"] = "Overtime minutes cannot be negative."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        zero_work_statuses = {
            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
            EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF,
            EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY,
        }

        if self.linked_attendance_id and not self.employee_id:
            self.employee_id = self.linked_attendance.employee_id

        if self.requested_day_status in zero_work_statuses:
            self.requested_clock_in_time = None
            self.requested_clock_out_time = None
            self.requested_late_minutes = 0
            self.requested_early_departure_minutes = 0

        self.requested_notes = (self.requested_notes or "").strip()
        self.request_reason = (self.request_reason or "").strip()
        self.review_notes = (self.review_notes or "").strip()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_PENDING: "badge-warning",
            self.STATUS_APPLIED: "badge-success",
            self.STATUS_REJECTED: "badge-danger",
        }
        return mapping.get(self.status, "badge")

    @property
    def requested_rule_label(self):
        temp = EmployeeAttendanceLedger(day_status=self.requested_day_status)
        return temp.attendance_rule_label

    @property
    def requested_rule_badge_class(self):
        temp = EmployeeAttendanceLedger(day_status=self.requested_day_status)
        return temp.attendance_rule_badge_class


class EmployeeAttendanceEvent(models.Model):
    STATUS_OPEN = "open"
    STATUS_COMPLETED = "completed"
    LOCATION_STATUS_INSIDE = "inside_radius"
    LOCATION_STATUS_OUTSIDE = "outside_radius"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_COMPLETED, "Completed"),
    ]
    LOCATION_STATUS_CHOICES = [
        (LOCATION_STATUS_INSIDE, "Inside Radius"),
        (LOCATION_STATUS_OUTSIDE, "Outside Radius"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_events",
    )
    attendance_date = models.DateField()
    shift = models.CharField(
        max_length=20,
        choices=EmployeeAttendanceLedger.SHIFT_CHOICES,
        default=EmployeeAttendanceLedger.SHIFT_MORNING,
    )
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_location_label = models.CharField(max_length=255, blank=True, default="")
    check_out_location_label = models.CharField(max_length=255, blank=True, default="")
    check_in_address = models.TextField(blank=True, default="")
    check_out_address = models.TextField(blank=True, default="")
    branch_latitude_used = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    branch_longitude_used = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    attendance_radius_meters_used = models.PositiveIntegerField(null=True, blank=True)
    check_in_distance_meters = models.PositiveIntegerField(null=True, blank=True)
    check_out_distance_meters = models.PositiveIntegerField(null=True, blank=True)
    check_in_location_validation_status = models.CharField(
        max_length=20,
        choices=LOCATION_STATUS_CHOICES,
        blank=True,
        default="",
    )
    check_out_location_validation_status = models.CharField(
        max_length=20,
        choices=LOCATION_STATUS_CHOICES,
        blank=True,
        default="",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    notes = models.TextField(blank=True)
    synced_ledger = models.ForeignKey(
        "EmployeeAttendanceLedger",
        on_delete=models.SET_NULL,
        related_name="self_service_events",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-attendance_date", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "attendance_date"],
                name="unique_employee_attendance_event_date",
            )
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.attendance_date} punch record"

    def clean(self):
        errors = {}
        if self.employee_id and self.attendance_date and self.employee.hire_date and self.attendance_date < self.employee.hire_date:
            errors["attendance_date"] = "Attendance event date cannot be earlier than the employee hire date."
        if self.check_in_at and self.check_out_at and self.check_out_at < self.check_in_at:
            errors["check_out_at"] = "Check-out must be later than check-in."
        if errors:
            raise ValidationError(errors)

    @property
    def is_checked_in(self):
        return bool(self.check_in_at)

    @property
    def is_checked_out(self):
        return bool(self.check_out_at)

    @property
    def worked_hours_display(self):
        if not self.check_in_at or not self.check_out_at or self.check_out_at <= self.check_in_at:
            return "0h 0m"
        return format_decimal_hours_as_hours_minutes(
            decimal_hours_from_datetimes(self.check_in_at, self.check_out_at)
        )

    @property
    def branch_location_used_label(self):
        if self.branch_latitude_used is None or self.branch_longitude_used is None:
            return ""
        return f"{self.branch_latitude_used}, {self.branch_longitude_used}"

    @property
    def day_status(self):
        return EmployeeAttendanceLedger.DAY_STATUS_PRESENT

    def get_day_status_display(self):
        return "Present"

    @property
    def day_status_badge_class(self):
        return "badge-success"

    @property
    def source_badge_class(self):
        return "badge-primary"

    def get_source_display(self):
        return "Self-Service Live"

    @property
    def attendance_rule_label(self):
        return "Working Day"

    @property
    def attendance_rule_badge_class(self):
        return "badge-success"

    @property
    def clock_in_time(self):
        if not self.check_in_at:
            return None
        return timezone.localtime(self.check_in_at).time().replace(microsecond=0)

    @property
    def clock_out_time(self):
        if not self.check_out_at:
            return None
        return timezone.localtime(self.check_out_at).time().replace(microsecond=0)

    @property
    def scheduled_hours(self):
        return WORKING_HOURS_PER_DAY

    @property
    def worked_hours(self):
        return self.worked_hours_display

    @property
    def late_minutes(self):
        if self.check_in_status_label != "Late":
            return 0

        temp_entry = EmployeeAttendanceLedger(
            attendance_date=self.attendance_date,
            shift=self.shift,
        )
        shift_start_dt, _shift_end_dt = temp_entry.get_shift_window()
        clock_in_dt = combine_date_and_time(self.attendance_date, self.clock_in_time)
        if not shift_start_dt or not clock_in_dt:
            return 0
        return int((clock_in_dt - shift_start_dt).total_seconds() // 60)

    def _calculate_progressive_check_out_delta(self):
        if not self.clock_out_time:
            return None, None

        temp_entry = EmployeeAttendanceLedger(
            attendance_date=self.attendance_date,
            shift=self.shift,
        )
        _shift_start_dt, shift_end_dt = temp_entry.get_shift_window()
        clock_out_dt = combine_date_and_time(self.attendance_date, self.clock_out_time)
        if not shift_end_dt or not clock_out_dt:
            return None, None
        if shift_end_dt.date() > self.attendance_date and clock_out_dt <= shift_end_dt - timedelta(days=1):
            clock_out_dt += timedelta(days=1)
        return clock_out_dt, shift_end_dt

    @property
    def early_departure_minutes(self):
        clock_out_dt, shift_end_dt = self._calculate_progressive_check_out_delta()
        if not shift_end_dt or not clock_out_dt:
            return 0
        if clock_out_dt >= shift_end_dt:
            return 0
        return int((shift_end_dt - clock_out_dt).total_seconds() // 60)

    @property
    def overtime_minutes(self):
        clock_out_dt, shift_end_dt = self._calculate_progressive_check_out_delta()
        if not shift_end_dt or not clock_out_dt:
            return 0
        if clock_out_dt <= shift_end_dt:
            return 0
        return int((clock_out_dt - shift_end_dt).total_seconds() // 60)

    @property
    def check_in_status_label(self):
        return EmployeeAttendanceLedger.resolve_check_in_status(
            day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            attendance_date=self.attendance_date,
            shift=self.shift,
            clock_in_time=self.clock_in_time,
        )

    @property
    def check_in_status_badge_class(self):
        return EmployeeAttendanceLedger.get_split_status_badge_class(self.check_in_status_label)

    @property
    def check_out_status_label(self):
        return EmployeeAttendanceLedger.resolve_check_out_status(
            day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            attendance_date=self.attendance_date,
            shift=self.shift,
            clock_in_time=self.clock_in_time,
            clock_out_time=self.clock_out_time,
            early_departure_minutes=self.early_departure_minutes,
            overtime_minutes=self.overtime_minutes,
        )

    @property
    def check_out_status_badge_class(self):
        return EmployeeAttendanceLedger.get_split_status_badge_class(self.check_out_status_label)

    @property
    def is_paid_day(self):
        return True

    @property
    def linked_leave(self):
        return None

    @property
    def linked_action_record(self):
        return None

    @property
    def created_by(self):
        return ""

    @property
    def is_correction_available(self):
        return False


class EmployeeHistory(models.Model):
    EVENT_PROFILE = "profile"
    EVENT_TRANSFER = "transfer"
    EVENT_DOCUMENT = "document"
    EVENT_STATUS = "status"
    EVENT_NOTE = "note"

    EVENT_TYPE_CHOICES = [
        (EVENT_PROFILE, "Profile Update"),
        (EVENT_TRANSFER, "Placement Change"),
        (EVENT_DOCUMENT, "Document Event"),
        (EVENT_STATUS, "Status / Workflow Event"),
        (EVENT_NOTE, "Manual Note"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="history_entries",
    )
    event_type = models.CharField(
        max_length=20,
        choices=EVENT_TYPE_CHOICES,
        default=EVENT_NOTE,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    event_date = models.DateField(null=True, blank=True)
    created_by = models.CharField(max_length=150, blank=True)
    is_system_generated = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_date", "-created_at", "-id"]

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    def clean(self):
        errors = {}

        if not (self.title or "").strip():
            errors["title"] = "Title is required."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.description = (self.description or "").strip()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def event_type_badge_class(self):
        mapping = {
            self.EVENT_PROFILE: "badge-primary",
            self.EVENT_TRANSFER: "badge-warning",
            self.EVENT_DOCUMENT: "badge-success",
            self.EVENT_STATUS: "badge-danger",
            self.EVENT_NOTE: "badge",
        }
        return mapping.get(self.event_type, "badge")


class EmployeeRequiredSubmission(models.Model):
    REQUEST_TYPE_PASSPORT_COPY = "passport_copy"
    REQUEST_TYPE_CIVIL_ID_COPY = "civil_id_copy"
    REQUEST_TYPE_CONTRACT_COPY = "contract_copy"
    REQUEST_TYPE_MEDICAL_DOCUMENT = "medical_document"
    REQUEST_TYPE_CERTIFICATE = "certificate"
    REQUEST_TYPE_GENERAL_DOCUMENT = "general_document"
    REQUEST_TYPE_OTHER = "other"

    REQUEST_TYPE_CHOICES = [
        (REQUEST_TYPE_PASSPORT_COPY, "Passport Copy"),
        (REQUEST_TYPE_CIVIL_ID_COPY, "Civil ID Copy"),
        (REQUEST_TYPE_CONTRACT_COPY, "Contract Copy"),
        (REQUEST_TYPE_MEDICAL_DOCUMENT, "Medical Document"),
        (REQUEST_TYPE_CERTIFICATE, "Certificate"),
        (REQUEST_TYPE_GENERAL_DOCUMENT, "General Document"),
        (REQUEST_TYPE_OTHER, "Other"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    STATUS_REQUESTED = "requested"
    STATUS_SUBMITTED = "submitted"
    STATUS_COMPLETED = "completed"
    STATUS_NEEDS_CORRECTION = "needs_correction"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_NEEDS_CORRECTION, "Needs Correction"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="required_submissions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_employee_required_submissions",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_employee_required_submissions",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    request_type = models.CharField(
        max_length=40,
        choices=REQUEST_TYPE_CHOICES,
        default=REQUEST_TYPE_GENERAL_DOCUMENT,
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_NORMAL,
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_REQUESTED,
    )
    instructions = models.TextField(blank=True)
    due_date = models.DateField(null=True, blank=True)
    employee_note = models.TextField(blank=True)
    response_file = models.FileField(
        upload_to=employee_submission_request_upload_to,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    response_reference_number = models.CharField(max_length=120, blank=True)
    response_issue_date = models.DateField(null=True, blank=True)
    response_expiry_date = models.DateField(null=True, blank=True)
    fulfilled_document = models.ForeignKey(
        "EmployeeDocument",
        on_delete=models.SET_NULL,
        related_name="submission_requests",
        null=True,
        blank=True,
    )
    review_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at", "-id"]

    def __str__(self):
        return f"{self.employee} - {self.title}"

    def clean(self):
        errors = {}

        if self.response_issue_date and self.response_expiry_date and self.response_expiry_date < self.response_issue_date:
            errors["response_expiry_date"] = "Response expiry date cannot be earlier than response issue date."

        if self.status in {self.STATUS_SUBMITTED, self.STATUS_COMPLETED} and not self.response_file:
            errors["response_file"] = "A response file is required once the employee submits this request."

        if errors:
            raise ValidationError(errors)

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_REQUESTED: "badge-warning",
            self.STATUS_SUBMITTED: "badge-primary",
            self.STATUS_COMPLETED: "badge-success",
            self.STATUS_NEEDS_CORRECTION: "badge-danger",
            self.STATUS_CANCELLED: "badge",
        }
        return mapping.get(self.status, "badge")

    @property
    def priority_badge_class(self):
        mapping = {
            self.PRIORITY_LOW: "badge",
            self.PRIORITY_NORMAL: "badge-light",
            self.PRIORITY_HIGH: "badge-warning",
            self.PRIORITY_URGENT: "badge-danger",
        }
        return mapping.get(self.priority, "badge-light")

    @property
    def is_overdue(self):
        return bool(
            self.due_date
            and self.due_date < timezone.localdate()
            and self.status not in {self.STATUS_COMPLETED, self.STATUS_CANCELLED}
        )

    @property
    def can_employee_submit(self):
        return self.status in {self.STATUS_REQUESTED, self.STATUS_NEEDS_CORRECTION}

    @property
    def mapped_document_type(self):
        mapping = {
            self.REQUEST_TYPE_PASSPORT_COPY: EmployeeDocument.DOCUMENT_TYPE_ID,
            self.REQUEST_TYPE_CIVIL_ID_COPY: EmployeeDocument.DOCUMENT_TYPE_ID,
            self.REQUEST_TYPE_CONTRACT_COPY: EmployeeDocument.DOCUMENT_TYPE_CONTRACT,
            self.REQUEST_TYPE_MEDICAL_DOCUMENT: EmployeeDocument.DOCUMENT_TYPE_MEDICAL,
            self.REQUEST_TYPE_CERTIFICATE: EmployeeDocument.DOCUMENT_TYPE_CERTIFICATE,
            self.REQUEST_TYPE_GENERAL_DOCUMENT: EmployeeDocument.DOCUMENT_TYPE_GENERAL,
            self.REQUEST_TYPE_OTHER: EmployeeDocument.DOCUMENT_TYPE_OTHER,
        }
        return mapping.get(self.request_type, EmployeeDocument.DOCUMENT_TYPE_GENERAL)

    @property
    def default_document_title(self):
        return self.title or self.get_request_type_display()


class EmployeeDocumentRequest(models.Model):
    REQUEST_TYPE_SALARY_CERTIFICATE = "salary_certificate"
    REQUEST_TYPE_SALARY_TRANSFER = "salary_transfer"
    REQUEST_TYPE_EXPERIENCE_CERTIFICATE = "experience_certificate"
    REQUEST_TYPE_NOC_LETTER = "noc_letter"
    REQUEST_TYPE_HR_LETTER = "hr_letter"
    REQUEST_TYPE_OTHER = "other"

    REQUEST_TYPE_CHOICES = [
        (REQUEST_TYPE_SALARY_CERTIFICATE, "Salary Certificate"),
        (REQUEST_TYPE_SALARY_TRANSFER, "Salary Transfer Letter"),
        (REQUEST_TYPE_EXPERIENCE_CERTIFICATE, "Experience Certificate"),
        (REQUEST_TYPE_NOC_LETTER, "No Objection Letter"),
        (REQUEST_TYPE_HR_LETTER, "HR Letter"),
        (REQUEST_TYPE_OTHER, "Other"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_NORMAL = "normal"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_NORMAL, "Normal"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    STATUS_REQUESTED = "requested"
    STATUS_APPROVED = "approved"
    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_REQUESTED, "Requested"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="document_requests",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_employee_document_requests",
        null=True,
        blank=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_employee_document_requests",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    request_type = models.CharField(
        max_length=40,
        choices=REQUEST_TYPE_CHOICES,
        default=REQUEST_TYPE_OTHER,
    )
    priority = models.CharField(
        max_length=20,
        choices=PRIORITY_CHOICES,
        default=PRIORITY_NORMAL,
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default=STATUS_REQUESTED,
    )
    request_note = models.TextField(blank=True)
    needed_by_date = models.DateField(null=True, blank=True)
    management_note = models.TextField(blank=True)
    response_file = models.FileField(
        upload_to=employee_management_request_upload_to,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    delivered_document = models.ForeignKey(
        "EmployeeDocument",
        on_delete=models.SET_NULL,
        related_name="delivered_employee_document_requests",
        null=True,
        blank=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at", "-id"]

    def __str__(self):
        return f"{self.employee} - {self.title}"

    def clean(self):
        errors = {}

        if self.status == self.STATUS_COMPLETED and not self.response_file:
            errors["response_file"] = "A reply file is required when this request is marked as completed."

        if errors:
            raise ValidationError(errors)

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_REQUESTED: "badge-warning",
            self.STATUS_APPROVED: "badge-primary",
            self.STATUS_COMPLETED: "badge-success",
            self.STATUS_REJECTED: "badge-danger",
            self.STATUS_CANCELLED: "badge",
        }
        return mapping.get(self.status, "badge")

    @property
    def priority_badge_class(self):
        mapping = {
            self.PRIORITY_LOW: "badge",
            self.PRIORITY_NORMAL: "badge-light",
            self.PRIORITY_HIGH: "badge-warning",
            self.PRIORITY_URGENT: "badge-danger",
        }
        return mapping.get(self.priority, "badge-light")

    @property
    def is_overdue(self):
        return bool(
            self.needed_by_date
            and self.needed_by_date < timezone.localdate()
            and self.status not in {self.STATUS_COMPLETED, self.STATUS_REJECTED, self.STATUS_CANCELLED}
        )

    @property
    def can_employee_cancel(self):
        return self.status in {self.STATUS_REQUESTED, self.STATUS_APPROVED}

    @property
    def mapped_document_type(self):
        if self.request_type == self.REQUEST_TYPE_OTHER:
            return EmployeeDocument.DOCUMENT_TYPE_GENERAL
        return EmployeeDocument.DOCUMENT_TYPE_CERTIFICATE

    @property
    def default_document_title(self):
        return self.title or self.get_request_type_display()



def get_schedule_week_start(target_date):
    if not target_date:
        return None

    sunday_weekday = 6
    offset = (target_date.weekday() - sunday_weekday) % 7
    return target_date - timedelta(days=offset)


class BranchWeeklyScheduleEntry(models.Model):
    DUTY_TYPE_SHIFT = "shift"
    DUTY_TYPE_OFF = "off"
    DUTY_TYPE_EXTRA_OFF = "extra_off"
    DUTY_TYPE_CUSTOM = "custom"

    DUTY_TYPE_CHOICES = [
        (DUTY_TYPE_SHIFT, "Shift"),
        (DUTY_TYPE_OFF, "Off"),
        (DUTY_TYPE_EXTRA_OFF, "Extra Off"),
        (DUTY_TYPE_CUSTOM, "Custom Duty"),
    ]

    STATUS_PLANNED = "planned"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_ON_HOLD = "on_hold"

    STATUS_CHOICES = [
        (STATUS_PLANNED, "Planned"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_ON_HOLD, "On Hold"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="weekly_schedule_entries",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="branch_weekly_schedule_entries",
    )
    week_start = models.DateField(db_index=True)
    schedule_date = models.DateField(db_index=True)
    duty_option = models.ForeignKey(
        "BranchWeeklyDutyOption",
        on_delete=models.SET_NULL,
        related_name="schedule_entries",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255, blank=True, default="")
    duty_type = models.CharField(
        max_length=20,
        choices=DUTY_TYPE_CHOICES,
        default=DUTY_TYPE_SHIFT,
    )
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    shift_label = models.CharField(max_length=100, blank=True)
    order_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PLANNED,
    )
    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["schedule_date", "employee__full_name", "title", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "employee", "schedule_date"],
                name="emp_weekly_entry_branch_emp_date_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | {self.employee.full_name} | {self.schedule_date} | {self.title}"

    def clean(self):
        errors = {}

        calculated_week_start = get_schedule_week_start(self.schedule_date)
        if self.schedule_date and self.week_start and self.week_start != calculated_week_start:
            errors["week_start"] = "Week start must match the selected schedule date."

        if self.employee_id and self.branch_id and self.employee.branch_id != self.branch_id:
            errors["employee"] = "Selected employee must belong to the selected branch."

        if self.duty_option_id and self.duty_option.branch_id != self.branch_id:
            errors["duty_option"] = "Selected duty option must belong to the same branch."

        if self.duty_type == self.DUTY_TYPE_SHIFT:
            if bool(self.start_time) != bool(self.end_time):
                errors["end_time"] = "Start time and end time are both required for a shift."
            elif self.start_time and self.end_time and self.end_time <= self.start_time:
                errors["end_time"] = "End time must be later than start time."
        else:
            self.start_time = None
            self.end_time = None

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.schedule_date:
            self.week_start = get_schedule_week_start(self.schedule_date)

        if self.duty_option_id:
            self.duty_type = self.duty_option.duty_type
            self.shift_label = self.duty_option.label
            if self.duty_option.duty_type == self.DUTY_TYPE_SHIFT:
                self.start_time = self.duty_option.default_start_time
                self.end_time = self.duty_option.default_end_time
            else:
                self.start_time = None
                self.end_time = None

        self.title = (self.title or "").strip()
        self.shift_label = (self.shift_label or "").strip()
        self.order_note = (self.order_note or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def status_badge_class(self):
        mapping = {
            self.STATUS_PLANNED: "badge-light",
            self.STATUS_IN_PROGRESS: "badge-primary",
            self.STATUS_COMPLETED: "badge-success",
            self.STATUS_ON_HOLD: "badge-warning",
        }
        return mapping.get(self.status, "badge-light")

    @property
    def sheet_value(self):
        if self.duty_type == self.DUTY_TYPE_OFF:
            return "off"
        if self.duty_type == self.DUTY_TYPE_EXTRA_OFF:
            return "extra off"
        if self.duty_type == self.DUTY_TYPE_CUSTOM:
            return self.title or self.shift_label or "custom"

        if self.start_time and self.end_time:
            start_label = self.start_time.strftime("%I %p").lstrip("0").lower()
            end_label = self.end_time.strftime("%I %p").lstrip("0").lower()
            return f"{start_label} to {end_label}"

        return self.title or self.shift_label or "shift"

    @property
    def sheet_detail(self):
        if self.duty_type == self.DUTY_TYPE_SHIFT and self.title:
            return self.title
        if self.shift_label:
            return self.shift_label
        return ""

    @property
    def formatted_time_range(self):
        if not (self.start_time and self.end_time):
            return ""
        return (
            f"{self.start_time.strftime('%I:%M %p').lstrip('0').lower()} "
            f"to {self.end_time.strftime('%I:%M %p').lstrip('0').lower()}"
        )

    @property
    def primary_schedule_label(self):
        if self.shift_label:
            return self.shift_label
        if self.duty_option_id:
            return self.duty_option.label
        if self.title:
            return self.title
        return self.get_duty_type_display()

    @property
    def should_show_time_range_line(self):
        if self.duty_type != self.DUTY_TYPE_SHIFT:
            return False

        time_range = self.formatted_time_range.strip().lower()
        primary_label = (self.primary_schedule_label or "").strip().lower()
        if not time_range:
            return False
        return time_range != primary_label

    @property
    def sheet_cell_class(self):
        if self.duty_type in {self.DUTY_TYPE_OFF, self.DUTY_TYPE_EXTRA_OFF}:
            return "is-off"
        if self.duty_type == self.DUTY_TYPE_CUSTOM:
            return "is-custom"
        if self.start_time and self.start_time.hour < 12:
            return "is-morning"
        return "is-shift"

    @property
    def inline_color_style(self):
        if not self.duty_option_id:
            return ""
        return self.duty_option.inline_color_style


class BranchWeeklyDutyOption(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="weekly_duty_options",
    )
    label = models.CharField(max_length=120)
    duty_type = models.CharField(
        max_length=20,
        choices=BranchWeeklyScheduleEntry.DUTY_TYPE_CHOICES,
        default=BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT,
    )
    default_start_time = models.TimeField(null=True, blank=True)
    default_end_time = models.TimeField(null=True, blank=True)
    background_color = models.CharField(max_length=7, blank=True, default="")
    text_color = models.CharField(max_length=7, blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "label", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "label"],
                name="emp_duty_option_branch_label_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | {self.label}"

    def clean(self):
        errors = {}
        if self.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT:
            if bool(self.default_start_time) != bool(self.default_end_time):
                errors["default_end_time"] = "Shift options need both start time and end time."
            elif (
                self.default_start_time
                and self.default_end_time
                and self.default_end_time <= self.default_start_time
            ):
                errors["default_end_time"] = "Default end time must be later than default start time."
        else:
            self.default_start_time = None
            self.default_end_time = None

        if self.background_color and not HEX_COLOR_RE.match(self.background_color):
            errors["background_color"] = "Background color must use full hex format like #2563eb."

        if self.text_color and not HEX_COLOR_RE.match(self.text_color):
            errors["text_color"] = "Text color must use full hex format like #ffffff."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.label = (self.label or "").strip()
        self.background_color = (self.background_color or "").strip()
        self.text_color = (self.text_color or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def resolved_background_color(self):
        """Return only the saved custom color.

        Safe live fix:
        - stop injecting hard-coded default colors based on label text
        - let the UI fall back naturally when no custom color is saved
        """
        return (self.background_color or "").strip()

    @property
    def resolved_text_color(self):
        """Return only the saved custom text color.

        Safe live fix:
        - stop injecting hard-coded default text colors based on label text
        - let the UI fall back naturally when no custom color is saved
        """
        return (self.text_color or "").strip()

    @property
    def inline_color_style(self):
        styles = []
        if self.resolved_background_color:
            styles.append(f"--branch-duty-bg: {self.resolved_background_color}")
        if self.resolved_text_color:
            styles.append(f"--branch-duty-text: {self.resolved_text_color}")
        return "; ".join(styles)


class BranchWeeklyScheduleTheme(models.Model):
    branch = models.OneToOneField(
        Branch,
        on_delete=models.CASCADE,
        related_name="weekly_schedule_theme",
    )
    employee_column_bg = models.CharField(max_length=7, blank=True, default="#101828")
    employee_column_text = models.CharField(max_length=7, blank=True, default="#f8fafc")
    job_title_column_bg = models.CharField(max_length=7, blank=True, default="#111827")
    job_title_column_text = models.CharField(max_length=7, blank=True, default="#f8fafc")
    pending_off_column_bg = models.CharField(max_length=7, blank=True, default="#172033")
    pending_off_column_text = models.CharField(max_length=7, blank=True, default="#f8fafc")
    day_header_bg = models.CharField(max_length=7, blank=True, default="#1d293d")
    day_header_text = models.CharField(max_length=7, blank=True, default="#f8fafc")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__name"]

    def __str__(self):
        return f"{self.branch.name} weekly schedule theme"

    def clean(self):
        errors = {}
        for field_name in [
            "employee_column_bg",
            "employee_column_text",
            "job_title_column_bg",
            "job_title_column_text",
            "pending_off_column_bg",
            "pending_off_column_text",
            "day_header_bg",
            "day_header_text",
        ]:
            value = (getattr(self, field_name, "") or "").strip()
            if value and not HEX_COLOR_RE.match(value):
                errors[field_name] = "Color must use full hex format like #2563eb."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        for field_name in [
            "employee_column_bg",
            "employee_column_text",
            "job_title_column_bg",
            "job_title_column_text",
            "pending_off_column_bg",
            "pending_off_column_text",
            "day_header_bg",
            "day_header_text",
        ]:
            setattr(self, field_name, (getattr(self, field_name, "") or "").strip())
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def inline_style(self):
        return "; ".join(
            [
                f"--schedule-employee-column-bg: {self.employee_column_bg}",
                f"--schedule-employee-column-text: {self.employee_column_text}",
                f"--schedule-job-title-column-bg: {self.job_title_column_bg}",
                f"--schedule-job-title-column-text: {self.job_title_column_text}",
                f"--schedule-pending-column-bg: {self.pending_off_column_bg}",
                f"--schedule-pending-column-text: {self.pending_off_column_text}",
                f"--schedule-day-header-bg: {self.day_header_bg}",
                f"--schedule-day-header-text: {self.day_header_text}",
            ]
        )

    @property
    def preview_label(self):
        if self.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT and self.default_start_time and self.default_end_time:
            start_label = self.default_start_time.strftime("%I %p").lstrip("0").lower()
            end_label = self.default_end_time.strftime("%I %p").lstrip("0").lower()
            return f"{self.label} · {start_label} to {end_label}"
        return self.label


class BranchWeeklyPendingOff(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="weekly_pending_off_records",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="weekly_pending_off_records",
    )
    week_start = models.DateField(db_index=True)
    pending_off_count = models.PositiveIntegerField(default=0)
    created_by = models.CharField(max_length=150, blank=True)
    updated_by = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["week_start", "employee__full_name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "employee", "week_start"],
                name="emp_pending_off_branch_emp_week_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | {self.employee.full_name} | {self.week_start} | {self.pending_off_count}"

    def clean(self):
        errors = {}
        if self.employee_id and self.branch_id and self.employee.branch_id != self.branch_id:
            errors["employee"] = "Selected employee must belong to the selected branch."
        if self.week_start and self.week_start != get_schedule_week_start(self.week_start):
            errors["week_start"] = "Pending off week must use the start date of that week."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.week_start:
            self.week_start = get_schedule_week_start(self.week_start)
        self.full_clean()
        return super().save(*args, **kwargs)


class BranchScheduleGridHeader(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="schedule_grid_headers",
    )
    column_index = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["column_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "column_index"],
                name="emp_grid_header_branch_col_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | Header {self.column_index}"

    def clean(self):
        errors = {}
        if self.column_index < 0 or self.column_index > 11:
            errors["column_index"] = "Header column index must stay between 0 and 11."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.label = (self.label or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)


class BranchScheduleGridRow(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="schedule_grid_rows",
    )
    row_index = models.PositiveSmallIntegerField()
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="assigned_schedule_grid_rows",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["row_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "row_index"],
                name="emp_grid_row_branch_row_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | Row {self.row_index}"

    def clean(self):
        errors = {}
        if self.employee_id and self.employee.branch_id != self.branch_id:
            errors["employee"] = "Selected employee must belong to the same branch."
        if self.row_index < 1:
            errors["row_index"] = "Row index must be at least 1."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class BranchScheduleGridCell(models.Model):
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="schedule_grid_cells",
    )
    row_index = models.PositiveSmallIntegerField()
    column_index = models.PositiveSmallIntegerField()
    value = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["row_index", "column_index", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "row_index", "column_index"],
                name="emp_grid_cell_branch_row_col_uniq",
            )
        ]

    def __str__(self):
        return f"{self.branch.name} | Row {self.row_index} | Column {self.column_index}"

    def clean(self):
        errors = {}
        if self.row_index < 1:
            errors["row_index"] = "Row index must be at least 1."
        if self.column_index < 1 or self.column_index > 10:
            errors["column_index"] = "Column index must stay between 1 and 10."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.value = (self.value or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)


class EmployeeDocument(models.Model):
    DOCUMENT_TYPE_GENERAL = "general"
    DOCUMENT_TYPE_CONTRACT = "contract"
    DOCUMENT_TYPE_ID = "id"
    DOCUMENT_TYPE_CERTIFICATE = "certificate"
    DOCUMENT_TYPE_PAYROLL = "payroll"
    DOCUMENT_TYPE_MEDICAL = "medical"
    DOCUMENT_TYPE_OTHER = "other"

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_GENERAL, "General"),
        (DOCUMENT_TYPE_CONTRACT, "Contract"),
        (DOCUMENT_TYPE_ID, "ID / Civil Documents"),
        (DOCUMENT_TYPE_CERTIFICATE, "Certificate"),
        (DOCUMENT_TYPE_PAYROLL, "Payroll"),
        (DOCUMENT_TYPE_MEDICAL, "Medical"),
        (DOCUMENT_TYPE_OTHER, "Other"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    linked_leave = models.ForeignKey(
        "EmployeeLeave",
        on_delete=models.SET_NULL,
        related_name="supporting_documents",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255, blank=True)
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default=DOCUMENT_TYPE_GENERAL,
    )
    reference_number = models.CharField(max_length=120, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    file = models.FileField(
        upload_to=employee_document_upload_to,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    description = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return self.title or self.filename

    def clean(self):
        errors = {}

        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            errors["expiry_date"] = "Expiry date cannot be earlier than issue date."

        if errors:
            raise ValidationError(errors)

    @property
    def filename(self):
        return Path(self.file.name).name if self.file else ""

    @property
    def extension(self):
        return Path(self.filename).suffix.lower().replace(".", "") if self.filename else ""

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        days = self.days_until_expiry
        return days is not None and days < 0

    @property
    def is_expiring_soon(self):
        days = self.days_until_expiry
        return days is not None and 0 <= days <= 30

    @property
    def compliance_status_label(self):
        if not self.expiry_date:
            return "No Expiry Date"
        if self.is_expired:
            return "Expired"
        if self.is_expiring_soon:
            return "Expiring Soon"
        return "Valid"

    @property
    def compliance_badge_class(self):
        if not self.expiry_date:
            return "badge"
        if self.is_expired:
            return "badge-danger"
        if self.is_expiring_soon:
            return "badge-primary"
        return "badge-success"

    @property
    def required_badge_class(self):
        return "badge-danger" if self.is_required else "badge"


def build_employee_working_time_summary(employee):
    if not employee or not employee.hire_date:
        return EmployeeWorkingTimeSummary(
            scheduled_working_days=0,
            service_days=0,
            completed_service_years=0,
            completed_service_months_remainder=0,
            service_duration_display="0 years, 0 months",
            annual_leave_entitlement_days=0,
            annual_leave_taken_days=0,
            annual_leave_balance_days=0,
            approved_future_annual_leave_days=0,
            annual_leave_available_after_planning_days=0,
            approved_leave_days=0,
            pending_leave_days=0,
            rejected_leave_requests=0,
            cancelled_leave_requests=0,
            unpaid_leave_days=0,
            annual_leave_days=0,
            sick_leave_days=0,
            maternity_leave_days=0,
            paternity_leave_days=0,
            hajj_leave_days=0,
            lieu_leave_days=0,
            emergency_leave_days=0,
            other_leave_days=0,
            absence_days=0,
            punctuality_deduction_hours=Decimal("0.00"),
            total_working_days=0,
            total_working_hours=Decimal("0.00"),
        )

    today = timezone.localdate()
    scheduled_working_days = count_policy_working_days(employee.hire_date, today)
    service_days = max((today - employee.hire_date).days + 1, 0)

    total_completed_months = max(service_days // 30, 0)
    completed_service_years = total_completed_months // 12
    completed_service_months_remainder = total_completed_months % 12

    year_label = "year" if completed_service_years == 1 else "years"
    month_label = "month" if completed_service_months_remainder == 1 else "months"
    service_duration_display = f"{completed_service_years} {year_label}, {completed_service_months_remainder} {month_label}"

    annual_leave_entitlement_days = max((service_days * 30) // 365, 0)

    leave_records = list(
        employee.leave_records.filter(
            start_date__lte=today,
            end_date__gte=employee.hire_date,
        ).order_by("start_date", "id")
    )

    approved_leave_days = 0
    pending_leave_days = 0
    rejected_leave_requests = 0
    cancelled_leave_requests = 0
    unpaid_leave_days = 0
    annual_leave_days = 0
    sick_leave_days = 0
    maternity_leave_days = 0
    paternity_leave_days = 0
    hajj_leave_days = 0
    lieu_leave_days = 0
    emergency_leave_days = 0
    other_leave_days = 0
    approved_leave_dates = set()

    for leave_record in leave_records:
        effective_start = max(employee.hire_date, leave_record.start_date)
        effective_end = min(today, leave_record.end_date)

        if effective_start > effective_end:
            continue

        leave_policy_days = count_policy_working_days(effective_start, effective_end)
        leave_policy_dates = {
            current_date
            for current_date in iterate_dates(effective_start, effective_end)
            if is_policy_working_day(current_date)
        }

        if leave_record.status == EmployeeLeave.STATUS_APPROVED:
            approved_leave_dates.update(leave_policy_dates)

            if leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_UNPAID:
                unpaid_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_ANNUAL:
                annual_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_SICK:
                sick_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_MATERNITY:
                maternity_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_PATERNITY:
                paternity_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_HAJJ:
                hajj_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_LIEU:
                lieu_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_EMERGENCY:
                emergency_leave_days += leave_policy_days
            elif leave_record.leave_type == EmployeeLeave.LEAVE_TYPE_OTHER:
                other_leave_days += leave_policy_days

        elif leave_record.status == EmployeeLeave.STATUS_PENDING:
            pending_leave_days += leave_policy_days
        elif leave_record.status == EmployeeLeave.STATUS_REJECTED:
            rejected_leave_requests += 1
        elif leave_record.status == EmployeeLeave.STATUS_CANCELLED:
            cancelled_leave_requests += 1

    approved_leave_days = len(approved_leave_dates)

    approved_future_annual_leave_days = 0
    future_approved_annual_leaves = employee.leave_records.filter(
        status=EmployeeLeave.STATUS_APPROVED,
        leave_type=EmployeeLeave.LEAVE_TYPE_ANNUAL,
        end_date__gt=today,
    ).order_by("start_date", "id")

    for leave_record in future_approved_annual_leaves:
        future_start = max(today + timedelta(days=1), employee.hire_date, leave_record.start_date)
        future_end = leave_record.end_date
        if future_start > future_end:
            continue

        approved_future_annual_leave_days += count_policy_working_days(future_start, future_end)

    annual_leave_taken_days = annual_leave_days
    annual_leave_balance_days = max(annual_leave_entitlement_days - annual_leave_taken_days, 0)
    annual_leave_available_after_planning_days = max(
        annual_leave_balance_days - approved_future_annual_leave_days,
        0,
    )

    ledger_entries = list(
        employee.attendance_ledgers.filter(
            attendance_date__gte=employee.hire_date,
            attendance_date__lte=today,
        ).order_by("attendance_date", "id")
    )

    if not ledger_entries:
        absence_days = employee.action_records.filter(
            action_type=EmployeeActionRecord.ACTION_TYPE_ABSENCE,
            action_date__gte=employee.hire_date,
            action_date__lte=today,
        ).count()

        punctuality_deduction_hours = Decimal("0.00")
        punctuality_records = employee.action_records.filter(
            action_type=EmployeeActionRecord.ACTION_TYPE_LATENESS,
            action_date__gte=employee.hire_date,
            action_date__lte=today,
        )
        for action_record in punctuality_records:
            punctuality_deduction_hours += get_lateness_deduction_hours(action_record)

        total_working_days = scheduled_working_days - approved_leave_days - absence_days
        if total_working_days < 0:
            total_working_days = 0

        total_working_hours = (Decimal(total_working_days) * WORKING_HOURS_PER_DAY) - punctuality_deduction_hours
        if total_working_hours < 0:
            total_working_hours = Decimal("0.00")

        return EmployeeWorkingTimeSummary(
            scheduled_working_days=scheduled_working_days,
            service_days=service_days,
            completed_service_years=completed_service_years,
            completed_service_months_remainder=completed_service_months_remainder,
            service_duration_display=service_duration_display,
            annual_leave_entitlement_days=annual_leave_entitlement_days,
            annual_leave_taken_days=annual_leave_taken_days,
            annual_leave_balance_days=annual_leave_balance_days,
            approved_future_annual_leave_days=approved_future_annual_leave_days,
            annual_leave_available_after_planning_days=annual_leave_available_after_planning_days,
            approved_leave_days=approved_leave_days,
            pending_leave_days=pending_leave_days,
            rejected_leave_requests=rejected_leave_requests,
            cancelled_leave_requests=cancelled_leave_requests,
            unpaid_leave_days=unpaid_leave_days,
            annual_leave_days=annual_leave_days,
            sick_leave_days=sick_leave_days,
            maternity_leave_days=maternity_leave_days,
            paternity_leave_days=paternity_leave_days,
            hajj_leave_days=hajj_leave_days,
            lieu_leave_days=lieu_leave_days,
            emergency_leave_days=emergency_leave_days,
            other_leave_days=other_leave_days,
            absence_days=absence_days,
            punctuality_deduction_hours=punctuality_deduction_hours.quantize(Decimal("0.01")),
            total_working_days=total_working_days,
            total_working_hours=total_working_hours.quantize(Decimal("0.01")),
        )

    ledger_by_date = {
        entry.attendance_date: entry
        for entry in ledger_entries
    }

    approved_leave_dates = get_employee_approved_leave_dates(employee, today)

    ledger_working_days = 0
    ledger_working_hours = Decimal("0.00")
    absence_days = 0
    punctuality_deduction_hours = Decimal("0.00")

    for entry in ledger_entries:
        if entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_ABSENT:
            absence_days += 1

        punctuality_deduction_hours += minutes_to_hours_decimal(entry.late_minutes or 0)
        punctuality_deduction_hours += minutes_to_hours_decimal(entry.early_departure_minutes or 0)

        if entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_PRESENT:
            ledger_working_days += 1
            ledger_working_hours += entry.worked_hours or Decimal("0.00")

    fallback_working_days = 0
    fallback_working_hours = Decimal("0.00")
    fallback_absence_days = 0
    fallback_punctuality_deduction_hours = Decimal("0.00")

    for current_date in iterate_dates(employee.hire_date, today):
        if not is_policy_working_day(current_date):
            continue

        if current_date in ledger_by_date:
            continue

        if current_date in approved_leave_dates:
            continue

        related_absence_action = employee.action_records.filter(
            action_type=EmployeeActionRecord.ACTION_TYPE_ABSENCE,
            action_date=current_date,
        ).exists()
        if related_absence_action:
            fallback_absence_days += 1
            continue

        fallback_working_days += 1
        fallback_working_hours += WORKING_HOURS_PER_DAY

        lateness_records = employee.action_records.filter(
            action_type=EmployeeActionRecord.ACTION_TYPE_LATENESS,
            action_date=current_date,
        )
        for action_record in lateness_records:
            fallback_punctuality_deduction_hours += get_lateness_deduction_hours(action_record)

    total_working_days = ledger_working_days + fallback_working_days
    total_working_hours = ledger_working_hours + fallback_working_hours
    absence_days += fallback_absence_days
    punctuality_deduction_hours += fallback_punctuality_deduction_hours

    if total_working_hours < 0:
        total_working_hours = Decimal("0.00")

    return EmployeeWorkingTimeSummary(
        scheduled_working_days=scheduled_working_days,
        service_days=service_days,
        completed_service_years=completed_service_years,
        completed_service_months_remainder=completed_service_months_remainder,
        service_duration_display=service_duration_display,
        annual_leave_entitlement_days=annual_leave_entitlement_days,
        annual_leave_taken_days=annual_leave_taken_days,
        annual_leave_balance_days=annual_leave_balance_days,
        approved_future_annual_leave_days=approved_future_annual_leave_days,
        annual_leave_available_after_planning_days=annual_leave_available_after_planning_days,
        approved_leave_days=approved_leave_days,
        pending_leave_days=pending_leave_days,
        rejected_leave_requests=rejected_leave_requests,
        cancelled_leave_requests=cancelled_leave_requests,
        unpaid_leave_days=unpaid_leave_days,
        annual_leave_days=annual_leave_days,
        sick_leave_days=sick_leave_days,
        maternity_leave_days=maternity_leave_days,
        paternity_leave_days=paternity_leave_days,
        hajj_leave_days=hajj_leave_days,
        lieu_leave_days=lieu_leave_days,
        emergency_leave_days=emergency_leave_days,
        other_leave_days=other_leave_days,
        absence_days=absence_days,
        punctuality_deduction_hours=punctuality_deduction_hours.quantize(Decimal("0.01")),
        total_working_days=total_working_days,
        total_working_hours=total_working_hours.quantize(Decimal("0.01")),
    )
```

## operations/models.py

```python
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Branch


def branch_post_attachment_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    branch_slug = (instance.branch.name or f"branch-{instance.branch_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"operations/branch-posts/{branch_slug}/{unique_name}{extension}"


class BranchPost(models.Model):
    POST_TYPE_ANNOUNCEMENT = "announcement"
    POST_TYPE_UPDATE = "update"
    POST_TYPE_TASK = "task"
    POST_TYPE_ISSUE = "issue"

    POST_TYPE_CHOICES = [
        (POST_TYPE_ANNOUNCEMENT, "Announcement"),
        (POST_TYPE_UPDATE, "Update"),
        (POST_TYPE_TASK, "Task"),
        (POST_TYPE_ISSUE, "Issue"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_DONE, "Done"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CLOSED, "Closed"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="posts")
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_posts",
        null=True,
        blank=True,
    )
    author_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="authored_branch_posts",
        null=True,
        blank=True,
    )
    assignee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="assigned_branch_posts",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default=POST_TYPE_UPDATE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, blank=True, default="")
    is_pinned = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    attachment = models.FileField(
        upload_to=branch_post_attachment_upload_to,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "gif",
                    "bmp",
                    "txt",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                ]
            )
        ],
    )
    due_date = models.DateField(null=True, blank=True)
    requires_acknowledgement = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_branch_posts",
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-updated_at", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "status", "-updated_at"]),
            models.Index(fields=["assignee", "status", "due_date"]),
            models.Index(fields=["post_type", "status"]),
        ]
        verbose_name = "Branch Post"
        verbose_name_plural = "Branch Posts"

    def __str__(self):
        return f"{self.branch.name} | {self.title}"

    @property
    def is_task_like(self):
        return self.post_type in {self.POST_TYPE_TASK, self.POST_TYPE_ISSUE}

    @property
    def author_display(self):
        if self.author_employee_id:
            return self.author_employee.full_name
        if self.author_user_id:
            return self.author_user.get_full_name() or self.author_user.email
        return "System"

    def mark_approved(self, user=None):
        self.status = self.STATUS_APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.closed_at = None

    def mark_closed(self):
        self.status = self.STATUS_CLOSED
        self.closed_at = timezone.now()


class BranchPostReply(models.Model):
    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="replies")
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_post_replies",
        null=True,
        blank=True,
    )
    author_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="branch_post_replies",
        null=True,
        blank=True,
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["post", "created_at"])]
        verbose_name = "Branch Post Reply"
        verbose_name_plural = "Branch Post Replies"

    def __str__(self):
        return f"Reply #{self.pk or 'new'} on {self.post_id}"

    @property
    def author_display(self):
        if self.author_employee_id:
            return self.author_employee.full_name
        if self.author_user_id:
            return self.author_user.get_full_name() or self.author_user.email
        return "System"


class BranchTaskAction(models.Model):
    ACTION_CREATED = "created"
    ACTION_STATUS_CHANGED = "status_changed"
    ACTION_ASSIGNED = "assigned"
    ACTION_REPLIED = "replied"
    ACTION_ACKNOWLEDGED = "acknowledged"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_PINNED = "pinned"
    ACTION_UNPINNED = "unpinned"
    ACTION_CLOSED = "closed"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_STATUS_CHANGED, "Status Changed"),
        (ACTION_ASSIGNED, "Assigned"),
        (ACTION_REPLIED, "Replied"),
        (ACTION_ACKNOWLEDGED, "Acknowledged"),
        (ACTION_APPROVED, "Approved"),
        (ACTION_REJECTED, "Rejected"),
        (ACTION_PINNED, "Pinned"),
        (ACTION_UNPINNED, "Unpinned"),
        (ACTION_CLOSED, "Closed"),
    ]

    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="actions")
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_task_actions",
        null=True,
        blank=True,
    )
    actor_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="branch_task_actions",
        null=True,
        blank=True,
    )
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["post", "-created_at"]),
            models.Index(fields=["action_type", "-created_at"]),
        ]
        verbose_name = "Branch Task Action"
        verbose_name_plural = "Branch Task Actions"

    def __str__(self):
        return f"{self.post_id} | {self.action_type}"

    @property
    def actor_display(self):
        if self.actor_employee_id:
            return self.actor_employee.full_name
        if self.actor_user_id:
            return self.actor_user.get_full_name() or self.actor_user.email
        return "System"


class BranchPostAcknowledgement(models.Model):
    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="acknowledgements")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="branch_post_acknowledgements")
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-acknowledged_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "employee"],
                name="ops_post_ack_post_employee_uniq",
            )
        ]
        verbose_name = "Branch Post Acknowledgement"
        verbose_name_plural = "Branch Post Acknowledgements"

    def __str__(self):
        return f"{self.post_id} | {self.employee.full_name}"
```

## organization/models.py

```python
from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def company_logo_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    company_slug = (instance.name or f"company-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"companies/logos/{company_slug}/{unique_name}{extension}"


def branch_image_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    company_name = instance.company.name if getattr(instance, "company_id", None) and instance.company_id else f"company-{getattr(instance, 'company_id', 'new')}"
    company_slug = str(company_name).strip().replace(" ", "-").lower()
    branch_slug = (instance.name or f"branch-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"branches/images/{company_slug}/{branch_slug}/{unique_name}{extension}"


class Company(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)

    # Current active business field
    legal_name = models.CharField(max_length=255, blank=True)

    # Compatibility-only legacy fields kept to match existing database safely.
    # These are not part of the new core hierarchy design, but must remain
    # until database cleanup is intentionally performed later.
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    address = models.TextField(blank=True, default="")
    logo = models.ImageField(
        upload_to=company_logo_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"]),
        ]
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name


class Branch(TimeStampedModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="branches",
    )
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    attendance_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    attendance_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    attendance_radius_meters = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Allowed attendance radius in meters from the fixed branch point.",
    )
    image = models.ImageField(
        upload_to=branch_image_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company__name", "name"]
        indexes = [
            models.Index(fields=["company", "is_active", "name"]),
            models.Index(fields=["city", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="org_branch_company_name_uniq",
            )
        ]
        verbose_name = "Branch"
        verbose_name_plural = "Branches"

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    def clean(self):
        errors = {}

        has_latitude = self.attendance_latitude is not None
        has_longitude = self.attendance_longitude is not None
        has_radius = self.attendance_radius_meters is not None

        if has_latitude or has_longitude or has_radius:
            if not (has_latitude and has_longitude and has_radius):
                message = "Latitude, longitude, and attendance radius must all be set together."
                if not has_latitude:
                    errors["attendance_latitude"] = message
                if not has_longitude:
                    errors["attendance_longitude"] = message
                if not has_radius:
                    errors["attendance_radius_meters"] = message

        if has_latitude and not (-90 <= self.attendance_latitude <= 90):
            errors["attendance_latitude"] = "Attendance latitude must stay between -90 and 90."

        if has_longitude and not (-180 <= self.attendance_longitude <= 180):
            errors["attendance_longitude"] = "Attendance longitude must stay between -180 and 180."

        if has_radius and self.attendance_radius_meters <= 0:
            errors["attendance_radius_meters"] = "Attendance radius must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def has_attendance_location_config(self):
        return (
            self.attendance_latitude is not None
            and self.attendance_longitude is not None
            and self.attendance_radius_meters is not None
        )


class Department(TimeStampedModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="departments",
    )
    # Compatibility-only field.
    # Must remain for database safety, but it is NOT part of the active hierarchy.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="legacy_departments",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    manager_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company__name", "name"]
        indexes = [
            models.Index(fields=["company", "is_active", "name"]),
            models.Index(fields=["branch", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="org_dept_company_name_uniq",
            )
        ]
        verbose_name = "Department"
        verbose_name_plural = "Departments"

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    def clean(self):
        errors = {}

        if self.branch and self.branch.company_id != self.company_id:
            errors["branch"] = "Legacy branch must belong to the same company as the department."

        if errors:
            raise ValidationError(errors)


class Section(TimeStampedModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="sections",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    supervisor_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department__company__name", "department__name", "name"]
        indexes = [
            models.Index(fields=["department", "is_active", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "name"],
                name="org_section_dept_name_uniq",
            )
        ]
        verbose_name = "Section"
        verbose_name_plural = "Sections"

    def __str__(self):
        return f"{self.department.name} - {self.name}"

    @property
    def company(self):
        return self.department.company


class JobTitle(TimeStampedModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="job_titles",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="job_titles",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [
            "section__department__company__name",
            "section__department__name",
            "section__name",
            "name",
        ]
        indexes = [
            models.Index(fields=["department", "is_active", "name"]),
            models.Index(fields=["section", "is_active", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "name"],
                name="org_jobtitle_section_name_uniq",
            )
        ]
        verbose_name = "Job Title"
        verbose_name_plural = "Job Titles"

    def __str__(self):
        if self.section:
            return f"{self.section.name} - {self.name}"
        return self.name

    @property
    def company(self):
        if self.section:
            return self.section.department.company
        return self.department.company

    def clean(self):
        errors = {}

        if not self.section:
            errors["section"] = "Job title must be linked to a section."

        if self.section:
            self.department = self.section.department

        if self.department and self.section and self.section.department_id != self.department_id:
            errors["section"] = "Selected section must belong to the selected department."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.section_id:
            self.department = self.section.department
        self.full_clean()
        return super().save(*args, **kwargs)


def branch_document_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    branch_slug = (instance.branch.name or f"branch-{instance.branch_id}").strip().replace(" ", "-").lower()
    company_slug = (instance.branch.company.name or f"company-{instance.branch.company_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"branches/documents/{company_slug}/{branch_slug}/{unique_name}{extension}"


class BranchDocumentRequirement(TimeStampedModel):
    DOCUMENT_TYPE_CHOICES = [
        ("legal", "Legal Document"),
        ("ad_license", "Ad License"),
        ("store_license", "Store License"),
        ("municipality", "Municipality / Permit"),
        ("lease", "Lease / Contract"),
        ("civil_defense", "Civil Defense / Safety"),
        ("insurance", "Insurance"),
        ("service", "Service Contract"),
        ("other", "Other"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="document_requirements",
    )
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default="other",
    )
    title = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_mandatory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch__company__name", "branch__name", "document_type", "title", "id"]
        indexes = [
            models.Index(fields=["branch", "is_active", "document_type"]),
            models.Index(fields=["is_mandatory", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "document_type"],
                name="org_branch_doc_req_type_uniq",
            )
        ]
        verbose_name = "Branch Document Requirement"
        verbose_name_plural = "Branch Document Requirements"

    def __str__(self):
        return f"{self.branch.name} - {self.display_title}"

    @property
    def display_title(self):
        return (self.title or self.get_document_type_display()).strip()



class BranchDocument(TimeStampedModel):
    DOCUMENT_TYPE_LEGAL = "legal"
    DOCUMENT_TYPE_AD_LICENSE = "ad_license"
    DOCUMENT_TYPE_STORE_LICENSE = "store_license"
    DOCUMENT_TYPE_MUNICIPALITY = "municipality"
    DOCUMENT_TYPE_LEASE = "lease"
    DOCUMENT_TYPE_CIVIL_DEFENSE = "civil_defense"
    DOCUMENT_TYPE_INSURANCE = "insurance"
    DOCUMENT_TYPE_SERVICE = "service"
    DOCUMENT_TYPE_OTHER = "other"

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_LEGAL, "Legal Document"),
        (DOCUMENT_TYPE_AD_LICENSE, "Ad License"),
        (DOCUMENT_TYPE_STORE_LICENSE, "Store License"),
        (DOCUMENT_TYPE_MUNICIPALITY, "Municipality / Permit"),
        (DOCUMENT_TYPE_LEASE, "Lease / Contract"),
        (DOCUMENT_TYPE_CIVIL_DEFENSE, "Civil Defense / Safety"),
        (DOCUMENT_TYPE_INSURANCE, "Insurance"),
        (DOCUMENT_TYPE_SERVICE, "Service Contract"),
        (DOCUMENT_TYPE_OTHER, "Other"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default=DOCUMENT_TYPE_OTHER,
    )
    reference_number = models.CharField(max_length=120, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    file = models.FileField(
        upload_to=branch_document_upload_to,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    description = models.TextField(blank=True)
    uploaded_by = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "document_type", "-created_at"]),
            models.Index(fields=["expiry_date", "is_required"]),
        ]
        verbose_name = "Branch Document"
        verbose_name_plural = "Branch Documents"

    def __str__(self):
        return self.title or self.filename

    def clean(self):
        errors = {}

        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            errors["expiry_date"] = "Expiry date cannot be earlier than issue date."

        if errors:
            raise ValidationError(errors)

    @property
    def filename(self):
        return Path(self.file.name).name if self.file else ""

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        from django.utils import timezone
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        days = self.days_until_expiry
        return days is not None and days < 0

    @property
    def is_expiring_soon(self):
        days = self.days_until_expiry
        return days is not None and 0 <= days <= 30

    @property
    def compliance_status_label(self):
        if not self.expiry_date:
            return "No Expiry Date"
        if self.is_expired:
            return "Expired"
        if self.is_expiring_soon:
            return "Expiring Soon"
        return "Valid"

    @property
    def compliance_badge_class(self):
        if not self.expiry_date:
            return "badge"
        if self.is_expired:
            return "badge-danger"
        if self.is_expiring_soon:
            return "badge-primary"
        return "badge-success"

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.reference_number = (self.reference_number or "").strip()
        self.description = (self.description or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)
```

## payroll/models.py

```python
from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Company


class PayrollProfile(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_HOLD = "hold"
    STATUS_INACTIVE = "inactive"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_HOLD, "On Hold"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="payroll_profile")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_profiles")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    housing_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    transport_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    fixed_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    pifss_employee_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0800"), validators=[MinValueValidator(Decimal("0.0000")), MaxValueValidator(Decimal("1.0000"))])
    pifss_employer_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1150"), validators=[MinValueValidator(Decimal("0.0000")), MaxValueValidator(Decimal("1.0000"))])
    bank_name = models.CharField(max_length=120, blank=True)
    iban = models.CharField(
        max_length=64,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z]{2}[0-9A-Z]{13,32}$",
                message="IBAN must use uppercase letters and numbers without spaces.",
            )
        ],
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee__full_name"]
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["employee", "status"]),
        ]
        verbose_name = "Payroll Profile"
        verbose_name_plural = "Payroll Profiles"

    def __str__(self):
        return f"{self.employee.full_name} payroll"

    @property
    def gross_salary(self):
        return (self.base_salary or Decimal("0.00")) + (self.housing_allowance or Decimal("0.00")) + (self.transport_allowance or Decimal("0.00"))

    @property
    def estimated_net_salary(self):
        pifss_employee_deduction = Decimal("0.00")
        if getattr(self.employee, "is_kuwaiti_national", False):
            pifss_employee_deduction = (
                (self.base_salary or Decimal("0.00")) * (self.pifss_employee_rate or Decimal("0.0000"))
            ).quantize(Decimal("0.01"))
        return self.gross_salary - (self.fixed_deduction or Decimal("0.00")) - pifss_employee_deduction


class PayrollObligation(models.Model):
    TYPE_LOAN = "loan"
    TYPE_ADVANCE = "advance"

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_HOLD = "hold"

    TYPE_CHOICES = [
        (TYPE_LOAN, "Loan"),
        (TYPE_ADVANCE, "Advance"),
    ]
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_HOLD, "On Hold"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_obligations")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_obligations")
    title = models.CharField(max_length=150)
    obligation_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    principal_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    installment_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    total_installments = models.PositiveIntegerField(default=1)
    paid_installments = models.PositiveIntegerField(default=0)
    start_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name", "-created_at"]
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["company", "status", "start_date"]),
        ]
        verbose_name = "Payroll Obligation"
        verbose_name_plural = "Payroll Obligations"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    @property
    def remaining_installments(self):
        return max(self.total_installments - self.paid_installments, 0)

    @property
    def remaining_balance(self):
        return max(
            (self.principal_amount or Decimal("0.00")) - (Decimal(self.paid_installments) * (self.installment_amount or Decimal("0.00"))),
            Decimal("0.00"),
        )

    @property
    def can_apply_installment(self):
        return self.status == self.STATUS_ACTIVE and self.remaining_installments > 0


class PayrollBonus(models.Model):
    TYPE_PERFORMANCE = "performance"
    TYPE_COMMISSION = "commission"
    TYPE_SEASONAL = "seasonal"
    TYPE_MANUAL = "manual"

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_HOLD = "hold"

    TYPE_CHOICES = [
        (TYPE_PERFORMANCE, "Performance"),
        (TYPE_COMMISSION, "Commission"),
        (TYPE_SEASONAL, "Seasonal"),
        (TYPE_MANUAL, "Manual"),
    ]
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_HOLD, "On Hold"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_bonuses")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_bonuses")
    title = models.CharField(max_length=150)
    bonus_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_MANUAL)
    awarded_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    award_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name", "-award_date", "-id"]
        indexes = [
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["company", "status", "-award_date"]),
        ]
        verbose_name = "Payroll Bonus"
        verbose_name_plural = "Payroll Bonuses"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    @property
    def remaining_balance(self):
        return max(
            (self.awarded_amount or Decimal("0.00")) - (self.paid_amount or Decimal("0.00")),
            Decimal("0.00"),
        )

    @property
    def can_apply_balance(self):
        return self.status == self.STATUS_ACTIVE and self.remaining_balance > Decimal("0.00")


class PayrollPeriod(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_REVIEW = "review"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_REVIEW, "In Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_periods")
    title = models.CharField(max_length=150)
    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        indexes = [
            models.Index(fields=["company", "status", "-period_start"]),
            models.Index(fields=["pay_date", "status"]),
        ]
        verbose_name = "Payroll Period"
        verbose_name_plural = "Payroll Periods"

    def __str__(self):
        return self.title

    @property
    def can_move_to_review(self):
        return self.status == self.STATUS_DRAFT

    @property
    def can_approve(self):
        return self.status == self.STATUS_REVIEW

    @property
    def can_mark_paid(self):
        return self.status == self.STATUS_APPROVED

    @property
    def can_reopen(self):
        return self.status in {self.STATUS_REVIEW, self.STATUS_APPROVED, self.STATUS_PAID}


class PayrollLine(models.Model):
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_lines")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    overtime_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    pifss_employee_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    pifss_employer_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0.00"))])
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=255, blank=True)
    snapshot_payload = models.JSONField(null=True, blank=True)
    snapshot_taken_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name"]
        indexes = [
            models.Index(fields=["payroll_period", "employee"]),
            models.Index(fields=["employee", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["payroll_period", "employee"],
                name="payroll_line_period_employee_uniq",
            )
        ]
        verbose_name = "Payroll Line"
        verbose_name_plural = "Payroll Lines"

    def __str__(self):
        return f"{self.employee.full_name} - {self.payroll_period.title}"

    @property
    def gross_total(self):
        return (
            (self.base_salary or Decimal("0.00"))
            + (self.allowances or Decimal("0.00"))
            + (self.overtime_amount or Decimal("0.00"))
            + self.adjustment_allowances_total
        )

    @property
    def adjustment_allowances_total(self):
        adjustments_manager = getattr(self, "adjustments", None)
        if adjustments_manager is None:
            return Decimal("0.00")
        total = Decimal("0.00")
        for adjustment in adjustments_manager.all():
            if adjustment.adjustment_type == PayrollAdjustment.TYPE_ALLOWANCE:
                total += adjustment.amount or Decimal("0.00")
        return total

    @property
    def adjustment_deductions_total(self):
        adjustments_manager = getattr(self, "adjustments", None)
        if adjustments_manager is None:
            return Decimal("0.00")
        total = Decimal("0.00")
        for adjustment in adjustments_manager.all():
            if adjustment.adjustment_type == PayrollAdjustment.TYPE_DEDUCTION:
                total += adjustment.amount or Decimal("0.00")
        return total

    @property
    def total_deductions_value(self):
        return (
            (self.deductions or Decimal("0.00"))
            + (self.pifss_employee_deduction or Decimal("0.00"))
            + self.adjustment_deductions_total
        )

    def calculate_net_pay(self):
        return self.gross_total - self.total_deductions_value

    @property
    def has_snapshot(self):
        return bool(self.snapshot_payload and self.snapshot_taken_at)


class PayrollAdjustment(models.Model):
    TYPE_ALLOWANCE = "allowance"
    TYPE_DEDUCTION = "deduction"

    TYPE_CHOICES = [
        (TYPE_ALLOWANCE, "Allowance"),
        (TYPE_DEDUCTION, "Deduction"),
    ]

    payroll_line = models.ForeignKey(PayrollLine, on_delete=models.CASCADE, related_name="adjustments")
    payroll_obligation = models.ForeignKey("PayrollObligation", on_delete=models.SET_NULL, related_name="generated_adjustments", null=True, blank=True)
    payroll_bonus = models.ForeignKey("PayrollBonus", on_delete=models.SET_NULL, related_name="generated_adjustments", null=True, blank=True)
    title = models.CharField(max_length=120)
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["adjustment_type", "title", "id"]
        indexes = [
            models.Index(fields=["payroll_line", "adjustment_type"]),
            models.Index(fields=["payroll_obligation"]),
            models.Index(fields=["payroll_bonus"]),
        ]
        verbose_name = "Payroll Adjustment"
        verbose_name_plural = "Payroll Adjustments"

    def __str__(self):
        return f"{self.title} - {self.payroll_line.employee.full_name}"


def current_payroll_month_label():
    return timezone.localdate().strftime("%B %Y")
```

## performance/models.py

```python
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Company


class ReviewCycle(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_CLOSED, "Closed"),
    ]

    title = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="review_cycles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        indexes = [
            models.Index(fields=["company", "status", "-period_start"]),
        ]
        verbose_name = "Review Cycle"
        verbose_name_plural = "Review Cycles"

    def __str__(self):
        return f"{self.title} - {self.company.name}"

    def clean(self):
        errors = {}
        if self.period_end and self.period_start and self.period_end < self.period_start:
            errors["period_end"] = "Review cycle end date cannot be earlier than the start date."
        if errors:
            raise ValidationError(errors)

    @property
    def is_locked(self):
        return self.status == self.STATUS_CLOSED

    def clone_as_draft(self):
        return ReviewCycle.objects.create(
            title=f"{self.title} (Copy)",
            period_start=self.period_start,
            period_end=self.period_end,
            status=self.STATUS_DRAFT,
            company=self.company,
        )


class PerformanceReview(models.Model):
    RATING_UNSATISFACTORY = "1"
    RATING_NEEDS_IMPROVEMENT = "2"
    RATING_MEETS_EXPECTATIONS = "3"
    RATING_EXCEEDS_EXPECTATIONS = "4"
    RATING_OUTSTANDING = "5"

    OVERALL_RATING_CHOICES = [
        (RATING_UNSATISFACTORY, "1 - Unsatisfactory"),
        (RATING_NEEDS_IMPROVEMENT, "2 - Needs Improvement"),
        (RATING_MEETS_EXPECTATIONS, "3 - Meets Expectations"),
        (RATING_EXCEEDS_EXPECTATIONS, "4 - Exceeds Expectations"),
        (RATING_OUTSTANDING, "5 - Outstanding"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_ACKNOWLEDGED = "acknowledged"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_ACKNOWLEDGED, "Acknowledged"),
    ]

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name="performance_reviews",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="performance_reviews",
    )
    reviewer = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="reviews_given",
    )
    overall_rating = models.CharField(
        max_length=2,
        choices=OVERALL_RATING_CHOICES,
        default=RATING_MEETS_EXPECTATIONS,
    )
    strengths = models.TextField()
    areas_for_improvement = models.TextField()
    goals_next_period = models.TextField()
    employee_comments = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_performance_reviews",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cycle__period_start", "-updated_at", "-id"]
        indexes = [
            models.Index(fields=["cycle", "status"]),
            models.Index(fields=["employee", "status"]),
            models.Index(fields=["reviewer", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["cycle", "employee"],
                name="perf_review_cycle_employee_uniq",
            )
        ]
        verbose_name = "Performance Review"
        verbose_name_plural = "Performance Reviews"

    def __str__(self):
        return f"{self.employee.full_name} - {self.cycle.title}"

    def clean(self):
        errors = {}
        if self.cycle_id and self.employee_id and self.employee.company_id != self.cycle.company_id:
            errors["cycle"] = "The selected review cycle must belong to the employee's company."
        if self.employee_id and self.reviewer_id and self.employee_id == self.reviewer_id:
            errors["reviewer"] = "Reviewer cannot be the same employee being reviewed."
        if self.reviewer_id and self.employee_id and self.reviewer.company_id != self.employee.company_id:
            errors["reviewer"] = "Reviewer must belong to the same company as the employee."
        if errors:
            raise ValidationError(errors)

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def acknowledge(self, *, employee_comments=""):
        self.status = self.STATUS_ACKNOWLEDGED
        if employee_comments:
            self.employee_comments = employee_comments
        self.acknowledged_at = timezone.now()
        self.save(update_fields=["status", "employee_comments", "acknowledged_at", "updated_at"])

    @property
    def is_locked(self):
        return bool(self.cycle_id and self.cycle.status == ReviewCycle.STATUS_CLOSED)


class PerformanceReviewComment(models.Model):
    review = models.ForeignKey(
        PerformanceReview,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performance_review_comments",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["review", "created_at"])]
        verbose_name = "Performance Review Comment"
        verbose_name_plural = "Performance Review Comments"

    def __str__(self):
        return f"{self.author_display_name} - {self.review}"

    @property
    def author_display_name(self):
        return self.author.get_full_name() or getattr(self.author, "username", "System")
```

## recruitment/models.py

```python
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Branch, Department


def candidate_cv_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.job_posting.title or f"job-{instance.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.full_name or f"candidate-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/cvs/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


def candidate_attachment_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.candidate.job_posting.title or f"job-{instance.candidate.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.candidate.full_name or f"candidate-{instance.candidate_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/attachments/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


def candidate_offer_letter_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.job_posting.title or f"job-{instance.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.full_name or f"candidate-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/offers/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


class JobPosting(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    title = models.CharField(max_length=255)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="job_postings",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="job_postings",
    )
    description = models.TextField()
    requirements = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    posted_date = models.DateField(default=timezone.localdate)
    closing_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_job_postings",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-posted_date", "-created_at", "title"]
        indexes = [
            models.Index(fields=["status", "-posted_date"]),
            models.Index(fields=["department", "status"]),
            models.Index(fields=["branch", "status"]),
        ]
        verbose_name = "Job Posting"
        verbose_name_plural = "Job Postings"

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.branch_id and self.department_id and self.branch.company_id != self.department.company_id:
            errors["branch"] = "Selected branch must belong to the same company as the department."
        if self.closing_date and self.posted_date and self.closing_date < self.posted_date:
            errors["closing_date"] = "Closing date cannot be earlier than the posted date."
        if errors:
            raise ValidationError(errors)


class Candidate(models.Model):
    STATUS_APPLIED = "applied"
    STATUS_SCREENING = "screening"
    STATUS_INTERVIEW = "interview"
    STATUS_OFFER = "offer"
    STATUS_HIRED = "hired"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_APPLIED, "Applied"),
        (STATUS_SCREENING, "Screening"),
        (STATUS_INTERVIEW, "Interview"),
        (STATUS_OFFER, "Offer"),
        (STATUS_HIRED, "Hired"),
        (STATUS_REJECTED, "Rejected"),
    ]

    OFFER_STATUS_NOT_SENT = "not_sent"
    OFFER_STATUS_PENDING = "pending"
    OFFER_STATUS_ACCEPTED = "accepted"
    OFFER_STATUS_DECLINED = "declined"

    OFFER_STATUS_CHOICES = [
        (OFFER_STATUS_NOT_SENT, "Not Sent"),
        (OFFER_STATUS_PENDING, "Pending Response"),
        (OFFER_STATUS_ACCEPTED, "Accepted"),
        (OFFER_STATUS_DECLINED, "Declined"),
    ]

    job_posting = models.ForeignKey(
        JobPosting,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50)
    nationality = models.CharField(max_length=100)
    cv_file = models.FileField(
        upload_to=candidate_cv_upload_to,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx"])
        ],
    )
    cover_letter = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_APPLIED)
    applied_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    offer_letter_file = models.FileField(
        upload_to=candidate_offer_letter_upload_to,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=["pdf", "doc", "docx"])
        ],
    )
    offer_sent_date = models.DateField(null=True, blank=True)
    offer_expiry_date = models.DateField(null=True, blank=True)
    offer_status = models.CharField(
        max_length=20,
        choices=OFFER_STATUS_CHOICES,
        default=OFFER_STATUS_NOT_SENT,
    )
    offer_decision_at = models.DateTimeField(null=True, blank=True)
    offer_decision_note = models.TextField(blank=True)
    recruiter_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_recruitment_candidates",
        null=True,
        blank=True,
    )
    hired_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="recruitment_candidates",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-applied_at", "full_name"]
        indexes = [
            models.Index(fields=["job_posting", "status", "-applied_at"]),
            models.Index(fields=["recruiter_owner", "status"]),
            models.Index(fields=["offer_status", "offer_expiry_date"]),
        ]
        verbose_name = "Candidate"
        verbose_name_plural = "Candidates"

    def __str__(self):
        return f"{self.full_name} - {self.job_posting.title}"

    @property
    def latest_interview(self):
        return self.interviews.order_by("-scheduled_at", "-id").first()

    @property
    def days_in_pipeline(self):
        applied_date = timezone.localtime(self.applied_at).date() if self.applied_at else timezone.localdate()
        return max((timezone.localdate() - applied_date).days, 0)

    def clean(self):
        errors = {}
        if self.offer_sent_date and self.offer_expiry_date and self.offer_expiry_date < self.offer_sent_date:
            errors["offer_expiry_date"] = "Offer expiry date cannot be earlier than the offer sent date."
        if self.offer_status in {self.OFFER_STATUS_ACCEPTED, self.OFFER_STATUS_DECLINED} and not self.offer_decision_at:
            self.offer_decision_at = timezone.now()
        if errors:
            raise ValidationError(errors)


class CandidateStageAction(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="stage_actions",
    )
    stage = models.CharField(max_length=50)
    action_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="candidate_stage_actions",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["candidate", "-created_at"]),
            models.Index(fields=["stage", "-created_at"]),
        ]
        verbose_name = "Candidate Stage Action"
        verbose_name_plural = "Candidate Stage Actions"

    def __str__(self):
        return f"{self.candidate.full_name} - {self.stage}"


class CandidateInterview(models.Model):
    INTERVIEW_TYPE_PHONE = "phone"
    INTERVIEW_TYPE_VIDEO = "video"
    INTERVIEW_TYPE_IN_PERSON = "in_person"

    INTERVIEW_TYPE_CHOICES = [
        (INTERVIEW_TYPE_PHONE, "Phone"),
        (INTERVIEW_TYPE_VIDEO, "Video"),
        (INTERVIEW_TYPE_IN_PERSON, "In Person"),
    ]

    RECOMMENDATION_STRONG_YES = "strong_yes"
    RECOMMENDATION_YES = "yes"
    RECOMMENDATION_HOLD = "hold"
    RECOMMENDATION_NO = "no"

    RECOMMENDATION_CHOICES = [
        (RECOMMENDATION_STRONG_YES, "Strong Yes"),
        (RECOMMENDATION_YES, "Yes"),
        (RECOMMENDATION_HOLD, "Hold"),
        (RECOMMENDATION_NO, "No"),
    ]

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="interviews",
    )
    scheduled_at = models.DateTimeField()
    interview_type = models.CharField(max_length=20, choices=INTERVIEW_TYPE_CHOICES, default=INTERVIEW_TYPE_IN_PERSON)
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="candidate_interviews",
        null=True,
        blank=True,
    )
    location = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    outcome = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
    )
    recommendation = models.CharField(
        max_length=20,
        choices=RECOMMENDATION_CHOICES,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at", "id"]
        indexes = [
            models.Index(fields=["candidate", "scheduled_at"]),
            models.Index(fields=["interviewer", "scheduled_at"]),
        ]
        verbose_name = "Candidate Interview"
        verbose_name_plural = "Candidate Interviews"

    def __str__(self):
        return f"{self.candidate.full_name} interview on {self.scheduled_at:%Y-%m-%d %H:%M}"

    def clean(self):
        errors = {}
        if self._state.adding and self.scheduled_at and self.scheduled_at < timezone.now():
            errors["scheduled_at"] = "Interview time cannot be in the past."
        if self.score is not None and self.score > 100:
            errors["score"] = "Interview score cannot be greater than 100."
        if errors:
            raise ValidationError(errors)


class CandidateInterviewFeedback(models.Model):
    interview = models.ForeignKey(
        CandidateInterview,
        on_delete=models.CASCADE,
        related_name="feedback_entries",
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="candidate_interview_feedback",
    )
    score = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MaxValueValidator(100)],
    )
    recommendation = models.CharField(
        max_length=20,
        choices=CandidateInterview.RECOMMENDATION_CHOICES,
        blank=True,
    )
    strengths = models.TextField(blank=True)
    concerns = models.TextField(blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["interview", "interviewer"],
                name="recruit_feedback_interviewer_uniq",
            )
        ]
        verbose_name = "Candidate Interview Feedback"
        verbose_name_plural = "Candidate Interview Feedback"

    def __str__(self):
        return f"{self.interview.candidate.full_name} feedback by {self.interviewer}"

    def clean(self):
        errors = {}
        if self.score is not None and self.score > 100:
            errors["score"] = "Feedback score cannot be greater than 100."
        if errors:
            raise ValidationError(errors)


class CandidateAttachment(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    title = models.CharField(max_length=255)
    file = models.FileField(
        upload_to=candidate_attachment_upload_to,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="candidate_attachments",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["candidate", "-created_at"])]
        verbose_name = "Candidate Attachment"
        verbose_name_plural = "Candidate Attachments"

    def __str__(self):
        return f"{self.candidate.full_name} - {self.title}"
```

## workcalendar/models.py

```python
from django.core.exceptions import ValidationError
from django.db import models


WEEKDAY_CHOICES = [
    (0, "Monday"),
    (1, "Tuesday"),
    (2, "Wednesday"),
    (3, "Thursday"),
    (4, "Friday"),
    (5, "Saturday"),
    (6, "Sunday"),
]


class RegionalWorkCalendar(models.Model):
    name = models.CharField(max_length=150, default="Kuwait Government Work Calendar")
    region_code = models.CharField(max_length=10, default="KW")
    weekend_days = models.CharField(max_length=20, default="4")
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regional Work Calendar"
        verbose_name_plural = "Regional Work Calendars"
        ordering = ["-is_active", "name", "-id"]
        indexes = [
            models.Index(fields=["is_active", "region_code"]),
        ]

    def __str__(self):
        return self.name

    @property
    def weekend_day_numbers(self):
        values = set()
        for raw_value in (self.weekend_days or "").split(","):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            try:
                weekday_number = int(raw_value)
            except (TypeError, ValueError):
                continue
            if 0 <= weekday_number <= 6:
                values.add(weekday_number)
        return values

    @property
    def weekend_day_labels(self):
        label_map = dict(WEEKDAY_CHOICES)
        return [label_map[number] for number in sorted(self.weekend_day_numbers) if number in label_map]

    def clean(self):
        errors = {}
        parsed_days = self.weekend_day_numbers
        if not parsed_days:
            errors["weekend_days"] = "Select at least one weekly off day."

        if self.is_active:
            existing_active = RegionalWorkCalendar.objects.filter(is_active=True)
            if self.pk:
                existing_active = existing_active.exclude(pk=self.pk)
            if existing_active.exists():
                errors["is_active"] = "Only one active regional work calendar can be enabled at a time."

        if errors:
            raise ValidationError(errors)


class RegionalHoliday(models.Model):
    HOLIDAY_TYPE_PUBLIC = "public"
    HOLIDAY_TYPE_OBSERVANCE = "observance"

    HOLIDAY_TYPE_CHOICES = [
        (HOLIDAY_TYPE_PUBLIC, "Public Holiday"),
        (HOLIDAY_TYPE_OBSERVANCE, "Official Observance"),
    ]

    calendar = models.ForeignKey(
        RegionalWorkCalendar,
        on_delete=models.CASCADE,
        related_name="holidays",
    )
    holiday_date = models.DateField(db_index=True)
    title = models.CharField(max_length=160)
    holiday_type = models.CharField(
        max_length=20,
        choices=HOLIDAY_TYPE_CHOICES,
        default=HOLIDAY_TYPE_PUBLIC,
    )
    is_non_working_day = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["holiday_date", "title", "id"]
        indexes = [
            models.Index(fields=["calendar", "holiday_date"]),
            models.Index(fields=["is_non_working_day", "holiday_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["calendar", "holiday_date", "title"],
                name="workcal_holiday_calendar_date_title_uniq",
            )
        ]
        verbose_name = "Regional Holiday"
        verbose_name_plural = "Regional Holidays"

    def __str__(self):
        return f"{self.title} ({self.holiday_date})"
```

## employees/migrations/0043_alter_branchschedulegridcell_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces legacy unique_together declarations with named
# UniqueConstraint objects for branch schedule/grid models. It keeps the same
# uniqueness rules already represented by previous migrations, but gives them
# stable names so future constraint changes are easier to reason about.
#
# No data backfill is required because this migration does not add stricter
# uniqueness than the existing schema already intended.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0042_alter_employee_options_and_more'),
        ('organization', '0011_alter_branch_unique_together_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='branchschedulegridcell',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchschedulegridheader',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchschedulegridrow',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchweeklydutyoption',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchweeklypendingoff',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchweeklyscheduleentry',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='branchschedulegridcell',
            constraint=models.UniqueConstraint(fields=('branch', 'row_index', 'column_index'), name='emp_grid_cell_branch_row_col_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchschedulegridheader',
            constraint=models.UniqueConstraint(fields=('branch', 'column_index'), name='emp_grid_header_branch_col_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchschedulegridrow',
            constraint=models.UniqueConstraint(fields=('branch', 'row_index'), name='emp_grid_row_branch_row_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchweeklydutyoption',
            constraint=models.UniqueConstraint(fields=('branch', 'label'), name='emp_duty_option_branch_label_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchweeklypendingoff',
            constraint=models.UniqueConstraint(fields=('branch', 'employee', 'week_start'), name='emp_pending_off_branch_emp_week_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchweeklyscheduleentry',
            constraint=models.UniqueConstraint(fields=('branch', 'employee', 'schedule_date'), name='emp_weekly_entry_branch_emp_date_uniq'),
        ),
    ]
```

## operations/migrations/0003_alter_branchpostacknowledgement_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces the legacy unique_together declaration on branch post
# acknowledgements with an equivalent named UniqueConstraint. The rule remains:
# one acknowledgement row per post/employee pair.
#
# No data backfill is required because the same uniqueness rule was already
# enforced by the legacy declaration.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0043_alter_branchschedulegridcell_unique_together_and_more'),
        ('operations', '0002_alter_branchpost_options_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='branchpostacknowledgement',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='branchpostacknowledgement',
            constraint=models.UniqueConstraint(fields=('post', 'employee'), name='ops_post_ack_post_employee_uniq'),
        ),
    ]
```

## organization/migrations/0011_alter_branch_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces legacy unique_together declarations with named
# UniqueConstraint objects for organization hierarchy models. It preserves the
# same uniqueness behavior that existing migrations already enforced, while
# giving each database rule a stable, descriptive name for future maintenance.
#
# No data backfill is required because this does not introduce a new uniqueness
# rule; it renames/re-expresses existing database semantics.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organization', '0010_alter_branch_options_alter_branchdocument_options_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='branch',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='branchdocumentrequirement',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='department',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='jobtitle',
            unique_together=set(),
        ),
        migrations.AlterUniqueTogether(
            name='section',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='branch',
            constraint=models.UniqueConstraint(fields=('company', 'name'), name='org_branch_company_name_uniq'),
        ),
        migrations.AddConstraint(
            model_name='branchdocumentrequirement',
            constraint=models.UniqueConstraint(fields=('branch', 'document_type'), name='org_branch_doc_req_type_uniq'),
        ),
        migrations.AddConstraint(
            model_name='department',
            constraint=models.UniqueConstraint(fields=('company', 'name'), name='org_dept_company_name_uniq'),
        ),
        migrations.AddConstraint(
            model_name='jobtitle',
            constraint=models.UniqueConstraint(fields=('section', 'name'), name='org_jobtitle_section_name_uniq'),
        ),
        migrations.AddConstraint(
            model_name='section',
            constraint=models.UniqueConstraint(fields=('department', 'name'), name='org_section_dept_name_uniq'),
        ),
    ]
```

## payroll/migrations/0008_alter_payrollline_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces the legacy unique_together declaration on PayrollLine
# with an equivalent named UniqueConstraint. The business rule remains one
# payroll line per payroll period and employee.
#
# No data backfill is required because the same uniqueness rule was already
# represented by the previous schema.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0043_alter_branchschedulegridcell_unique_together_and_more'),
        ('payroll', '0007_alter_payrollbonus_paid_amount_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='payrollline',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='payrollline',
            constraint=models.UniqueConstraint(fields=('payroll_period', 'employee'), name='payroll_line_period_employee_uniq'),
        ),
    ]
```

## performance/migrations/0004_alter_performancereview_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces the legacy unique_together declaration on
# PerformanceReview with an equivalent named UniqueConstraint. The rule remains
# one review per cycle and employee.
#
# No data backfill is required because this preserves an existing uniqueness
# rule instead of introducing a new one.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0043_alter_branchschedulegridcell_unique_together_and_more'),
        ('performance', '0003_alter_performancereview_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='performancereview',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='performancereview',
            constraint=models.UniqueConstraint(fields=('cycle', 'employee'), name='perf_review_cycle_employee_uniq'),
        ),
    ]
```

## recruitment/migrations/0008_alter_candidateinterviewfeedback_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces the legacy unique_together declaration on candidate
# interview feedback with an equivalent named UniqueConstraint. The rule remains
# one feedback row per interview/interviewer pair.
#
# No data backfill is required because the same uniqueness rule was already
# represented by the previous schema.

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recruitment', '0007_alter_candidate_options_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='candidateinterviewfeedback',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='candidateinterviewfeedback',
            constraint=models.UniqueConstraint(fields=('interview', 'interviewer'), name='recruit_feedback_interviewer_uniq'),
        ),
    ]
```

## workcalendar/migrations/0004_alter_regionalholiday_unique_together_and_more.py

```python
# Generated by Django 6.0.3 on 2026-04-24 12:20
#
# Phase 2 model-quality migration.
#
# This migration replaces the legacy unique_together declaration on regional
# holidays with an equivalent named UniqueConstraint. The rule remains one
# holiday title per calendar/date pair.
#
# No data backfill is required because this preserves an existing uniqueness
# rule instead of adding a stricter one.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workcalendar', '0003_alter_regionalholiday_options_and_more'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='regionalholiday',
            unique_together=set(),
        ),
        migrations.AddConstraint(
            model_name='regionalholiday',
            constraint=models.UniqueConstraint(fields=('calendar', 'holiday_date', 'title'), name='workcal_holiday_calendar_date_title_uniq'),
        ),
    ]
```
