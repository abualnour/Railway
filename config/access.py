"""
Central access-control layer for NourAxis.

All role checks, mixins, and decorators live here.
Import from here everywhere else - never duplicate role logic in view files.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views import View


def is_superuser(user):
    return bool(user and user.is_authenticated and user.is_superuser)


def is_hr(user):
    return bool(user and user.is_authenticated and getattr(user, "is_hr", False))


def is_finance(user):
    return bool(user and user.is_authenticated and getattr(user, "is_finance_manager", False))


def is_supervisor(user):
    return bool(user and user.is_authenticated and getattr(user, "is_supervisor", False))


def is_operations(user):
    return bool(user and user.is_authenticated and getattr(user, "is_operations_manager", False))


def is_employee_role(user):
    return bool(user and user.is_authenticated and getattr(user, "is_employee_role", False))


def is_management(user):
    return bool(user and user.is_authenticated and getattr(user, "is_management_role", False))


def is_hr_or_ops(user):
    return is_hr(user) or is_operations(user) or is_superuser(user)


def is_hr_or_finance(user):
    return is_hr(user) or is_finance(user) or is_superuser(user)


def is_any_management(user):
    return is_management(user) or is_superuser(user)


class RoleRequiredMixin(View):
    """
    Mixin for class-based views.

    Set allowed_roles as a list of predicate functions.

    Example:
        class MyView(RoleRequiredMixin, View):
            allowed_roles = [is_hr, is_finance]
    """

    allowed_roles = []
    deny_message = "You do not have permission to access this page."
    deny_redirect = "home"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not any(fn(request.user) for fn in self.allowed_roles):
            messages.error(request, self.deny_message)
            return redirect(self.deny_redirect)
        return super().dispatch(request, *args, **kwargs)


def role_required(*predicates, message="You do not have permission.", redirect_to="home"):
    """
    Decorator for function-based views.

    Usage:
        @role_required(is_hr, is_finance)
    """

    def decorator(view_fn):
        @wraps(view_fn)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not any(fn(request.user) for fn in predicates):
                messages.error(request, message)
                return redirect(redirect_to)
            return view_fn(request, *args, **kwargs)

        return wrapper

    return decorator


def api_role_required(*predicates, message="Permission denied."):
    """JSON-safe version for API views."""

    def decorator(view_fn):
        @wraps(view_fn)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not any(fn(request.user) for fn in predicates):
                return JsonResponse({"error": message}, status=403)
            return view_fn(request, *args, **kwargs)

        return wrapper

    return decorator
