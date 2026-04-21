import tempfile
from datetime import date, time

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from notifications.models import InAppNotification
from organization.models import Branch, Company, Department, JobTitle, Section

from .models import (
    BranchWeeklyDutyOption,
    Employee,
    EmployeeActionRecord,
    EmployeeAttendanceCorrection,
    EmployeeAttendanceLedger,
    EmployeeDocumentRequest,
    EmployeeLeave,
    EmployeeRequiredSubmission,
)


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
class EmployeeRequestNotificationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.company = Company.objects.create(name="Notify Company")
        self.branch = Branch.objects.create(company=self.company, name="Main Branch")
        self.department = Department.objects.create(company=self.company, name="Operations")
        self.section = Section.objects.create(department=self.department, name="Frontline")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Team Member",
        )

        self.employee_user = self.user_model.objects.create_user(
            email="employee@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )
        self.hr_user = self.user_model.objects.create_user(
            email="hr@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        self.operations_user = self.user_model.objects.create_user(
            email="ops@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_OPERATIONS_MANAGER,
        )
        self.supervisor_user = self.user_model.objects.create_user(
            email="supervisor@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_SUPERVISOR,
        )

        self.employee = Employee.objects.create(
            user=self.employee_user,
            employee_id="EMP001",
            full_name="Employee One",
            email="employee@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary="500.00",
        )
        self.supervisor_employee = Employee.objects.create(
            user=self.supervisor_user,
            employee_id="SUP001",
            full_name="Branch Supervisor",
            email="supervisor@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=JobTitle.objects.create(
                department=self.department,
                section=self.section,
                name="Branch Supervisor",
            ),
            hire_date=date(2025, 1, 1),
            salary="900.00",
        )

    def test_document_request_submission_creates_employee_notification(self):
        self.client.force_login(self.employee_user)

        self.client.post(
            reverse("employees:employee_document_request_create", args=[self.employee.pk]),
            {
                "title": "Salary Certificate",
                "request_type": EmployeeDocumentRequest.REQUEST_TYPE_SALARY_CERTIFICATE,
                "priority": EmployeeDocumentRequest.PRIORITY_NORMAL,
                "request_note": "Needed for the bank.",
                "needed_by_date": "2026-05-05",
            },
            follow=True,
        )

        notification = InAppNotification.objects.get(recipient=self.employee_user, category=InAppNotification.CATEGORY_REQUEST)
        self.assertIn("Document request submitted", notification.title)
        self.assertIn("salary certificate request", notification.body.lower())

    def test_document_request_review_notifies_employee_about_status_change(self):
        document_request = EmployeeDocumentRequest.objects.create(
            employee=self.employee,
            created_by=self.employee_user,
            title="Experience Certificate",
            request_type=EmployeeDocumentRequest.REQUEST_TYPE_EXPERIENCE_CERTIFICATE,
            priority=EmployeeDocumentRequest.PRIORITY_HIGH,
            status=EmployeeDocumentRequest.STATUS_REQUESTED,
            submitted_at=None,
        )
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("employees:employee_document_request_review", args=[document_request.pk]),
            {
                "status": EmployeeDocumentRequest.STATUS_APPROVED,
                "management_note": "Being prepared now.",
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertIn("Document request updated", notification.title)
        self.assertIn("approved", notification.body.lower())

    def test_required_submission_create_notifies_employee(self):
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("employees:employee_required_submission_create", args=[self.employee.pk]),
            {
                "title": "Renew Passport Copy",
                "request_type": EmployeeRequiredSubmission.REQUEST_TYPE_PASSPORT_COPY,
                "priority": EmployeeRequiredSubmission.PRIORITY_HIGH,
                "instructions": "Upload the renewed passport copy.",
                "due_date": "2026-05-10",
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertIn("Required document requested", notification.title)
        self.assertIn("passport copy", notification.body.lower())

    def test_required_submission_submit_notifies_creator(self):
        submission_request = EmployeeRequiredSubmission.objects.create(
            employee=self.employee,
            created_by=self.hr_user,
            title="Civil ID Copy",
            request_type=EmployeeRequiredSubmission.REQUEST_TYPE_CIVIL_ID_COPY,
            status=EmployeeRequiredSubmission.STATUS_REQUESTED,
        )
        self.client.force_login(self.employee_user)

        self.client.post(
            reverse("employees:employee_required_submission_submit", args=[submission_request.pk]),
            {
                "employee_note": "Uploaded the latest card.",
                "response_reference_number": "CID-2026",
                "response_issue_date": "2026-04-01",
                "response_expiry_date": "2027-04-01",
                "response_file": SimpleUploadedFile("civil-id.pdf", b"file-content", content_type="application/pdf"),
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.hr_user).latest("id")
        self.assertIn("Required document submitted", notification.title)
        self.assertIn("submitted", notification.body.lower())

    def test_leave_stage_change_notifies_next_reviewer_and_employee(self):
        leave_record = EmployeeLeave.objects.create(
            employee=self.employee,
            requested_by=self.employee_user,
            leave_type=EmployeeLeave.LEAVE_TYPE_ANNUAL,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            reason="Family trip",
            status=EmployeeLeave.STATUS_PENDING,
            current_stage=EmployeeLeave.STAGE_SUPERVISOR_REVIEW,
            created_by="Employee",
            updated_by="Employee",
        )
        self.client.force_login(self.supervisor_user)

        self.client.post(
            reverse("employees:employee_leave_approve", args=[self.employee.pk, leave_record.pk]),
            {
                "approval_note": "Forwarding to operations.",
            },
            follow=True,
        )

        employee_notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        operations_notification = InAppNotification.objects.filter(recipient=self.operations_user).latest("id")
        self.assertIn("Leave moved to operations review", employee_notification.title)
        self.assertIn("operations review", employee_notification.body.lower())
        self.assertIn("awaiting review", operations_notification.title.lower())

    def test_attendance_correction_review_notifies_request_stakeholders(self):
        attendance_entry = EmployeeAttendanceLedger.objects.create(
            employee=self.employee,
            attendance_date=date(2026, 4, 20),
            day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            shift=EmployeeAttendanceLedger.SHIFT_MORNING,
            clock_in_time=time(9, 0),
            clock_out_time=time(17, 0),
            scheduled_hours="8.00",
            source=EmployeeAttendanceLedger.SOURCE_MANUAL,
        )
        correction = EmployeeAttendanceCorrection.objects.create(
            linked_attendance=attendance_entry,
            employee=self.employee,
            requested_by=self.hr_user,
            requested_day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            requested_clock_in_time=None,
            requested_clock_out_time=None,
            requested_scheduled_hours="8.00",
            requested_late_minutes=0,
            requested_early_departure_minutes=0,
            requested_overtime_minutes=0,
            request_reason="Need to update overtime minutes.",
            status=EmployeeAttendanceCorrection.STATUS_PENDING,
            created_by="HR",
            updated_by="HR",
        )
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("employees:employee_attendance_correction_reject", args=[correction.pk]),
            {
                "review_notes": "Please resubmit with the exact time.",
            },
            follow=True,
        )

        employee_notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        requester_notification = InAppNotification.objects.filter(recipient=self.hr_user).latest("id")
        self.assertIn("Attendance correction updated", employee_notification.title)
        self.assertIn("rejected", employee_notification.body.lower())
        self.assertIn("exact time", requester_notification.body.lower())

    def test_employee_status_update_notifies_employee(self):
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("employees:employee_status_update", args=[self.employee.pk]),
            {
                "target_status": Employee.EMPLOYMENT_STATUS_ON_LEAVE,
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertEqual(notification.category, InAppNotification.CATEGORY_EMPLOYEE)
        self.assertIn("Employment status updated", notification.title)
        self.assertIn("on leave", notification.body.lower())

    def test_employee_action_record_create_notifies_employee(self):
        self.client.force_login(self.hr_user)

        self.client.post(
            reverse("employees:employee_action_record_create", args=[self.employee.pk]),
            {
                "title": "Late Arrival",
                "action_type": EmployeeActionRecord.ACTION_TYPE_LATENESS,
                "status": EmployeeActionRecord.STATUS_OPEN,
                "severity": EmployeeActionRecord.SEVERITY_MEDIUM,
                "action_date": "2026-04-21",
                "description": "Employee arrived late due to traffic.",
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(recipient=self.employee_user).latest("id")
        self.assertEqual(notification.category, InAppNotification.CATEGORY_EMPLOYEE)
        self.assertIn("Employee record added", notification.title)
        self.assertIn("late", notification.body.lower())

    def test_manual_schedule_update_notifies_affected_employee(self):
        duty_option = BranchWeeklyDutyOption.objects.create(
            branch=self.branch,
            label="Morning Shift",
            duty_type="shift",
            default_start_time=time(9, 0),
            default_end_time=time(17, 0),
            is_active=True,
        )
        self.client.force_login(self.supervisor_user)

        self.client.post(
            reverse("employees:self_service_weekly_schedule"),
            {
                "schedule_action": "save_manual_schedule_builder",
                "week": "2026-04-19",
                f"manual_duty_{self.employee.id}_2026-04-20": str(duty_option.id),
            },
            follow=True,
        )

        notification = InAppNotification.objects.filter(
            recipient=self.employee_user,
            category=InAppNotification.CATEGORY_SCHEDULE,
        ).latest("id")
        self.assertIn("Weekly schedule updated", notification.title)
        self.assertIn("week starting", notification.body.lower())
