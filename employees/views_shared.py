from datetime import date, datetime, timedelta
import csv
from decimal import Decimal
import io
from math import asin, cos, radians, sin, sqrt
import mimetypes
import re
from pathlib import Path

from django import forms
from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, IntegerField, Prefetch, Q, When
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from config.access import (
    api_role_required,
    is_any_management,
    is_employee_role,
    is_hr,
    is_operations,
    is_supervisor,
    role_required,
)
from config.mixins import ProtectedDeleteMixin
from organization.models import Branch, Company, Department, JobTitle, Section
from payroll.forms import PayrollProfileForm
from operations.forms import BranchPostForm
from operations.services import build_branch_workspace_context, build_employee_schedule_snapshot
from openpyxl import Workbook, load_workbook
from notifications.models import InAppNotification, build_in_app_notification
from notifications.views import persist_in_app_notifications

from .access import (
    get_user_scope_branch as get_user_scope_branch_for_role,
    get_workspace_home_label,
    get_workspace_profile_url,
    is_admin_compatible as is_admin_compatible_role,
    is_branch_scoped_supervisor as is_branch_scoped_supervisor_for_role,
    is_employee_role_user as is_employee_role_user_role,
    is_hr_user as is_hr_user_role,
    is_operations_manager_user as is_operations_manager_user_role,
    is_supervisor_user as is_supervisor_user_role,
    should_use_management_own_profile,
)
from .forms import (
    AttendanceFilterForm,
    AttendanceManagementFilterForm,
    BranchWeeklyScheduleThemeForm,
    BranchWeeklyDutyOptionStyleForm,
    BranchWeeklyDutyOptionTimingForm,
    BranchWeeklyDutyOptionForm,
    BranchWeeklyScheduleImportForm,
    BranchWeeklyPendingOffForm,
    BranchWeeklyScheduleEntryForm,
    EmployeeActionRecordForm,
    EmployeeAttendanceCorrectionForm,
    EmployeeSelfServiceAttendanceForm,
    EmployeeAttendanceLedgerForm,
    EmployeeContractForm,
    EmployeeDocumentForm,
    EmployeeForm,
    EmployeeHistoryForm,
    EmployeeLeaveForm,
    EmployeeOvertimeRequestForm,
    EmployeeRequiredSubmissionCreateForm,
    EmployeeRequiredSubmissionResponseForm,
    EmployeeRequiredSubmissionReviewForm,
    EmployeeDocumentRequestCreateForm,
    EmployeeDocumentRequestReviewForm,
    OvertimeRequestReviewForm,
    EmployeeSelfServiceLeaveRequestForm,
    EmployeeTransferForm,
)
from .models import (
    BranchScheduleGridCell,
    BranchScheduleGridHeader,
    BranchScheduleGridRow,
    BranchWeeklyScheduleTheme,
    BranchWeeklyDutyOption,
    BranchWeeklyPendingOff,
    BranchWeeklyScheduleEntry,
    Employee,
    EmployeeActionRecord,
    EmployeeAttendanceCorrection,
    EmployeeAttendanceEvent,
    EmployeeAttendanceLedger,
    EmployeeDocument,
    EmployeeHistory,
    EmployeeLeave,
    OvertimeRequest,
    EmployeeRequiredSubmission,
    EmployeeDocumentRequest,
    WORKING_HOURS_PER_DAY,
    build_employee_working_time_summary,
    count_policy_working_days,
    format_decimal_hours_as_hours_minutes,
    format_minutes_as_hours_minutes,
    get_schedule_week_start,
    is_policy_holiday,
    is_policy_weekly_off_day,
)

FREE_SCHEDULE_GRID_DEFAULT_HEADERS = {
    0: "Employee",
    1: "Job Title",
    2: "Sunday",
    3: "Monday",
    4: "Tuesday",
    5: "Wednesday",
    6: "Thursday",
    7: "Friday",
    8: "Saturday",
    9: "Notes",
    10: "Orders",
    11: "Follow Up",
}


def create_employee_history(
    employee,
    title,
    description="",
    event_type=EmployeeHistory.EVENT_NOTE,
    created_by="",
    is_system_generated=False,
    event_date=None,
):
    EmployeeHistory.objects.create(
        employee=employee,
        title=title,
        description=description,
        event_type=event_type,
        created_by=created_by,
        is_system_generated=is_system_generated,
        event_date=event_date or timezone.localdate(),
    )


def get_distinct_active_notification_users(*users):
    distinct_users = []
    seen_user_ids = set()
    for user in users:
        if not user or not getattr(user, "is_active", False):
            continue
        if user.pk in seen_user_ids:
            continue
        seen_user_ids.add(user.pk)
        distinct_users.append(user)
    return distinct_users


def get_distinct_active_notification_users_excluding(*users, exclude=None):
    excluded_user_ids = {
        user.pk
        for user in exclude or []
        if user and getattr(user, "pk", None) is not None
    }
    return [
        user
        for user in get_distinct_active_notification_users(*users)
        if user.pk not in excluded_user_ids
    ]


def get_employee_notification_user(employee):
    linked_user = getattr(employee, "user", None)
    if linked_user and linked_user.is_active:
        return linked_user
    return None


def get_employee_management_detail_url(employee):
    return reverse("employees:employee_detail", kwargs={"pk": employee.pk})


def queue_request_notification(
    notifications,
    *,
    recipient,
    employee,
    title,
    body,
    self_service_url,
    management_url="",
    category=InAppNotification.CATEGORY_REQUEST,
    level=InAppNotification.LEVEL_INFO,
    exclude_users=None,
):
    if not recipient or not getattr(recipient, "is_active", False):
        return

    action_url = self_service_url if getattr(employee, "user_id", None) == recipient.pk else (management_url or self_service_url)
    notifications.append(
        build_in_app_notification(
            recipient=recipient,
            title=title,
            body=body,
            category=category,
            level=level,
            action_url=action_url,
            exclude_users=exclude_users,
        )
    )


def notify_employee_status_updated(employee, *, actor_label=""):
    employee_user = get_employee_notification_user(employee)
    if not employee_user:
        return

    notifications = []
    queue_request_notification(
        notifications,
        recipient=employee_user,
        employee=employee,
        title="Employment status updated",
        body=(
            f"Your employee status is now {employee.get_employment_status_display()}."
            + (f" Updated by {actor_label}." if actor_label else "")
        ),
        self_service_url=reverse("employees:self_service_profile"),
        management_url=get_employee_management_detail_url(employee),
        category=InAppNotification.CATEGORY_EMPLOYEE,
        level=InAppNotification.LEVEL_INFO,
    )
    dispatch_request_notifications(notifications)


