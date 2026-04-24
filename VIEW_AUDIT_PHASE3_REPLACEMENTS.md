# Phase 3 View Audit Replacement Files

## finance/views.py

```python
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from config.access import is_finance, is_hr, is_superuser, role_required
from employees.access import is_admin_compatible, is_finance_manager_user, is_hr_user

from .forms import ExpenseClaimReviewForm
from .models import ExpenseClaim


def can_review_expense_claims(user):
    return bool(
        user
        and user.is_authenticated
        and (is_admin_compatible(user) or is_hr_user(user) or is_finance_manager_user(user))
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_finance,
    is_superuser,
    message="You do not have permission to access finance expense claims.",
)
def expense_claim_dashboard(request):
    status_filter = (request.GET.get("status") or "").strip()
    claims = ExpenseClaim.objects.select_related(
        "employee",
        "employee__branch",
        "employee__department",
        "reviewed_by",
    )
    if status_filter:
        claims = claims.filter(status=status_filter)
    claims = claims.order_by("-submitted_at", "-expense_date", "-id")
    paginator = Paginator(claims, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "claims": list(page_obj.object_list),
        "page_obj": page_obj,
        "paginator": paginator,
        "status_choices": ExpenseClaim.STATUS_CHOICES,
        "selected_status": status_filter,
        "claim_total": ExpenseClaim.objects.count(),
        "submitted_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_SUBMITTED).count(),
        "approved_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_APPROVED).count(),
        "paid_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_PAID).count(),
    }
    return render(request, "finance/expense_claim_dashboard.html", context)


@role_required(
    is_admin_compatible,
    is_hr,
    is_finance,
    is_superuser,
    message="You do not have permission to review expense claims.",
    redirect_to="finance:expense_claim_dashboard",
)
def expense_claim_review(request, claim_pk):
    claim = get_object_or_404(
        ExpenseClaim.objects.select_related("employee", "reviewed_by"),
        pk=claim_pk,
    )

    if request.method == "POST":
        form = ExpenseClaimReviewForm(request.POST, instance=claim)
        if form.is_valid():
            reviewed_claim = form.save(commit=False)
            reviewed_claim.reviewed_by = request.user
            reviewed_claim.reviewed_at = timezone.now()
            reviewed_claim.save()
            messages.success(request, "Expense claim review saved successfully.")
            return redirect("finance:expense_claim_dashboard")
        messages.error(request, "Please review the expense claim decision and try again.")
    else:
        form = ExpenseClaimReviewForm(instance=claim)

    return render(
        request,
        "finance/expense_claim_review.html",
        {
            "claim": claim,
            "form": form,
        },
    )

# Create your views here.
```

## notifications/views.py

```python
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .email_sender import send_notification_email
from .forms import NotificationPreferenceForm
from .models import (
    InAppNotification,
    NotificationPreference,
    build_in_app_notification,
    get_notification_preferences_for_user,
)


NOTIFICATION_CATEGORY_ORDER = [
    InAppNotification.CATEGORY_PAYROLL,
    InAppNotification.CATEGORY_REQUEST,
    InAppNotification.CATEGORY_OPERATIONS,
    InAppNotification.CATEGORY_SCHEDULE,
    InAppNotification.CATEGORY_EMPLOYEE,
    InAppNotification.CATEGORY_HR,
    InAppNotification.CATEGORY_CONTRACT,
    InAppNotification.CATEGORY_CALENDAR,
]


def trigger_document_expiry_notifications(reference_date=None):
    from employees.models import Employee

    user_model = get_user_model()
    reference_date = reference_date or timezone.localdate()
    notification_cutoff = reference_date + timedelta(days=30)

    hr_recipients = list(
        user_model.objects.filter(
            is_active=True,
            role=user_model.ROLE_HR,
        ).order_by("email", "id")
    )
    if not hr_recipients:
        return []

    employee_queryset = Employee.objects.select_related("branch").filter(is_active=True).order_by("full_name", "employee_id")
    pending_notifications = []

    for employee in employee_queryset:
        document_entries = [
            ("Civil ID", employee.civil_id_expiry_date),
            ("Passport", employee.passport_expiry_date),
        ]

        for document_label, expiry_date in document_entries:
            if not expiry_date or expiry_date < reference_date or expiry_date > notification_cutoff:
                continue

            days_until_expiry = (expiry_date - reference_date).days
            title = f"{document_label} expiring soon for {employee.full_name}"
            body = (
                f"{employee.full_name} ({employee.employee_id}) in "
                f"{employee.branch.name if employee.branch_id else 'No Branch'} has a {document_label.lower()} "
                f"expiring on {expiry_date.strftime('%B %d, %Y')} "
                f"({days_until_expiry} days remaining)."
            )
            action_url = reverse("employees:employee_detail", kwargs={"pk": employee.pk})

            for recipient in hr_recipients:
                already_exists = InAppNotification.objects.filter(
                    recipient=recipient,
                    category=InAppNotification.CATEGORY_HR,
                    title=title,
                    action_url=action_url,
                    created_at__date=reference_date,
                ).exists()
                if already_exists:
                    continue

                notification = build_in_app_notification(
                    recipient=recipient,
                    title=title,
                    body=body,
                    category=InAppNotification.CATEGORY_HR,
                    action_url=action_url,
                    level=InAppNotification.LEVEL_WARNING,
                )
                if notification is None:
                    continue

                pending_notifications.append(notification)

    return persist_in_app_notifications(pending_notifications)


def trigger_contract_expiry_notifications(reference_date=None):
    from employees.models import EmployeeContract

    user_model = get_user_model()
    reference_date = reference_date or timezone.localdate()
    notification_cutoff = reference_date + timedelta(days=60)

    hr_recipients = list(
        user_model.objects.filter(
            is_active=True,
            role=user_model.ROLE_HR,
        ).order_by("email", "id")
    )
    if not hr_recipients:
        return []

    contract_queryset = (
        EmployeeContract.objects.select_related("employee", "employee__branch", "employee__company")
        .filter(
            is_active=True,
            end_date__isnull=False,
            end_date__gte=reference_date,
            end_date__lte=notification_cutoff,
        )
        .order_by("end_date", "employee__full_name", "id")
    )
    pending_notifications = []

    for contract in contract_queryset:
        employee = contract.employee
        days_until_expiry = (contract.end_date - reference_date).days
        title = f"Contract expiring soon for {employee.full_name}"
        body = (
            f"{employee.full_name} ({employee.employee_id}) has an active "
            f"{contract.get_contract_type_display().lower()} contract ending on "
            f"{contract.end_date.strftime('%B %d, %Y')} "
            f"({days_until_expiry} days remaining)"
            f" in {employee.branch.name if employee.branch_id else 'No Branch'}."
        )
        action_url = reverse("employees:employee_detail", kwargs={"pk": employee.pk})

        for recipient in hr_recipients:
            already_exists = InAppNotification.objects.filter(
                recipient=recipient,
                category=InAppNotification.CATEGORY_CONTRACT,
                title=title,
                action_url=action_url,
                created_at__date=reference_date,
            ).exists()
            if already_exists:
                continue

            notification = build_in_app_notification(
                recipient=recipient,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_CONTRACT,
                action_url=action_url,
                level=InAppNotification.LEVEL_WARNING,
            )
            if notification is None:
                continue

            pending_notifications.append(notification)

    return persist_in_app_notifications(pending_notifications)


def persist_in_app_notifications(notifications):
    deduped_notifications = []
    seen_keys = set()

    for notification in notifications:
        if notification is None:
            continue
        notification_key = (
            notification.recipient_id,
            notification.title,
            notification.body,
            notification.category,
            notification.action_url,
        )
        if notification_key in seen_keys:
            continue
        seen_keys.add(notification_key)
        deduped_notifications.append(notification)

    saved_notifications = []
    for notification in deduped_notifications:
        notification.save()

        preferences = get_notification_preferences_for_user(notification.recipient)
        allow_email = bool(
            preferences
            and getattr(preferences, "email_enabled", True)
            and getattr(notification.recipient, "email", "").strip()
        )
        if allow_email:
            try:
                send_notification_email(
                    recipient_email=notification.recipient.email,
                    subject=notification.title,
                    body_text=notification.body,
                )
            except Exception as exc:
                notification.email_failed = True
                notification.email_failed_reason = str(exc)[:255]
                notification.save(update_fields=["email_failed", "email_failed_reason"])
            else:
                notification.email_sent = True
                notification.save(update_fields=["email_sent"])

        saved_notifications.append(notification)

    return saved_notifications


def build_notification_category_cards(notifications):
    category_label_map = dict(InAppNotification.CATEGORY_CHOICES)
    cards = []
    for category in NOTIFICATION_CATEGORY_ORDER:
        category_notifications = [notification for notification in notifications if notification.category == category]
        unread_total = sum(1 for notification in category_notifications if not notification.is_read)
        cards.append(
            {
                "key": category,
                "label": category_label_map.get(category, category.title()),
                "total": len(category_notifications),
                "unread_total": unread_total,
                "notifications": category_notifications[:12],
            }
        )
    return cards


def build_notification_category_summary(recipient):
    category_label_map = dict(InAppNotification.CATEGORY_CHOICES)
    base_queryset = InAppNotification.objects.filter(recipient=recipient, is_deleted=False)
    cards = []
    for category in NOTIFICATION_CATEGORY_ORDER:
        category_queryset = base_queryset.filter(category=category)
        cards.append(
            {
                "key": category,
                "label": category_label_map.get(category, category.title()),
                "total": category_queryset.count(),
                "unread_total": category_queryset.filter(is_read=False).count(),
            }
        )
    return cards


def filter_visible_category_cards(category_cards, selected_category):
    if selected_category:
        return [
            category
            for category in category_cards
            if category["key"] == selected_category and category["notifications"]
        ]
    return [category for category in category_cards if category["notifications"]]


@login_required
def notification_center(request):
    base_queryset = InAppNotification.objects.filter(recipient=request.user, is_deleted=False)
    unread_total = base_queryset.filter(is_read=False).count()
    preferences = get_notification_preferences_for_user(request.user)
    selected_category = (request.GET.get("category") or "").strip()
    valid_categories = {choice[0] for choice in InAppNotification.CATEGORY_CHOICES}
    if selected_category and selected_category not in valid_categories:
        selected_category = ""

    filtered_queryset = base_queryset
    if selected_category:
        filtered_queryset = filtered_queryset.filter(category=selected_category)

    paginator = Paginator(filtered_queryset, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    notifications = list(page_obj.object_list)
    category_cards = build_notification_category_summary(request.user)
    visible_category_cards = filter_visible_category_cards(
        build_notification_category_cards(notifications),
        selected_category,
    )
    selected_category_label = dict(InAppNotification.CATEGORY_CHOICES).get(selected_category, "All Notifications")

    context = {
        "notifications": notifications,
        "all_notifications_total": base_queryset.count(),
        "unread_total": unread_total,
        "preference_form": NotificationPreferenceForm(instance=preferences),
        "category_cards": category_cards,
        "visible_category_cards": visible_category_cards,
        "selected_category": selected_category,
        "selected_category_label": selected_category_label,
        "notification_categories": InAppNotification.CATEGORY_CHOICES,
        "page_obj": page_obj,
        "paginator": paginator,
    }
    return render(request, "notifications/center.html", context)


@login_required
@require_POST
def mark_notification_read(request, pk):
    notification = get_object_or_404(
        InAppNotification,
        pk=pk,
        recipient=request.user,
        is_deleted=False,
    )
    notification.mark_read()
    next_url = (request.POST.get("next") or "").strip()
    if next_url:
        return redirect(next_url)
    return redirect("notifications:home")


@login_required
@require_POST
def mark_all_read(request):
    unread_notifications = InAppNotification.objects.filter(
        recipient=request.user,
        is_read=False,
        is_deleted=False,
    )
    unread_notifications.update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip()
    return redirect(next_url or "notifications:home")


@login_required
@require_POST
def mark_category_read(request, category):
    valid_categories = {choice[0] for choice in InAppNotification.CATEGORY_CHOICES}
    if category in valid_categories:
        InAppNotification.objects.filter(
            recipient=request.user,
            category=category,
            is_read=False,
            is_deleted=False,
        ).update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip()
    return redirect(next_url or "notifications:home")


@login_required
@require_POST
def delete_notification(request, pk):
    notification = get_object_or_404(
        InAppNotification,
        pk=pk,
        recipient=request.user,
        is_deleted=False,
    )
    notification.is_deleted = True
    notification.deleted_at = timezone.now()
    notification.save(update_fields=["is_deleted", "deleted_at"])
    return redirect(request.POST.get("next") or "notifications:home")


@login_required
@require_POST
def bulk_delete_notifications(request):
    raw_ids = (request.POST.get("ids") or "").strip()
    notification_ids = []
    for value in raw_ids.split(","):
        value = value.strip()
        if not value:
            continue
        try:
            notification_ids.append(int(value))
        except (TypeError, ValueError):
            continue
    if notification_ids:
        InAppNotification.objects.filter(
            recipient=request.user,
            pk__in=notification_ids,
            is_deleted=False,
        ).update(is_deleted=True, deleted_at=timezone.now())
    return redirect(request.POST.get("next") or "notifications:home")


@login_required
def delivery_performance(request):
    if not (request.user.is_management_role or request.user.is_superuser):
        return redirect("notifications:home")

    base_qs = InAppNotification.objects.all()
    summary_counts = base_qs.aggregate(
        total=Count("id"),
        email_sent=Count("id", filter=Q(email_sent=True)),
        email_failed=Count("id", filter=Q(email_failed=True)),
    )
    summary = {
        "total": summary_counts["total"] or 0,
        "email_sent": summary_counts["email_sent"] or 0,
        "email_failed": summary_counts["email_failed"] or 0,
        "last_sent": base_qs.filter(email_sent=True).order_by("-created_at").values_list("created_at", flat=True).first(),
    }
    summary["failure_rate"] = (
        round(summary["email_failed"] / summary["email_sent"] * 100, 1)
        if summary["email_sent"]
        else 0
    )

    category_label_map = dict(InAppNotification.CATEGORY_CHOICES)
    category_breakdown = []
    for cat in NOTIFICATION_CATEGORY_ORDER:
        qs = base_qs.filter(category=cat)
        category_breakdown.append(
            {
                "label": category_label_map.get(cat, cat),
                "total": qs.count(),
                "email_sent": qs.filter(email_sent=True).count(),
                "email_failed": qs.filter(email_failed=True).count(),
            }
        )

    recent_failures = (
        base_qs.filter(email_failed=True)
        .select_related("recipient")
        .order_by("-created_at")[:20]
    )
    opt_outs = NotificationPreference.objects.filter(email_enabled=False).select_related("user").order_by("user__role")

    context = {
        "summary": summary,
        "category_breakdown": category_breakdown,
        "recent_failures": recent_failures,
        "opt_outs": opt_outs,
    }
    return render(request, "notifications/performance.html", context)


@login_required
@require_POST
def update_notification_preferences(request):
    next_url = (request.POST.get("next") or "").strip()
    preferences = get_notification_preferences_for_user(request.user)
    form = NotificationPreferenceForm(request.POST, instance=preferences)
    if form.is_valid():
        form.save()
        messages.success(
            request,
            "Notification delivery settings saved. Payroll delivery and category-based in-app alerts will use your new choices.",
        )
    else:
        messages.error(request, "Please review the notification preference settings.")
    return redirect(next_url or "notifications:home")
```

