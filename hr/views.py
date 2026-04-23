from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from config.access import is_hr, is_operations, is_superuser, is_supervisor, role_required
from employees.access import is_admin_compatible as is_admin_compatible_role
from employees.models import (
    Employee,
    EmployeeActionRecord,
    EmployeeAttendanceCorrection,
    EmployeeAttendanceLedger,
    EmployeeDocumentRequest,
    EmployeeLeave,
    EmployeeRequiredSubmission,
)
from payroll.models import PayrollObligation, PayrollPeriod

from .models import HRAnnouncement, HRPolicy


def can_access_hr_workspace(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_hr", False)
            or getattr(user, "is_operations_manager", False)
            or getattr(user, "is_supervisor", False)
        )
    )


@role_required(
    is_admin_compatible_role,
    is_hr,
    is_operations,
    is_supervisor,
    is_superuser,
    message="You do not have permission to access the HR workspace.",
)
def hr_home(request):
    today = timezone.localdate()
    compliance_attention_date = today + timedelta(days=30)
    employees = Employee.objects.select_related("company", "department", "branch", "job_title")
    policies = HRPolicy.objects.select_related("company").filter(is_active=True).order_by("title")[:6]
    announcements = HRAnnouncement.objects.filter(is_active=True).order_by("-published_at", "-id")[:5]
    pending_leaves = EmployeeLeave.objects.select_related("employee").filter(status=EmployeeLeave.STATUS_PENDING).order_by("-created_at")[:6]
    open_submission_requests = EmployeeRequiredSubmission.objects.select_related("employee").exclude(
        status=EmployeeRequiredSubmission.STATUS_COMPLETED
    ).order_by("-updated_at", "-created_at")[:6]
    recent_actions = EmployeeActionRecord.objects.select_related("employee").order_by("-action_date", "-created_at")[:6]
    open_document_requests = EmployeeDocumentRequest.objects.select_related("employee").filter(
        status=EmployeeDocumentRequest.STATUS_REQUESTED
    ).order_by("-created_at")[:6]
    attendance_exceptions = EmployeeAttendanceLedger.objects.select_related("employee").filter(
        attendance_date=today,
        day_status__in=[
            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            EmployeeAttendanceLedger.DAY_STATUS_OTHER,
        ],
    ).order_by("employee__full_name")[:6]
    pending_attendance_corrections = EmployeeAttendanceCorrection.objects.select_related(
        "employee",
        "linked_attendance",
    ).filter(status=EmployeeAttendanceCorrection.STATUS_PENDING).order_by("-created_at")[:6]
    compliance_alerts = employees.filter(
        is_active=True,
    ).filter(
        passport_expiry_date__isnull=False,
        passport_expiry_date__lte=compliance_attention_date,
    ).order_by("passport_expiry_date", "full_name")[:4]
    civil_id_alerts = employees.filter(
        is_active=True,
        civil_id_expiry_date__isnull=False,
        civil_id_expiry_date__lte=compliance_attention_date,
    ).order_by("civil_id_expiry_date", "full_name")[:4]
    recent_payroll_periods = PayrollPeriod.objects.select_related("company").order_by("-period_start", "-id")[:4]
    active_obligations = PayrollObligation.objects.select_related("employee", "company").filter(
        status=PayrollObligation.STATUS_ACTIVE
    ).order_by("-updated_at", "-id")[:6]
    branch_distribution = {}
    company_distribution = {}
    employment_mix = {
        Employee.EMPLOYMENT_STATUS_ACTIVE: 0,
        Employee.EMPLOYMENT_STATUS_ON_LEAVE: 0,
        Employee.EMPLOYMENT_STATUS_EMERGENCY_LEAVE: 0,
        Employee.EMPLOYMENT_STATUS_UNPAID_LEAVE: 0,
        Employee.EMPLOYMENT_STATUS_INACTIVE: 0,
    }
    for employee in employees:
        branch_name = employee.branch.name if employee.branch_id else "Unassigned"
        branch_distribution[branch_name] = branch_distribution.get(branch_name, 0) + 1
        company_name = employee.company.name if employee.company_id else "Unassigned"
        company_distribution[company_name] = company_distribution.get(company_name, 0) + 1
        if employee.employment_status in employment_mix:
            employment_mix[employee.employment_status] += 1

    context = {
        "workspace_title": "HR Workspace",
        "today": today,
        "employee_total": employees.count(),
        "active_employee_total": employees.filter(is_active=True).count(),
        "inactive_employee_total": employees.filter(is_active=False).count(),
        "pending_leave_total": EmployeeLeave.objects.filter(status=EmployeeLeave.STATUS_PENDING).count(),
        "open_document_request_total": EmployeeDocumentRequest.objects.filter(
            status=EmployeeDocumentRequest.STATUS_REQUESTED
        ).count(),
        "open_submission_total": EmployeeRequiredSubmission.objects.exclude(
            status=EmployeeRequiredSubmission.STATUS_COMPLETED
        ).count(),
        "pending_attendance_correction_total": EmployeeAttendanceCorrection.objects.filter(
            status=EmployeeAttendanceCorrection.STATUS_PENDING
        ).count(),
        "attendance_exception_total": EmployeeAttendanceLedger.objects.filter(
            attendance_date=today,
            day_status__in=[
                EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
                EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
                EmployeeAttendanceLedger.DAY_STATUS_OTHER,
            ],
        ).count(),
        "compliance_alert_total": employees.filter(
            is_active=True,
            passport_expiry_date__isnull=False,
            passport_expiry_date__lte=compliance_attention_date,
        ).count()
        + employees.filter(
            is_active=True,
            civil_id_expiry_date__isnull=False,
            civil_id_expiry_date__lte=compliance_attention_date,
        ).count(),
        "active_payroll_period_total": PayrollPeriod.objects.exclude(status=PayrollPeriod.STATUS_PAID).count(),
        "active_obligation_total": PayrollObligation.objects.filter(status=PayrollObligation.STATUS_ACTIVE).count(),
        "policy_total": HRPolicy.objects.filter(is_active=True).count(),
        "policies": policies,
        "announcements": announcements,
        "pending_leaves": pending_leaves,
        "open_submission_requests": open_submission_requests,
        "recent_actions": recent_actions,
        "open_document_requests": open_document_requests,
        "attendance_exceptions": attendance_exceptions,
        "pending_attendance_corrections": pending_attendance_corrections,
        "passport_alerts": compliance_alerts,
        "civil_id_alerts": civil_id_alerts,
        "recent_payroll_periods": recent_payroll_periods,
        "active_obligations": active_obligations,
        "branch_distribution": sorted(branch_distribution.items(), key=lambda item: (-item[1], item[0]))[:6],
        "company_distribution": sorted(company_distribution.items(), key=lambda item: (-item[1], item[0]))[:6],
        "employment_mix": employment_mix,
    }
    return render(request, "hr/home.html", context)
