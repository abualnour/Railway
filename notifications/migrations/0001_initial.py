from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InAppNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=160)),
                ("body", models.TextField()),
                ("category", models.CharField(choices=[("payroll", "Payroll")], default="payroll", max_length=40)),
                ("level", models.CharField(choices=[("info", "Info"), ("success", "Success"), ("warning", "Warning")], default="info", max_length=20)),
                ("action_url", models.CharField(blank=True, max_length=255)),
                ("is_read", models.BooleanField(default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="in_app_notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "In-App Notification",
                "verbose_name_plural": "In-App Notifications",
                "ordering": ["is_read", "-created_at", "-id"],
            },
        ),
    ]
