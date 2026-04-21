import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from employees.models import Employee
from notifications.models import InAppNotification
from organization.models import Branch, Company, Department, JobTitle, Section

from .models import BranchPost


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    STORAGES={
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    },
)
class BranchWorkspaceNotificationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.company = Company.objects.create(name="Operations Notify Co")
        self.branch = Branch.objects.create(company=self.company, name="Airport Branch")
        self.department = Department.objects.create(company=self.company, name="Operations")
        self.section = Section.objects.create(department=self.department, name="Duty")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Crew",
        )

        self.supervisor_user = self.user_model.objects.create_user(
            email="branch-supervisor@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_SUPERVISOR,
        )
        self.employee_user = self.user_model.objects.create_user(
            email="branch-employee@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )

        self.supervisor_employee = Employee.objects.create(
            user=self.supervisor_user,
            employee_id="OPS001",
            full_name="Branch Supervisor",
            email="branch-supervisor@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=JobTitle.objects.create(
                department=self.department,
                section=self.section,
                name="Supervisor",
            ),
            hire_date=date(2025, 1, 1),
            salary="900.00",
        )
        self.employee = Employee.objects.create(
            user=self.employee_user,
            employee_id="OPS002",
            full_name="Frontline Employee",
            email="branch-employee@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2025, 6, 1),
            salary="500.00",
        )

    def test_branch_task_assignment_notifies_assignee(self):
        self.client.force_login(self.supervisor_user)

        self.client.post(
            reverse("operations:branch_post_create", args=[self.branch.pk]),
            {
                "post_type": BranchPost.POST_TYPE_TASK,
                "title": "Closing stock count",
                "body": "Please finish the stock count before closing.",
                "assignee": str(self.employee.pk),
                "priority": BranchPost.PRIORITY_HIGH,
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertEqual(notification.category, InAppNotification.CATEGORY_OPERATIONS)
        self.assertIn("assigned", notification.title.lower())
        self.assertIn("airport branch", notification.body.lower())

    def test_branch_announcement_notifies_branch_team(self):
        self.client.force_login(self.supervisor_user)

        self.client.post(
            reverse("operations:branch_post_create", args=[self.branch.pk]),
            {
                "post_type": BranchPost.POST_TYPE_ANNOUNCEMENT,
                "title": "Friday briefing",
                "body": "Briefing starts at 8:30 AM.",
                "priority": BranchPost.PRIORITY_MEDIUM,
                "requires_acknowledgement": "on",
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertEqual(notification.category, InAppNotification.CATEGORY_OPERATIONS)
        self.assertIn("announcement", notification.title.lower())
        self.assertIn("airport branch", notification.body.lower())

    def test_branch_status_update_notifies_author(self):
        post = BranchPost.objects.create(
            branch=self.branch,
            author_user=self.employee_user,
            author_employee=self.employee,
            title="Broken printer",
            body="Printer near desk 2 is not working.",
            post_type=BranchPost.POST_TYPE_ISSUE,
            status=BranchPost.STATUS_OPEN,
        )
        self.client.force_login(self.supervisor_user)

        self.client.post(
            reverse("operations:branch_post_status_update", args=[post.pk]),
            {
                "target_status": BranchPost.STATUS_APPROVED,
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertEqual(notification.category, InAppNotification.CATEGORY_OPERATIONS)
        self.assertIn("status updated", notification.title.lower())
        self.assertIn("approved", notification.body.lower())
