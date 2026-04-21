from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from employees.models import Employee
from notifications.models import InAppNotification
from organization.models import Branch, Company, Department, JobTitle, Section

from .models import HRAnnouncement, HRPolicy


class HRNotificationSignalTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.company = Company.objects.create(name="HR Notify Co")
        self.branch = Branch.objects.create(company=self.company, name="Main Branch")
        self.department = Department.objects.create(company=self.company, name="HR Department")
        self.section = Section.objects.create(department=self.department, name="General")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Employee",
        )
        self.employee_user = self.user_model.objects.create_user(
            email="hr-employee@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )
        self.hr_user = self.user_model.objects.create_user(
            email="hr-manager@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        self.supervisor_user = self.user_model.objects.create_user(
            email="hr-supervisor@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_SUPERVISOR,
        )
        self.employee = Employee.objects.create(
            user=self.employee_user,
            employee_id="HRE001",
            full_name="HR Employee",
            email="hr-employee@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
        )

    def test_active_hr_announcement_notifies_target_audience(self):
        HRAnnouncement.objects.create(
            title="New Dress Code",
            audience=HRAnnouncement.AUDIENCE_EMPLOYEES,
            message="Please review the updated dress code policy.",
            published_at=date(2026, 4, 22),
            is_active=True,
        )

        self.assertTrue(
            InAppNotification.objects.filter(
                recipient=self.employee_user,
                category=InAppNotification.CATEGORY_HR,
                title__icontains="announcement",
            ).exists()
        )
        self.assertFalse(
            InAppNotification.objects.filter(
                recipient=self.hr_user,
                category=InAppNotification.CATEGORY_HR,
                title__icontains="announcement",
            ).exists()
        )

    def test_active_hr_policy_notifies_company_users(self):
        HRPolicy.objects.create(
            company=self.company,
            title="Travel Reimbursement",
            category=HRPolicy.CATEGORY_BENEFIT,
            effective_date=date(2026, 5, 1),
            is_active=True,
        )

        notifications = InAppNotification.objects.filter(category=InAppNotification.CATEGORY_HR)
        self.assertTrue(notifications.filter(recipient=self.employee_user, title__icontains="policy").exists())
        self.assertTrue(notifications.filter(recipient=self.hr_user, title__icontains="policy").exists())
        self.assertTrue(notifications.filter(recipient=self.supervisor_user, title__icontains="policy").exists())
