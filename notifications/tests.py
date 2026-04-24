from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from config.context_processors import navbar_context

from .models import InAppNotification, NotificationPreference


@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class NotificationCenterTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="notify-user@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_HR,
        )
        self.client.force_login(self.user)
        self.notification = InAppNotification.objects.create(
            recipient=self.user,
            title="Payroll period moved to Approved",
            body="April payroll has been approved.",
            action_url="/payroll/periods/1/",
        )
        self.request_notification = InAppNotification.objects.create(
            recipient=self.user,
            title="Leave request submitted",
            body="Your leave request is pending review.",
            category=InAppNotification.CATEGORY_REQUEST,
            action_url="/employees/self-service/leave/",
        )

    def test_notification_center_shows_unread_notifications(self):
        response = self.client.get(reverse("notifications:home"))

        self.assertContains(response, "Notification Center")
        self.assertContains(response, "Payroll period moved to Approved")
        self.assertContains(response, "Unread")

    def test_mark_notification_read_updates_notification(self):
        response = self.client.post(
            reverse("notifications:mark_read", args=[self.notification.pk]),
            {"next": reverse("notifications:home")},
            follow=True,
        )

        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertContains(response, "Read")

    def test_mark_all_notifications_read_updates_only_current_user_notifications(self):
        other_user = get_user_model().objects.create_user(
            email="notify-other@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_FINANCE_MANAGER,
        )
        other_notification = InAppNotification.objects.create(
            recipient=other_user,
            title="Leave untouched",
            body="Other user notification",
        )

        self.client.post(reverse("notifications:mark_all_read"), follow=True)

        self.notification.refresh_from_db()
        other_notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertFalse(other_notification.is_read)

    def test_update_notification_preferences_saves_user_delivery_choices(self):
        response = self.client.post(
            reverse("notifications:preferences"),
            {
                "payroll_management_email_enabled": "on",
                "payroll_employee_email_enabled": "on",
            },
            follow=True,
        )

        preferences = NotificationPreference.objects.get(user=self.user)
        self.assertFalse(preferences.payroll_management_in_app_enabled)
        self.assertTrue(preferences.payroll_management_email_enabled)
        self.assertFalse(preferences.payroll_employee_in_app_enabled)
        self.assertTrue(preferences.payroll_employee_email_enabled)
        self.assertFalse(preferences.payroll_employee_include_pdf_link)
        self.assertContains(response, "Notification delivery settings saved.")

    def test_notification_center_shows_grouped_preference_sections(self):
        response = self.client.get(reverse("notifications:home"))

        self.assertContains(response, "Management Workflow Alerts")
        self.assertContains(response, "Employee Payslip Delivery")
        self.assertContains(response, "In-App Category Alerts")
        self.assertContains(response, "In-app workflow alerts")
        self.assertContains(response, "Email payslip delivery alerts")

    def test_notification_center_filters_by_category(self):
        response = self.client.get(reverse("notifications:home"), {"category": InAppNotification.CATEGORY_REQUEST})

        self.assertContains(response, "Leave request submitted")
        self.assertNotContains(response, "Payroll period moved to Approved")

    def test_mark_notification_category_read_updates_only_selected_category(self):
        response = self.client.post(
            reverse("notifications:mark_category_read", args=[InAppNotification.CATEGORY_REQUEST]),
            {"next": reverse("notifications:home")},
            follow=True,
        )

        self.request_notification.refresh_from_db()
        self.notification.refresh_from_db()
        self.assertTrue(self.request_notification.is_read)
        self.assertFalse(self.notification.is_read)
        self.assertContains(response, "Payroll period moved to Approved")

    def test_update_notification_preferences_saves_category_controls(self):
        self.client.post(
            reverse("notifications:preferences"),
            {
                "payroll_management_in_app_enabled": "on",
                "payroll_management_email_enabled": "on",
                "request_in_app_enabled": "on",
                "employee_in_app_enabled": "on",
            },
            follow=True,
        )

        preferences = NotificationPreference.objects.get(user=self.user)
        self.assertTrue(preferences.request_in_app_enabled)
        self.assertFalse(preferences.operations_in_app_enabled)
        self.assertFalse(preferences.schedule_in_app_enabled)
        self.assertTrue(preferences.employee_in_app_enabled)
        self.assertFalse(preferences.hr_in_app_enabled)
        self.assertFalse(preferences.calendar_in_app_enabled)

    def test_navbar_unread_counts_ignore_deleted_notifications(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Deleted unread request",
            body="This notification should not count.",
            category=InAppNotification.CATEGORY_REQUEST,
            is_deleted=True,
        )
        request = RequestFactory().get("/")
        middleware = SessionMiddleware(lambda request: None)
        middleware.process_request(request)
        request.session.save()
        request.user = self.user

        context = navbar_context(request)

        self.assertEqual(context["nav_notification_unread_total"], 2)
        self.assertEqual(
            context["nav_notification_category_unread_counts"][InAppNotification.CATEGORY_REQUEST],
            1,
        )

    def test_notification_center_shows_all_current_page_category_notifications(self):
        for index in range(13):
            InAppNotification.objects.create(
                recipient=self.user,
                title=f"Operations item {index}",
                body="Current page item",
                category=InAppNotification.CATEGORY_OPERATIONS,
            )

        response = self.client.get(
            reverse("notifications:home"),
            {"category": InAppNotification.CATEGORY_OPERATIONS},
        )

        self.assertContains(response, "Operations item 0")
        self.assertContains(response, "Operations item 12")

    def test_notification_mutations_ignore_external_next_redirects(self):
        response = self.client.post(
            reverse("notifications:mark_read", args=[self.notification.pk]),
            {"next": "https://example.com/phishing"},
        )

        self.assertRedirects(
            response,
            reverse("notifications:home"),
            fetch_redirect_response=False,
        )

    def test_delivery_performance_link_matches_view_permissions(self):
        response = self.client.get(reverse("notifications:home"))
        self.assertContains(response, "Delivery Performance")

        finance_user = get_user_model().objects.create_user(
            email="finance-user@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_FINANCE_MANAGER,
        )
        self.client.force_login(finance_user)

        response = self.client.get(reverse("notifications:home"))
        self.assertNotContains(response, "Delivery Performance")
