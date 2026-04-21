from django.db import migrations, models


def copy_existing_notification_preferences(apps, schema_editor):
    NotificationPreference = apps.get_model("notifications", "NotificationPreference")
    for preference in NotificationPreference.objects.all():
        preference.payroll_management_in_app_enabled = preference.payroll_in_app_enabled
        preference.payroll_management_email_enabled = preference.payroll_email_enabled
        preference.payroll_employee_in_app_enabled = preference.payroll_in_app_enabled
        preference.payroll_employee_email_enabled = preference.payroll_email_enabled
        preference.payroll_employee_include_pdf_link = preference.payroll_include_pdf_link
        preference.save(
            update_fields=[
                "payroll_management_in_app_enabled",
                "payroll_management_email_enabled",
                "payroll_employee_in_app_enabled",
                "payroll_employee_email_enabled",
                "payroll_employee_include_pdf_link",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_notificationpreference"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="payroll_employee_email_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="payroll_employee_in_app_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="payroll_employee_include_pdf_link",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="payroll_management_email_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="payroll_management_in_app_enabled",
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(copy_existing_notification_preferences, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="notificationpreference",
            name="payroll_email_enabled",
        ),
        migrations.RemoveField(
            model_name="notificationpreference",
            name="payroll_in_app_enabled",
        ),
        migrations.RemoveField(
            model_name="notificationpreference",
            name="payroll_include_pdf_link",
        ),
    ]
