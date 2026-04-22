from django.conf import settings
from django.core.mail import send_mail


def send_notification_email(recipient_email, subject, body_text, body_html=None):
    if not recipient_email:
        return 0

    return send_mail(
        subject=subject,
        message=body_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[recipient_email],
        html_message=body_html,
        fail_silently=False,
    )
