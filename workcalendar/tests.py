from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notifications.models import InAppNotification, NotificationPreference

from .models import RegionalHoliday, RegionalWorkCalendar


class WorkCalendarNotificationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.hr_user = self.user_model.objects.create_user(
            email="calendar-hr@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        self.employee_user = self.user_model.objects.create_user(
            email="calendar-employee@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )

    def test_saving_calendar_notifies_users(self):
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("workcalendar:home"),
            {
                "calendar_action": "save_calendar",
                "name": "Kuwait Calendar",
                "region_code": "KW",
                "notes": "Updated weekly off settings.",
                "is_active": "on",
                "weekend_day_selection": ["4", "5"],
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(
            recipient=self.employee_user,
            category=InAppNotification.CATEGORY_CALENDAR,
        ).latest("id")
        self.assertIn("Work calendar updated", notification.title)
        self.assertIn("friday", notification.body.lower())

    def test_adding_holiday_notifies_users(self):
        calendar = RegionalWorkCalendar.objects.create(
            name="Kuwait Calendar",
            region_code="KW",
            weekend_days="4",
            is_active=True,
        )
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("workcalendar:home"),
            {
                "calendar_action": "add_holiday",
                "holiday_date": "2026-06-28",
                "title": "Eid Holiday",
                "holiday_type": RegionalHoliday.HOLIDAY_TYPE_PUBLIC,
                "is_non_working_day": "on",
                "notes": "Public holiday",
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(
            recipient=self.employee_user,
            category=InAppNotification.CATEGORY_CALENDAR,
        ).latest("id")
        self.assertIn("Holiday added", notification.title)
        self.assertIn("non-working day", notification.body.lower())

    def test_removing_holiday_notifies_users(self):
        calendar = RegionalWorkCalendar.objects.create(
            name="Kuwait Calendar",
            region_code="KW",
            weekend_days="4",
            is_active=True,
        )
        holiday = RegionalHoliday.objects.create(
            calendar=calendar,
            holiday_date="2026-06-28",
            title="Eid Holiday",
            holiday_type=RegionalHoliday.HOLIDAY_TYPE_PUBLIC,
            is_non_working_day=True,
        )
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("workcalendar:home"),
            {
                "calendar_action": "delete_holiday",
                "holiday_id": str(holiday.pk),
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(
            recipient=self.employee_user,
            category=InAppNotification.CATEGORY_CALENDAR,
        ).latest("id")
        self.assertIn("Holiday removed", notification.title)
        self.assertIn("removed", notification.body.lower())

    def test_calendar_notification_preference_suppresses_delivery(self):
        NotificationPreference.objects.create(
            user=self.employee_user,
            calendar_in_app_enabled=False,
        )
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("workcalendar:home"),
            {
                "calendar_action": "save_calendar",
                "name": "Kuwait Calendar",
                "region_code": "KW",
                "notes": "Updated weekly off settings.",
                "is_active": "on",
                "weekend_day_selection": ["4", "5"],
            },
            follow=True,
        )

        self.assertFalse(
            InAppNotification.objects.filter(
                recipient=self.employee_user,
                category=InAppNotification.CATEGORY_CALENDAR,
            ).exists()
        )
