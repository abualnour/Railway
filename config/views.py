from django.shortcuts import render

from employees.models import Employee
from organization.models import Branch, Company, Department, JobTitle, Section


def is_admin_compatible(user):
    return bool(
        user
        and user.is_authenticated
        and (getattr(user, "is_superuser", False) or getattr(user, "is_staff", False))
    )


def is_hr_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_hr", False))


def is_supervisor_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_supervisor", False))


def is_operations_manager_user(user):
    return bool(user and user.is_authenticated and getattr(user, "is_operations_manager", False))


def is_management_user(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_supervisor_user(user)
            or is_operations_manager_user(user)
        )
    )


def can_access_dashboard(user):
    return is_management_user(user)


def can_view_organization_setup(user):
    return is_management_user(user)


def can_manage_organization_setup(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
        )
    )


def get_user_employee_profile(user):
    if not user or not user.is_authenticated:
        return None

    return (
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        )
        .filter(user=user)
        .first()
    )


def system_landing(request):
    user = request.user
    linked_employee = get_user_employee_profile(user)
    is_management = is_management_user(user)
    is_employee_role = bool(
        user
        and user.is_authenticated
        and getattr(user, "is_employee_role", False)
    )

    company_count = Company.objects.count()
    branch_count = Branch.objects.count()
    department_count = Department.objects.count()
    active_employee_count = Employee.objects.filter(is_active=True).count()

    context = {
        "is_management_user": is_management,
        "is_employee_role": is_employee_role,
        "linked_employee": linked_employee,
        "company_count": company_count,
        "branch_count": branch_count,
        "department_count": department_count,
        "active_employee_count": active_employee_count,
        "can_view_dashboard": can_access_dashboard(user),
        "can_view_employee_directory": is_management,
        "can_view_organization_setup": can_view_organization_setup(user),
    }

    return render(request, "system_landing.html", context)