def notify_employee_action_record_created(employee, action_record):
    employee_user = get_employee_notification_user(employee)
    if not employee_user:
        return

    notifications = []
    queue_request_notification(
        notifications,
        recipient=employee_user,
        employee=employee,
        title=f"Employee record added: {action_record.title}",
        body=(
            f"{action_record.get_action_type_display()} was recorded with status "
            f"{action_record.get_status_display()} and severity {action_record.get_severity_display()}."
            + (f" Note: {action_record.description}" if action_record.description else "")
        ),
        self_service_url=reverse("employees:self_service_profile"),
        management_url=get_employee_management_detail_url(employee),
        category=InAppNotification.CATEGORY_EMPLOYEE,
        level=InAppNotification.LEVEL_WARNING,
    )
    dispatch_request_notifications(notifications)


def notify_employee_attendance_record_created(employee, attendance_entry):
    employee_user = get_employee_notification_user(employee)
    if not employee_user:
        return

    notifications = []
    queue_request_notification(
        notifications,
        recipient=employee_user,
        employee=employee,
        title=f"Attendance updated: {attendance_entry.attendance_date:%b %d, %Y}",
        body=(
            f"Your attendance was updated to {attendance_entry.get_day_status_display()}."
            + (
                f" Worked hours: {attendance_entry.worked_hours_display}."
                if attendance_entry.worked_hours is not None
                else ""
            )
        ),
        self_service_url=reverse("employees:self_service_attendance"),
        management_url=reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
        category=InAppNotification.CATEGORY_EMPLOYEE,
        level=InAppNotification.LEVEL_INFO,
    )
    dispatch_request_notifications(notifications)


def notify_schedule_week_updated(branch, week_start, employees, *, actor_label="", detail_text=""):
    notifications = []
    management_url = reverse("employees:self_service_weekly_schedule") + f"?week={week_start.isoformat()}"
    for employee in employees:
        employee_user = get_employee_notification_user(employee)
        if not employee_user:
            continue
        queue_request_notification(
            notifications,
            recipient=employee_user,
            employee=employee,
            title=f"Weekly schedule updated: {branch.name}",
            body=(
                f"Your schedule for the week starting {week_start:%b %d, %Y} was updated."
                + (f" {detail_text}" if detail_text else "")
                + (f" Updated by {actor_label}." if actor_label else "")
            ),
            self_service_url=reverse("employees:self_service_my_schedule"),
            management_url=management_url,
            category=InAppNotification.CATEGORY_SCHEDULE,
            level=InAppNotification.LEVEL_INFO,
        )
    dispatch_request_notifications(notifications)


def dispatch_request_notifications(notifications):
    deduped_notifications = []
    seen_keys = set()
    for notification in notifications:
        if notification is None:
            continue
        notification_key = (
            notification.recipient_id,
            notification.title,
            notification.body,
            notification.action_url,
            notification.category,
        )
        if notification_key in seen_keys:
            continue
        seen_keys.add(notification_key)
        deduped_notifications.append(notification)

    return len(persist_in_app_notifications(deduped_notifications))


def get_leave_stage_reviewer_users(leave_record):
    user_model = get_user_model()
    employee = leave_record.employee

    if leave_record.current_stage == EmployeeLeave.STAGE_SUPERVISOR_REVIEW:
        return list(
            user_model.objects.filter(
                is_active=True,
                role=user_model.ROLE_SUPERVISOR,
                employee_profile__branch=employee.branch,
            ).distinct().order_by("email")
        )

    if leave_record.current_stage == EmployeeLeave.STAGE_OPERATIONS_REVIEW:
        return list(
            user_model.objects.filter(
                Q(is_superuser=True) | Q(role=user_model.ROLE_OPERATIONS_MANAGER),
                is_active=True,
            ).distinct().order_by("email")
        )

    if leave_record.current_stage == EmployeeLeave.STAGE_HR_REVIEW:
        return list(
            user_model.objects.filter(
                Q(is_superuser=True) | Q(role=user_model.ROLE_HR),
                is_active=True,
            ).distinct().order_by("email")
        )

    return []


def get_employee_management_reviewer_users(employee):
    user_model = get_user_model()
    if not employee:
        return []

    branch_supervisors = user_model.objects.filter(
        is_active=True,
        role=user_model.ROLE_SUPERVISOR,
        employee_profile__branch=employee.branch,
    )
    company_reviewers = user_model.objects.filter(
        Q(is_superuser=True)
        | Q(role=user_model.ROLE_HR)
        | Q(role=user_model.ROLE_OPERATIONS_MANAGER),
        is_active=True,
    )
    return list(
        get_distinct_active_notification_users(
            *branch_supervisors.distinct().order_by("email"),
            *company_reviewers.distinct().order_by("email"),
        )
    )


def get_document_request_reviewer_users(document_request):
    if not document_request:
        return []
    return get_employee_management_reviewer_users(document_request.employee)


def get_required_submission_reviewer_users(submission_request):
    if not submission_request:
        return []

    primary_reviewer = submission_request.created_by
    if primary_reviewer and getattr(primary_reviewer, "is_active", False):
        return [primary_reviewer]

    return get_employee_management_reviewer_users(submission_request.employee)


def get_attendance_correction_reviewer_users(correction):
    if not correction:
        return []
    return get_employee_management_reviewer_users(correction.employee)


def notify_leave_request_submitted(leave_record):
    employee = leave_record.employee
    reviewer_users = get_distinct_active_notification_users(*get_leave_stage_reviewer_users(leave_record))
    notifications = []
    leave_label = leave_record.get_leave_type_display()
    employee_url = reverse("employees:self_service_leave")

    for user in reviewer_users:
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Leave request awaiting review: {employee.full_name}",
            body=(
                f"{employee.full_name} submitted a {leave_label.lower()} request "
                f"for {leave_record.total_days} day(s)."
            ),
            self_service_url=employee_url,
            management_url=reverse("employees:employee_requests_overview"),
            level=InAppNotification.LEVEL_WARNING,
            exclude_users=[leave_record.requested_by],
        )

    dispatch_request_notifications(notifications)


def notify_leave_request_status_change(leave_record, *, title, body, notify_next_stage=False):
    employee = leave_record.employee
    employee_user = get_employee_notification_user(employee)
    actor_users = get_distinct_active_notification_users(
        leave_record.reviewed_by,
        leave_record.approved_by,
        leave_record.rejected_by,
        leave_record.cancelled_by,
    )
    stakeholder_users = get_distinct_active_notification_users_excluding(
        employee_user,
        leave_record.requested_by,
        leave_record.reviewed_by,
        leave_record.approved_by,
        leave_record.rejected_by,
        leave_record.cancelled_by,
        exclude=actor_users,
    )
    notifications = []
    employee_url = reverse("employees:self_service_leave")
    management_url = get_employee_management_detail_url(employee)
    if notify_next_stage:
        next_stage_label = get_leave_current_stage_owner_label(leave_record)
        body = f"{body} Next step: {next_stage_label}."

    for user in stakeholder_users:
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=title,
            body=body,
            self_service_url=employee_url,
            management_url=management_url,
            level=InAppNotification.LEVEL_SUCCESS if leave_record.status == EmployeeLeave.STATUS_APPROVED else InAppNotification.LEVEL_INFO,
        )

    if notify_next_stage:
        for user in get_distinct_active_notification_users_excluding(
            *get_leave_stage_reviewer_users(leave_record),
            exclude=actor_users,
        ):
            queue_request_notification(
                notifications,
                recipient=user,
                employee=employee,
                title=f"Leave request awaiting review: {employee.full_name}",
                body=body,
                self_service_url=employee_url,
                management_url=reverse("employees:employee_requests_overview"),
                level=InAppNotification.LEVEL_WARNING,
            )

    dispatch_request_notifications(notifications)


