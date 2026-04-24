from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

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

    def test_notification_center_status_all_shows_read_and_unread(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Read payroll update",
            body="Already reviewed.",
            is_read=True,
        )

        response = self.client.get(reverse("notifications:home"), {"status": "all"})

        self.assertContains(response, "Payroll period moved to Approved")
        self.assertContains(response, "Read payroll update")

    def test_notification_center_status_unread_shows_only_unread(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Read payroll update",
            body="Already reviewed.",
            is_read=True,
        )

        response = self.client.get(reverse("notifications:home"), {"status": "unread"})

        self.assertContains(response, "Payroll period moved to Approved")
        self.assertNotContains(response, "Read payroll update")

    def test_notification_center_status_read_shows_only_read(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Read payroll update",
            body="Already reviewed.",
            is_read=True,
        )

        response = self.client.get(reverse("notifications:home"), {"status": "read"})

        self.assertNotContains(response, "Payroll period moved to Approved")
        self.assertContains(response, "Read payroll update")

    def test_notification_center_invalid_status_falls_back_to_all(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Read payroll update",
            body="Already reviewed.",
            is_read=True,
        )

        response = self.client.get(reverse("notifications:home"), {"status": "archived"})

        self.assertEqual(response.context["selected_status"], "all")
        self.assertContains(response, "Payroll period moved to Approved")
        self.assertContains(response, "Read payroll update")

    def test_notification_center_category_and_status_filters_work_together(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Read request update",
            body="Already reviewed request.",
            category=InAppNotification.CATEGORY_REQUEST,
            is_read=True,
        )

        response = self.client.get(
            reverse("notifications:home"),
            {"category": InAppNotification.CATEGORY_REQUEST, "status": "read"},
        )

        self.assertContains(response, "Read request update")
        self.assertNotContains(response, "Leave request submitted")
        self.assertNotContains(response, "Payroll period moved to Approved")

    def test_notification_center_pagination_preserves_category_and_status(self):
        for index in range(26):
            InAppNotification.objects.create(
                recipient=self.user,
                title=f"Paged operations item {index}",
                body="Paged unread item",
                category=InAppNotification.CATEGORY_OPERATIONS,
            )

        response = self.client.get(
            reverse("notifications:home"),
            {"category": InAppNotification.CATEGORY_OPERATIONS, "status": "unread"},
        )

        self.assertContains(
            response,
            "?category=operations&amp;status=unread&amp;page=2#feed",
        )

    def test_notification_mutations_preserve_safe_filtered_next_url(self):
        next_url = (
            f"{reverse('notifications:home')}?"
            f"category={InAppNotification.CATEGORY_REQUEST}&status=unread#feed"
        )

        response = self.client.post(
            reverse("notifications:delete", args=[self.request_notification.pk]),
            {"next": next_url},
        )

        self.assertRedirects(response, next_url, fetch_redirect_response=False)

    def test_delivery_performance_uses_failed_over_attempted_rate(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Email sent",
            body="Sent",
            email_sent=True,
        )
        InAppNotification.objects.create(
            recipient=self.user,
            title="Email failed",
            body="Failed",
            email_failed=True,
            email_failed_reason="SMTP error",
        )
        InAppNotification.objects.create(
            recipient=self.user,
            title="No email attempt",
            body="No email flags",
        )

        response = self.client.get(reverse("notifications:performance"))

        self.assertEqual(response.context["summary"]["attempted"], 2)
        self.assertEqual(response.context["summary"]["email_sent"], 1)
        self.assertEqual(response.context["summary"]["email_failed"], 1)
        self.assertEqual(response.context["summary"]["failure_rate"], 50.0)
        self.assertEqual(response.context["summary"]["unattempted"], 3)

    def test_delivery_performance_category_and_status_filters(self):
        InAppNotification.objects.create(
            recipient=self.user,
            title="Request failed",
            body="Failed",
            category=InAppNotification.CATEGORY_REQUEST,
            email_failed=True,
            email_failed_reason="SMTP error",
        )
        InAppNotification.objects.create(
            recipient=self.user,
            title="Payroll sent",
            body="Sent",
            category=InAppNotification.CATEGORY_PAYROLL,
            email_sent=True,
        )

        response = self.client.get(
            reverse("notifications:performance"),
            {
                "category": InAppNotification.CATEGORY_REQUEST,
                "delivery_status": "failed",
            },
        )

        self.assertEqual(response.context["filter_state"]["category"], InAppNotification.CATEGORY_REQUEST)
        self.assertEqual(response.context["filter_state"]["delivery_status"], "failed")
        self.assertEqual(response.context["summary"]["total"], 1)
        self.assertContains(response, "Request failed")
        self.assertNotContains(response, "Payroll sent")

    def test_delivery_performance_date_filters_are_safe(self):
        old_notification = InAppNotification.objects.create(
            recipient=self.user,
            title="Old failed",
            body="Old",
            email_failed=True,
            email_failed_reason="Old SMTP error",
        )
        new_notification = InAppNotification.objects.create(
            recipient=self.user,
            title="New failed",
            body="New",
            email_failed=True,
            email_failed_reason="New SMTP error",
        )
        old_datetime = timezone.now() - timedelta(days=10)
        today = timezone.localdate()
        InAppNotification.objects.filter(pk=old_notification.pk).update(created_at=old_datetime)
        InAppNotification.objects.filter(pk=new_notification.pk).update(created_at=timezone.now())

        response = self.client.get(
            reverse("notifications:performance"),
            {"start_date": today.isoformat(), "end_date": today.isoformat()},
        )

        self.assertContains(response, "New failed")
        self.assertNotContains(response, "Old failed")

        response = self.client.get(
            reverse("notifications:performance"),
            {"start_date": "not-a-date", "end_date": "also-bad"},
        )

        self.assertEqual(response.context["filter_state"]["start_date_value"], "")
        self.assertEqual(response.context["filter_state"]["end_date_value"], "")

    def test_delivery_performance_invalid_filters_fall_back(self):
        response = self.client.get(
            reverse("notifications:performance"),
            {"category": "bad-category", "delivery_status": "bad-status"},
        )

        self.assertEqual(response.context["filter_state"]["category"], "")
        self.assertEqual(response.context["filter_state"]["delivery_status"], "all")
        self.assertContains(response, "Delivery Performance")

    def test_delivery_performance_lists_are_bounded_and_empty_state_is_safe(self):
        InAppNotification.objects.all().delete()
        response = self.client.get(reverse("notifications:performance"))
        self.assertEqual(response.context["summary"]["total"], 0)
        self.assertContains(response, "No delivery failures")

        for index in range(25):
            InAppNotification.objects.create(
                recipient=self.user,
                title=f"Failure {index}",
                body="Failed",
                email_failed=True,
                email_failed_reason="SMTP error",
            )

        response = self.client.get(reverse("notifications:performance"))
        self.assertEqual(len(response.context["recent_failures"]), 20)

    def test_delivery_performance_preserves_access_restrictions(self):
        finance_user = get_user_model().objects.create_user(
            email="finance-performance@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_FINANCE_MANAGER,
        )
        self.client.force_login(finance_user)

        response = self.client.get(reverse("notifications:performance"))

        self.assertRedirects(
            response,
            reverse("notifications:home"),
            fetch_redirect_response=False,
        )
