from django.urls import reverse

from employees.models import Employee


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
            "nav_employee_profile": None,
            "nav_is_branch_scoped_supervisor": False,
            "nav_scoped_branch": None,
            "nav_show_supervisor_workspace": False,
            "nav_show_operations_workspace": False,
            "nav_primary_home_url": None,
            "nav_primary_home_label": "System Home",
            "nav_is_employee_self_service_only": False,
            "nav_supervisor_branch_url": "",
            "nav_can_view_branch_documents": False,
        }

    role_value = (getattr(user, "role", "") or "").strip().lower()
    is_admin_compatible = bool(
        getattr(user, "is_superuser", False)
        or (
            getattr(user, "is_staff", False)
            and role_value not in {"hr", "supervisor", "operations_manager", "employee"}
        )
    )
    is_hr_user = bool(getattr(user, "is_hr", False))
    is_supervisor_user = bool(getattr(user, "is_supervisor", False))
    is_operations_manager_user = bool(getattr(user, "is_operations_manager", False))
    is_employee_role_user = bool(getattr(user, "is_employee_role", False))

    employee_profile = (
        Employee.objects.filter(user=user)
        .select_related("company", "branch", "department", "section", "job_title")
        .first()
    )

    nav_scoped_branch = None
    if (
        is_supervisor_user
        and not is_admin_compatible
        and not is_hr_user
        and not is_operations_manager_user
    ):
        nav_scoped_branch = getattr(employee_profile, "branch", None)

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
        primary_home_url = ("employees:employee_detail", {"pk": employee_profile.pk})
        primary_home_label = "My Supervisor Profile"
    elif show_operations_workspace:
        primary_home_url = ("employees:employee_detail", {"pk": employee_profile.pk})
        primary_home_label = "My Operations Profile"
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
        nav_supervisor_branch_url = reverse(
            "organization:branch_detail",
            kwargs={"pk": nav_scoped_branch.pk},
        )

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
        "nav_employee_profile": employee_profile,
        "nav_is_branch_scoped_supervisor": nav_scoped_branch is not None,
        "nav_scoped_branch": nav_scoped_branch,
        "nav_show_supervisor_workspace": show_supervisor_workspace,
        "nav_show_operations_workspace": show_operations_workspace,
        "nav_primary_home_url": primary_home_url,
        "nav_primary_home_label": primary_home_label,
        "nav_is_employee_self_service_only": nav_is_employee_self_service_only,
        "nav_supervisor_branch_url": nav_supervisor_branch_url,
        "nav_can_view_branch_documents": bool(
            is_admin_compatible
            or is_hr_user
            or is_operations_manager_user
            or nav_scoped_branch is not None
        ),
    }