def notify_document_request_submitted(document_request):
    employee = document_request.employee
    notifications = []
    for user in get_distinct_active_notification_users(*get_document_request_reviewer_users(document_request)):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Document request awaiting review: {employee.full_name}",
            body=(
                f"{employee.full_name} submitted a "
                f"{document_request.get_request_type_display().lower()} request: "
                f"{document_request.title}."
            ),
            self_service_url=reverse("employees:self_service_documents"),
            management_url=get_employee_management_detail_url(employee),
            level=InAppNotification.LEVEL_WARNING,
            exclude_users=[document_request.created_by],
        )
    dispatch_request_notifications(notifications)


def notify_document_request_status_change(document_request):
    employee = document_request.employee
    status_label = document_request.get_status_display()
    body = (
        f"{document_request.title} is now {status_label.lower()}."
        + (f" Note: {document_request.management_note}" if document_request.management_note else "")
    )
    notifications = []
    for user in get_distinct_active_notification_users_excluding(
        get_employee_notification_user(employee),
        document_request.created_by,
        document_request.reviewed_by,
        exclude=[document_request.reviewed_by],
    ):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Document request updated: {document_request.title}",
            body=body,
            self_service_url=reverse("employees:self_service_documents"),
            management_url=get_employee_management_detail_url(employee),
            level=InAppNotification.LEVEL_SUCCESS if document_request.status == EmployeeDocumentRequest.STATUS_COMPLETED else InAppNotification.LEVEL_INFO,
        )
    dispatch_request_notifications(notifications)


def notify_required_submission_created(submission_request):
    employee = submission_request.employee
    notifications = []
    employee_user = get_employee_notification_user(employee)
    if employee_user:
        queue_request_notification(
            notifications,
            recipient=employee_user,
            employee=employee,
            title=f"Required document requested: {submission_request.title}",
            body=(
                f"A {submission_request.get_request_type_display().lower()} request "
                f"has been opened for you."
                + (
                    f" Due date: {submission_request.due_date:%b %d, %Y}."
                    if submission_request.due_date
                    else ""
                )
            ),
            self_service_url=reverse("employees:self_service_documents"),
            management_url=get_employee_management_detail_url(employee),
            level=InAppNotification.LEVEL_WARNING,
            exclude_users=[submission_request.created_by],
        )
    dispatch_request_notifications(notifications)


def notify_required_submission_submitted(submission_request):
    employee = submission_request.employee
    notifications = []
    for user in get_distinct_active_notification_users(*get_required_submission_reviewer_users(submission_request)):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Required submission awaiting review: {employee.full_name}",
            body=(
                f"{employee.full_name} submitted the requested "
                f"{submission_request.get_request_type_display().lower()} file "
                f"for {submission_request.title}."
            ),
            self_service_url=reverse("employees:self_service_documents"),
            management_url=get_employee_management_detail_url(employee),
            level=InAppNotification.LEVEL_WARNING,
            exclude_users=[submission_request.created_by],
        )
    dispatch_request_notifications(notifications)


def notify_required_submission_reviewed(submission_request):
    employee = submission_request.employee
    notifications = []
    status_label = submission_request.get_status_display()
    body = (
        f"{submission_request.title} is now {status_label.lower()}."
        + (f" Review note: {submission_request.review_note}" if submission_request.review_note else "")
    )
    for user in get_distinct_active_notification_users_excluding(
        get_employee_notification_user(employee),
        submission_request.created_by,
        submission_request.reviewed_by,
        exclude=[submission_request.reviewed_by],
    ):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Required submission updated: {submission_request.title}",
            body=body,
            self_service_url=reverse("employees:self_service_documents"),
            management_url=get_employee_management_detail_url(employee),
            level=InAppNotification.LEVEL_SUCCESS if submission_request.status == EmployeeRequiredSubmission.STATUS_COMPLETED else InAppNotification.LEVEL_INFO,
        )
    dispatch_request_notifications(notifications)


def notify_attendance_correction_submitted(correction):
    employee = correction.employee
    notifications = []
    for user in get_distinct_active_notification_users(*get_attendance_correction_reviewer_users(correction)):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Attendance correction requested: {correction.linked_attendance.attendance_date:%b %d, %Y}",
            body=(
                f"{employee.full_name} submitted an attendance correction request "
                f"for {correction.linked_attendance.attendance_date:%b %d, %Y}."
            ),
            self_service_url=reverse("employees:self_service_attendance"),
            management_url=reverse("employees:attendance_management"),
            level=InAppNotification.LEVEL_WARNING,
            exclude_users=[correction.requested_by],
        )
    dispatch_request_notifications(notifications)


def notify_attendance_correction_reviewed(correction):
    employee = correction.employee
    notifications = []
    status_label = correction.get_status_display()
    body = (
        f"The attendance correction for {correction.linked_attendance.attendance_date:%b %d, %Y} "
        f"is now {status_label.lower()}."
        + (f" Review note: {correction.review_notes}" if correction.review_notes else "")
    )
    for user in get_distinct_active_notification_users_excluding(
        get_employee_notification_user(employee),
        correction.requested_by,
        correction.reviewed_by,
        exclude=[correction.reviewed_by],
    ):
        queue_request_notification(
            notifications,
            recipient=user,
            employee=employee,
            title=f"Attendance correction updated: {correction.linked_attendance.attendance_date:%b %d, %Y}",
            body=body,
            self_service_url=reverse("employees:self_service_attendance"),
            management_url=reverse("employees:attendance_management"),
            level=InAppNotification.LEVEL_SUCCESS if correction.status == EmployeeAttendanceCorrection.STATUS_APPLIED else InAppNotification.LEVEL_INFO,
        )
    dispatch_request_notifications(notifications)


def get_actor_label(user):
    if not user or not user.is_authenticated:
        return ""

    full_name = ""
    if hasattr(user, "get_full_name"):
        full_name = user.get_full_name().strip()

    return full_name or getattr(user, "username", "") or str(user)


def get_user_employee_profile(user):
    if not user or not user.is_authenticated:
        return None

    try:
        return user.employee_profile
    except Employee.DoesNotExist:
        return None
    except AttributeError:
        return None