## organization/views.py

```python
from datetime import timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from config.mixins import ProtectedDeleteMixin
from employees.access import is_admin_compatible as is_admin_compatible_role
from employees.models import Employee

from .forms import (
    BranchDocumentForm,
    BranchDocumentRequirementForm,
    BranchForm,
    CompanyForm,
    DepartmentForm,
    JobTitleForm,
    SectionForm,
)
from .models import (
    Branch,
    BranchDocument,
    BranchDocumentRequirement,
    Company,
    Department,
    JobTitle,
    Section,
)


def is_admin_compatible(user):
    return is_admin_compatible_role(user)


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


def can_view_organization_setup(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
        )
    )


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
    return Employee.objects.filter(user=user).first()


def status_badge_class(value):
    return "badge-success" if value else "badge-danger"


def status_label(value):
    return "Active" if value else "Inactive"


def format_text(value, fallback="—"):
    if value in (None, ""):
        return fallback
    return str(value)


def get_organization_form_meta(model):
    model_name = getattr(getattr(model, "_meta", None), "model_name", "")

    form_meta_map = {
        "company": {
            "subtitle": "Set up the company profile information that appears on the company detail record.",
            "title": "Company record setup",
            "description": "Keep the public-facing company details complete so the organization directory stays consistent between create, edit, and detail views.",
            "highlights": [
                {
                    "label": "Display Name",
                    "value": "Used as the primary company name across navigation, lists, and linked records.",
                },
                {
                    "label": "Legal + Contact",
                    "value": "Legal name, email, phone, and address feed the company summary shown later.",
                },
                {
                    "label": "Logo + Notes",
                    "value": "Optional visual branding and internal notes remain available on the detail page.",
                },
            ],
        },
        "branch": {
            "subtitle": "Create a branch record with company placement, visible contact data, and optional attendance location settings.",
            "title": "Branch setup",
            "description": "Branch details, compliance work, and branch-specific attendance checks all depend on this record staying complete and accurate.",
            "highlights": [
                {
                    "label": "Company Placement",
                    "value": "Every branch is tied to one company and appears under that company detail view.",
                },
                {
                    "label": "Attendance Point",
                    "value": "Latitude, longitude, and radius should be filled together only when live attendance location control is needed.",
                },
                {
                    "label": "Branch Identity",
                    "value": "City, email, image, and notes show up in branch-facing summaries and admin review pages.",
                },
            ],
        },
        "department": {
            "subtitle": "Set up a department under the correct company with the labels used across employee and organization pages.",
            "title": "Department setup",
            "description": "Departments drive section structure, job-title grouping, and employee organization without changing the existing hierarchy.",
            "highlights": [
                {
                    "label": "Company Link",
                    "value": "The selected company controls where this department appears in the organization structure.",
                },
                {
                    "label": "Code + Manager",
                    "value": "Optional code and manager name are shown later on the department detail record.",
                },
                {
                    "label": "Legacy Safety",
                    "value": "Older branch-linked department records are still preserved safely even though that field is not part of the normal form.",
                },
            ],
        },
        "section": {
            "subtitle": "Create a section under the right department and keep the team-supervision details clear.",
            "title": "Section setup",
            "description": "Sections define where job titles and employees sit inside each department, so a clean department link matters here.",
            "highlights": [
                {
                    "label": "Department Link",
                    "value": "The selected department automatically determines the section's company placement.",
                },
                {
                    "label": "Supervisor",
                    "value": "Supervisor name appears in section details and related organization summaries.",
                },
                {
                    "label": "Notes",
                    "value": "Use internal notes for HR or operations context without changing employee access scope.",
                },
            ],
        },
        "jobtitle": {
            "subtitle": "Create the role under the correct section so employees and structure pages remain aligned.",
            "title": "Job title setup",
            "description": "Job titles are section-based in the active design, and the department is derived automatically from the section you choose.",
            "highlights": [
                {
                    "label": "Section Required",
                    "value": "Selecting a section is required because the role's placement is section-first in the current hierarchy.",
                },
                {
                    "label": "Department Auto-Link",
                    "value": "The system keeps department alignment automatically based on the chosen section.",
                },
                {
                    "label": "Clean Directory Data",
                    "value": "Code and notes remain optional, but they are available for clearer reporting and record detail pages.",
                },
            ],
        },
    }

    return form_meta_map.get(model_name, {})


def get_organization_list_meta(model):
    model_name = getattr(getattr(model, "_meta", None), "model_name", "")

    list_meta_map = {
        "company": {
            "directory_subtitle": "Review company records, open the full profile, and keep legal and contact details aligned.",
            "empty_title": "No companies found",
            "empty_action_label": "Add First Company",
            "record_label": "Company records",
        },
        "branch": {
            "directory_subtitle": "Review branch records, company placement, and branch-level operations context from one workspace.",
            "empty_title": "No branches found",
            "empty_action_label": "Add First Branch",
            "record_label": "Branch records",
        },
        "department": {
            "directory_subtitle": "Browse departments, their company placement, and the team structure connected to each record.",
            "empty_title": "No departments found",
            "empty_action_label": "Add First Department",
            "record_label": "Department records",
        },
        "section": {
            "directory_subtitle": "Browse sections, keep supervision details clear, and open the linked organization structure.",
            "empty_title": "No sections found",
            "empty_action_label": "Add First Section",
            "record_label": "Section records",
        },
        "jobtitle": {
            "directory_subtitle": "Browse role records, section placement, and employee assignment context without leaving the directory.",
            "empty_title": "No job titles found",
            "empty_action_label": "Add First Job Title",
            "record_label": "Job title records",
        },
    }

    return list_meta_map.get(model_name, {})


def get_organization_detail_meta(model):
    model_name = getattr(getattr(model, "_meta", None), "model_name", "")

    detail_meta_map = {
        "company": {"summary_label": "Company Summary"},
        "branch": {"summary_label": "Branch Summary"},
        "department": {"summary_label": "Department Summary"},
        "section": {"summary_label": "Section Summary"},
        "jobtitle": {"summary_label": "Job Title Summary"},
    }

    return detail_meta_map.get(model_name, {"summary_label": "Record Summary"})


def summarize_organization_object(obj):
    model_name = getattr(getattr(obj, "_meta", None), "model_name", "")

    if model_name == "company":
        legal_name = (getattr(obj, "legal_name", "") or "").strip()
        if legal_name:
            return f"Legal name: {legal_name}"
        return "Open this company to review branches, departments, and assigned employees."

    if model_name == "branch":
        company_name = getattr(getattr(obj, "company", None), "name", "")
        city = (getattr(obj, "city", "") or "").strip()
        if company_name and city:
            return f"{company_name} · {city}"
        if company_name:
            return f"Company: {company_name}"
        if city:
            return f"City: {city}"
        return "Open this branch to review employees, compliance, and branch documents."

    if model_name == "department":
        company_name = getattr(getattr(obj, "company", None), "name", "")
        manager_name = (getattr(obj, "manager_name", "") or "").strip()
        if company_name and manager_name:
            return f"{company_name} · Manager: {manager_name}"
        if company_name:
            return f"Company: {company_name}"
        if manager_name:
            return f"Manager: {manager_name}"
        return "Open this department to review sections, job titles, and assigned employees."

    if model_name == "section":
        department = getattr(obj, "department", None)
        department_name = getattr(department, "name", "")
        company_name = getattr(getattr(department, "company", None), "name", "")
        if department_name and company_name:
            return f"{company_name} · {department_name}"
        if department_name:
            return f"Department: {department_name}"
        return "Open this section to review linked roles and assigned employees."

    if model_name == "jobtitle":
        section = getattr(obj, "section", None)
        department = getattr(obj, "department", None)
        section_name = getattr(section, "name", "")
        department_name = getattr(department, "name", "")
        if section_name and department_name:
            return f"{department_name} · {section_name}"
        if section_name:
            return f"Section: {section_name}"
        if department_name:
            return f"Department: {department_name}"
        return "Open this job title to review role placement and assigned employees."

    return "Open this record to review full details and linked team data."


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
    content_type = "application/octet-stream"
    if extension == "pdf":
        content_type = "application/pdf"
    elif extension == "png":
        content_type = "image/png"
    elif extension in {"jpg", "jpeg"}:
        content_type = "image/jpeg"
    elif extension == "webp":
        content_type = "image/webp"
    elif extension == "gif":
        content_type = "image/gif"
    elif extension == "bmp":
        content_type = "image/bmp"
    elif extension == "txt":
        content_type = "text/plain"

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


def get_document_status_badge_class(document):
    if document.is_expired:
        return "badge-danger"
    if document.is_expiring_soon:
        return "badge-warning"
    if document.expiry_date:
        return "badge-success"
    return "badge-light"


def get_document_days_label(document):
    days = document.days_until_expiry
    if days is None:
        return "No expiry date"
    if days < 0:
        return f"Expired {abs(days)} day{'s' if abs(days) != 1 else ''} ago"
    if days == 0:
        return "Expires today"
    if days == 1:
        return "1 day remaining"
    return f"{days} days remaining"


def build_branch_document_rows(documents):
    rows = []
    for document in documents:
        rows.append(
            {
                "id": document.pk,
                "branch_name": document.branch.name if document.branch_id else "—",
                "company_name": (
                    document.branch.company.name
                    if document.branch_id and document.branch.company_id
                    else "—"
                ),
                "title": document.title or document.filename or "Untitled document",
                "document_type": document.get_document_type_display(),
                "reference_number": document.reference_number or "—",
                "issue_date": document.issue_date,
                "expiry_date": document.expiry_date,
                "status_label": document.compliance_status_label,
                "status_badge_class": get_document_status_badge_class(document),
                "days_label": get_document_days_label(document),
                "is_required": document.is_required,
                "uploaded_by": document.uploaded_by or "—",
                "has_file": bool(document.file),
                "view_url": (
                    reverse(
                        "organization:branch_document_view",
                        kwargs={"branch_pk": document.branch_id, "document_pk": document.pk},
                    )
                    if document.branch_id and document.file
                    else ""
                ),
                "download_url": (
                    reverse(
                        "organization:branch_document_download",
                        kwargs={"branch_pk": document.branch_id, "document_pk": document.pk},
                    )
                    if document.branch_id and document.file
                    else ""
                ),
                "file_name": document.filename or document.title or "Document",
                "branch_detail_url": (
                    reverse("organization:branch_detail", kwargs={"pk": document.branch_id})
                    if document.branch_id
                    else ""
                ),
                "delete_url": (
                    reverse(
                        "organization:branch_document_delete",
                        kwargs={
                            "branch_pk": document.branch_id,
                            "document_pk": document.pk,
                        },
                    )
                    if document.branch_id
                    else ""
                ),
            }
        )
    return rows




def get_requirement_status_payload(selected_document):
    if not selected_document:
        return {
            "state_key": "missing",
            "status_label": "Missing",
            "badge_class": "badge-danger",
            "days_label": "No uploaded document",
        }

    if selected_document.is_expired:
        return {
            "state_key": "expired",
            "status_label": "Expired",
            "badge_class": "badge-danger",
            "days_label": get_document_days_label(selected_document),
        }

    if selected_document.is_expiring_soon:
        return {
            "state_key": "expiring_soon",
            "status_label": "Expiring Soon",
            "badge_class": "badge-warning",
            "days_label": get_document_days_label(selected_document),
        }

    if selected_document.expiry_date:
        return {
            "state_key": "valid",
            "status_label": "Valid",
            "badge_class": "badge-success",
            "days_label": get_document_days_label(selected_document),
        }

    return {
        "state_key": "recorded",
        "status_label": "Recorded",
        "badge_class": "badge-primary",
        "days_label": "No expiry date",
    }


def build_requirement_rows(requirements, documents):
    latest_documents_by_type = {}
    for document in documents:
        latest_documents_by_type.setdefault(document.document_type, document)

    rows = []
    for requirement in requirements:
        selected_document = latest_documents_by_type.get(requirement.document_type)
        status_payload = get_requirement_status_payload(selected_document)
        rows.append(
            {
                "id": requirement.pk,
                "branch_id": requirement.branch_id,
                "title": requirement.display_title,
                "document_type": requirement.get_document_type_display(),
                "notes": requirement.notes or "—",
                "is_mandatory": requirement.is_mandatory,
                "document_title": selected_document.title if selected_document else "Not uploaded",
                "document_reference_number": selected_document.reference_number if selected_document else "—",
                "document_issue_date": selected_document.issue_date if selected_document else None,
                "document_expiry_date": selected_document.expiry_date if selected_document else None,
                "document_has_file": bool(selected_document and selected_document.file),
                "document_view_url": (
                    reverse(
                        "organization:branch_document_view",
                        kwargs={"branch_pk": selected_document.branch_id, "document_pk": selected_document.pk},
                    )
                    if selected_document and selected_document.file and selected_document.branch_id
                    else ""
                ),
                "document_download_url": (
                    reverse(
                        "organization:branch_document_download",
                        kwargs={"branch_pk": selected_document.branch_id, "document_pk": selected_document.pk},
                    )
                    if selected_document and selected_document.file and selected_document.branch_id
                    else ""
                ),
                "status_label": status_payload["status_label"],
                "status_badge_class": status_payload["badge_class"],
                "days_label": status_payload["days_label"],
                "state_key": status_payload["state_key"],
                "delete_url": reverse(
                    "organization:branch_document_requirement_delete",
                    kwargs={"branch_pk": requirement.branch_id, "requirement_pk": requirement.pk},
                ),
            }
        )
    return rows


def build_requirement_summary(rows):
    summary = {
        "requirement_total": len(rows),
        "requirement_missing_total": 0,
        "requirement_expired_total": 0,
        "requirement_expiring_soon_total": 0,
        "requirement_valid_total": 0,
        "requirement_recorded_total": 0,
    }

    for row in rows:
        state_key = row["state_key"]
        if state_key == "missing":
            summary["requirement_missing_total"] += 1
        elif state_key == "expired":
            summary["requirement_expired_total"] += 1
        elif state_key == "expiring_soon":
            summary["requirement_expiring_soon_total"] += 1
        elif state_key == "valid":
            summary["requirement_valid_total"] += 1
        elif state_key == "recorded":
            summary["requirement_recorded_total"] += 1

    return summary


def build_numbered_pagination_items(page_obj, window=1):
    if not page_obj or page_obj.paginator.num_pages <= 1:
        return []

    current_page = page_obj.number
    total_pages = page_obj.paginator.num_pages
    visible_numbers = {1, total_pages}

    for page_number in range(current_page - window, current_page + window + 1):
        if 1 <= page_number <= total_pages:
            visible_numbers.add(page_number)

    items = []
    last_number = None
    for page_number in sorted(visible_numbers):
        if last_number is not None and page_number - last_number > 1:
            items.append({"type": "ellipsis"})
        items.append(
            {
                "type": "page",
                "number": page_number,
                "is_current": page_number == current_page,
            }
        )
        last_number = page_number

    return items


def build_updated_querystring(request, excluded_keys=None, **updates):
    query_data = request.GET.copy()

    for key in excluded_keys or []:
        query_data.pop(key, None)

    for key, value in updates.items():
        if value in (None, ""):
            query_data.pop(key, None)
        else:
            query_data[key] = value

    return query_data.urlencode()


def get_branch_compliance_status_payload(summary):
    requirement_total = summary.get("requirement_total", 0)
    missing_total = summary.get("requirement_missing_total", 0)
    expired_total = summary.get("requirement_expired_total", 0)
    expiring_soon_total = summary.get("requirement_expiring_soon_total", 0)
    compliant_total = summary.get("requirement_valid_total", 0) + summary.get("requirement_recorded_total", 0)

    if requirement_total == 0:
        return {
            "label": "No Checklist",
            "badge_class": "badge-light",
            "card_class": "metric-card",
            "help_text": "No active required checklist items configured yet.",
        }

    if missing_total or expired_total:
        return {
            "label": "Critical",
            "badge_class": "badge-danger",
            "card_class": "metric-card metric-card-danger",
            "help_text": "At least one required document is missing or expired.",
        }

    if expiring_soon_total:
        return {
            "label": "Needs Attention",
            "badge_class": "badge-warning",
            "card_class": "metric-card metric-card-warning",
            "help_text": "Required documents exist, but one or more will expire soon.",
        }

    if compliant_total >= requirement_total:
        return {
            "label": "Compliant",
            "badge_class": "badge-success",
            "card_class": "metric-card metric-card-success",
            "help_text": "All required checklist items are currently covered.",
        }

    return {
        "label": "In Review",
        "badge_class": "badge-primary",
        "card_class": "metric-card",
        "help_text": "Checklist is partially covered and should be reviewed.",
    }


def build_branch_compliance_snapshot(branch, requirements, documents):
    requirement_rows = build_requirement_rows(requirements, documents)
    summary = build_requirement_summary(requirement_rows)
    compliant_total = summary["requirement_valid_total"] + summary["requirement_recorded_total"]
    requirement_total = summary["requirement_total"]
    compliance_percentage = int(round((compliant_total / requirement_total) * 100)) if requirement_total else 0
    status_payload = get_branch_compliance_status_payload(summary)

    return {
        "branch": branch,
        "branch_id": branch.pk,
        "branch_name": branch.name,
        "branch_image_url": branch.image.url if getattr(branch, "image", None) else "",
        "company_name": branch.company.name if getattr(branch, "company_id", None) else "—",
        "employee_total": getattr(branch, "employee_total", 0),
        "document_total": getattr(branch, "document_total", 0),
        "requirement_total": requirement_total,
        "missing_total": summary["requirement_missing_total"],
        "expired_total": summary["requirement_expired_total"],
        "expiring_soon_total": summary["requirement_expiring_soon_total"],
        "compliant_total": compliant_total,
        "compliance_percentage": compliance_percentage,
        "status_label": status_payload["label"],
        "status_badge_class": status_payload["badge_class"],
        "status_card_class": status_payload["card_class"],
        "status_help_text": status_payload["help_text"],
        "detail_url": reverse("organization:branch_detail", kwargs={"pk": branch.pk}),
        "document_center_url": f'{reverse("organization:branch_document_list")}?branch={branch.pk}',
    }


def build_branch_compliance_overview(branches):
    branches = list(branches)
    branch_ids = [branch.pk for branch in branches]
    requirements = list(
        BranchDocumentRequirement.objects.filter(branch_id__in=branch_ids, is_active=True)
        .select_related("branch", "branch__company")
        .order_by("branch__company__name", "branch__name", "document_type", "title")
    )
    documents = list(
        BranchDocument.objects.filter(branch_id__in=branch_ids)
        .select_related("branch", "branch__company")
        .order_by("branch_id", "document_type", "-issue_date", "-pk")
    )

    requirements_by_branch = {}
    for requirement in requirements:
        requirements_by_branch.setdefault(requirement.branch_id, []).append(requirement)

    documents_by_branch = {}
    for document in documents:
        documents_by_branch.setdefault(document.branch_id, []).append(document)

    rows = []
    summary = {
        "branch_total": len(branches),
        "requirement_total": 0,
        "missing_total": 0,
        "expired_total": 0,
        "expiring_soon_total": 0,
        "compliant_total": 0,
        "critical_total": 0,
        "needs_attention_total": 0,
        "compliant_branch_total": 0,
        "no_checklist_total": 0,
    }

    for branch in branches:
        row = build_branch_compliance_snapshot(
            branch,
            requirements_by_branch.get(branch.pk, []),
            documents_by_branch.get(branch.pk, []),
        )
        rows.append(row)
        summary["requirement_total"] += row["requirement_total"]
        summary["missing_total"] += row["missing_total"]
        summary["expired_total"] += row["expired_total"]
        summary["expiring_soon_total"] += row["expiring_soon_total"]
        summary["compliant_total"] += row["compliant_total"]

        if row["status_label"] == "Critical":
            summary["critical_total"] += 1
        elif row["status_label"] == "Needs Attention":
            summary["needs_attention_total"] += 1
        elif row["status_label"] == "Compliant":
            summary["compliant_branch_total"] += 1
        elif row["status_label"] == "No Checklist":
            summary["no_checklist_total"] += 1

    return rows, summary


def get_supervisor_scoped_branch(user):
    if not user or not user.is_authenticated:
        return None

    if (
        not is_supervisor_user(user)
        or is_hr_user(user)
        or is_operations_manager_user(user)
        or is_admin_compatible(user)
    ):
        return None

    employee_profile = get_user_employee_profile(user)
    if not employee_profile or not employee_profile.branch_id:
        return None

    return employee_profile.branch


def can_supervisor_view_branch_detail(user, branch):
    scoped_branch = get_supervisor_scoped_branch(user)
    return bool(scoped_branch and branch and scoped_branch.pk == branch.pk)


def can_view_branch_documents(user, branch):
    return bool(
        can_manage_organization_setup(user) or can_supervisor_view_branch_detail(user, branch)
    )


def can_manage_branch_documents(user, branch):
    return bool(
        can_manage_organization_setup(user) or can_supervisor_view_branch_detail(user, branch)
    )


def can_access_branch_document_center(user):
    return bool(can_manage_organization_setup(user) or get_supervisor_scoped_branch(user))


class OrganizationAccessMixin(LoginRequiredMixin):
    permission_denied_message = "You do not have permission to access organization setup."

    def has_required_permission(self):
        return can_view_organization_setup(self.request.user)

    def get_permission_denied_message(self):
        return self.permission_denied_message

    def handle_restricted_access(self):
        messages.error(self.request, self.get_permission_denied_message())

        linked_employee = get_user_employee_profile(self.request.user)
        if linked_employee:
            return redirect("employees:employee_detail", pk=linked_employee.pk)

        raise PermissionDenied(self.get_permission_denied_message())

    def dispatch(self, request, *args, **kwargs):
        if not self.has_required_permission():
            return self.handle_restricted_access()
        return super().dispatch(request, *args, **kwargs)


class OrganizationManageAccessMixin(OrganizationAccessMixin):
    permission_denied_message = "You do not have permission to manage organization setup."

    def has_required_permission(self):
        return can_manage_organization_setup(self.request.user)


class OrganizationBaseListView(OrganizationAccessMixin, ListView):
    template_name = "organization/entity_list.html"
    context_object_name = "objects"
    paginate_by = 20
    page_title = ""
    page_subtitle = ""
    create_url = ""
    detail_url_name = ""
    update_url_name = ""
    delete_url_name = ""

    def get_queryset(self):
        return self.model.objects.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_manage = can_manage_organization_setup(self.request.user)
        list_meta = get_organization_list_meta(self.model)
        context["page_title"] = self.page_title
        context["page_subtitle"] = (
            self.page_subtitle or f"Manage {self.page_title.lower()} in your HR system."
        )
        context["create_url"] = self.create_url if can_manage else ""
        context["detail_url_name"] = self.detail_url_name
        context["update_url_name"] = self.update_url_name if can_manage else ""
        context["delete_url_name"] = self.delete_url_name if can_manage else ""
        context["can_manage_organization"] = can_manage
        context["organization_list_meta"] = list_meta
        context["organization_directory_rows"] = [
            {
                "object": current_object,
                "summary": summarize_organization_object(current_object),
            }
            for current_object in context.get("objects", [])
        ]
        return context


class OrganizationBaseCreateView(OrganizationManageAccessMixin, CreateView):
    template_name = "organization/entity_form.html"
    success_message = ""
    page_title = ""
    submit_label = "Save"
    cancel_url = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.cancel_url or self.success_url
        context["organization_form_meta"] = get_organization_form_meta(self.model)
        return context


class OrganizationBaseUpdateView(OrganizationManageAccessMixin, UpdateView):
    template_name = "organization/entity_form.html"
    success_message = ""
    page_title = ""
    submit_label = "Update"
    cancel_url = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["submit_label"] = self.submit_label
        context["cancel_url"] = self.cancel_url or self.success_url
        context["organization_form_meta"] = get_organization_form_meta(self.model)
        return context


class OrganizationBaseDeleteView(OrganizationManageAccessMixin, ProtectedDeleteMixin, DeleteView):
    template_name = "organization/entity_confirm_delete.html"
    page_title = "Delete Item"
    protected_message = (
        "You cannot delete this item because there is related data connected to this action."
    )
    cancel_url = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["cancel_url"] = self.cancel_url or self.success_url
        return context

    def get_protected_redirect_url(self):
        return self.cancel_url or self.success_url


class OrganizationBaseDetailView(OrganizationAccessMixin, DetailView):
    template_name = "organization/entity_detail.html"
    page_title = ""
    page_subtitle = ""
    edit_url_name = ""
    delete_url_name = ""
    list_url_name = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        can_manage = can_manage_organization_setup(self.request.user)
        detail_meta = get_organization_detail_meta(self.model)
        context["page_title"] = self.page_title
        context["page_subtitle"] = self.page_subtitle
        context["back_url"] = reverse(self.list_url_name) if self.list_url_name else ""
        context["edit_url"] = (
            reverse(self.edit_url_name, kwargs={"pk": self.object.pk})
            if can_manage and self.edit_url_name
            else ""
        )
        context["delete_url"] = (
            reverse(self.delete_url_name, kwargs={"pk": self.object.pk})
            if can_manage and self.delete_url_name
            else ""
        )
        context["can_manage_organization"] = can_manage
        context["object_status_label"] = status_label(getattr(self.object, "is_active", False))
        context["object_status_badge_class"] = status_badge_class(
            getattr(self.object, "is_active", False)
        )
        context["organization_detail_meta"] = detail_meta
        return context


def build_employee_rows(queryset):
    rows = []
    for employee in queryset:
        rows.append(
            [
                employee.employee_id,
                employee.full_name,
                employee.job_title.name if employee.job_title_id else "—",
                employee.branch.name if employee.branch_id else "—",
                employee.section.name if employee.section_id else "—",
                status_label(employee.is_active),
            ]
        )
    return rows


def build_simple_rows(items, *resolvers):
    rows = []
    for item in items:
        row = []
        for resolver in resolvers:
            value = resolver(item) if callable(resolver) else getattr(item, resolver, "")
            row.append(format_text(value))
        rows.append(row)
    return rows


class CompanyListView(OrganizationBaseListView):
    model = Company
    page_title = "Companies"
    page_subtitle = (
        "Manage company records and open each company to see departments, branches, and assigned employees."
    )
    create_url = reverse_lazy("organization:company_create")
    detail_url_name = "organization:company_detail"
    update_url_name = "organization:company_update"
    delete_url_name = "organization:company_delete"

    def get_queryset(self):
        return (
            Company.objects.annotate(
                branch_total=Count("branches", distinct=True),
                department_total=Count("departments", distinct=True),
                employee_total=Count("employees", distinct=True),
            )
            .all()
            .order_by("name")
        )


class CompanyDetailView(OrganizationBaseDetailView):
    model = Company
    page_title = "Company Details"
    page_subtitle = "Company structure, linked branches, departments, and employees."
    edit_url_name = "organization:company_update"
    delete_url_name = "organization:company_delete"
    list_url_name = "organization:company_list"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.object
        branches = company.branches.all().order_by("name")
        departments = company.departments.all().order_by("name")
        employees = company.employees.select_related("job_title", "branch", "section").order_by(
            "employee_id",
            "full_name",
        )

        context["record_name"] = company.name
        context["detail_items"] = [
            {"label": "Display Name", "value": company.name},
            {"label": "Legal Name", "value": format_text(company.legal_name)},
            {"label": "Email", "value": format_text(getattr(company, "email", ""))},
            {"label": "Phone", "value": format_text(getattr(company, "phone", ""))},
            {"label": "Address", "value": format_text(getattr(company, "address", ""))},
            {"label": "Notes", "value": format_text(company.notes)},
        ]
        context["stat_cards"] = [
            {
                "label": "Branches",
                "value": branches.count(),
                "help_text": "Active and inactive company branches.",
            },
            {
                "label": "Departments",
                "value": departments.count(),
                "help_text": "Departments under this company.",
            },
            {
                "label": "Employees",
                "value": employees.count(),
                "help_text": "Employees assigned to this company.",
            },
        ]
        context["related_blocks"] = [
            {
                "title": "Branches",
                "subtitle": "All branch records linked to this company.",
                "columns": ["Branch", "City", "Email", "Status"],
                "rows": build_simple_rows(
                    branches,
                    lambda branch: branch.name,
                    lambda branch: getattr(branch, "city", ""),
                    lambda branch: getattr(branch, "email", ""),
                    lambda branch: status_label(branch.is_active),
                ),
                "empty_message": "No branches are linked to this company yet.",
            },
            {
                "title": "Departments",
                "subtitle": "Departments configured under this company.",
                "columns": ["Department", "Code", "Manager", "Status"],
                "rows": build_simple_rows(
                    departments,
                    lambda department: department.name,
                    lambda department: getattr(department, "code", ""),
                    lambda department: getattr(department, "manager_name", ""),
                    lambda department: status_label(department.is_active),
                ),
                "empty_message": "No departments are linked to this company yet.",
            },
            {
                "title": "Employees",
                "subtitle": "Employees currently assigned to this company.",
                "columns": [
                    "Employee ID",
                    "Employee",
                    "Job Title",
                    "Branch",
                    "Section",
                    "Status",
                ],
                "rows": build_employee_rows(employees),
                "empty_message": "No employees are assigned to this company yet.",
            },
        ]
        return context


class CompanyCreateView(OrganizationBaseCreateView):
    model = Company
    form_class = CompanyForm
    page_title = "Create Company"
    success_url = reverse_lazy("organization:company_list")
    success_message = "Company created successfully."
    cancel_url = reverse_lazy("organization:company_list")


class CompanyUpdateView(OrganizationBaseUpdateView):
    model = Company
    form_class = CompanyForm
    page_title = "Update Company"
    success_url = reverse_lazy("organization:company_list")
    success_message = "Company updated successfully."
    cancel_url = reverse_lazy("organization:company_list")


class CompanyDeleteView(OrganizationBaseDeleteView):
    model = Company
    page_title = "Delete Company"
    success_url = reverse_lazy("organization:company_list")
    cancel_url = reverse_lazy("organization:company_list")


class BranchListView(OrganizationBaseListView):
    model = Branch
    page_title = "Branches"
    page_subtitle = (
        "Review each branch with live compliance health, linked team placement, and direct access to branch detail and branch documents."
    )
    create_url = reverse_lazy("organization:branch_create")
    detail_url_name = "organization:branch_detail"
    update_url_name = "organization:branch_update"
    delete_url_name = "organization:branch_delete"

    STATUS_FILTER_CHOICES = {
        "": "All Statuses",
        "compliant": "Compliant",
        "needs_attention": "Needs Attention",
        "critical": "Critical",
        "no_checklist": "No Checklist",
    }

    def get_queryset(self):
        queryset = (
            Branch.objects.select_related("company")
            .annotate(
                employee_total=Count("employees", distinct=True),
                document_total=Count("documents", distinct=True),
            )
            .order_by("company__name", "name")
        )

        company_value = (self.request.GET.get("company") or "").strip()
        if company_value.isdigit():
            queryset = queryset.filter(company_id=int(company_value))

        return queryset

    def _apply_branch_compliance_filters(self, rows):
        status_filter = (self.request.GET.get("status") or "").strip()
        issue_filter = (self.request.GET.get("issue") or "").strip()
        search_query = (self.request.GET.get("q") or "").strip().lower()

        filtered_rows = rows

        if status_filter == "compliant":
            filtered_rows = [row for row in filtered_rows if row["status_label"] == "Compliant"]
        elif status_filter == "needs_attention":
            filtered_rows = [row for row in filtered_rows if row["status_label"] == "Needs Attention"]
        elif status_filter == "critical":
            filtered_rows = [row for row in filtered_rows if row["status_label"] == "Critical"]
        elif status_filter == "no_checklist":
            filtered_rows = [row for row in filtered_rows if row["status_label"] == "No Checklist"]

        if issue_filter == "missing":
            filtered_rows = [row for row in filtered_rows if row["missing_total"] > 0]
        elif issue_filter == "expired":
            filtered_rows = [row for row in filtered_rows if row["expired_total"] > 0]
        elif issue_filter == "expiring_soon":
            filtered_rows = [row for row in filtered_rows if row["expiring_soon_total"] > 0]
        elif issue_filter == "with_checklist":
            filtered_rows = [row for row in filtered_rows if row["requirement_total"] > 0]

        if search_query:
            filtered_rows = [
                row
                for row in filtered_rows
                if search_query in row["branch_name"].lower()
                or search_query in row["company_name"].lower()
            ]

        return filtered_rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        object_list = list(context["page_obj"].object_list) if context.get("page_obj") else list(context["objects"])
        compliance_rows, compliance_summary = build_branch_compliance_overview(object_list)
        filtered_rows = self._apply_branch_compliance_filters(compliance_rows)
        filtered_summary = {
            "branch_total": len(filtered_rows),
            "requirement_total": sum(row["requirement_total"] for row in filtered_rows),
            "missing_total": sum(row["missing_total"] for row in filtered_rows),
            "expired_total": sum(row["expired_total"] for row in filtered_rows),
            "expiring_soon_total": sum(row["expiring_soon_total"] for row in filtered_rows),
            "compliant_total": sum(row["compliant_total"] for row in filtered_rows),
            "critical_total": sum(1 for row in filtered_rows if row["status_label"] == "Critical"),
            "needs_attention_total": sum(1 for row in filtered_rows if row["status_label"] == "Needs Attention"),
            "compliant_branch_total": sum(1 for row in filtered_rows if row["status_label"] == "Compliant"),
            "no_checklist_total": sum(1 for row in filtered_rows if row["status_label"] == "No Checklist"),
        }
        selected_company = (self.request.GET.get("company") or "").strip()
        selected_status = (self.request.GET.get("status") or "").strip()
        selected_issue = (self.request.GET.get("issue") or "").strip()
        search_query = (self.request.GET.get("q") or "").strip()

        context["organization_list_variant"] = "branch_compliance_overview"
        context["branch_compliance_rows"] = filtered_rows
        context["branch_compliance_summary"] = filtered_summary
        context["branch_compliance_unfiltered_summary"] = compliance_summary
        context["branch_company_choices"] = Company.objects.order_by("name").values("id", "name")
        context["branch_filter_values"] = {
            "company": selected_company,
            "status": selected_status,
            "issue": selected_issue,
            "q": search_query,
        }
        context["branch_status_choices"] = [
            {"value": value, "label": label}
            for value, label in self.STATUS_FILTER_CHOICES.items()
        ]
        context["branch_issue_choices"] = [
            {"value": "", "label": "All Checklist Issues"},
            {"value": "missing", "label": "Missing Only"},
            {"value": "expired", "label": "Expired Only"},
            {"value": "expiring_soon", "label": "Expiring Soon Only"},
            {"value": "with_checklist", "label": "With Checklist Only"},
        ]
        context["branch_filters_applied"] = bool(selected_company or selected_status or selected_issue or search_query)
        context["stat_cards"] = [
            {
                "label": "Branches Shown",
                "value": filtered_summary["branch_total"],
                "help_text": "Branch records shown after the current filters are applied.",
                "card_class": "metric-card",
            },
            {
                "label": "Compliant",
                "value": filtered_summary["compliant_branch_total"],
                "help_text": "Branches with all required checklist items covered.",
                "card_class": "metric-card metric-card-success",
            },
            {
                "label": "Needs Attention",
                "value": filtered_summary["needs_attention_total"],
                "help_text": "Branches with required documents expiring soon.",
                "card_class": "metric-card metric-card-warning",
            },
            {
                "label": "Critical",
                "value": filtered_summary["critical_total"],
                "help_text": "Branches with missing or expired required documents.",
                "card_class": "metric-card metric-card-danger",
            },
        ]
        return context


class BranchDetailView(OrganizationBaseDetailView):
    model = Branch
    page_title = "Branch Details"
    page_subtitle = (
        "Branch information, linked employees, working team inside this branch, and branch store documents."
    )
    edit_url_name = "organization:branch_update"
    delete_url_name = "organization:branch_delete"
    list_url_name = "organization:branch_list"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if can_supervisor_view_branch_detail(request.user, self.object):
            return DetailView.dispatch(self, request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return Branch.objects.select_related("company")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = self.object
        employees = branch.employees.select_related("department", "section", "job_title").order_by(
            "job_title__name",
            "employee_id",
            "full_name",
        )
        department_ids = list(employees.values_list("department_id", flat=True).distinct())
        section_ids = list(employees.values_list("section_id", flat=True).distinct())
        departments = Department.objects.filter(pk__in=department_ids).order_by("name")
        sections = (
            Section.objects.filter(pk__in=section_ids)
            .select_related("department")
            .order_by("department__name", "name")
        )
        branch_documents = list(
            branch.documents.select_related("branch", "branch__company").all().order_by(
                "document_type",
                "-created_at",
                "-id",
            )
        )
        branch_requirements = list(
            BranchDocumentRequirement.objects.filter(branch=branch).order_by(
                "-is_mandatory",
                "document_type",
                "title",
                "id",
            )
        )
        branch_requirement_rows = build_requirement_rows(branch_requirements, branch_documents)
        branch_requirement_summary = build_requirement_summary(branch_requirement_rows)
        required_checklist_total = sum(
            1 for row in branch_requirement_rows if row["is_mandatory"]
        )
        missing_required_total = sum(
            1
            for row in branch_requirement_rows
            if row["is_mandatory"] and row["state_key"] == "missing"
        )
        expired_required_total = sum(
            1
            for row in branch_requirement_rows
            if row["is_mandatory"] and row["state_key"] == "expired"
        )
        expiring_soon_required_total = sum(
            1
            for row in branch_requirement_rows
            if row["is_mandatory"] and row["state_key"] == "expiring_soon"
        )
        compliant_required_total = sum(
            1
            for row in branch_requirement_rows
            if row["is_mandatory"] and row["state_key"] in {"valid", "recorded"}
        )

        context["record_name"] = branch.name
        context["detail_items"] = [
            {"label": "Branch", "value": branch.name},
            {"label": "Company", "value": branch.company.name},
            {"label": "City", "value": format_text(getattr(branch, "city", ""))},
            {"label": "Email", "value": format_text(getattr(branch, "email", ""))},
            {
                "label": "Attendance Point",
                "value": (
                    f"{branch.attendance_latitude}, {branch.attendance_longitude}"
                    if branch.has_attendance_location_config
                    else "Not configured"
                ),
            },
            {
                "label": "Attendance Radius",
                "value": (
                    f"{branch.attendance_radius_meters} meters"
                    if branch.has_attendance_location_config
                    else "Not configured"
                ),
            },
            {"label": "Notes", "value": format_text(branch.notes)},
        ]
        context["stat_cards"] = [
            {
                "label": "Employees",
                "value": employees.count(),
                "help_text": "Employees assigned to this branch.",
            },
            {
                "label": "Departments Used",
                "value": len(department_ids),
                "help_text": "Departments represented by branch staff.",
            },
            {
                "label": "Sections Used",
                "value": len([pk for pk in section_ids if pk]),
                "help_text": "Sections represented by branch staff.",
            },
            {
                "label": "Store Files",
                "value": len(branch_documents),
                "help_text": "Branch-specific legal and store compliance files.",
            },
        ]
        context["related_blocks"] = [
            {
                "title": "Branch Team",
                "subtitle": "Employees working in this branch.",
                "columns": [
                    "Employee ID",
                    "Employee",
                    "Job Title",
                    "Department",
                    "Section",
                    "Status",
                ],
                "rows": [
                    [
                        employee.employee_id,
                        employee.full_name,
                        employee.job_title.name if employee.job_title_id else "—",
                        employee.department.name if employee.department_id else "—",
                        employee.section.name if employee.section_id else "—",
                        status_label(employee.is_active),
                    ]
                    for employee in employees
                ],
                "empty_message": "No employees are assigned to this branch yet.",
            },
            {
                "title": "Departments Represented",
                "subtitle": "Departments currently represented inside this branch.",
                "columns": ["Department", "Company", "Manager", "Status"],
                "rows": build_simple_rows(
                    departments,
                    lambda department: department.name,
                    lambda department: department.company.name,
                    lambda department: getattr(department, "manager_name", ""),
                    lambda department: status_label(department.is_active),
                ),
                "empty_message": "No departments are represented in this branch yet.",
            },
            {
                "title": "Sections Represented",
                "subtitle": "Sections that currently have employees in this branch.",
                "columns": ["Section", "Department", "Supervisor", "Status"],
                "rows": build_simple_rows(
                    sections,
                    lambda section: section.name,
                    lambda section: section.department.name,
                    lambda section: getattr(section, "supervisor_name", ""),
                    lambda section: status_label(section.is_active),
                ),
                "empty_message": "No sections are represented in this branch yet.",
            },
        ]
        context["can_manage_branch_documents"] = can_manage_branch_documents(
            self.request.user,
            branch,
        )
        context["can_view_branch_documents"] = can_view_branch_documents(
            self.request.user,
            branch,
        )
        context["branch_document_form"] = kwargs.get("branch_document_form") or BranchDocumentForm()
        context["branch_documents"] = branch_documents
        context["branch_documents_required_count"] = sum(
            1 for document in branch_documents if document.is_required
        )
        context["branch_documents_expired_count"] = sum(
            1 for document in branch_documents if document.is_expired
        )
        context["branch_documents_expiring_soon_count"] = sum(
            1 for document in branch_documents if document.is_expiring_soon
        )
        context["branch_document_total"] = len(branch_documents)
        context["branch_detail_has_document_workspace"] = bool(
            branch_documents or context["can_manage_branch_documents"]
        )
        context["branch_requirement_rows"] = branch_requirement_rows
        context["branch_requirement_total"] = len(branch_requirement_rows)
        context["branch_required_checklist_total"] = required_checklist_total
        context["branch_missing_required_total"] = missing_required_total
        context["branch_expired_required_total"] = expired_required_total
        context["branch_expiring_soon_required_total"] = expiring_soon_required_total
        context["branch_compliant_required_total"] = compliant_required_total
        context["branch_requirement_valid_total"] = (
            branch_requirement_summary["requirement_valid_total"]
            + branch_requirement_summary["requirement_recorded_total"]
        )
        context["branch_compliance_completion_percent"] = (
            int(round((compliant_required_total / required_checklist_total) * 100))
            if required_checklist_total
            else 0
        )
        context["branch_compliance_summary_cards"] = [
            {
                "label": "Required Checklist",
                "value": required_checklist_total,
                "help_text": "Mandatory compliance items configured for this branch.",
                "tone": "default",
            },
            {
                "label": "Missing",
                "value": missing_required_total,
                "help_text": "Required items with no uploaded document.",
                "tone": "danger" if missing_required_total else "success",
            },
            {
                "label": "Expired",
                "value": expired_required_total,
                "help_text": "Required items that are already expired.",
                "tone": "danger" if expired_required_total else "success",
            },
            {
                "label": "Expiring Soon",
                "value": expiring_soon_required_total,
                "help_text": "Required items approaching expiry soon.",
                "tone": "warning" if expiring_soon_required_total else "success",
            },
            {
                "label": "Compliant",
                "value": compliant_required_total,
                "help_text": "Required items currently valid or recorded without expiry.",
                "tone": "success" if compliant_required_total else "default",
            },
        ]
        return context



class BranchDocumentListView(LoginRequiredMixin, ListView):
    model = BranchDocument
    template_name = "organization/branch_document_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def dispatch(self, request, *args, **kwargs):
        if not can_access_branch_document_center(request.user):
            messages.error(
                request,
                "You do not have permission to access branch documents.",
            )
            linked_employee = get_user_employee_profile(request.user)
            if linked_employee:
                return redirect("employees:employee_detail", pk=linked_employee.pk)
            raise PermissionDenied("You do not have permission to access branch documents.")
        return super().dispatch(request, *args, **kwargs)

    def get_scope_branch(self):
        return get_supervisor_scoped_branch(self.request.user)

    def get_branch_picker_search_value(self):
        return (self.request.GET.get("branch_search") or "").strip()

    def get_selected_branch_id(self):
        scoped_branch = self.get_scope_branch()
        if scoped_branch:
            return str(scoped_branch.pk)
        return (self.request.GET.get("branch") or "").strip()

    def should_open_branch_workspace(self):
        scoped_branch = self.get_scope_branch()
        if scoped_branch:
            return True
        return (self.request.GET.get("workspace") or "").strip() == "1"

    def get_branch_picker_queryset(self):
        scoped_branch = self.get_scope_branch()
        queryset = (
            Branch.objects.select_related("company")
            .annotate(
                employee_total=Count("employees", distinct=True),
                document_total=Count("documents", distinct=True),
            )
            .order_by("company__name", "name")
        )

        if scoped_branch:
            return queryset.filter(pk=scoped_branch.pk)

        branch_search_value = self.get_branch_picker_search_value()
        if branch_search_value:
            queryset = queryset.filter(
                Q(name__icontains=branch_search_value)
                | Q(company__name__icontains=branch_search_value)
                | Q(code__icontains=branch_search_value)
                | Q(manager_name__icontains=branch_search_value)
            )

        return queryset

    def get_queryset(self):
        queryset = (
            BranchDocument.objects.select_related("branch", "branch__company")
            .all()
            .order_by("branch__company__name", "branch__name", "-created_at", "-id")
        )

        scoped_branch = self.get_scope_branch()
        if scoped_branch:
            queryset = queryset.filter(branch_id=scoped_branch.pk)

        branch_id = self.get_selected_branch_id()
        document_type = (self.request.GET.get("document_type") or "").strip()
        status_filter = (self.request.GET.get("status") or "").strip()
        search_value = (self.request.GET.get("search") or "").strip()

        if not branch_id and not scoped_branch:
            return queryset.none()

        if not self.should_open_branch_workspace() and not scoped_branch:
            return queryset.none()

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if document_type:
            queryset = queryset.filter(document_type=document_type)

        today = timezone.localdate()
        if status_filter == "expired":
            queryset = queryset.filter(expiry_date__lt=today)
        elif status_filter == "expiring_soon":
            queryset = queryset.filter(
                expiry_date__gte=today,
                expiry_date__lte=today + timedelta(days=30),
            )
        elif status_filter == "valid":
            queryset = queryset.filter(expiry_date__gt=today)
        elif status_filter == "no_expiry":
            queryset = queryset.filter(expiry_date__isnull=True)
        elif status_filter == "required":
            queryset = queryset.filter(is_required=True)

        if search_value:
            queryset = queryset.filter(
                Q(title__icontains=search_value)
                | Q(reference_number__icontains=search_value)
                | Q(description__icontains=search_value)
                | Q(uploaded_by__icontains=search_value)
                | Q(branch__name__icontains=search_value)
                | Q(branch__company__name__icontains=search_value)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        current_user = self.request.user
        scoped_branch = self.get_scope_branch()
        is_branch_scoped_supervisor = scoped_branch is not None

        filtered_documents = list(
            context["page_obj"].object_list if context.get("page_obj") else context["documents"]
        )

        all_documents_queryset = BranchDocument.objects.select_related("branch", "branch__company")
        if is_branch_scoped_supervisor:
            all_documents_queryset = all_documents_queryset.filter(branch_id=scoped_branch.pk)
        all_documents = list(all_documents_queryset)

        branch_choices = (
            Branch.objects.filter(pk=scoped_branch.pk).select_related("company").order_by("company__name", "name")
            if is_branch_scoped_supervisor
            else Branch.objects.select_related("company").order_by("company__name", "name")
        )
        branch_picker_queryset = self.get_branch_picker_queryset()
        branch_picker_paginator = Paginator(branch_picker_queryset, 6)
        branch_picker_page = branch_picker_paginator.get_page(
            (self.request.GET.get("branch_page") or "").strip() or 1
        )
        branch_picker_results = list(branch_picker_page.object_list)

        branch_id = self.get_selected_branch_id()
        document_type = (self.request.GET.get("document_type") or "").strip()
        status_filter = (self.request.GET.get("status") or "").strip()
        search_value = (self.request.GET.get("search") or "").strip()
        branch_search_value = self.get_branch_picker_search_value()

        branch_workspace_is_selected = self.should_open_branch_workspace() and bool(branch_id)

        upload_branch = None
        if branch_workspace_is_selected:
            upload_branch = Branch.objects.select_related("company").filter(pk=branch_id).first()
        if is_branch_scoped_supervisor and scoped_branch:
            upload_branch = scoped_branch
            branch_workspace_is_selected = True

        branch_document_form = kwargs.get("branch_document_form") or BranchDocumentForm()
        requirement_form = kwargs.get("branch_document_requirement_form") or BranchDocumentRequirementForm()

        requirements_queryset = BranchDocumentRequirement.objects.select_related("branch", "branch__company").filter(is_active=True)
        if is_branch_scoped_supervisor and scoped_branch:
            requirements_queryset = requirements_queryset.filter(branch_id=scoped_branch.pk)
        elif upload_branch:
            requirements_queryset = requirements_queryset.filter(branch_id=upload_branch.pk)

        active_requirements = list(
            requirements_queryset.order_by("branch__company__name", "branch__name", "document_type", "title")
        )

        requirement_rows = []
        requirement_summary = build_requirement_summary(requirement_rows)
        requirement_branch = upload_branch or scoped_branch
        if requirement_branch:
            branch_requirements = [item for item in active_requirements if item.branch_id == requirement_branch.pk]
            branch_documents = [document for document in all_documents if document.branch_id == requirement_branch.pk]
            requirement_rows = build_requirement_rows(branch_requirements, branch_documents)
            requirement_summary = build_requirement_summary(requirement_rows)

        context["page_title"] = (
            "My Branch Documents"
            if is_branch_scoped_supervisor
            else "Branch Documents Center"
        )
        context["page_subtitle"] = (
            "Submit and monitor official documents for your assigned branch. Operations and Admin can track expiry and renewal from the same records."
            if is_branch_scoped_supervisor
            else "Upload and monitor store licenses, legal documents, permits, lease files, and other important branch records across all branches."
        )
        context["branch_choices"] = branch_choices
        context["branch_picker_results"] = branch_picker_results
        context["branch_picker_page"] = branch_picker_page
        context["branch_picker_paginator"] = branch_picker_paginator
        context["branch_picker_pagination_items"] = build_numbered_pagination_items(branch_picker_page)
        context["branch_picker_search_value"] = branch_search_value
        context["branch_picker_search_querystring"] = build_updated_querystring(
            self.request,
            excluded_keys=["branch_search", "branch_page"],
        )
        context["branch_picker_page_querystring"] = build_updated_querystring(
            self.request,
            excluded_keys=["branch_page"],
        )
        context["branch_picker_select_querystring"] = build_updated_querystring(
            self.request,
            excluded_keys=["branch", "page", "workspace"],
        )
        context["document_registry_querystring"] = build_updated_querystring(
            self.request,
            excluded_keys=["page"],
        )
        context["document_type_choices"] = BranchDocument.DOCUMENT_TYPE_CHOICES
        context["selected_branch"] = branch_id if branch_workspace_is_selected else ""
        context["selected_document_type"] = document_type
        context["selected_status"] = status_filter
        context["search_value"] = search_value
        context["status_choices"] = [
            ("", "All statuses"),
            ("expired", "Expired"),
            ("expiring_soon", "Expiring Soon"),
            ("valid", "Valid"),
            ("no_expiry", "No Expiry Date"),
            ("required", "Required Only"),
        ]
        context["document_rows"] = build_branch_document_rows(filtered_documents)
        context["all_document_total"] = len(all_documents)
        context["filtered_document_total"] = self.get_queryset().count()
        context["required_document_total"] = sum(1 for document in all_documents if document.is_required)
        context["expired_document_total"] = sum(1 for document in all_documents if document.is_expired)
        context["expiring_soon_document_total"] = sum(1 for document in all_documents if document.is_expiring_soon)
        context["valid_document_total"] = sum(
            1
            for document in all_documents
            if document.expiry_date
            and not document.is_expired
            and not document.is_expiring_soon
        )
        context["branch_document_form"] = branch_document_form
        context["branch_document_requirement_form"] = requirement_form
        context["upload_branch"] = upload_branch
        context["branch_workspace_is_selected"] = branch_workspace_is_selected
        context["branch_document_create_url"] = (
            reverse("organization:branch_document_create", kwargs={"pk": upload_branch.pk})
            if upload_branch
            else ""
        )
        context["branch_document_requirement_create_url"] = (
            reverse("organization:branch_document_requirement_create", kwargs={"pk": upload_branch.pk})
            if upload_branch and can_manage_organization_setup(current_user)
            else ""
        )
        context["branch_document_return_url"] = self.request.get_full_path()
        context["can_manage_organization"] = can_manage_organization_setup(current_user)
        context["is_branch_scoped_supervisor"] = is_branch_scoped_supervisor
        context["scoped_branch"] = scoped_branch
        context["requirement_rows"] = requirement_rows
        context["requirement_total"] = requirement_summary["requirement_total"]
        context["requirement_missing_total"] = requirement_summary["requirement_missing_total"]
        context["requirement_expired_total"] = requirement_summary["requirement_expired_total"]
        context["requirement_expiring_soon_total"] = requirement_summary["requirement_expiring_soon_total"]
        context["requirement_valid_total"] = (
            requirement_summary["requirement_valid_total"] + requirement_summary["requirement_recorded_total"]
        )
        return context


class BranchCreateView(OrganizationBaseCreateView):
    model = Branch
    form_class = BranchForm
    page_title = "Create Branch"
    success_url = reverse_lazy("organization:branch_list")
    success_message = "Branch created successfully."
    cancel_url = reverse_lazy("organization:branch_list")


class BranchUpdateView(OrganizationBaseUpdateView):
    model = Branch
    form_class = BranchForm
    page_title = "Update Branch"
    success_url = reverse_lazy("organization:branch_list")
    success_message = "Branch updated successfully."
    cancel_url = reverse_lazy("organization:branch_list")


class BranchDeleteView(OrganizationBaseDeleteView):
    model = Branch
    page_title = "Delete Branch"
    success_url = reverse_lazy("organization:branch_list")
    cancel_url = reverse_lazy("organization:branch_list")


class DepartmentListView(OrganizationBaseListView):
    model = Department
    page_title = "Departments"
    page_subtitle = "Review departments, linked sections, configured roles, and assigned employees."
    create_url = reverse_lazy("organization:department_create")
    detail_url_name = "organization:department_detail"
    update_url_name = "organization:department_update"
    delete_url_name = "organization:department_delete"

    def get_queryset(self):
        return (
            Department.objects.select_related("company")
            .annotate(
                section_total=Count("sections", distinct=True),
                job_title_total=Count("job_titles", distinct=True),
                employee_total=Count("employees", distinct=True),
            )
            .order_by("company__name", "name")
        )


class DepartmentDetailView(OrganizationBaseDetailView):
    model = Department
    page_title = "Department Details"
    page_subtitle = "Department information, linked sections, configured job titles, and assigned employees."
    edit_url_name = "organization:department_update"
    delete_url_name = "organization:department_delete"
    list_url_name = "organization:department_list"

    def get_queryset(self):
        return Department.objects.select_related("company", "branch")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        department = self.object
        sections = department.sections.all().order_by("name")
        job_titles = department.job_titles.select_related("section").order_by("name")
        employees = department.employees.select_related("branch", "section", "job_title").order_by(
            "employee_id",
            "full_name",
        )

        context["record_name"] = department.name
        context["detail_items"] = [
            {"label": "Department", "value": department.name},
            {"label": "Company", "value": department.company.name},
            {"label": "Code", "value": format_text(department.code)},
            {"label": "Manager", "value": format_text(department.manager_name)},
            {
                "label": "Legacy Branch",
                "value": format_text(getattr(getattr(department, "branch", None), "name", "")),
            },
            {"label": "Notes", "value": format_text(department.notes)},
        ]
        context["stat_cards"] = [
            {"label": "Sections", "value": sections.count(), "help_text": "Sections linked to this department."},
            {"label": "Job Titles", "value": job_titles.count(), "help_text": "Titles configured under this department."},
            {"label": "Employees", "value": employees.count(), "help_text": "Employees assigned to this department."},
        ]
        context["related_blocks"] = [
            {
                "title": "Sections",
                "subtitle": "Sections configured under this department.",
                "columns": ["Section", "Code", "Supervisor", "Status"],
                "rows": build_simple_rows(
                    sections,
                    lambda section: section.name,
                    lambda section: getattr(section, "code", ""),
                    lambda section: getattr(section, "supervisor_name", ""),
                    lambda section: status_label(section.is_active),
                ),
                "empty_message": "No sections are linked to this department yet.",
            },
            {
                "title": "Job Titles",
                "subtitle": "Job titles configured under this department.",
                "columns": ["Job Title", "Section", "Code", "Status"],
                "rows": build_simple_rows(
                    job_titles,
                    lambda title: title.name,
                    lambda title: getattr(getattr(title, "section", None), "name", ""),
                    lambda title: getattr(title, "code", ""),
                    lambda title: status_label(title.is_active),
                ),
                "empty_message": "No job titles are linked to this department yet.",
            },
            {
                "title": "Employees",
                "subtitle": "Employees currently assigned to this department.",
                "columns": ["Employee ID", "Employee", "Job Title", "Branch", "Section", "Status"],
                "rows": build_employee_rows(employees),
                "empty_message": "No employees are assigned to this department yet.",
            },
        ]
        return context


class DepartmentCreateView(OrganizationBaseCreateView):
    model = Department
    form_class = DepartmentForm
    page_title = "Create Department"
    success_url = reverse_lazy("organization:department_list")
    success_message = "Department created successfully."
    cancel_url = reverse_lazy("organization:department_list")


class DepartmentUpdateView(OrganizationBaseUpdateView):
    model = Department
    form_class = DepartmentForm
    page_title = "Update Department"
    success_url = reverse_lazy("organization:department_list")
    success_message = "Department updated successfully."
    cancel_url = reverse_lazy("organization:department_list")


class DepartmentDeleteView(OrganizationBaseDeleteView):
    model = Department
    page_title = "Delete Department"
    success_url = reverse_lazy("organization:department_list")
    cancel_url = reverse_lazy("organization:department_list")


class SectionListView(OrganizationBaseListView):
    model = Section
    page_title = "Sections"
    page_subtitle = "Review sections, related job titles, and assigned employees."
    create_url = reverse_lazy("organization:section_create")
    detail_url_name = "organization:section_detail"
    update_url_name = "organization:section_update"
    delete_url_name = "organization:section_delete"

    def get_queryset(self):
        return (
            Section.objects.select_related("department", "department__company")
            .annotate(
                job_title_total=Count("job_titles", distinct=True),
                employee_total=Count("employees", distinct=True),
            )
            .order_by("department__company__name", "department__name", "name")
        )


class SectionDetailView(OrganizationBaseDetailView):
    model = Section
    page_title = "Section Details"
    page_subtitle = "Section information, linked job titles, and assigned employees."
    edit_url_name = "organization:section_update"
    delete_url_name = "organization:section_delete"
    list_url_name = "organization:section_list"

    def get_queryset(self):
        return Section.objects.select_related("department", "department__company")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        section = self.object
        job_titles = section.job_titles.all().order_by("name")
        employees = section.employees.select_related("branch", "department", "job_title").order_by(
            "employee_id",
            "full_name",
        )

        context["record_name"] = section.name
        context["detail_items"] = [
            {"label": "Section", "value": section.name},
            {"label": "Department", "value": section.department.name},
            {"label": "Company", "value": section.department.company.name},
            {"label": "Code", "value": format_text(section.code)},
            {"label": "Supervisor", "value": format_text(section.supervisor_name)},
            {"label": "Notes", "value": format_text(section.notes)},
        ]
        context["stat_cards"] = [
            {"label": "Job Titles", "value": job_titles.count(), "help_text": "Titles configured in this section."},
            {"label": "Employees", "value": employees.count(), "help_text": "Employees assigned to this section."},
        ]
        context["related_blocks"] = [
            {
                "title": "Job Titles",
                "subtitle": "Roles configured in this section.",
                "columns": ["Job Title", "Department", "Code", "Status"],
                "rows": build_simple_rows(
                    job_titles,
                    lambda title: title.name,
                    lambda title: title.department.name,
                    lambda title: getattr(title, "code", ""),
                    lambda title: status_label(title.is_active),
                ),
                "empty_message": "No job titles are linked to this section yet.",
            },
            {
                "title": "Employees",
                "subtitle": "Employees currently assigned to this section.",
                "columns": ["Employee ID", "Employee", "Job Title", "Branch", "Section", "Status"],
                "rows": build_employee_rows(employees),
                "empty_message": "No employees are assigned to this section yet.",
            },
        ]
        return context


class SectionCreateView(OrganizationBaseCreateView):
    model = Section
    form_class = SectionForm
    page_title = "Create Section"
    success_url = reverse_lazy("organization:section_list")
    success_message = "Section created successfully."
    cancel_url = reverse_lazy("organization:section_list")


class SectionUpdateView(OrganizationBaseUpdateView):
    model = Section
    form_class = SectionForm
    page_title = "Update Section"
    success_url = reverse_lazy("organization:section_list")
    success_message = "Section updated successfully."
    cancel_url = reverse_lazy("organization:section_list")


class SectionDeleteView(OrganizationBaseDeleteView):
    model = Section
    page_title = "Delete Section"
    success_url = reverse_lazy("organization:section_list")
    cancel_url = reverse_lazy("organization:section_list")


class JobTitleListView(OrganizationBaseListView):
    model = JobTitle
    page_title = "Job Titles"
    page_subtitle = "Review configured titles, their linked section placement, and assigned employees."
    create_url = reverse_lazy("organization:jobtitle_create")
    detail_url_name = "organization:jobtitle_detail"
    update_url_name = "organization:jobtitle_update"
    delete_url_name = "organization:jobtitle_delete"

    def get_queryset(self):
        return (
            JobTitle.objects.select_related("department", "section", "section__department", "section__department__company")
            .annotate(employee_total=Count("employees", distinct=True))
            .order_by("section__department__company__name", "section__department__name", "section__name", "name")
        )


class JobTitleDetailView(OrganizationBaseDetailView):
    model = JobTitle
    page_title = "Job Title Details"
    page_subtitle = "Job title information, related section placement, and assigned employees."
    edit_url_name = "organization:jobtitle_update"
    delete_url_name = "organization:jobtitle_delete"
    list_url_name = "organization:jobtitle_list"

    def get_queryset(self):
        return JobTitle.objects.select_related("department", "section", "section__department", "section__department__company")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object
        employees = role.employees.select_related("branch", "section").order_by("employee_id", "full_name")
        peer_titles = JobTitle.objects.filter(section=role.section).exclude(pk=role.pk).order_by("name") if role.section_id else JobTitle.objects.none()

        context["record_name"] = role.name
        context["detail_items"] = [
            {"label": "Job Title", "value": role.name},
            {"label": "Department", "value": role.department.name},
            {"label": "Section", "value": format_text(getattr(getattr(role, "section", None), "name", ""))},
            {"label": "Code", "value": format_text(role.code)},
            {"label": "Notes", "value": format_text(role.notes)},
        ]
        context["stat_cards"] = [
            {"label": "Employees", "value": employees.count(), "help_text": "Employees assigned to this title."},
            {"label": "Peer Titles", "value": peer_titles.count(), "help_text": "Other titles configured in the same section."},
        ]
        context["related_blocks"] = [
            {
                "title": "Assigned Employees",
                "subtitle": "Employees currently holding this title.",
                "columns": ["Employee ID", "Employee", "Job Title", "Branch", "Section", "Status"],
                "rows": build_employee_rows(employees),
                "empty_message": "No employees are assigned to this title yet.",
            },
            {
                "title": "Same Section Roles",
                "subtitle": "Other job titles configured inside the same section.",
                "columns": ["Job Title", "Department", "Section", "Status"],
                "rows": build_simple_rows(
                    peer_titles,
                    lambda current_role: current_role.name,
                    lambda current_role: current_role.department.name,
                    lambda current_role: getattr(getattr(current_role, "section", None), "name", ""),
                    lambda current_role: status_label(current_role.is_active),
                ),
                "empty_message": "No other job titles exist in this section yet.",
            },
        ]
        return context


class JobTitleCreateView(OrganizationBaseCreateView):
    model = JobTitle
    form_class = JobTitleForm
    page_title = "Create Job Title"
    success_url = reverse_lazy("organization:jobtitle_list")
    success_message = "Job title created successfully."
    cancel_url = reverse_lazy("organization:jobtitle_list")


class JobTitleUpdateView(OrganizationBaseUpdateView):
    model = JobTitle
    form_class = JobTitleForm
    page_title = "Update Job Title"
    success_url = reverse_lazy("organization:jobtitle_list")
    success_message = "Job title updated successfully."
    cancel_url = reverse_lazy("organization:jobtitle_list")


class JobTitleDeleteView(OrganizationBaseDeleteView):
    model = JobTitle
    page_title = "Delete Job Title"
    success_url = reverse_lazy("organization:jobtitle_list")
    cancel_url = reverse_lazy("organization:jobtitle_list")



@login_required
@require_POST
def branch_document_requirement_create(request, pk):
    next_url = (request.POST.get("next") or "").strip()
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=pk)

    if not can_manage_organization_setup(request.user):
        messages.error(request, "You do not have permission to manage branch document requirements.")
        if next_url:
            return redirect(next_url)
        return redirect("organization:branch_document_list")

    form = BranchDocumentRequirementForm(request.POST)
    if form.is_valid():
        requirement = form.save(commit=False)
        requirement.branch = branch
        requirement.save()
        messages.success(request, "Branch document requirement saved successfully.")
    else:
        first_error = "Please review the requirement form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    if next_url:
        return redirect(next_url)
    return redirect("organization:branch_document_list")


@login_required
@require_POST
def branch_document_requirement_delete(request, branch_pk, requirement_pk):
    next_url = (request.POST.get("next") or "").strip()
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=branch_pk)
    requirement = get_object_or_404(BranchDocumentRequirement, pk=requirement_pk, branch=branch)

    if not can_manage_organization_setup(request.user):
        messages.error(request, "You do not have permission to delete branch document requirements.")
        if next_url:
            return redirect(next_url)
        return redirect("organization:branch_document_list")

    requirement.delete()
    messages.success(request, "Branch document requirement deleted successfully.")

    if next_url:
        return redirect(next_url)
    return redirect("organization:branch_document_list")


@login_required
@require_POST
def branch_document_create(request, pk):
    next_url = (request.POST.get("next") or "").strip()
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=pk)

    if not can_manage_branch_documents(request.user, branch):
        messages.error(request, "You do not have permission to upload branch store documents.")
        if next_url:
            return redirect(next_url)
        return redirect("organization:branch_detail", pk=branch.pk)

    form = BranchDocumentForm(request.POST, request.FILES)
    if form.is_valid():
        branch_document = form.save(commit=False)
        branch_document.branch = branch
        actor_name = ""
        if request.user.is_authenticated:
            actor_name = (
                request.user.get_full_name()
                or getattr(request.user, "email", "")
                or getattr(request.user, "username", "")
            )
        branch_document.uploaded_by = actor_name.strip()
        branch_document.save()
        messages.success(request, "Branch store document uploaded successfully.")
    else:
        first_error = "Please review the branch document form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    if next_url:
        return redirect(next_url)
    return redirect("organization:branch_detail", pk=branch.pk)


@login_required
@require_POST
def branch_document_delete(request, branch_pk, document_pk):
    next_url = (request.POST.get("next") or "").strip()
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=branch_pk)
    branch_document = get_object_or_404(BranchDocument, pk=document_pk, branch=branch)

    if not can_manage_branch_documents(request.user, branch):
        messages.error(request, "You do not have permission to delete branch store documents.")
        if next_url:
            return redirect(next_url)
        return redirect("organization:branch_detail", pk=branch.pk)

    branch_document.delete()
    messages.success(request, "Branch store document deleted successfully.")

    if next_url:
        return redirect(next_url)
    return redirect("organization:branch_detail", pk=branch.pk)


@login_required
def branch_document_view(request, branch_pk, document_pk):
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=branch_pk)
    branch_document = get_object_or_404(BranchDocument, pk=document_pk, branch=branch)

    if not can_view_branch_documents(request.user, branch):
        raise PermissionDenied("You do not have permission to access this branch document.")

    return build_browser_file_response(branch_document.file, force_download=False)


@login_required
def branch_document_download(request, branch_pk, document_pk):
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=branch_pk)
    branch_document = get_object_or_404(BranchDocument, pk=document_pk, branch=branch)

    if not can_view_branch_documents(request.user, branch):
        raise PermissionDenied("You do not have permission to access this branch document.")

    return build_browser_file_response(branch_document.file, force_download=True)
```

