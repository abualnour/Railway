from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import NotificationPreferenceForm
from .models import InAppNotification, get_notification_preferences_for_user


NOTIFICATION_CATEGORY_ORDER = [
    InAppNotification.CATEGORY_PAYROLL,
    InAppNotification.CATEGORY_REQUEST,
    InAppNotification.CATEGORY_OPERATIONS,
    InAppNotification.CATEGORY_SCHEDULE,
    InAppNotification.CATEGORY_EMPLOYEE,
    InAppNotification.CATEGORY_HR,
    InAppNotification.CATEGORY_CALENDAR,
]


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
    all_notifications = list(InAppNotification.objects.filter(recipient=request.user)[:120])
    unread_total = sum(1 for notification in all_notifications if not notification.is_read)
    preferences = get_notification_preferences_for_user(request.user)
    selected_category = (request.GET.get("category") or "").strip()
    valid_categories = {choice[0] for choice in InAppNotification.CATEGORY_CHOICES}
    if selected_category and selected_category not in valid_categories:
        selected_category = ""

    filtered_notifications = [
        notification
        for notification in all_notifications
        if not selected_category or notification.category == selected_category
    ]
    category_cards = build_notification_category_cards(all_notifications)
    selected_category_label = dict(InAppNotification.CATEGORY_CHOICES).get(selected_category, "All Notifications")

    context = {
        "notifications": filtered_notifications[:40],
        "all_notifications_total": len(all_notifications),
        "unread_total": unread_total,
        "preference_form": NotificationPreferenceForm(instance=preferences),
        "category_cards": category_cards,
        "visible_category_cards": filter_visible_category_cards(category_cards, selected_category),
        "selected_category": selected_category,
        "selected_category_label": selected_category_label,
        "notification_categories": InAppNotification.CATEGORY_CHOICES,
    }
    return render(request, "notifications/center.html", context)


@login_required
def mark_notification_read(request, pk):
    if request.method == "POST":
        notification = get_object_or_404(InAppNotification, pk=pk, recipient=request.user)
        notification.mark_read()
        next_url = (request.POST.get("next") or "").strip()
        if next_url:
            return redirect(next_url)
    return redirect("notifications:home")


@login_required
def mark_all_notifications_read(request):
    if request.method == "POST":
        unread_notifications = InAppNotification.objects.filter(recipient=request.user, is_read=False)
        unread_notifications.update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip() if request.method == "POST" else ""
    return redirect(next_url or "notifications:home")


@login_required
def mark_notification_category_read(request, category):
    valid_categories = {choice[0] for choice in InAppNotification.CATEGORY_CHOICES}
    if request.method == "POST" and category in valid_categories:
        InAppNotification.objects.filter(
            recipient=request.user,
            category=category,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
    next_url = (request.POST.get("next") or "").strip() if request.method == "POST" else ""
    return redirect(next_url or "notifications:home")


@login_required
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