def get_safe_next_url(request, fallback_url):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback_url


def get_self_service_home_label(employee, user):
    return get_workspace_home_label(user, employee)


def build_self_service_page_context(request, employee, *, current_section):
    from .views_directory import EmployeeDetailView

    detail_view = EmployeeDetailView()
    detail_view.request = request
    detail_view.object = employee
    context = detail_view.get_context_data(object=employee)
    context["self_service_home_label"] = get_self_service_home_label(employee, request.user)
    context["self_service_current_section"] = current_section
    context["self_service_profile_url"] = get_workspace_profile_url(request.user, employee)
    context["self_service_leave_url"] = reverse("employees:self_service_leave")
    context["self_service_documents_url"] = reverse("employees:self_service_documents")
    context["self_service_attendance_url"] = reverse("employees:self_service_attendance")
    context["self_service_working_time_url"] = reverse("employees:self_service_working_time")
    context["self_service_overtime_url"] = reverse("employees:overtime_request_list")
    context["self_service_branch_url"] = reverse("employees:self_service_branch")
    context["self_service_weekly_schedule_url"] = reverse("employees:self_service_weekly_schedule")
    context["self_service_my_schedule_url"] = reverse("employees:self_service_my_schedule")
    return context


def get_shift_time_defaults(shift_value):
    shift_map = EmployeeAttendanceLedger.get_shift_time_map()
    shift_config = shift_map.get(shift_value or EmployeeAttendanceLedger.SHIFT_MORNING)
    return shift_config or shift_map[EmployeeAttendanceLedger.SHIFT_MORNING]


