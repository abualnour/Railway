from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from notifications.models import InAppNotification, build_in_app_notification

from .models import HRAnnouncement, HRPolicy


def build_hr_notification_users(*, audience=HRAnnouncement.AUDIENCE_ALL, company=None):
    user_model = get_user_model()
    queryset = user_model.objects.filter(is_active=True)

    if audience == HRAnnouncement.AUDIENCE_EMPLOYEES:
        queryset = queryset.filter(role=user_model.ROLE_EMPLOYEE)
    elif audience == HRAnnouncement.AUDIENCE_MANAGEMENT:
        queryset = queryset.filter(
            role__in=[
                user_model.ROLE_HR,
                user_model.ROLE_FINANCE_MANAGER,
                user_model.ROLE_SUPERVISOR,
                user_model.ROLE_OPERATIONS_MANAGER,
            ]
        )
    elif audience == HRAnnouncement.AUDIENCE_HR:
        queryset = queryset.filter(role=user_model.ROLE_HR)

    if company is not None:
        queryset = queryset.filter(
            Q(employee_profile__company=company)
            | Q(employee_profile__isnull=True, role__in=[user_model.ROLE_HR, user_model.ROLE_FINANCE_MANAGER, user_model.ROLE_OPERATIONS_MANAGER, user_model.ROLE_SUPERVISOR])
        ).distinct()

    return list(queryset.order_by("email"))


def dispatch_hr_notifications(users, *, title, body, level=InAppNotification.LEVEL_INFO):
    notifications = []
    seen_user_ids = set()
    for user in users:
        if not user or user.pk in seen_user_ids:
            continue
        seen_user_ids.add(user.pk)
        notifications.append(
            build_in_app_notification(
                recipient=user,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_HR,
                level=level,
                action_url="/hr/",
            )
        )
    notifications = [notification for notification in notifications if notification is not None]
    if notifications:
        InAppNotification.objects.bulk_create(notifications)


@receiver(post_save, sender=HRAnnouncement)
def create_hr_announcement_notifications(sender, instance, created, **kwargs):
    if not instance.is_active:
        return

    audience_users = build_hr_notification_users(audience=instance.audience)
    if not audience_users:
        return

    verb = "published" if created else "updated"
    dispatch_hr_notifications(
        audience_users,
        title=f"HR announcement {verb}: {instance.title}",
        body=instance.message,
        level=InAppNotification.LEVEL_INFO,
    )


@receiver(post_save, sender=HRPolicy)
def create_hr_policy_notifications(sender, instance, created, **kwargs):
    if not instance.is_active:
        return

    policy_users = build_hr_notification_users(company=instance.company)
    if not policy_users:
        return

    company_label = instance.company.name if instance.company_id else "all companies"
    verb = "published" if created else "updated"
    dispatch_hr_notifications(
        policy_users,
        title=f"HR policy {verb}: {instance.title}",
        body=(
            f"{instance.get_category_display()} policy for {company_label} is active from "
            f"{instance.effective_date:%b %d, %Y}."
        ),
        level=InAppNotification.LEVEL_WARNING if created else InAppNotification.LEVEL_INFO,
    )
from django.db.models import Q
