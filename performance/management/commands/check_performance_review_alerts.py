from django.core.management.base import BaseCommand

from performance.views import trigger_performance_review_alerts


class Command(BaseCommand):
    help = "Send performance review reminders for due drafts and pending acknowledgements."

    def handle(self, *args, **options):
        notifications = trigger_performance_review_alerts()
        self.stdout.write(
            self.style.SUCCESS(
                f"Performance review alert check completed. {len(notifications)} notification(s) created."
            )
        )
