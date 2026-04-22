from django.conf import settings
from django.db import models
from django.utils import timezone


class InAppNotification(models.Model):
    LEVEL_INFO = "info"
    LEVEL_SUCCESS = "success"
    LEVEL_WARNING = "warning"

    LEVEL_CHOICES = [
        (LEVEL_INFO, "Info"),
        (LEVEL_SUCCESS, "Success"),
        (LEVEL_WARNING, "Warning"),
    ]

    CATEGORY_PAYROLL = "payroll"
    CATEGORY_REQUEST = "request"
    CATEGORY_OPERATIONS = "operations"
    CATEGORY_SCHEDULE = "schedule"
    CATEGORY_EMPLOYEE = "employee"
    CATEGORY_HR = "hr"
    CATEGORY_CONTRACT = "contract"
    CATEGORY_CALENDAR = "calendar"

    CATEGORY_CHOICES = [
        (CATEGORY_PAYROLL, "Payroll"),
        (CATEGORY_REQUEST, "Requests"),
        (CATEGORY_OPERATIONS, "Operations"),
        (CATEGORY_SCHEDULE, "Schedule"),
        (CATEGORY_EMPLOYEE, "Employee Updates"),
        (CATEGORY_HR, "HR"),
        (CATEGORY_CONTRACT, "Contract"),
        (CATEGORY_CALENDAR, "Calendar"),
    ]

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="in_app_notifications",
    )
    title = models.CharField(max_length=160)
    body = models.TextField()
    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, default=CATEGORY_PAYROLL)
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    action_url = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_read", "-created_at", "-id"]
        verbose_name = "In-App Notification"
        verbose_name_plural = "In-App Notifications"

    def __str__(self):
        return f"{self.recipient} | {self.title}"

    def mark_read(self):
        if self.is_read:
            return
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    payroll_management_in_app_enabled = models.BooleanField(default=True)
    payroll_management_email_enabled = models.BooleanField(default=True)
    payroll_employee_in_app_enabled = models.BooleanField(default=True)
    payroll_employee_email_enabled = models.BooleanField(default=True)
    payroll_employee_include_pdf_link = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    request_in_app_enabled = models.BooleanField(default=True)
    operations_in_app_enabled = models.BooleanField(default=True)
    schedule_in_app_enabled = models.BooleanField(default=True)
    employee_in_app_enabled = models.BooleanField(default=True)
    hr_in_app_enabled = models.BooleanField(default=True)
    calendar_in_app_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Notification Preference"
        verbose_name_plural = "Notification Preferences"

    def __str__(self):
        return f"{self.user} notification preferences"


def get_notification_preferences_for_user(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None
    preferences, _ = NotificationPreference.objects.get_or_create(user=user)
    return preferences


CATEGORY_PREFERENCE_FIELD_MAP = {
    InAppNotification.CATEGORY_REQUEST: "request_in_app_enabled",
    InAppNotification.CATEGORY_OPERATIONS: "operations_in_app_enabled",
    InAppNotification.CATEGORY_SCHEDULE: "schedule_in_app_enabled",
    InAppNotification.CATEGORY_EMPLOYEE: "employee_in_app_enabled",
    InAppNotification.CATEGORY_HR: "hr_in_app_enabled",
    InAppNotification.CATEGORY_CONTRACT: "hr_in_app_enabled",
    InAppNotification.CATEGORY_CALENDAR: "calendar_in_app_enabled",
}


def user_allows_in_app_notification(user, category):
    if not user or not getattr(user, "is_authenticated", False):
        return False

    if category == InAppNotification.CATEGORY_PAYROLL:
        return True

    preference_field = CATEGORY_PREFERENCE_FIELD_MAP.get(category)
    if not preference_field:
        return True

    preferences = get_notification_preferences_for_user(user)
    return bool(preferences and getattr(preferences, preference_field, True))


def build_in_app_notification(*, recipient, title, body, category, action_url="", level=InAppNotification.LEVEL_INFO):
    if not recipient or not getattr(recipient, "is_active", False):
        return None
    if not user_allows_in_app_notification(recipient, category):
        return None
    return InAppNotification(
        recipient=recipient,
        title=title,
        body=body,
        category=category,
        level=level,
        action_url=action_url,
    )
