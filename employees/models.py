from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import re
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
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
    photo = models.ImageField(upload_to="employees/photos/", blank=True, null=True)

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
    salary = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
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


WORKING_HOURS_PER_DAY = Decimal("8.00")
WEEKLY_OFF_WEEKDAYS = {4}  # Friday only
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

    working_days = 0
    for current_date in iterate_dates(start_date, end_date):
        if current_date.weekday() not in WEEKLY_OFF_WEEKDAYS:
            working_days += 1
    return working_days


def is_policy_working_day(value):
    if not value:
        return False
    return value.weekday() not in WEEKLY_OFF_WEEKDAYS


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


def combine_date_and_time(target_date, target_time):
    if not target_date or not target_time:
        return None
    return datetime.combine(target_date, target_time)


def decimal_hours_from_datetimes(start_dt, end_dt):
    if not start_dt or not end_dt or end_dt <= start_dt:
        return Decimal("0.00")
    total_seconds = Decimal((end_dt - start_dt).total_seconds())
    total_hours = total_seconds / Decimal("3600")
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
    LEAVE_TYPE_EMERGENCY = "emergency"
    LEAVE_TYPE_OTHER = "other"

    LEAVE_TYPE_CHOICES = [
        (LEAVE_TYPE_ANNUAL, "Annual Leave"),
        (LEAVE_TYPE_SICK, "Sick Leave"),
        (LEAVE_TYPE_UNPAID, "Unpaid Leave"),
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
    total_days = models.PositiveIntegerField(default=1)
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
        return (self.end_date - self.start_date).days + 1

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

    SHIFT_CHOICES = [
        (SHIFT_MORNING, "Morning Shift"),
        (SHIFT_MIDDLE, "Middle Shift"),
        (SHIFT_NIGHT, "Night Shift"),
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
        SHIFT_MORNING: ("09:00", "18:00"),
        SHIFT_MIDDLE: ("13:00", "22:00"),
        SHIFT_NIGHT: ("22:00", "06:00"),
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
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "attendance_date"],
                name="unique_employee_attendance_date",
            )
        ]

    def __str__(self):
        return f"{self.employee.full_name} - {self.attendance_date} - {self.get_day_status_display()}"

    @classmethod
    def get_shift_time_map(cls):
        return {
            cls.SHIFT_MORNING: {"label": "Morning Shift", "start": "09:00", "end": "18:00"},
            cls.SHIFT_MIDDLE: {"label": "Middle Shift", "start": "13:00", "end": "22:00"},
            cls.SHIFT_NIGHT: {"label": "Night Shift", "start": "22:00", "end": "06:00"},
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
            return "0.00"
        total_seconds = Decimal((self.check_out_at - self.check_in_at).total_seconds())
        hours = total_seconds / Decimal("3600")
        return f"{hours.quantize(Decimal('0.01'))}"

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
        unique_together = ("branch", "employee", "schedule_date")

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
        unique_together = ("branch", "label")

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
        unique_together = ("branch", "employee", "week_start")

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
        unique_together = ("branch", "column_index")

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
        unique_together = ("branch", "row_index")

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
        unique_together = ("branch", "row_index", "column_index")

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
        emergency_leave_days=emergency_leave_days,
        other_leave_days=other_leave_days,
        absence_days=absence_days,
        punctuality_deduction_hours=punctuality_deduction_hours.quantize(Decimal("0.01")),
        total_working_days=total_working_days,
        total_working_hours=total_working_hours.quantize(Decimal("0.01")),
    )
