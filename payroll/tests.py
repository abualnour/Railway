from datetime import date, time
from decimal import Decimal

from django.contrib.messages import get_messages
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse

from employees.models import Employee, EmployeeAttendanceLedger
from notifications.models import InAppNotification, NotificationPreference
from organization.models import Branch, Company, Department, JobTitle, Section

from .models import PayrollAdjustment, PayrollBonus, PayrollLine, PayrollPeriod, PayrollProfile
from .views import (
    build_payroll_lines_for_period,
    build_payroll_line_breakdown,
    calculate_overtime_amount,
    calculate_unpaid_leave_deduction,
)


class PayrollPeriodLockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="hr@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_HR,
        )
        self.client.force_login(self.user)

        self.company = Company.objects.create(name="NourAxis Co")
        self.branch = Branch.objects.create(company=self.company, name="Main Branch")
        self.department = Department.objects.create(company=self.company, name="Operations")
        self.section = Section.objects.create(department=self.department, name="Payroll")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Payroll Officer",
        )
        self.employee = Employee.objects.create(
            employee_id="EMP100",
            full_name="Test Employee",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("1200.00"),
        )
        self.payroll_profile = PayrollProfile.objects.create(
            employee=self.employee,
            company=self.company,
            base_salary=Decimal("1200.00"),
            housing_allowance=Decimal("100.00"),
            transport_allowance=Decimal("50.00"),
            fixed_deduction=Decimal("25.00"),
        )

    def _create_period(self, title, status):
        return PayrollPeriod.objects.create(
            company=self.company,
            title=title,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            status=status,
        )

    def _create_line(self, payroll_period, notes="Original note"):
        return PayrollLine.objects.create(
            payroll_period=payroll_period,
            employee=self.employee,
            base_salary=Decimal("1200.00"),
            allowances=Decimal("150.00"),
            deductions=Decimal("25.00"),
            overtime_amount=Decimal("0.00"),
            net_pay=Decimal("1325.00"),
            notes=notes,
        )

    def _messages(self, response):
        return [str(message) for message in get_messages(response.wsgi_request)]

    def test_review_period_still_allows_line_updates(self):
        payroll_period = self._create_period("April Review", PayrollPeriod.STATUS_REVIEW)
        payroll_line = self._create_line(payroll_period)

        response = self.client.post(
            reverse("payroll:period_detail", args=[payroll_period.pk]),
            {
                "payroll_action": "update_line",
                "line_id": payroll_line.pk,
                "base_salary": "1300.00",
                "allowances": "200.00",
                "deductions": "40.00",
                "overtime_amount": "10.00",
                "notes": "Reviewed update",
            },
            follow=True,
        )

        payroll_line.refresh_from_db()
        self.assertEqual(payroll_line.base_salary, Decimal("1300.00"))
        self.assertEqual(payroll_line.net_pay, Decimal("1470.00"))
        self.assertIn("Payroll line updated", " ".join(self._messages(response)))

    def test_approved_period_blocks_line_updates(self):
        payroll_period = self._create_period("April Approved", PayrollPeriod.STATUS_APPROVED)
        payroll_line = self._create_line(payroll_period)

        response = self.client.post(
            reverse("payroll:period_detail", args=[payroll_period.pk]),
            {
                "payroll_action": "update_line",
                "line_id": payroll_line.pk,
                "base_salary": "1300.00",
                "allowances": "200.00",
                "deductions": "40.00",
                "overtime_amount": "10.00",
                "notes": "Should not save",
            },
            follow=True,
        )

        payroll_line.refresh_from_db()
        self.assertEqual(payroll_line.base_salary, Decimal("1200.00"))
        self.assertEqual(payroll_line.notes, "Original note")
        self.assertIn("Payroll lines are locked", " ".join(self._messages(response)))

    def test_paid_period_blocks_adjustments_and_bonus_application(self):
        payroll_period = self._create_period("April Paid", PayrollPeriod.STATUS_PAID)
        payroll_line = self._create_line(payroll_period)
        payroll_bonus = PayrollBonus.objects.create(
            employee=self.employee,
            company=self.company,
            title="Performance Bonus",
            awarded_amount=Decimal("300.00"),
            paid_amount=Decimal("0.00"),
            award_date=date(2026, 4, 15),
        )

        adjustment_response = self.client.post(
            reverse("payroll:period_detail", args=[payroll_period.pk]),
            {
                "payroll_action": "add_adjustment",
                "line_id": payroll_line.pk,
                "title": "Manual Deduction",
                "adjustment_type": PayrollAdjustment.TYPE_DEDUCTION,
                "amount": "20.00",
                "notes": "Should not save",
            },
            follow=True,
        )
        self.assertEqual(PayrollAdjustment.objects.filter(payroll_line=payroll_line).count(), 0)
        self.assertIn("Payroll adjustments are locked", " ".join(self._messages(adjustment_response)))

        bonus_response = self.client.post(
            reverse("payroll:period_detail", args=[payroll_period.pk]),
            {
                "payroll_action": "apply_bonus",
                "line_id": payroll_line.pk,
                "payroll_bonus": payroll_bonus.pk,
                "amount": "50.00",
                "notes": "Should not save",
            },
            follow=True,
        )

        payroll_bonus.refresh_from_db()
        self.assertEqual(payroll_bonus.paid_amount, Decimal("0.00"))
        self.assertEqual(PayrollAdjustment.objects.filter(payroll_line=payroll_line).count(), 0)
        self.assertIn("Bonus application is locked", " ".join(self._messages(bonus_response)))

    def test_generate_lines_is_blocked_once_period_is_approved(self):
        payroll_period = self._create_period("April Locked", PayrollPeriod.STATUS_APPROVED)

        response = self.client.post(
            reverse("payroll:home"),
            {
                "payroll_action": "generate_lines",
                "payroll_period": payroll_period.pk,
            },
            follow=True,
        )

        self.assertEqual(PayrollLine.objects.filter(payroll_period=payroll_period).count(), 0)
        self.assertIn("cannot be regenerated", " ".join(self._messages(response)))


