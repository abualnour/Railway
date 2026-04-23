from django.core.management.base import BaseCommand

from recruitment.views import trigger_recruitment_alerts


class Command(BaseCommand):
    help = "Send recruitment alerts for upcoming interviews, expiring offers, and aging candidates."

    def handle(self, *args, **options):
        notifications = trigger_recruitment_alerts()
        self.stdout.write(
            self.style.SUCCESS(
                f"Recruitment alert check completed. {len(notifications)} notification(s) created."
            )
        )
