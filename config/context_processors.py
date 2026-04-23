from django.urls import reverse
from django.db.utils import OperationalError, ProgrammingError

from employees.access import (
    get_user_scope_branch as get_user_scope_branch_for_nav,
    get_workspace_profile_url,
    is_admin_compatible as is_admin_compatible_role,
    is_employee_role_user as is_employee_role_user_role,
    is_finance_manager_user as is_finance_manager_user_role,
    is_hr_user as is_hr_user_role,
    is_operations_manager_user as is_operations_manager_user_role,
    is_supervisor_user as is_supervisor_user_role,
)
from employees.models import Employee
from notifications.models import InAppNotification
from .session_timeout import (
    format_session_remaining_seconds,
    get_session_remaining_seconds,
    get_session_timeout_seconds,
    get_session_warning_seconds,
)


def navbar_context(request):
    user = request.user

    if not user.is_authenticated:
        return {
            "nav_is_authenticated": False,
            "nav_can_access_dashboard": False,
            "nav_can_view_organization": False,
            "nav_can_manage_organization": False,
            "nav_can_view_employee_directory": False,
            "nav_can_add_employee": False,
            "nav_can_access_admin": False,
            "nav_can_view_requests": False,
            "nav_can_view_attendance_management": False,
            "nav_can_view_branch_schedule_overview": False,
            "nav_employee_profile": None,
            "nav_is_branch_scoped_supervisor": False,
            "nav_scoped_branch": None,
            "nav_show_supervisor_workspace": False,
            "nav_show_operations_workspace": False,
            "nav_primary_home_url": None,
            "nav_primary_home_label": "System Home",
            "nav_is_employee_self_service_only": False,
            "nav_supervisor_branch_url": "",
            "nav_supervisor_attendance_history_url": "",
            "nav_can_view_branch_documents": False,
            "nav_self_service_leave_url": "",
            "nav_self_service_documents_url": "",
            "nav_self_service_profile_url": "",
            "nav_self_service_attendance_url": "",
            "nav_self_service_expenses_url": "",
            "nav_self_service_working_time_url": "",
            "nav_self_service_branch_url": "",
            "nav_self_service_my_schedule_url": "",
            "nav_self_service_weekly_schedule_url": "",
            "nav_can_view_hr_workspace": False,
            "nav_can_view_payroll_workspace": False,
            "nav_can_manage_work_calendar": False,
            "nav_can_view_recruitment": False,
            "nav_can_view_performance": False,
            "nav_can_view_assets": False,
            "nav_can_view_finance": False,
            "nav_hr_workspace_url": "",
            "nav_payroll_workspace_url": "",
            "nav_work_calendar_url": "",
            "nav_recruitment_url": "",
            "nav_performance_url": "",
            "nav_assets_url": "",
            "nav_finance_url": "",
            "nav_branch_schedule_overview_url": "",
            "session_timeout_enabled": False,
            "session_timeout_remaining_seconds": 0,
            "session_timeout_total_seconds": 0,
            "session_timeout_warning_seconds": 0,
            "session_timeout_ping_url": "",
            "session_timeout_expire_url": "",
            "session_timeout_login_url": reverse("login"),
            "nav_notifications_url": "",
            "nav_notification_unread_total": 0,
            "nav_notification_category_unread_counts": {},
        }

    is_admin_compatible = is_admin_compatible_role(user)
    is_hr_user = is_hr_user_role(user)
    is_finance_manager_user = is_finance_manager_user_role(user)
    is_supervisor_user = is_supervisor_user_role(user)
    is_operations_manager_user = is_operations_manager_user_role(user)
    is_employee_role_user = is_employee_role_user_role(user)

    employee_profile = (
        Employee.objects.filter(user=user)
        .select_related("company", "branch", "department", "section", "job_title")
        .first()
    )

    nav_scoped_branch = get_user_scope_branch_for_nav(user, employee_profile)

    show_supervisor_workspace = bool(nav_scoped_branch is not None and employee_profile)
    show_operations_workspace = bool(is_operations_manager_user and employee_profile)

    can_access_dashboard = bool(
        is_admin_compatible
        or is_hr_user
        or is_operations_manager_user
        or is_employee_role_user
        or show_supervisor_workspace
    )

    if show_supervisor_workspace:
        primary_home_url = ("employees:self_service_profile", None)
        primary_home_label = "My Supervisor Workspace"
    elif employee_profile and is_hr_user:
        primary_home_url = ("employees:employee_detail", {"pk": employee_profile.pk})
        primary_home_label = "My HR Workspace"
    elif show_operations_workspace:
        primary_home_url = ("employees:employee_detail", {"pk": employee_profile.pk})
        primary_home_label = "My Operations Workspace"
    elif employee_profile and is_employee_role_user:
        primary_home_url = ("employees:self_service_profile", None)
        primary_home_label = "My Workspace"
    else:
        primary_home_url = ("home", None)
        primary_home_label = "System Home"

    nav_is_employee_self_service_only = bool(
        is_employee_role_user
        and employee_profile
        and not is_admin_compatible
        and not is_hr_user
        and not is_operations_manager_user
        and nav_scoped_branch is None
    )

    nav_supervisor_branch_url = ""
    if nav_scoped_branch:
        nav_supervisor_branch_url = reverse("employees:self_service_branch")
    nav_supervisor_attendance_history_url = ""
    if nav_scoped_branch:
        nav_supervisor_attendance_history_url = reverse("employees:supervisor_attendance_history")

    nav_self_service_leave_url = ""
    nav_self_service_documents_url = ""
    nav_self_service_profile_url = ""
    nav_self_service_attendance_url = ""
    nav_self_service_expenses_url = ""
    nav_self_service_working_time_url = ""
    nav_self_service_branch_url = ""
    nav_self_service_my_schedule_url = ""
    nav_self_service_weekly_schedule_url = ""
    session_timeout_remaining_seconds = get_session_remaining_seconds(request)

    if employee_profile:
        nav_self_service_profile_url = get_workspace_profile_url(user, employee_profile)

        nav_self_service_leave_url = reverse("employees:self_service_leave")
        nav_self_service_documents_url = reverse("employees:self_service_documents")
        nav_self_service_attendance_url = reverse("employees:self_service_attendance")
        nav_self_service_expenses_url = reverse("employees:expense_claim_list")
        nav_self_service_working_time_url = reverse("employees:self_service_working_time")
        nav_self_service_my_schedule_url = reverse("employees:self_service_my_schedule")

        if getattr(employee_profile, "branch_id", None):
            nav_self_service_branch_url = reverse("employees:self_service_branch")
            nav_self_service_weekly_schedule_url = reverse("employees:self_service_weekly_schedule")

    try:
        nav_notification_unread_total = InAppNotification.objects.filter(
            recipient=user,
            is_read=False,
        ).count()
        nav_notification_category_unread_counts = {
            category: InAppNotification.objects.filter(
                recipient=user,
                category=category,
                is_read=False,
            ).count()
            for category, _label in InAppNotification.CATEGORY_CHOICES
        }
    except (OperationalError, ProgrammingError):
        nav_notification_unread_total = 0
        nav_notification_category_unread_counts = {}

    return {
        "nav_is_authenticated": True,
        "nav_can_access_dashboard": can_access_dashboard,
        "nav_can_view_organization": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_manage_organization": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_view_employee_directory": bool(
            is_admin_compatible
            or is_hr_user
            or is_operations_manager_user
            or nav_scoped_branch is not None
        ),
        "nav_can_add_employee": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_access_admin": is_admin_compatible,
        "nav_can_view_requests": bool(
            is_admin_compatible
            or is_hr_user
            or is_operations_manager_user
            or nav_scoped_branch is not None
        ),
        "nav_can_view_attendance_management": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_view_branch_schedule_overview": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_employee_profile": employee_profile,
        "nav_is_branch_scoped_supervisor": nav_scoped_branch is not None,
        "nav_scoped_branch": nav_scoped_branch,
        "nav_show_supervisor_workspace": show_supervisor_workspace,
        "nav_show_operations_workspace": show_operations_workspace,
        "nav_primary_home_url": primary_home_url,
        "nav_primary_home_label": primary_home_label,
        "nav_is_employee_self_service_only": nav_is_employee_self_service_only,
        "nav_supervisor_branch_url": nav_supervisor_branch_url,
        "nav_supervisor_attendance_history_url": nav_supervisor_attendance_history_url,
        "nav_can_view_branch_documents": bool(
            is_admin_compatible
            or is_hr_user
            or is_operations_manager_user
            or nav_scoped_branch is not None
        ),
        "nav_self_service_profile_url": nav_self_service_profile_url,
        "nav_self_service_leave_url": nav_self_service_leave_url,
        "nav_self_service_documents_url": nav_self_service_documents_url,
        "nav_self_service_attendance_url": nav_self_service_attendance_url,
        "nav_self_service_expenses_url": nav_self_service_expenses_url,
        "nav_self_service_working_time_url": nav_self_service_working_time_url,
        "nav_self_service_branch_url": nav_self_service_branch_url,
        "nav_self_service_my_schedule_url": nav_self_service_my_schedule_url,
        "nav_self_service_weekly_schedule_url": nav_self_service_weekly_schedule_url,
        "nav_can_view_hr_workspace": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_view_payroll_workspace": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_view_recruitment": bool(
            is_admin_compatible or is_hr_user
        ),
        "nav_can_view_performance": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user or employee_profile is not None
        ),
        "nav_can_view_assets": bool(
            is_admin_compatible or is_hr_user or is_operations_manager_user
        ),
        "nav_can_view_finance": bool(
            is_admin_compatible or is_hr_user or is_finance_manager_user
        ),
        "nav_can_manage_work_calendar": bool(
            is_admin_compatible or is_hr_user
        ),
        "nav_hr_workspace_url": reverse("hr:home"),
        "nav_payroll_workspace_url": reverse("payroll:home"),
        "nav_work_calendar_url": reverse("workcalendar:home"),
        "nav_recruitment_url": reverse("recruitment:job_posting_list"),
        "nav_performance_url": reverse("performance:dashboard"),
        "nav_assets_url": reverse("assets:asset_list"),
        "nav_finance_url": reverse("finance:expense_claim_dashboard"),
        "nav_branch_schedule_overview_url": reverse("employees:branch_schedule_overview"),
        "nav_notifications_url": reverse("notifications:home"),
        "nav_notification_unread_total": nav_notification_unread_total,
        "nav_notification_category_unread_counts": nav_notification_category_unread_counts,
        "session_timeout_enabled": True,
        "session_timeout_remaining_seconds": session_timeout_remaining_seconds,
        "session_timeout_remaining_label": format_session_remaining_seconds(session_timeout_remaining_seconds),
        "session_timeout_total_seconds": get_session_timeout_seconds(),
        "session_timeout_warning_seconds": get_session_warning_seconds(),
        "session_timeout_ping_url": reverse("session_ping"),
        "session_timeout_expire_url": reverse("session_expire"),
        "session_timeout_login_url": reverse("login"),
    }