def normalize_attendance_shift_label(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def resolve_attendance_shift_value(*, label="", start_time=None, end_time=None):
    shift_map = EmployeeAttendanceLedger.get_shift_time_map()
    normalized_label = normalize_attendance_shift_label(label)
    start_value = start_time.strftime("%H:%M") if start_time else ""
    end_value = end_time.strftime("%H:%M") if end_time else ""

    if normalized_label and start_value and end_value:
        for shift_value, shift_config in shift_map.items():
            if (
                normalize_attendance_shift_label(shift_config.get("label")) == normalized_label
                and shift_config.get("start") == start_value
                and shift_config.get("end") == end_value
            ):
                return shift_value

    if start_value and end_value:
        for shift_value, shift_config in shift_map.items():
            if shift_config.get("start") == start_value and shift_config.get("end") == end_value:
                return shift_value

    if normalized_label:
        for shift_value, shift_config in shift_map.items():
            if normalize_attendance_shift_label(shift_config.get("label")) == normalized_label:
                return shift_value

    return ""


def build_self_service_shift_choices(branch):
    if not branch:
        return list(EmployeeAttendanceLedger.SHIFT_CHOICES)

    duty_options = list(
        BranchWeeklyDutyOption.objects.filter(
            branch=branch,
            is_active=True,
            duty_type=BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT,
        ).order_by("display_order", "label", "id")
    )
    if not duty_options:
        return list(EmployeeAttendanceLedger.SHIFT_CHOICES)

    choices = []
    seen_pairs = set()
    fallback_seen_values = set()
    fallback_choices = []

    for duty_option in duty_options:
        shift_value = resolve_attendance_shift_value(
            label=duty_option.label,
            start_time=duty_option.default_start_time,
            end_time=duty_option.default_end_time,
        )
        if not shift_value:
            continue

        pair = (shift_value, duty_option.label)
        if pair not in seen_pairs:
            choices.append(pair)
            seen_pairs.add(pair)

        if shift_value not in fallback_seen_values:
            fallback_choices.append((shift_value, dict(EmployeeAttendanceLedger.SHIFT_CHOICES).get(shift_value, duty_option.label)))
            fallback_seen_values.add(shift_value)

    return choices or fallback_choices or list(EmployeeAttendanceLedger.SHIFT_CHOICES)


def build_attendance_location_label(cleaned_data):
    if not cleaned_data:
        return ""

    primary_label = (cleaned_data.get("location_label") or "").strip()
    location_address = (cleaned_data.get("location_address") or "").strip()

    if primary_label and location_address:
        return f"{primary_label} - {location_address}"
    if location_address:
        return location_address
    return primary_label


def calculate_haversine_distance_meters(latitude_a, longitude_a, latitude_b, longitude_b):
    earth_radius_meters = 6371000

    latitude_a = radians(float(latitude_a))
    longitude_a = radians(float(longitude_a))
    latitude_b = radians(float(latitude_b))
    longitude_b = radians(float(longitude_b))

    delta_latitude = latitude_b - latitude_a
    delta_longitude = longitude_b - longitude_a

    haversine_value = (
        sin(delta_latitude / 2) ** 2
        + cos(latitude_a) * cos(latitude_b) * sin(delta_longitude / 2) ** 2
    )
    central_angle = 2 * asin(sqrt(haversine_value))
    return int(round(earth_radius_meters * central_angle))


def get_branch_attendance_validation_result(employee, live_latitude, live_longitude):
    branch = getattr(employee, "branch", None) if employee else None
    if branch is None:
        return {
            "is_configured": False,
            "error_message": "This employee is not assigned to a branch attendance location.",
        }

    if not getattr(branch, "has_attendance_location_config", False):
        return {
            "is_configured": False,
            "error_message": (
                f"{branch.name} does not have a fixed attendance point configured yet. "
                "Please contact HR or Operations."
            ),
        }

    distance_meters = calculate_haversine_distance_meters(
        live_latitude,
        live_longitude,
        branch.attendance_latitude,
        branch.attendance_longitude,
    )
    allowed_radius_meters = int(branch.attendance_radius_meters or 0)
    is_inside_radius = distance_meters <= allowed_radius_meters

    return {
        "is_configured": True,
        "branch": branch,
        "branch_latitude": branch.attendance_latitude,
        "branch_longitude": branch.attendance_longitude,
        "allowed_radius_meters": allowed_radius_meters,
        "distance_meters": distance_meters,
        "is_inside_radius": is_inside_radius,
        "validation_status": (
            EmployeeAttendanceEvent.LOCATION_STATUS_INSIDE
            if is_inside_radius
            else EmployeeAttendanceEvent.LOCATION_STATUS_OUTSIDE
        ),
        "branch_location_label": f"{branch.name} attendance point",
        "validation_summary": (
            f"Validated against {branch.name} fixed attendance point. "
            f"Distance {distance_meters} m of allowed {allowed_radius_meters} m."
        ),
    }


def sync_attendance_event_to_ledger(event, actor_label="System"):
    if not event or not event.employee_id or not event.check_in_at or not event.check_out_at:
        return None

    clock_in_time = timezone.localtime(event.check_in_at).time().replace(second=0, microsecond=0)
    clock_out_time = timezone.localtime(event.check_out_at).time().replace(second=0, microsecond=0)

    ledger, _created = EmployeeAttendanceLedger.objects.get_or_create(
        employee=event.employee,
        attendance_date=event.attendance_date,
        defaults={
            "day_status": EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            "shift": event.shift or EmployeeAttendanceLedger.SHIFT_MORNING,
            "clock_in_time": clock_in_time,
            "clock_out_time": clock_out_time,
            "scheduled_hours": WORKING_HOURS_PER_DAY,
            "source": EmployeeAttendanceLedger.SOURCE_SYSTEM,
            "notes": "",
            "created_by": actor_label,
            "updated_by": actor_label,
        },
    )

    ledger.day_status = EmployeeAttendanceLedger.DAY_STATUS_PRESENT
    ledger.shift = event.shift or EmployeeAttendanceLedger.SHIFT_MORNING
    ledger.clock_in_time = clock_in_time
    ledger.clock_out_time = clock_out_time
    ledger.scheduled_hours = WORKING_HOURS_PER_DAY
    ledger.source = EmployeeAttendanceLedger.SOURCE_SYSTEM
    ledger.check_in_latitude = event.check_in_latitude
    ledger.check_in_longitude = event.check_in_longitude
    ledger.check_out_latitude = event.check_out_latitude
    ledger.check_out_longitude = event.check_out_longitude
    ledger.check_in_location_label = event.check_in_location_label or ""
    ledger.check_out_location_label = event.check_out_location_label or ""
    ledger.check_in_address = event.check_in_address or ""
    ledger.check_out_address = event.check_out_address or ""
    location_bits = []
    if event.check_in_location_label:
        location_bits.append(f"Check-in: {event.check_in_location_label}")
    if event.check_out_location_label:
        location_bits.append(f"Check-out: {event.check_out_location_label}")
    if event.check_in_address and event.check_in_address != event.check_in_location_label:
        location_bits.append(f"Check-in address: {event.check_in_address}")
    if event.check_out_address and event.check_out_address != event.check_out_location_label:
        location_bits.append(f"Check-out address: {event.check_out_address}")
    if event.check_in_latitude is not None and event.check_in_longitude is not None:
        location_bits.append(
            f"Check-in coordinates: {event.check_in_latitude}, {event.check_in_longitude}"
        )
    if event.check_in_distance_meters is not None:
        location_bits.append(
            f"Check-in validation: {event.get_check_in_location_validation_status_display() or event.check_in_location_validation_status} at {event.check_in_distance_meters} m"
        )
    if event.check_out_latitude is not None and event.check_out_longitude is not None:
        location_bits.append(
            f"Check-out coordinates: {event.check_out_latitude}, {event.check_out_longitude}"
        )
    if event.check_out_distance_meters is not None:
        location_bits.append(
            f"Check-out validation: {event.get_check_out_location_validation_status_display() or event.check_out_location_validation_status} at {event.check_out_distance_meters} m"
        )
    if event.branch_latitude_used is not None and event.branch_longitude_used is not None:
        location_bits.append(
            f"Branch point used: {event.branch_latitude_used}, {event.branch_longitude_used}"
        )
    if event.attendance_radius_meters_used is not None:
        location_bits.append(f"Allowed radius: {event.attendance_radius_meters_used} m")
    event_note = "Self-service attendance"
    if location_bits:
        event_note = f"{event_note}. {' | '.join(location_bits)}"
    ledger.notes = event_note
    ledger.updated_by = actor_label
    if not ledger.created_by:
        ledger.created_by = actor_label
    ledger.save()

    event.synced_ledger = ledger
    event.status = EmployeeAttendanceEvent.STATUS_COMPLETED
    event.save(update_fields=["synced_ledger", "status", "updated_at"])
    return ledger


is_admin_compatible = is_admin_compatible_role


def is_self_employee(user, employee):
    linked_employee = get_user_employee_profile(user)
    return bool(linked_employee and employee and linked_employee.pk == employee.pk)


def get_user_scope_branch(user):
    linked_employee = get_user_employee_profile(user)
    return get_user_scope_branch_for_role(user, linked_employee)


def is_branch_scoped_supervisor(user):
    linked_employee = get_user_employee_profile(user)
    return is_branch_scoped_supervisor_for_role(user, linked_employee)


is_hr_user = is_hr
is_supervisor_user = is_supervisor
is_operations_manager_user = is_operations
is_employee_role_user = is_employee_role
is_management_user = is_any_management


def can_supervisor_view_employee(user, employee):
    scoped_branch = get_user_scope_branch(user)
    if not scoped_branch or not employee:
        return False
    return bool(employee.branch_id and employee.branch_id == scoped_branch.id)


def get_employee_directory_queryset_for_user(user, queryset=None):
    base_queryset = queryset or Employee.objects.all()

    if is_branch_scoped_supervisor(user):
        scoped_branch = get_user_scope_branch(user)
        return base_queryset.filter(branch_id=scoped_branch.id)

    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return base_queryset

    linked_employee = get_user_employee_profile(user)
    if linked_employee:
        return base_queryset.filter(pk=linked_employee.pk)

    return base_queryset.none()


def get_leave_queryset_for_user(user, queryset=None):
    base_queryset = queryset or EmployeeLeave.objects.all()

    if is_branch_scoped_supervisor(user):
        scoped_branch = get_user_scope_branch(user)
        return base_queryset.filter(employee__branch_id=scoped_branch.id)

    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return base_queryset

    linked_employee = get_user_employee_profile(user)
    if linked_employee:
        return base_queryset.filter(employee=linked_employee)

    return base_queryset.none()


def can_view_employee_requests_overview(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or is_branch_scoped_supervisor(user)
        )
    )


def can_view_management_employee_sections(user, employee=None):
    if not user or not user.is_authenticated:
        return False

    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return True

    return can_supervisor_view_employee(user, employee)


def can_view_employee_directory(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or is_branch_scoped_supervisor(user)
        )
    )


def can_view_employee_profile(user, employee):
    return bool(
        is_self_employee(user, employee)
        or is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or can_supervisor_view_employee(user, employee)
    )


