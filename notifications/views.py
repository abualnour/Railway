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

from config.access import is_hr, is_operations, is_superuser, role_required
from employees.access import is_admin_compatible

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
    if request.method == "POST":
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
    if request.method == "POST":
        unread_notifications = InAppNotification.objects.filter(
            recipient=request.user,
            is_read=False,
            is_deleted=False,
        )
        unread_notifications.update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip() if request.method == "POST" else ""
    return redirect(next_url or "notifications:home")


@login_required
@require_POST
def mark_category_read(request, category):
    valid_categories = {choice[0] for choice in InAppNotification.CATEGORY_CHOICES}
    if request.method == "POST" and category in valid_categories:
        InAppNotification.objects.filter(
            recipient=request.user,
            category=category,
            is_read=False,
            is_deleted=False,
        ).update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip() if request.method == "POST" else ""
    return redirect(next_url or "notifications:home")


@login_required
@require_POST
def delete_notification(request, pk):
    if request.method == "POST":
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
    if request.method == "POST":
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


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to view notification delivery performance.",
    redirect_to="notifications:home",
)
def delivery_performance(request):
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
    next_url = (request.POST.get("next") or "").strip() if request.method == "POST" else ""
    if request.method == "POST":
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