class PayrollApprovalSnapshotTests(TestCase):
    def setUp(self):
        self.finance_user = get_user_model().objects.create_user(
            email="finance@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_FINANCE_MANAGER,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.finance_user)

        self.company = Company.objects.create(name="Snapshot Co")
        self.branch = Branch.objects.create(company=self.company, name="Snapshot Branch")
        self.department = Department.objects.create(company=self.company, name="Finance")
        self.section = Section.objects.create(department=self.department, name="Payroll")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Finance Analyst",
        )
        self.employee = Employee.objects.create(
            employee_id="EMP200",
            full_name="Frozen Employee",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("2100.00"),
        )
        self.payroll_profile = PayrollProfile.objects.create(
            employee=self.employee,
            company=self.company,
            base_salary=Decimal("2100.00"),
            housing_allowance=Decimal("200.00"),
            transport_allowance=Decimal("100.00"),
            fixed_deduction=Decimal("50.00"),
        )
        self.payroll_period = PayrollPeriod.objects.create(
            company=self.company,
            title="May 2026",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            status=PayrollPeriod.STATUS_REVIEW,
        )
        self.payroll_line = PayrollLine.objects.create(
            payroll_period=self.payroll_period,
            employee=self.employee,
            base_salary=Decimal("2100.00"),
            allowances=Decimal("300.00"),
            deductions=Decimal("50.00"),
            overtime_amount=Decimal("25.00"),
            net_pay=Decimal("2375.00"),
            notes="Approved payroll note",
        )
        self.adjustment = PayrollAdjustment.objects.create(
            payroll_line=self.payroll_line,
            title="Manual bonus",
            adjustment_type=PayrollAdjustment.TYPE_ALLOWANCE,
            amount=Decimal("75.00"),
            notes="Frozen adjustment note",
        )
        self.payroll_line.net_pay = self.payroll_line.calculate_net_pay()
        self.payroll_line.save(update_fields=["net_pay", "updated_at"])

    def test_approval_creates_snapshot_payload(self):
        response = self.client.post(
            reverse("payroll:period_detail", args=[self.payroll_period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_APPROVED,
            },
            follow=True,
        )

        self.payroll_period.refresh_from_db()
        self.payroll_line.refresh_from_db()

        self.assertEqual(self.payroll_period.status, PayrollPeriod.STATUS_APPROVED)
        self.assertIsNotNone(self.payroll_period.approved_at)
        self.assertTrue(self.payroll_line.has_snapshot)
        self.assertEqual(self.payroll_line.snapshot_payload["employee"]["full_name"], "Frozen Employee")
        self.assertEqual(self.payroll_line.snapshot_payload["line"]["net_pay"], "2450.00")
        self.assertEqual(
            self.payroll_line.snapshot_payload["line"]["breakdown"]["adjustment_allowances_total"],
            "75.00",
        )
        self.assertEqual(self.payroll_line.snapshot_payload["adjustments"][0]["title"], "Manual bonus")
        self.assertIn("moved to Approved", " ".join(str(message) for message in get_messages(response.wsgi_request)))

    def test_reopen_to_review_clears_snapshot(self):
        self.client.post(
            reverse("payroll:period_detail", args=[self.payroll_period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_APPROVED,
            },
            follow=True,
        )

        response = self.client.post(
            reverse("payroll:period_detail", args=[self.payroll_period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_REVIEW,
            },
            follow=True,
        )

        self.payroll_period.refresh_from_db()
        self.payroll_line.refresh_from_db()

        self.assertEqual(self.payroll_period.status, PayrollPeriod.STATUS_REVIEW)
        self.assertIsNone(self.payroll_period.approved_at)
        self.assertIsNone(self.payroll_line.snapshot_payload)
        self.assertIsNone(self.payroll_line.snapshot_taken_at)
        self.assertIn("moved to In Review", " ".join(str(message) for message in get_messages(response.wsgi_request)))

    def test_payslip_uses_frozen_snapshot_after_employee_changes(self):
        self.client.post(
            reverse("payroll:period_detail", args=[self.payroll_period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_APPROVED,
            },
            follow=True,
        )

        self.employee.full_name = "Changed Employee"
        self.employee.save(update_fields=["full_name"])
        self.job_title.name = "Changed Title"
        self.job_title.save(update_fields=["name"])
        self.branch.name = "Changed Branch"
        self.branch.save(update_fields=["name"])
        self.payroll_line.notes = "Live note should not show"
        self.payroll_line.save(update_fields=["notes", "updated_at"])
        self.adjustment.title = "Changed adjustment"
        self.adjustment.save(update_fields=["title", "updated_at"])

        response = self.client.get(reverse("payroll:line_payslip", args=[self.payroll_line.pk]))

        self.assertContains(response, "Frozen Employee")
        self.assertContains(response, "Finance Analyst")
        self.assertContains(response, "Snapshot Branch")
        self.assertContains(response, "Approved payroll note")
        self.assertContains(response, "Manual bonus")
        self.assertContains(response, "Calculation Trace")
        self.assertContains(response, "75.00")
        self.assertNotContains(response, "Changed Employee")
        self.assertNotContains(response, "Changed Title")
        self.assertNotContains(response, "Changed Branch")
        self.assertNotContains(response, "Live note should not show")
        self.assertNotContains(response, "Changed adjustment")

    def test_pdf_payslip_uses_frozen_snapshot_after_employee_changes(self):
        self.client.post(
            reverse("payroll:period_detail", args=[self.payroll_period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_APPROVED,
            },
            follow=True,
        )

        self.employee.full_name = "Changed Employee"
        self.employee.save(update_fields=["full_name"])

        response = self.client.get(reverse("payroll:line_payslip_pdf", args=[self.payroll_line.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))


class PayrollCalculationTraceTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Trace Co")
        self.branch = Branch.objects.create(company=self.company, name="Trace Branch")
        self.department = Department.objects.create(company=self.company, name="Finance")
        self.section = Section.objects.create(department=self.department, name="Payroll")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Payroll Specialist",
        )
        self.employee = Employee.objects.create(
            employee_id="EMP250",
            full_name="Trace Employee",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 2, 1),
            salary=Decimal("2000.00"),
        )
        self.payroll_period = PayrollPeriod.objects.create(
            company=self.company,
            title="Trace Period",
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 31),
            status=PayrollPeriod.STATUS_REVIEW,
        )
        self.payroll_line = PayrollLine.objects.create(
            payroll_period=self.payroll_period,
            employee=self.employee,
            base_salary=Decimal("2000.00"),
            allowances=Decimal("250.00"),
            deductions=Decimal("80.00"),
            overtime_amount=Decimal("35.00"),
            net_pay=Decimal("2205.00"),
            notes="Trace note",
        )
        PayrollAdjustment.objects.create(
            payroll_line=self.payroll_line,
            title="Manual allowance",
            adjustment_type=PayrollAdjustment.TYPE_ALLOWANCE,
            amount=Decimal("40.00"),
        )
        PayrollAdjustment.objects.create(
            payroll_line=self.payroll_line,
            title="Penalty",
            adjustment_type=PayrollAdjustment.TYPE_DEDUCTION,
            amount=Decimal("20.00"),
        )
        self.payroll_line.net_pay = self.payroll_line.calculate_net_pay()
        self.payroll_line.save(update_fields=["net_pay", "updated_at"])

    def test_build_payroll_line_breakdown_includes_adjustment_totals(self):
        breakdown = build_payroll_line_breakdown(self.payroll_line)

        self.assertEqual(breakdown["base_salary"], "2000.00")
        self.assertEqual(breakdown["allowances"], "250.00")
        self.assertEqual(breakdown["overtime_amount"], "35.00")
        self.assertEqual(breakdown["adjustment_allowances_total"], "40.00")
        self.assertEqual(breakdown["gross_total"], "2325.00")
        self.assertEqual(breakdown["fixed_deductions"], "80.00")
        self.assertEqual(breakdown["adjustment_deductions_total"], "20.00")
        self.assertEqual(breakdown["total_deductions_value"], "100.00")
        self.assertEqual(breakdown["net_pay"], "2225.00")

    def test_period_detail_shows_calculation_trace(self):
        user = get_user_model().objects.create_user(
            email="trace-hr@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_HR,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("payroll:period_detail", args=[self.payroll_period.pk]))

        self.assertContains(response, "Calculation Trace")
        self.assertContains(response, "Adjustment Allowances")
        self.assertContains(response, "40.00")
        self.assertContains(response, "Total Deductions")
        self.assertContains(response, "100.00")

    def test_html_payslip_shows_download_pdf_action(self):
        user = get_user_model().objects.create_user(
            email="trace-finance@example.com",
            password="test-pass-123",
            role=get_user_model().ROLE_FINANCE_MANAGER,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("payroll:line_payslip", args=[self.payroll_line.pk]))

        self.assertContains(response, "Download PDF")
        self.assertContains(response, reverse("payroll:line_payslip_pdf", args=[self.payroll_line.pk]))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="payroll@example.com",
)
class PayrollStatusNotificationTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.finance_user = self.user_model.objects.create_user(
            email="finance-team@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_FINANCE_MANAGER,
        )
        self.hr_user = self.user_model.objects.create_user(
            email="hr-team@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        self.operations_user = self.user_model.objects.create_user(
            email="ops-team@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_OPERATIONS_MANAGER,
        )
        self.employee_user = self.user_model.objects.create_user(
            email="employee-login@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )
        self.company = Company.objects.create(name="Notify Co")
        self.branch = Branch.objects.create(company=self.company, name="Notify Branch")
        self.department = Department.objects.create(company=self.company, name="Notify Department")
        self.section = Section.objects.create(department=self.department, name="Notify Section")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Notify Role",
        )
        self.employee = Employee.objects.create(
            user=self.employee_user,
            employee_id="EMP900",
            full_name="Payroll Employee",
            email="employee@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("1000.00"),
        )
        self.period = PayrollPeriod.objects.create(
            company=self.company,
            title="September 2026",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            status=PayrollPeriod.STATUS_DRAFT,
        )
        self.payroll_line = PayrollLine.objects.create(
            payroll_period=self.period,
            employee=self.employee,
            base_salary=Decimal("1000.00"),
            allowances=Decimal("100.00"),
            deductions=Decimal("20.00"),
            overtime_amount=Decimal("0.00"),
            net_pay=Decimal("1080.00"),
            notes="Ready for payment",
        )

    def _approve_period_as_finance(self):
        approver = self.user_model.objects.create_user(
            email="payroll-finance@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_FINANCE_MANAGER,
        )
        self.period.status = PayrollPeriod.STATUS_REVIEW
        self.period.save(update_fields=["status", "updated_at"])
        self.client.force_login(approver)
        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_APPROVED,
            },
            follow=True,
        )
        return approver

    def test_submit_for_review_emails_finance_only(self):
        requester = self.user_model.objects.create_user(
            email="payroll-hr@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        self.client.force_login(requester)

        response = self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_REVIEW,
            },
            follow=True,
        )

        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.STATUS_REVIEW)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["finance-team@example.com"])
        self.assertEqual(
            InAppNotification.objects.filter(
                recipient=self.finance_user,
                title__icontains="In Review",
            ).count(),
            1,
        )
        self.assertIn("September 2026", mail.outbox[0].subject)
        self.assertIn("is now In Review", mail.outbox[0].subject)
        self.assertContains(response, "moved to In Review")

    def test_approval_and_paid_notifications_email_hr_and_finance(self):
        approver = self._approve_period_as_finance()
        approval_response = self.client.get(reverse("payroll:period_detail", args=[self.period.pk]))

        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.STATUS_APPROVED)
        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(
            mail.outbox[0].to,
            ["finance-team@example.com", "hr-team@example.com", "payroll-finance@example.com"],
        )
        self.assertEqual(
            InAppNotification.objects.filter(title__icontains="Approved").count(),
            3,
        )
        self.assertIn("Approved", mail.outbox[0].subject)
        self.assertContains(approval_response, "September 2026")

        paid_response = self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_PAID,
            },
            follow=True,
        )

        self.period.refresh_from_db()
        self.assertEqual(self.period.status, PayrollPeriod.STATUS_PAID)
        self.assertEqual(len(mail.outbox), 3)
        self.assertCountEqual(
            mail.outbox[1].to,
            ["finance-team@example.com", "hr-team@example.com", "payroll-finance@example.com"],
        )
        self.assertEqual(
            InAppNotification.objects.filter(title__icontains="Paid").count(),
            3,
        )
        self.assertIn("Paid", mail.outbox[1].subject)
        self.assertEqual(mail.outbox[2].to, ["employee@example.com"])
        self.assertIn("Your Payslip Is Ready", mail.outbox[2].subject)
        self.assertIn(
            reverse("payroll:employee_line_payslip", args=[self.payroll_line.pk]),
            mail.outbox[2].body,
        )
        self.assertIn(
            reverse("payroll:employee_line_payslip_pdf", args=[self.payroll_line.pk]),
            mail.outbox[2].body,
        )
        self.assertEqual(
            InAppNotification.objects.filter(
                recipient=self.employee_user,
                title__icontains="Your payslip is ready",
            ).count(),
            1,
        )
        self.assertContains(paid_response, "moved to Paid")
        self.assertNotIn("ops-team@example.com", mail.outbox[1].to)

    def test_paid_employee_delivery_respects_email_preference(self):
        approver = self._approve_period_as_finance()
        NotificationPreference.objects.create(
            user=self.employee_user,
            payroll_employee_email_enabled=False,
        )
        mail.outbox.clear()

        self.client.force_login(approver)
        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_PAID,
            },
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 1)
        self.assertCountEqual(
            mail.outbox[0].to,
            ["finance-team@example.com", "hr-team@example.com", "payroll-finance@example.com"],
        )
        self.assertEqual(
            InAppNotification.objects.filter(
                recipient=self.employee_user,
                title__icontains="Your payslip is ready",
            ).count(),
            1,
        )

    def test_paid_employee_delivery_respects_in_app_preference(self):
        approver = self._approve_period_as_finance()
        NotificationPreference.objects.create(
            user=self.employee_user,
            payroll_employee_in_app_enabled=False,
        )
        mail.outbox.clear()

        self.client.force_login(approver)
        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_PAID,
            },
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["employee@example.com"])
        self.assertEqual(
            InAppNotification.objects.filter(
                recipient=self.employee_user,
                title__icontains="Your payslip is ready",
            ).count(),
            0,
        )

    def test_paid_employee_delivery_respects_pdf_link_preference(self):
        approver = self._approve_period_as_finance()
        NotificationPreference.objects.create(
            user=self.employee_user,
            payroll_employee_include_pdf_link=False,
        )
        mail.outbox.clear()

        self.client.force_login(approver)
        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_PAID,
            },
            follow=True,
        )

        employee_email = mail.outbox[1]
        self.assertEqual(employee_email.to, ["employee@example.com"])
        self.assertIn(
            reverse("payroll:employee_line_payslip", args=[self.payroll_line.pk]),
            employee_email.body,
        )
        self.assertNotIn(
            reverse("payroll:employee_line_payslip_pdf", args=[self.payroll_line.pk]),
            employee_email.body,
        )
        employee_notification = InAppNotification.objects.get(
            recipient=self.employee_user,
            title__icontains="Your payslip is ready",
        )
        self.assertNotIn("Download your PDF copy", employee_notification.body)

    def test_management_workflow_email_respects_manager_preference(self):
        requester = self.user_model.objects.create_user(
            email="payroll-hr-pref@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        NotificationPreference.objects.create(
            user=self.finance_user,
            payroll_management_email_enabled=False,
        )
        self.client.force_login(requester)

        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_REVIEW,
            },
            follow=True,
        )

        self.assertEqual(len(mail.outbox), 0)

    def test_management_workflow_in_app_respects_manager_preference(self):
        requester = self.user_model.objects.create_user(
            email="payroll-hr-alerts@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_HR,
        )
        NotificationPreference.objects.create(
            user=self.finance_user,
            payroll_management_in_app_enabled=False,
        )
        self.client.force_login(requester)

        self.client.post(
            reverse("payroll:period_detail", args=[self.period.pk]),
            {
                "payroll_action": "change_period_status",
                "target_status": PayrollPeriod.STATUS_REVIEW,
            },
            follow=True,
        )

        self.assertEqual(
            InAppNotification.objects.filter(
                recipient=self.finance_user,
                title__icontains="In Review",
            ).count(),
            0,
        )


class EmployeePayslipAccessTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.company = Company.objects.create(name="Self Service Co")
        self.branch = Branch.objects.create(company=self.company, name="Employee Branch")
        self.department = Department.objects.create(company=self.company, name="Employee Department")
        self.section = Section.objects.create(department=self.department, name="Employee Section")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Employee Role",
        )
        self.employee_user = self.user_model.objects.create_user(
            email="self-service@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )
        self.other_user = self.user_model.objects.create_user(
            email="other-employee@example.com",
            password="test-pass-123",
            role=self.user_model.ROLE_EMPLOYEE,
        )
        self.employee = Employee.objects.create(
            user=self.employee_user,
            employee_id="EMP901",
            full_name="Self Service Employee",
            email="self-service@example.com",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("1500.00"),
        )
        self.period = PayrollPeriod.objects.create(
            company=self.company,
            title="October 2026",
            period_start=date(2026, 10, 1),
            period_end=date(2026, 10, 31),
            status=PayrollPeriod.STATUS_PAID,
        )
        self.line = PayrollLine.objects.create(
            payroll_period=self.period,
            employee=self.employee,
            base_salary=Decimal("1500.00"),
            allowances=Decimal("100.00"),
            deductions=Decimal("10.00"),
            overtime_amount=Decimal("15.00"),
            net_pay=Decimal("1605.00"),
            notes="Employee copy",
        )

    def test_employee_can_open_own_self_service_payslip(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(reverse("payroll:employee_line_payslip", args=[self.line.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Self Service Employee")
        self.assertContains(response, "Download PDF")

    def test_employee_can_download_own_self_service_payslip_pdf(self):
        self.client.force_login(self.employee_user)

        response = self.client.get(reverse("payroll:employee_line_payslip_pdf", args=[self.line.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_employee_cannot_open_someone_else_payslip(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("payroll:employee_line_payslip", args=[self.line.pk]))

        self.assertEqual(response.status_code, 403)


class PayrollOvertimeCalculationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Overtime Co")
        self.branch = Branch.objects.create(company=self.company, name="Overtime Branch")
        self.department = Department.objects.create(company=self.company, name="Operations")
        self.section = Section.objects.create(department=self.department, name="Coverage")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Shift Worker",
        )
        self.employee = Employee.objects.create(
            employee_id="EMP300",
            full_name="Overtime Employee",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("2400.00"),
        )
        self.payroll_profile = PayrollProfile.objects.create(
            employee=self.employee,
            company=self.company,
            base_salary=Decimal("2400.00"),
            housing_allowance=Decimal("200.00"),
            transport_allowance=Decimal("100.00"),
            fixed_deduction=Decimal("50.00"),
        )
        self.payroll_period = PayrollPeriod.objects.create(
            company=self.company,
            title="June 2026",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            status=PayrollPeriod.STATUS_DRAFT,
        )

    def test_calculate_overtime_amount_uses_base_salary_hourly_rate(self):
        overtime_amount = calculate_overtime_amount(Decimal("2400.00"), 120)
        self.assertEqual(overtime_amount, Decimal("20.00"))

    def test_generate_lines_includes_attendance_overtime_amount(self):
        EmployeeAttendanceLedger.objects.create(
            employee=self.employee,
            attendance_date=date(2026, 6, 10),
            day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT,
            shift=EmployeeAttendanceLedger.SHIFT_MORNING,
            clock_in_time=time(9, 0),
            clock_out_time=time(18, 0),
        )

        created_count, updated_count = build_payroll_lines_for_period(self.payroll_period)
        payroll_line = PayrollLine.objects.get(payroll_period=self.payroll_period, employee=self.employee)

        self.assertEqual(created_count, 1)
        self.assertEqual(updated_count, 0)
        self.assertEqual(payroll_line.overtime_amount, Decimal("10.00"))
        self.assertEqual(payroll_line.net_pay, Decimal("2660.00"))
        self.assertIn("Attendance overtime logged: 1.00 hour(s).", payroll_line.notes)
        self.assertIn("Overtime amount calculated from base salary: 10.00.", payroll_line.notes)


class PayrollUnpaidLeaveDeductionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Leave Co")
        self.branch = Branch.objects.create(company=self.company, name="Leave Branch")
        self.department = Department.objects.create(company=self.company, name="Operations")
        self.section = Section.objects.create(department=self.department, name="Coverage")
        self.job_title = JobTitle.objects.create(
            department=self.department,
            section=self.section,
            name="Coverage Agent",
        )
        self.employee = Employee.objects.create(
            employee_id="EMP400",
            full_name="Leave Employee",
            company=self.company,
            department=self.department,
            branch=self.branch,
            section=self.section,
            job_title=self.job_title,
            hire_date=date(2026, 1, 1),
            salary=Decimal("2400.00"),
        )
        self.payroll_profile = PayrollProfile.objects.create(
            employee=self.employee,
            company=self.company,
            base_salary=Decimal("2400.00"),
            housing_allowance=Decimal("200.00"),
            transport_allowance=Decimal("100.00"),
            fixed_deduction=Decimal("50.00"),
        )
        self.payroll_period = PayrollPeriod.objects.create(
            company=self.company,
            title="July 2026",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            status=PayrollPeriod.STATUS_DRAFT,
        )

    def test_calculate_unpaid_leave_deduction_uses_hourly_base_salary_rate(self):
        deduction_amount = calculate_unpaid_leave_deduction(Decimal("2400.00"), Decimal("8.00"))
        self.assertEqual(deduction_amount, Decimal("80.00"))

    def test_generate_lines_includes_unpaid_leave_deduction(self):
        EmployeeAttendanceLedger.objects.create(
            employee=self.employee,
            attendance_date=date(2026, 7, 10),
            day_status=EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            shift=EmployeeAttendanceLedger.SHIFT_MORNING,
            scheduled_hours=Decimal("8.00"),
        )

        created_count, updated_count = build_payroll_lines_for_period(self.payroll_period)
        payroll_line = PayrollLine.objects.get(payroll_period=self.payroll_period, employee=self.employee)

        self.assertEqual(created_count, 1)
        self.assertEqual(updated_count, 0)
        self.assertEqual(payroll_line.deductions, Decimal("130.00"))
        self.assertEqual(payroll_line.net_pay, Decimal("2570.00"))
        self.assertIn("Unpaid leave logged: 1.00 day(s) / 8.00 hour(s).", payroll_line.notes)
        self.assertIn("Unpaid leave deduction calculated from base salary: 80.00.", payroll_line.notes)