def can_create_or_edit_employees(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_delete_employee(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_transfer_employee(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_change_employee_status(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_manage_employee_documents(user, employee=None):
    return bool(
        is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or can_supervisor_view_employee(user, employee)
    )


def can_manage_employee_required_submissions(user, employee=None):
    return bool(
        is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or can_supervisor_view_employee(user, employee)
    )


def can_submit_employee_required_submission(user, submission_request):
    return bool(
        submission_request
        and is_self_employee(user, submission_request.employee)
        and submission_request.status in {
            EmployeeRequiredSubmission.STATUS_REQUESTED,
            EmployeeRequiredSubmission.STATUS_NEEDS_CORRECTION,
        }
    )


def can_review_employee_required_submission(user, submission_request):
    return bool(
        submission_request
        and can_manage_employee_required_submissions(user, submission_request.employee)
    )


def can_create_employee_document_request(user, employee):
    return bool(employee and is_self_employee(user, employee))


def can_review_employee_document_request(user, document_request):
    return bool(
        document_request
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or can_supervisor_view_employee(user, document_request.employee)
        )
    )


def can_cancel_employee_document_request(user, document_request):
    return bool(
        document_request
        and is_self_employee(user, document_request.employee)
        and document_request.can_employee_cancel
    )


def build_employee_document_request_summary(document_request):
    parts = [
        f"Document request created as {document_request.get_request_type_display()}.",
        f"Status: {document_request.get_status_display()}.",
    ]

    if document_request.needed_by_date:
        parts.append(f"Needed by: {document_request.needed_by_date.strftime('%B %d, %Y')}.")
    if document_request.request_note:
        parts.append(f"Employee note: {document_request.request_note}")

    return " ".join(parts)


def build_employee_document_request_review_summary(document_request, previous_status, new_status, management_note=""):
    parts = [
        f"Employee document request status changed from {previous_status} to {new_status}.",
        f"Request type: {document_request.get_request_type_display()}.",
    ]

    if management_note:
        parts.append(f"Management note: {management_note}")

    return " ".join(parts)


def can_request_leave(user, employee):
    return bool(
        is_self_employee(user, employee)
        or is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or can_supervisor_view_employee(user, employee)
    )


def can_review_leave(user):
    return (
        is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or is_branch_scoped_supervisor(user)
    )


def get_leave_current_stage_owner_label(leave_record):
    if not leave_record:
        return ""

    if leave_record.status == EmployeeLeave.STATUS_PENDING:
        if leave_record.current_stage == EmployeeLeave.STAGE_SUPERVISOR_REVIEW:
            return "Supervisor review"
        if leave_record.current_stage == EmployeeLeave.STAGE_OPERATIONS_REVIEW:
            return "Operations review"
        if leave_record.current_stage == EmployeeLeave.STAGE_HR_REVIEW:
            return "HR final review"
        return "Pending workflow review"

    if leave_record.status == EmployeeLeave.STATUS_APPROVED:
        return "Workflow completed"
    if leave_record.status == EmployeeLeave.STATUS_REJECTED:
        return "Workflow closed as rejected"
    if leave_record.status == EmployeeLeave.STATUS_CANCELLED:
        return "Workflow cancelled"

    return leave_record.get_status_display()


def can_user_review_leave_stage(user, leave_record):
    if not user or not leave_record or leave_record.status != EmployeeLeave.STATUS_PENDING:
        return False

    if is_branch_scoped_supervisor(user):
        return leave_record.current_stage == EmployeeLeave.STAGE_SUPERVISOR_REVIEW

    if is_operations_manager_user(user):
        return leave_record.current_stage == EmployeeLeave.STAGE_OPERATIONS_REVIEW

    if is_hr_user(user) or is_admin_compatible(user):
        return leave_record.current_stage == EmployeeLeave.STAGE_HR_REVIEW

    return False


def can_cancel_leave(user, leave_record):
    if can_review_leave(user):
        if is_branch_scoped_supervisor(user):
            return can_supervisor_view_employee(user, leave_record.employee)
        return True

    if is_self_employee(user, leave_record.employee):
        return leave_record.status == EmployeeLeave.STATUS_PENDING

    return False


def can_create_action_records(user):
    return (
        is_admin_compatible(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or is_branch_scoped_supervisor(user)
    )


def can_manage_attendance_records(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_view_attendance_management(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_view_branch_schedule_overview(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_view_branch_self_service(employee):
    return bool(employee and employee.branch_id)


def can_manage_branch_weekly_schedule(user, branch):
    if not user or not user.is_authenticated or not branch:
        return False

    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return True

    linked_employee = get_user_employee_profile(user)
    return bool(
        is_branch_scoped_supervisor(user)
        and linked_employee
        and linked_employee.branch_id == branch.id
    )


def can_add_manual_history(user):
    return is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user)


def can_access_employee_form_dependencies(user):
    return can_create_or_edit_employees(user) or can_transfer_employee(user)


def get_employee_access_redirect(user, employee=None):
    if employee and can_view_employee_profile(user, employee):
        return redirect("employees:employee_detail", pk=employee.pk)

    linked_employee = get_user_employee_profile(user)
    if linked_employee and can_view_employee_profile(user, linked_employee):
        return redirect("employees:employee_detail", pk=linked_employee.pk)

    if can_view_employee_directory(user):
        return redirect("employees:employee_list")

    raise PermissionDenied("You do not have permission to access this area.")


def deny_employee_access(request, message, employee=None):
    messages.error(request, message)
    return get_employee_access_redirect(request.user, employee=employee)


def deny_json_access(message="You do not have permission to access this endpoint."):
    return JsonResponse({"results": [], "error": message}, status=403)


def format_history_value(value):
    if value in [None, ""]:
        return "empty"

    if hasattr(value, "strftime"):
        return value.strftime("%B %d, %Y")

    if isinstance(value, bool):
        return "Active" if value else "Inactive"

    return str(value)


def build_employee_change_summary(old_employee, new_employee):
    changes = []

    tracked_fields = [
        ("full_name", "Full name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("birth_date", "Birth date"),
        ("marital_status", "Marital status"),
        ("nationality", "Nationality"),
        ("company", "Company"),
        ("department", "Department"),
        ("branch", "Branch"),
        ("section", "Section"),
        ("job_title", "Job title"),
        ("hire_date", "Hire date"),
        ("salary", "Salary"),
        ("is_active", "Operational status"),
        ("notes", "Notes"),
    ]

    for field_name, label in tracked_fields:
        old_value = getattr(old_employee, field_name)
        new_value = getattr(new_employee, field_name)
        if old_value != new_value:
            changes.append(
                f"{label} changed from {format_history_value(old_value)} to {format_history_value(new_value)}."
            )

    return " ".join(changes) if changes else "Employee profile details were updated."


def build_employee_transfer_summary(old_employee, new_employee, transfer_note=""):
    changes = []

    tracked_fields = [
        ("company", "Company"),
        ("department", "Department"),
        ("branch", "Branch"),
        ("section", "Section"),
        ("job_title", "Job title"),
    ]

    for field_name, label in tracked_fields:
        old_value = getattr(old_employee, field_name)
        new_value = getattr(new_employee, field_name)
        if old_value != new_value:
            changes.append(
                f"{label} changed from {format_history_value(old_value)} to {format_history_value(new_value)}."
            )

    if transfer_note:
        changes.append(f"Transfer note: {transfer_note}")

    return " ".join(changes)




PREVIEWABLE_FILE_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "webp", "gif", "bmp", "txt"}


def get_file_extension(file_field):
    if not file_field or not getattr(file_field, "name", ""):
        return ""
    return Path(file_field.name).suffix.lower().lstrip(".")


def build_browser_file_response(file_field, *, force_download=False):
    if not file_field or not getattr(file_field, "name", ""):
        raise Http404("The requested file is not available.")

    storage = getattr(file_field, "storage", None)
    if storage and not storage.exists(file_field.name):
        raise Http404("The requested file is not available on this system.")

    filename = Path(file_field.name).name
    extension = get_file_extension(file_field)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    as_attachment = force_download or extension not in PREVIEWABLE_FILE_EXTENSIONS

    file_handle = file_field.open("rb")
    response = FileResponse(
        file_handle,
        as_attachment=as_attachment,
        filename=filename,
        content_type=content_type,
    )

    if not as_attachment:
        response["Content-Disposition"] = f'inline; filename="{filename}"'

    return response

def build_document_summary(document):
    parts = [
        f"Document type: {document.get_document_type_display()}",
        f"Reference number: {document.reference_number or 'empty'}",
    ]

    if document.issue_date:
        parts.append(f"Issue date: {document.issue_date.strftime('%B %d, %Y')}")
    if document.expiry_date:
        parts.append(f"Expiry date: {document.expiry_date.strftime('%B %d, %Y')}")
    if document.description:
        parts.append(f"Description: {document.description}")

    return ". ".join(parts)


def build_leave_request_summary(leave_record):
    parts = [
        f"Leave request created as {leave_record.get_leave_type_display()}.",
        f"Date range: {leave_record.start_date.strftime('%B %d, %Y')} to {leave_record.end_date.strftime('%B %d, %Y')}.",
        f"Total days: {leave_record.total_days}.",
        f"Status: {leave_record.get_status_display()}.",
    ]

    if leave_record.reason:
        parts.append(f"Reason: {leave_record.reason}")

    return " ".join(parts)


def build_leave_status_summary(leave_record, previous_status, new_status, approval_note=""):
    parts = [
        f"{leave_record.get_leave_type_display()} status changed from {previous_status} to {new_status}.",
        f"Date range: {leave_record.start_date.strftime('%B %d, %Y')} to {leave_record.end_date.strftime('%B %d, %Y')}.",
        f"Total days: {leave_record.total_days}.",
    ]

    if approval_note:
        parts.append(f"Action note: {approval_note}")

    return " ".join(parts)


def build_action_record_summary(action_record):
    lines = [
        f"Action Type: {action_record.get_action_type_display()}",
        f"Action Date: {format_history_value(action_record.action_date)}",
        f"Status: {action_record.get_status_display()}",
        f"Severity: {action_record.get_severity_display()}",
    ]

    if action_record.description:
        lines.append(f"Note: {action_record.description}")

    return "\n".join(lines)


def build_attendance_ledger_summary(attendance_entry):
    lines = [
        f"Attendance Date: {format_history_value(attendance_entry.attendance_date)}",
        f"Day Status: {attendance_entry.get_day_status_display()}",
        f"Scheduled Hours: {attendance_entry.scheduled_hours_display}",
        f"Worked Hours: {attendance_entry.worked_hours_display}",
        f"Late Time: {attendance_entry.late_minutes_display}",
        f"Early Departure: {attendance_entry.early_departure_minutes_display}",
        f"Overtime: {attendance_entry.overtime_minutes_display}",
        f"Paid Day: {'Yes' if attendance_entry.is_paid_day else 'No'}",
        f"Source: {attendance_entry.get_source_display()}",
    ]

    if attendance_entry.notes:
        lines.append(f"Notes: {attendance_entry.notes}")

    return "\n".join(lines)


def build_attendance_correction_summary(correction):
    lines = [
        f"Attendance Date: {format_history_value(correction.linked_attendance.attendance_date)}",
        f"Requested Status: {correction.get_requested_day_status_display()}",
        f"Requested Scheduled Hours: {correction.requested_scheduled_hours}",
        f"Requested Late Minutes: {correction.requested_late_minutes}",
        f"Requested Early Departure Minutes: {correction.requested_early_departure_minutes}",
        f"Requested Overtime Minutes: {correction.requested_overtime_minutes}",
        f"Review Status: {correction.get_status_display()}",
    ]

    if correction.request_reason:
        lines.append(f"Request Reason: {correction.request_reason}")
    if correction.review_notes:
        lines.append(f"Review Notes: {correction.review_notes}")

    return "\n".join(lines)


def get_month_date_range(target_date):
    start_date = target_date.replace(day=1)
    if target_date.month == 12:
        next_month = target_date.replace(year=target_date.year + 1, month=1, day=1)
    else:
        next_month = target_date.replace(month=target_date.month + 1, day=1)
    end_date = next_month - timedelta(days=1)
    return start_date, end_date


def build_attendance_summary(attendance_entries):
    total_scheduled_hours = Decimal("0.00")
    total_worked_hours = Decimal("0.00")
    total_overtime_minutes = 0
    total_late_minutes = 0
    total_early_departure_minutes = 0

    present_count = 0
    absence_count = 0
    leave_count = 0
    weekly_off_count = 0
    holiday_count = 0
    paid_day_count = 0
    unpaid_day_count = 0

    for entry in attendance_entries:
        total_scheduled_hours += entry.scheduled_hours or Decimal("0.00")
        total_worked_hours += entry.worked_hours or Decimal("0.00")
        total_overtime_minutes += entry.overtime_minutes or 0
        total_late_minutes += entry.late_minutes or 0
        total_early_departure_minutes += entry.early_departure_minutes or 0

        if entry.is_paid_day:
            paid_day_count += 1
        else:
            unpaid_day_count += 1

        if entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_PRESENT:
            present_count += 1
        elif entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_ABSENT:
            absence_count += 1
        elif entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF:
            weekly_off_count += 1
        elif entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY:
            holiday_count += 1
        elif entry.day_status in {
            EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
        }:
            leave_count += 1

    punctuality_deduction_hours = (
        Decimal(total_late_minutes + total_early_departure_minutes) / Decimal("60")
    ).quantize(Decimal("0.01"))
    overtime_hours = (Decimal(total_overtime_minutes) / Decimal("60")).quantize(Decimal("0.01"))

    return {
        "attendance_total": len(attendance_entries),
        "present_attendance_count": present_count,
        "absence_attendance_count": absence_count,
        "leave_attendance_count": leave_count,
        "weekly_off_attendance_count": weekly_off_count,
        "holiday_attendance_count": holiday_count,
        "paid_day_count": paid_day_count,
        "unpaid_day_count": unpaid_day_count,
        "total_scheduled_hours": total_scheduled_hours.quantize(Decimal("0.01")),
        "total_worked_hours": total_worked_hours.quantize(Decimal("0.01")),
        "total_overtime_minutes": total_overtime_minutes,
        "total_overtime_hours": overtime_hours,
        "total_late_minutes": total_late_minutes,
        "total_early_departure_minutes": total_early_departure_minutes,
        "punctuality_deduction_hours": punctuality_deduction_hours,
        "total_scheduled_hours_display": format_decimal_hours_as_hours_minutes(total_scheduled_hours),
        "total_worked_hours_display": format_decimal_hours_as_hours_minutes(total_worked_hours),
        "total_overtime_minutes_display": format_minutes_as_hours_minutes(total_overtime_minutes),
        "total_late_minutes_display": format_minutes_as_hours_minutes(total_late_minutes),
        "total_early_departure_minutes_display": format_minutes_as_hours_minutes(total_early_departure_minutes),
        "punctuality_deduction_hours_display": format_decimal_hours_as_hours_minutes(
            punctuality_deduction_hours
        ),
    }


def apply_attendance_management_form_scope(form, user):
    if not form:
        return form

    scoped_branch = get_user_scope_branch(user)
    employee_queryset = get_employee_directory_queryset_for_user(
        user,
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        ),
    ).order_by("full_name", "employee_id")

    form.fields["employee"].queryset = employee_queryset

    if is_branch_scoped_supervisor(user) and scoped_branch:
        form.fields["company"].queryset = Company.objects.filter(
            id=scoped_branch.company_id,
            is_active=True,
        ).order_by("name")
        form.fields["branch"].queryset = Branch.objects.filter(
            id=scoped_branch.id,
            is_active=True,
        ).order_by("name")
        form.fields["department"].queryset = Department.objects.filter(
            company_id=scoped_branch.company_id,
            is_active=True,
        ).order_by("name")
        form.fields["section"].queryset = Section.objects.filter(
            department__company_id=scoped_branch.company_id,
            is_active=True,
        ).order_by("name")
        return form

    form.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
    form.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
    form.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
    form.fields["section"].queryset = Section.objects.filter(is_active=True).order_by("name")
    return form


def build_attendance_history_pagination(page_obj):
    if not page_obj:
        return []

    paginator = page_obj.paginator
    current_page = page_obj.number
    total_pages = paginator.num_pages
    page_numbers = {1, total_pages}

    for page_number in range(current_page - 1, current_page + 2):
        if 1 <= page_number <= total_pages:
            page_numbers.add(page_number)

    sorted_pages = sorted(page_numbers)
    pagination_items = []
    previous_page = None

    for page_number in sorted_pages:
        if previous_page is not None and page_number - previous_page > 1:
            pagination_items.append({"type": "ellipsis"})
        pagination_items.append(
            {
                "type": "page",
                "number": page_number,
                "is_current": page_number == current_page,
            }
        )
        previous_page = page_number

    return pagination_items


def build_attendance_management_filter_state(request, user=None):
    initial = AttendanceManagementFilterForm.default_initial()
    has_query = bool(request.GET)
    form = AttendanceManagementFilterForm(request.GET or None, initial=initial)
    if user is not None:
        apply_attendance_management_form_scope(form, user)

    today = timezone.localdate()
    start_date = initial["start_date"]
    end_date = initial["end_date"]
    filter_type = initial["filter_type"]
    search_value = ""
    employee = None
    company = None
    branch = None
    department = None
    section = None
    day_status = ""

    if form.is_bound and form.is_valid():
        filter_type = form.cleaned_data.get("filter_type") or AttendanceFilterForm.FILTER_THIS_MONTH
        start_date = form.cleaned_data.get("start_date")
        end_date = form.cleaned_data.get("end_date")
        search_value = form.cleaned_data.get("search") or ""
        employee = form.cleaned_data.get("employee")
        company = form.cleaned_data.get("company")
        branch = form.cleaned_data.get("branch")
        department = form.cleaned_data.get("department")
        section = form.cleaned_data.get("section")
        day_status = form.cleaned_data.get("day_status") or ""

        if filter_type == AttendanceFilterForm.FILTER_THIS_MONTH:
            start_date, end_date = get_month_date_range(today)
        elif filter_type == AttendanceFilterForm.FILTER_LAST_MONTH:
            last_month_anchor = today.replace(day=1) - timedelta(days=1)
            start_date, end_date = get_month_date_range(last_month_anchor)
        elif filter_type == AttendanceFilterForm.FILTER_ALL:
            start_date = None
            end_date = None
    elif has_query:
        start_date = None
        end_date = None
        filter_type = AttendanceFilterForm.FILTER_ALL
    else:
        form = AttendanceManagementFilterForm(initial=initial)
        if user is not None:
            apply_attendance_management_form_scope(form, user)

    if filter_type == AttendanceFilterForm.FILTER_CUSTOM and start_date and end_date:
        period_label = f"{start_date:%b %d, %Y} to {end_date:%b %d, %Y}"
    elif filter_type == AttendanceFilterForm.FILTER_LAST_MONTH and start_date and end_date:
        period_label = f"Last Month ({start_date:%b %d, %Y} to {end_date:%b %d, %Y})"
    elif filter_type == AttendanceFilterForm.FILTER_ALL:
        period_label = "All attendance records"
    else:
        period_label = f"This Month ({start_date:%b %d, %Y} to {end_date:%b %d, %Y})"

    return {
        "form": form,
        "search_value": search_value,
        "employee": employee,
        "company": company,
        "branch": branch,
        "department": department,
        "section": section,
        "day_status": day_status,
        "filter_type": filter_type,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": period_label,
        "is_applied": has_query,
    }


def build_attendance_filter_state(request):
    initial = AttendanceFilterForm.default_initial()
    form = AttendanceFilterForm(request.GET or initial)

    if request.GET and form.is_valid():
        cleaned = form.cleaned_data
        filter_type = cleaned.get("filter_type") or AttendanceFilterForm.FILTER_THIS_MONTH
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
    else:
        filter_type = initial["filter_type"]
        start_date = initial["start_date"]
        end_date = initial["end_date"]

    today = timezone.localdate()

    if filter_type == AttendanceFilterForm.FILTER_THIS_MONTH:
        start_date, end_date = get_month_date_range(today)
        period_label = f"{start_date.strftime('%B %Y')}"
    elif filter_type == AttendanceFilterForm.FILTER_LAST_MONTH:
        previous_month_anchor = today.replace(day=1) - timedelta(days=1)
        start_date, end_date = get_month_date_range(previous_month_anchor)
        period_label = f"{start_date.strftime('%B %Y')}"
    elif filter_type == AttendanceFilterForm.FILTER_CUSTOM and start_date and end_date:
        period_label = f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
    else:
        start_date = None
        end_date = None
        period_label = "All attendance records"

    return {
        "form": form,
        "filter_type": filter_type,
        "start_date": start_date,
        "end_date": end_date,
        "period_label": period_label,
        "is_applied": bool(start_date or end_date or filter_type != AttendanceFilterForm.FILTER_THIS_MONTH),
    }


