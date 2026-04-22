from django.core.management.base import BaseCommand

from notifications.views import trigger_contract_expiry_notifications


class Command(BaseCommand):
    help = "Create in-app and email notifications for active employee contracts expiring within 60 days."

    def handle(self, *args, **options):
        notifications = trigger_contract_expiry_notifications()
        self.stdout.write(
            self.style.SUCCESS(
                f"Created {len(notifications)} contract expiry notification(s)."
            )
        )
