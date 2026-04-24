from .email_sender import send_notification_email
from .models import build_in_app_notification, get_notification_preferences_for_user


def create_in_app_notification(**kwargs):
    return build_in_app_notification(**kwargs)


def deliver_notification_email(notification):
    preferences = get_notification_preferences_for_user(notification.recipient)
    allow_email = bool(
        preferences
        and getattr(preferences, "email_enabled", True)
        and getattr(notification.recipient, "email", "").strip()
    )
    if not allow_email:
        return

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


def dedupe_unsaved_notifications(notifications):
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

    return deduped_notifications


def persist_in_app_notifications(notifications):
    saved_notifications = []
    for notification in dedupe_unsaved_notifications(notifications):
        notification.save()
        deliver_notification_email(notification)
        saved_notifications.append(notification)

    return saved_notifications
