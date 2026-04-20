from django.urls import reverse


ROLE_EXCLUDED_STAFF_VALUES = {"hr", "finance_manager", "supervisor", "operations_manager", "employee"}


def is_admin_compatible(user):
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_superuser", False):
        return True

    role_value = (getattr(user, "role", "") or "").strip().lower()
    if role_value in ROLE_EXCLUDED_STAFF_VALUES:
        return False

    return bool(getattr(user, "is_staff", False))


def is_hr_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_hr", False))


def is_supervisor_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_supervisor", False))


def is_finance_manager_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_finance_manager", False))


def is_operations_manager_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_operations_manager", False))


def is_employee_role_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_employee_role", False))


def get_user_scope_branch(user, employee_profile=None):
    if (
        not is_supervisor_user(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or is_admin_compatible(user)
    ):
        return None

    if not employee_profile or not getattr(employee_profile, "branch_id", None):
        return None

    return employee_profile.branch


def is_branch_scoped_supervisor(user, employee_profile=None):
    return get_user_scope_branch(user, employee_profile) is not None


def get_workspace_home_label(user, employee_profile=None):
    if is_admin_compatible(user):
        return "Admin Workspace"
    if is_hr_user(user):
        return "HR Workspace"
    if is_finance_manager_user(user):
        return "Finance Workspace"
    if is_operations_manager_user(user):
        return "Operations Workspace"
    if is_branch_scoped_supervisor(user, employee_profile):
        return "Supervisor Workspace"
    return "Employee Self-Service"


def get_workspace_profile_url(user, employee_profile=None):
    if not employee_profile:
        return reverse("home")

    if is_admin_compatible(user) or is_hr_user(user) or is_finance_manager_user(user) or is_operations_manager_user(user):
        return reverse("employees:employee_detail", kwargs={"pk": employee_profile.pk})

    return reverse("employees:self_service_profile")


def should_use_management_own_profile(user, employee_profile=None):
    return bool(
        employee_profile
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_finance_manager_user(user)
            or is_operations_manager_user(user)
        )
    )