## performance/views.py

```python
from datetime import timedelta

from django.contrib import messages
from django.db.models import Avg, Count, IntegerField, Q
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from config.access import is_hr, is_operations, is_superuser, role_required
from employees.access import (
    get_user_scope_branch,
    is_admin_compatible,
    is_branch_scoped_supervisor,
    is_hr_user,
    is_operations_manager_user,
)
from employees.models import Employee
from notifications.models import InAppNotification, build_in_app_notification
from notifications.views import persist_in_app_notifications

from .forms import (
    PerformanceAcknowledgementForm,
    PerformanceReviewCommentForm,
    PerformanceReviewForm,
    ReviewCycleForm,
)
from .models import PerformanceReview, PerformanceReviewComment, ReviewCycle


def get_linked_employee(user):
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "employee_profile", None)


def has_linked_employee_profile(user):
    return bool(get_linked_employee(user))


def can_manage_performance_reviews(user, employee=None):
    if not user or not user.is_authenticated:
        return False
    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return True
    if employee and is_branch_scoped_supervisor(user):
        scoped_branch = get_user_scope_branch(user, get_linked_employee(user))
        return bool(scoped_branch and employee.branch_id == scoped_branch.id)
    return False


def can_access_performance_dashboard(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or get_linked_employee(user) is not None
        )
    )


def can_acknowledge_performance_review(user, review):
    if not user or not user.is_authenticated or not review:
        return False
    employee_user = getattr(review.employee, "user", None)
    return bool(
        employee_user
        and employee_user.pk == user.pk
        and not review.is_locked
        and review.status == PerformanceReview.STATUS_SUBMITTED
    )


def can_edit_performance_review(user, review):
    return bool(review and not review.is_locked and can_manage_performance_reviews(user, review.employee))


def can_comment_on_performance_review(user, review):
    if not user or not user.is_authenticated or not review:
        return False
    if can_manage_performance_reviews(user, review.employee):
        return True
    linked_employee = get_linked_employee(user)
    employee_user = getattr(review.employee, "user", None)
    return bool(
        (linked_employee and linked_employee.pk == review.reviewer_id)
        or (employee_user and employee_user.pk == user.pk)
    )


def can_force_complete_performance_review(user, review):
    return bool(
        review
        and review.is_locked
        and review.status != PerformanceReview.STATUS_ACKNOWLEDGED
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or can_manage_performance_reviews(user, review.employee)
        )
    )


def build_performance_review_queryset():
    return PerformanceReview.objects.select_related(
        "cycle",
        "cycle__company",
        "employee",
        "employee__branch",
        "employee__department",
        "reviewer",
        "reviewer__branch",
        "reviewer__department",
        "created_by",
    ).prefetch_related(
        "comments__author",
    ).annotate(
        overall_rating_value=Cast("overall_rating", IntegerField()),
    ).order_by("-cycle__period_start", "-updated_at", "-id")


def get_performance_notification_recipients(exclude_users=None):
    excluded_user_ids = {
        user.pk
        for user in exclude_users or []
        if user and getattr(user, "pk", None) is not None
    }
    recipients = []
    seen_user_ids = set()
    for user in Employee._meta.get_field("user").remote_field.model.objects.filter(is_active=True).order_by("id"):
        if user.pk in excluded_user_ids or user.pk in seen_user_ids:
            continue
        if can_access_performance_dashboard(user):
            recipients.append(user)
            seen_user_ids.add(user.pk)
    return recipients


def trigger_performance_review_alerts(reference_date=None):
    reference_date = reference_date or timezone.localdate()
    alert_cutoff = reference_date + timedelta(days=7)
    notifications = []

    due_reviews = PerformanceReview.objects.select_related(
        "cycle",
        "employee",
        "reviewer",
        "reviewer__user",
    ).filter(
        status=PerformanceReview.STATUS_DRAFT,
        cycle__status=ReviewCycle.STATUS_ACTIVE,
        cycle__period_end__lte=alert_cutoff,
    ).order_by("cycle__period_end", "employee__full_name", "id")

    for review in due_reviews:
        reviewer_user = getattr(review.reviewer, "user", None)
        if not reviewer_user or not reviewer_user.is_active:
            continue
        action_url = f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance"
        title = f"Performance review due for {review.employee.full_name}"
        body = (
            f"{review.employee.full_name} has a {review.cycle.title} review still in draft status. "
            f"Cycle end date: {review.cycle.period_end.strftime('%B %d, %Y')}."
        )
        already_exists = InAppNotification.objects.filter(
            recipient=reviewer_user,
            category=InAppNotification.CATEGORY_HR,
            title=title,
            action_url=action_url,
            created_at__date=reference_date,
        ).exists()
        if already_exists:
            continue
        notification = build_in_app_notification(
            recipient=reviewer_user,
            title=title,
            body=body,
            category=InAppNotification.CATEGORY_HR,
            action_url=action_url,
            level=InAppNotification.LEVEL_WARNING,
        )
        if notification is not None:
            notifications.append(notification)

    pending_ack_reviews = PerformanceReview.objects.select_related(
        "cycle",
        "employee",
        "employee__user",
        "reviewer",
    ).filter(
        status=PerformanceReview.STATUS_SUBMITTED,
        submitted_at__date__lte=reference_date - timedelta(days=2),
    ).order_by("submitted_at", "employee__full_name", "id")

    for review in pending_ack_reviews:
        employee_user = getattr(review.employee, "user", None)
        if not employee_user or not employee_user.is_active:
            continue
        action_url = f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance"
        title = f"Performance review awaiting acknowledgement"
        body = (
            f"Your {review.cycle.title} performance review from {review.reviewer.full_name} "
            f"is ready for acknowledgement."
        )
        already_exists = InAppNotification.objects.filter(
            recipient=employee_user,
            category=InAppNotification.CATEGORY_HR,
            title=title,
            action_url=action_url,
            created_at__date=reference_date,
        ).exists()
        if already_exists:
            continue
        notification = build_in_app_notification(
            recipient=employee_user,
            title=title,
            body=body,
            category=InAppNotification.CATEGORY_HR,
            action_url=action_url,
            level=InAppNotification.LEVEL_INFO,
        )
        if notification is not None:
            notifications.append(notification)

    return persist_in_app_notifications(notifications)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to access the performance workspace.",
)
def performance_dashboard(request):
    linked_employee = get_linked_employee(request.user)
    manager_scope = is_admin_compatible(request.user) or is_hr_user(request.user) or is_operations_manager_user(request.user)

    cycle_queryset = ReviewCycle.objects.select_related("company").annotate(
        review_total=Count("performance_reviews"),
        submitted_total=Count("performance_reviews", filter=Q(performance_reviews__status=PerformanceReview.STATUS_SUBMITTED)),
        acknowledged_total=Count("performance_reviews", filter=Q(performance_reviews__status=PerformanceReview.STATUS_ACKNOWLEDGED)),
    ).order_by("-period_start", "-id")
    review_queryset = build_performance_review_queryset()

    assigned_reviews = []
    if linked_employee:
        assigned_reviews = list(
            review_queryset.filter(reviewer=linked_employee).order_by("cycle__period_end", "employee__full_name")
        )

    if not manager_scope and linked_employee:
        cycle_queryset = cycle_queryset.filter(company=linked_employee.company)
        review_queryset = review_queryset.filter(Q(employee=linked_employee) | Q(reviewer=linked_employee))

    review_status_totals = {
        "draft": review_queryset.filter(status=PerformanceReview.STATUS_DRAFT).count(),
        "submitted": review_queryset.filter(status=PerformanceReview.STATUS_SUBMITTED).count(),
        "acknowledged": review_queryset.filter(status=PerformanceReview.STATUS_ACKNOWLEDGED).count(),
    }
    rating_summary = review_queryset.aggregate(average_rating=Avg("overall_rating_value"))
    department_rating_summary = list(
        review_queryset.values("employee__department__name")
        .annotate(
            average_rating=Avg("overall_rating_value"),
            review_total=Count("id"),
            outstanding_total=Count("id", filter=Q(overall_rating=PerformanceReview.RATING_OUTSTANDING)),
        )
        .order_by("-review_total", "employee__department__name")[:6]
    )
    for row in department_rating_summary:
        row["label"] = row.pop("employee__department__name") or "Unassigned Department"

    branch_rating_summary = list(
        review_queryset.values("employee__branch__name")
        .annotate(
            average_rating=Avg("overall_rating_value"),
            review_total=Count("id"),
            needs_support_total=Count(
                "id",
                filter=Q(
                    overall_rating__in=[
                        PerformanceReview.RATING_UNSATISFACTORY,
                        PerformanceReview.RATING_NEEDS_IMPROVEMENT,
                    ]
                ),
            ),
        )
        .order_by("-review_total", "employee__branch__name")[:6]
    )
    for row in branch_rating_summary:
        row["label"] = row.pop("employee__branch__name") or "Unassigned Branch"

    calibration_summary = {
        "unsatisfactory": review_queryset.filter(overall_rating=PerformanceReview.RATING_UNSATISFACTORY).count(),
        "needs_improvement": review_queryset.filter(overall_rating=PerformanceReview.RATING_NEEDS_IMPROVEMENT).count(),
        "meets_expectations": review_queryset.filter(overall_rating=PerformanceReview.RATING_MEETS_EXPECTATIONS).count(),
        "exceeds_expectations": review_queryset.filter(overall_rating=PerformanceReview.RATING_EXCEEDS_EXPECTATIONS).count(),
        "outstanding": review_queryset.filter(overall_rating=PerformanceReview.RATING_OUTSTANDING).count(),
    }
    max_calibration_total = max(calibration_summary.values()) if calibration_summary else 0
    calibration_bands = [
        {
            "label": "Unsatisfactory",
            "count": calibration_summary["unsatisfactory"],
            "width": int((calibration_summary["unsatisfactory"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "danger",
        },
        {
            "label": "Needs Improvement",
            "count": calibration_summary["needs_improvement"],
            "width": int((calibration_summary["needs_improvement"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "warning",
        },
        {
            "label": "Meets Expectations",
            "count": calibration_summary["meets_expectations"],
            "width": int((calibration_summary["meets_expectations"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "primary",
        },
        {
            "label": "Exceeds Expectations",
            "count": calibration_summary["exceeds_expectations"],
            "width": int((calibration_summary["exceeds_expectations"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "success",
        },
        {
            "label": "Outstanding",
            "count": calibration_summary["outstanding"],
            "width": int((calibration_summary["outstanding"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "success",
        },
    ]
    overdue_reviews = list(
        review_queryset.filter(
            status=PerformanceReview.STATUS_DRAFT,
            cycle__status=ReviewCycle.STATUS_ACTIVE,
            cycle__period_end__lt=timezone.localdate(),
        ).select_related("cycle", "employee", "reviewer")[:8]
    )
    pending_ack_reviews = list(
        review_queryset.filter(status=PerformanceReview.STATUS_SUBMITTED).select_related("cycle", "employee", "reviewer")[:8]
    )
    reviewer_queue = list(
        review_queryset.filter(
            reviewer=linked_employee,
            status__in=[PerformanceReview.STATUS_DRAFT, PerformanceReview.STATUS_SUBMITTED],
        ).order_by("cycle__period_end", "employee__full_name", "id")[:12]
    ) if linked_employee else []

    context = {
        "cycle_form": ReviewCycleForm(),
        "cycles": list(cycle_queryset[:10]),
        "review_total": review_queryset.count(),
        "cycle_total": cycle_queryset.count(),
        "active_cycle_total": cycle_queryset.filter(status=ReviewCycle.STATUS_ACTIVE).count(),
        "closed_cycle_total": cycle_queryset.filter(status=ReviewCycle.STATUS_CLOSED).count(),
        "draft_review_total": review_status_totals["draft"],
        "submitted_review_total": review_status_totals["submitted"],
        "acknowledged_review_total": review_status_totals["acknowledged"],
        "average_rating": rating_summary["average_rating"],
        "assigned_reviews": assigned_reviews[:8],
        "reviewer_queue": reviewer_queue,
        "overdue_reviews": overdue_reviews,
        "pending_ack_reviews": pending_ack_reviews,
        "department_rating_summary": department_rating_summary,
        "branch_rating_summary": branch_rating_summary,
        "calibration_bands": calibration_bands,
        "can_manage_cycles": manager_scope,
    }
    return render(request, "performance/dashboard.html", context)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to create review cycles.",
    redirect_to="performance:dashboard",
)
def review_cycle_create(request):
    if request.method == "POST":
        form = ReviewCycleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Review cycle created successfully.")
            return redirect("performance:dashboard")
    else:
        form = ReviewCycleForm()

    return render(
        request,
        "performance/cycle_form.html",
        {
            "form": form,
            "page_title": "Create Review Cycle",
            "submit_label": "Create Cycle",
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to update review cycles.",
    redirect_to="performance:dashboard",
)
def review_cycle_update(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle, pk=cycle_pk)
    if request.method == "POST":
        form = ReviewCycleForm(request.POST, instance=cycle)
        if form.is_valid():
            form.save()
            messages.success(request, "Review cycle updated successfully.")
            return redirect("performance:dashboard")
    else:
        form = ReviewCycleForm(instance=cycle)

    return render(
        request,
        "performance/cycle_form.html",
        {
            "form": form,
            "page_title": "Update Review Cycle",
            "submit_label": "Save Cycle",
            "cycle": cycle,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to clone review cycles.",
    redirect_to="performance:dashboard",
)
@require_POST
def review_cycle_clone(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle.objects.select_related("company"), pk=cycle_pk)
    cloned_cycle = cycle.clone_as_draft()
    messages.success(request, f"{cycle.title} was cloned into a new draft cycle.")
    return redirect("performance:review_cycle_update", cycle_pk=cloned_cycle.pk)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to close review cycles.",
    redirect_to="performance:dashboard",
)
@require_POST
def review_cycle_close(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle, pk=cycle_pk)
    if cycle.status == ReviewCycle.STATUS_CLOSED:
        messages.info(request, "This review cycle is already closed and locked.")
        return redirect("performance:dashboard")
    cycle.status = ReviewCycle.STATUS_CLOSED
    cycle.save(update_fields=["status", "updated_at"])
    messages.success(request, f"{cycle.title} is now closed and locked for standard review updates.")
    return redirect("performance:dashboard")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to create performance reviews.",
)
def performance_review_create(request, employee_pk):
    employee = get_object_or_404(
        Employee.objects.select_related("company", "branch", "user"),
        pk=employee_pk,
    )
    if not can_manage_performance_reviews(request.user, employee):
        messages.error(request, "You do not have permission to create performance reviews for this employee.")
        return redirect("employees:employee_detail", pk=employee.pk)

    if request.method == "POST":
        form = PerformanceReviewForm(request.POST, employee=employee)
        if form.is_valid():
            review = form.save(commit=False)
            review.employee = employee
            review.created_by = request.user
            review.save()
            if review.status == PerformanceReview.STATUS_SUBMITTED and not review.submitted_at:
                review.submit()
            messages.success(request, "Performance review saved successfully.")
            return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': employee.pk})}?tab=performance")
    else:
        form = PerformanceReviewForm(employee=employee)

    return render(
        request,
        "performance/review_form.html",
        {
            "employee": employee,
            "form": form,
            "page_title": "Create Performance Review",
            "submit_label": "Save Review",
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to update performance reviews.",
)
def performance_review_update(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "cycle", "reviewer"),
        pk=review_pk,
    )
    if not can_edit_performance_review(request.user, review):
        if review.is_locked:
            messages.error(request, "This performance review belongs to a closed cycle and is locked for standard edits.")
        else:
            messages.error(request, "You do not have permission to update this performance review.")
        return redirect("employees:employee_detail", pk=review.employee.pk)

    if request.method == "POST":
        form = PerformanceReviewForm(request.POST, instance=review, employee=review.employee)
        if form.is_valid():
            updated_review = form.save()
            if updated_review.status == PerformanceReview.STATUS_SUBMITTED and not updated_review.submitted_at:
                updated_review.submit()
            messages.success(request, "Performance review updated successfully.")
            return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")
    else:
        form = PerformanceReviewForm(instance=review, employee=review.employee)

    return render(
        request,
        "performance/review_form.html",
        {
            "employee": review.employee,
            "form": form,
            "page_title": "Update Performance Review",
            "submit_label": "Save Review",
            "review": review,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to acknowledge performance reviews.",
)
@require_POST
def performance_review_acknowledge(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "employee__user", "cycle", "reviewer"),
        pk=review_pk,
    )
    if not can_acknowledge_performance_review(request.user, review):
        if review.is_locked:
            messages.error(request, "This review belongs to a closed cycle and can only be completed by management.")
        else:
            messages.error(request, "You do not have permission to acknowledge this performance review.")
        return redirect("employees:employee_detail", pk=review.employee.pk)

    form = PerformanceAcknowledgementForm(request.POST, instance=review)
    if form.is_valid():
        review.acknowledge(employee_comments=form.cleaned_data.get("employee_comments", ""))
        messages.success(request, "Performance review acknowledged successfully.")
    else:
        messages.error(request, "Please review your acknowledgement comment.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to comment on performance reviews.",
)
@require_POST
def performance_review_comment_create(request, review_pk):
    review = get_object_or_404(
        build_performance_review_queryset(),
        pk=review_pk,
    )
    if not can_comment_on_performance_review(request.user, review):
        messages.error(request, "You do not have permission to add a note to this performance review.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")

    form = PerformanceReviewCommentForm(request.POST)
    if form.is_valid():
        PerformanceReviewComment.objects.create(
            review=review,
            author=request.user,
            note=form.cleaned_data["note"],
        )
        messages.success(request, "Performance review note added successfully.")
    else:
        messages.error(request, "Please enter a note before saving.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to force-complete performance reviews.",
)
@require_POST
def performance_review_force_complete(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "cycle", "reviewer"),
        pk=review_pk,
    )
    if not can_force_complete_performance_review(request.user, review):
        messages.error(request, "You do not have permission to force-complete this review.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")

    if not review.submitted_at:
        review.submitted_at = timezone.now()
    review.status = PerformanceReview.STATUS_ACKNOWLEDGED
    review.acknowledged_at = timezone.now()
    review.save(update_fields=["status", "submitted_at", "acknowledged_at", "updated_at"])
    PerformanceReviewComment.objects.create(
        review=review,
        author=request.user,
        note="Review force-completed after the cycle was closed and locked.",
    )
    messages.success(request, "Performance review force-completed successfully.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to access the reviewer queue.",
)
def performance_reviewer_queue(request):
    linked_employee = get_linked_employee(request.user)
    queue_reviews = []
    if linked_employee:
        queue_reviews = list(
            build_performance_review_queryset().filter(
                reviewer=linked_employee,
                status__in=[PerformanceReview.STATUS_DRAFT, PerformanceReview.STATUS_SUBMITTED],
            ).order_by("cycle__period_end", "employee__full_name", "id")
        )

    return render(
        request,
        "performance/reviewer_queue.html",
        {
            "queue_reviews": queue_reviews,
            "linked_employee": linked_employee,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to export performance reviews.",
)
def performance_reviews_export(request):
    review_queryset = build_performance_review_queryset()
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="performance-reviews.csv"'
    response.write(
        "Cycle,Company,Employee ID,Employee,Department,Branch,Reviewer,Rating,Status,Submitted At,Acknowledged At\n"
    )
    for review in review_queryset:
        response.write(
            (
                f"\"{review.cycle.title}\","
                f"\"{review.cycle.company.name}\","
                f"\"{review.employee.employee_id}\","
                f"\"{review.employee.full_name}\","
                f"\"{getattr(review.employee.department, 'name', '')}\","
                f"\"{getattr(review.employee.branch, 'name', '')}\","
                f"\"{review.reviewer.full_name}\","
                f"\"{review.get_overall_rating_display()}\","
                f"\"{review.get_status_display()}\","
                f"\"{review.submitted_at or ''}\","
                f"\"{review.acknowledged_at or ''}\"\n"
            )
        )
    return response


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to view this performance review export.",
)
def performance_review_print(request, review_pk):
    review = get_object_or_404(
        build_performance_review_queryset(),
        pk=review_pk,
    )
    return render(
        request,
        "performance/review_print.html",
        {
            "review": review,
        },
    )
```
