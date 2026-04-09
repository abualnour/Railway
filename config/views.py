from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import redirect, render
from django.utils import timezone

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


@login_required
def dashboard_home(request):
    if not can_access_dashboard(request.user):
        messages.error(request, "You do not have permission to access the dashboard.")

        linked_employee = get_user_employee_profile(request.user)
        if linked_employee:
            return redirect("employees:employee_detail", pk=linked_employee.pk)

        raise PermissionDenied("You do not have permission to access the dashboard.")

    today = timezone.localdate()
    recent_hire_cutoff = today - timedelta(days=30)

    total_employees = Employee.objects.count()
    active_employees = Employee.objects.filter(is_active=True).count()
    inactive_employees = Employee.objects.filter(is_active=False).count()

    recent_employees = (
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        )
        .order_by("-id")[:8]
    )

    recent_hires = (
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        )
        .filter(hire_date__isnull=False)
        .order_by("-hire_date", "-id")[:6]
    )

    recently_updated_employees = (
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        )
        .order_by("-updated_at")[:6]
    )

    employees_by_company = (
        Employee.objects.filter(company__isnull=False)
        .values("company_id", "company__name")
        .annotate(total=Count("id"))
        .order_by("-total", "company__name")[:6]
    )

    employees_by_branch = (
        Employee.objects.filter(branch__isnull=False)
        .values("branch_id", "branch__name")
        .annotate(total=Count("id"))
        .order_by("-total", "branch__name")[:6]
    )

    employees_by_department = (
        Employee.objects.filter(department__isnull=False)
        .values("department_id", "department__name")
        .annotate(total=Count("id"))
        .order_by("-total", "department__name")[:6]
    )

    if total_employees > 0:
        active_ratio = round((active_employees / total_employees) * 100)
        inactive_ratio = round((inactive_employees / total_employees) * 100)
    else:
        active_ratio = 0
        inactive_ratio = 0

    context = {
        "metrics": {
            "total_companies": Company.objects.count(),
            "total_departments": Department.objects.count(),
            "total_branches": Branch.objects.count(),
            "total_sections": Section.objects.count(),
            "total_job_titles": JobTitle.objects.count(),
            "total_employees": total_employees,
            "active_employees": active_employees,
            "inactive_employees": inactive_employees,
            "active_ratio": active_ratio,
            "inactive_ratio": inactive_ratio,
            "recent_hires_30_days": Employee.objects.filter(
                hire_date__isnull=False,
                hire_date__gte=recent_hire_cutoff,
            ).count(),
        },
        "recent_employees": recent_employees,
        "recent_hires": recent_hires,
        "recently_updated_employees": recently_updated_employees,
        "employees_by_company": employees_by_company,
        "employees_by_branch": employees_by_branch,
        "employees_by_department": employees_by_department,
        "can_view_employee_directory": True,
        "can_view_organization_setup": can_view_organization_setup(request.user),
        "can_manage_organization_setup": can_manage_organization_setup(request.user),
    }

    return render(request, "dashboard/home.html", context)
