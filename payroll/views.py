import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
try:
    from xhtml2pdf import pisa
except ImportError:
    pisa = None

from employees.access import is_admin_compatible as is_admin_compatible_role
from employees.models import Employee, EmployeeAttendanceLedger
from notifications.models import InAppNotification, get_notification_preferences_for_user

from .forms import (
    PayrollAdjustmentForm,
    PayrollBonusApplyForm,
    PayrollBonusForm,
    PayrollLineForm,
    PayrollLineGenerationForm,
    PayrollObligationForm,
    PayrollPeriodForm,
)
from .models import PayrollAdjustment, PayrollBonus, PayrollLine, PayrollObligation, PayrollPeriod, PayrollProfile

logger = logging.getLogger("payroll")


def decimal_to_display(value):
    return str((value or Decimal("0.00")).quantize(Decimal("0.01")))


def can_access_payroll_workspace(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_hr", False)
            or getattr(user, "is_finance_manager", False)
            or getattr(user, "is_operations_manager", False)
        )
    )


def can_prepare_payroll(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_hr", False)
            or getattr(user, "is_operations_manager", False)
        )
    )


def can_return_payroll_to_draft(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_hr", False)
            or getattr(user, "is_finance_manager", False)
            or getattr(user, "is_operations_manager", False)
        )
    )


def can_approve_payroll(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_finance_manager", False)
        )
    )


def can_mark_payroll_paid(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible_role(user)
            or getattr(user, "is_finance_manager", False)
        )
    )


def can_access_payroll_line_as_employee(user, payroll_line):
    return bool(
        user
        and user.is_authenticated
        and payroll_line
        and getattr(payroll_line.employee, "user_id", None) == getattr(user, "id", None)
    )


def calculate_overtime_amount(base_salary, overtime_minutes):
    base_salary_value = base_salary or Decimal("0.00")
    overtime_minutes_value = Decimal(overtime_minutes or 0)
    if base_salary_value <= Decimal("0.00") or overtime_minutes_value <= Decimal("0"):
        return Decimal("0.00")

    overtime_hours = overtime_minutes_value / Decimal("60")
    hourly_rate = base_salary_value / Decimal("30") / Decimal("8")
    return (hourly_rate * overtime_hours).quantize(Decimal("0.01"))


def calculate_unpaid_leave_deduction(base_salary, unpaid_leave_hours):
    base_salary_value = base_salary or Decimal("0.00")
    unpaid_leave_hours_value = Decimal(unpaid_leave_hours or Decimal("0.00"))
    if base_salary_value <= Decimal("0.00") or unpaid_leave_hours_value <= Decimal("0.00"):
        return Decimal("0.00")

    hourly_rate = base_salary_value / Decimal("30") / Decimal("8")
    return (hourly_rate * unpaid_leave_hours_value).quantize(Decimal("0.01"))


def build_payroll_line_breakdown(payroll_line):
    base_salary = payroll_line.base_salary or Decimal("0.00")
    allowances = payroll_line.allowances or Decimal("0.00")
    overtime_amount = payroll_line.overtime_amount or Decimal("0.00")
    fixed_deductions = payroll_line.deductions or Decimal("0.00")
    adjustment_allowances_total = payroll_line.adjustment_allowances_total
    adjustment_deductions_total = payroll_line.adjustment_deductions_total
    gross_total = payroll_line.gross_total
    total_deductions_value = payroll_line.total_deductions_value
    net_pay = payroll_line.net_pay or Decimal("0.00")

    return {
        "base_salary": decimal_to_display(base_salary),
        "allowances": decimal_to_display(allowances),
        "overtime_amount": decimal_to_display(overtime_amount),
        "adjustment_allowances_total": decimal_to_display(adjustment_allowances_total),
        "gross_total": decimal_to_display(gross_total),
        "fixed_deductions": decimal_to_display(fixed_deductions),
        "adjustment_deductions_total": decimal_to_display(adjustment_deductions_total),
        "total_deductions_value": decimal_to_display(total_deductions_value),
        "net_pay": decimal_to_display(net_pay),
        "formula_label": "Net Pay = Base Salary + Allowances + Overtime + Adjustment Allowances - Deductions - Adjustment Deductions",
    }


def build_payslip_context(payroll_line):
    snapshot_payload = payroll_line.snapshot_payload if payroll_line.has_snapshot else {}
    snapshot_employee = snapshot_payload.get("employee", {})
    snapshot_period = snapshot_payload.get("period", {})
    snapshot_line = snapshot_payload.get("line", {})
    snapshot_adjustments = snapshot_payload.get("adjustments", [])
    use_snapshot = bool(snapshot_payload)
    breakdown = (
        snapshot_line.get("breakdown", {})
        if use_snapshot
        else build_payroll_line_breakdown(payroll_line)
    )
    gross_total = snapshot_line.get("gross_total") if use_snapshot else payroll_line.gross_total
    total_deductions_value = (
        snapshot_line.get("total_deductions_value")
        if use_snapshot
        else payroll_line.total_deductions_value
    )
    employee_bonus_balances = PayrollBonus.objects.filter(employee=payroll_line.employee).order_by("-award_date", "-id")
    outstanding_bonus_balance = sum(
        bonus.remaining_balance
        for bonus in employee_bonus_balances.filter(status=PayrollBonus.STATUS_ACTIVE)
    )
    return {
        "payroll_line": payroll_line,
        "use_snapshot": use_snapshot,
        "snapshot_taken_at": payroll_line.snapshot_taken_at,
        "payslip_employee": snapshot_employee,
        "payslip_period": snapshot_period,
        "payslip_line": snapshot_line,
        "gross_total": gross_total,
        "total_deductions_value": total_deductions_value,
        "breakdown": breakdown,
        "payslip_adjustments": snapshot_adjustments if use_snapshot else payroll_line.adjustments.all(),
        "employee_bonus_balances": employee_bonus_balances,
        "outstanding_bonus_balance": outstanding_bonus_balance,
    }


def render_payslip_pdf_response(template_name, context, filename):
    if pisa is None:
        return HttpResponse("PDF generation is temporarily unavailable.", status=503)

    html = render_to_string(template_name, context)
    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    pdf_status = pisa.CreatePDF(html, dest=response, encoding="utf-8")
    if pdf_status.err:
        return HttpResponse("Unable to generate payslip PDF.", status=500)
    return response

def get_payroll_status_notification_users(target_status):
    user_model = get_user_model()
    role_filters = []
    if target_status == PayrollPeriod.STATUS_REVIEW:
        role_filters = [user_model.ROLE_FINANCE_MANAGER]
    elif target_status in {PayrollPeriod.STATUS_APPROVED, PayrollPeriod.STATUS_PAID}:
        role_filters = [user_model.ROLE_HR, user_model.ROLE_FINANCE_MANAGER]

    if not role_filters:
        return user_model.objects.none()

    return user_model.objects.filter(
        is_active=True,
        role__in=role_filters,
    ).order_by("email")


def create_payroll_status_notifications(payroll_period, target_status, recipient_users):
    status_label = payroll_period.get_status_display()
    action_url = reverse("payroll:period_detail", kwargs={"pk": payroll_period.pk})
    notification_level = (
        InAppNotification.LEVEL_WARNING
        if target_status == PayrollPeriod.STATUS_REVIEW
        else InAppNotification.LEVEL_SUCCESS
    )
    notifications = [
        InAppNotification(
            recipient=user,
            title=f"Payroll period moved to {status_label}",
            body=(
                f"{payroll_period.title} for {payroll_period.company.name} "
                f"is now {status_label}. Review the payroll period for the next action."
            ),
            category=InAppNotification.CATEGORY_PAYROLL,
            level=notification_level,
            action_url=action_url,
        )
        for user in recipient_users
        if get_notification_preferences_for_user(user).payroll_management_in_app_enabled
    ]
    if notifications:
        InAppNotification.objects.bulk_create(notifications)
    return len(notifications)


def get_employee_paid_notification_targets(payroll_period):
    employee_lines = payroll_period.lines.select_related("employee", "employee__user").all()
    targets = []
    for line in employee_lines:
        employee = line.employee
        if not employee:
            continue
        in_app_recipient = employee.user if employee.user_id and employee.user.is_active else None
        email_address = (employee.email or "").strip() or (
            (employee.user.email or "").strip()
            if employee.user_id and employee.user and employee.user.is_active
            else ""
        )
        if not in_app_recipient and not email_address:
            continue
        targets.append(
            {
                "line": line,
                "employee": employee,
                "user": in_app_recipient,
                "email": email_address,
            }
        )
    return targets


def send_employee_paid_payslip_notifications(payroll_period):
    if payroll_period.status != PayrollPeriod.STATUS_PAID:
        return {"emails_sent": 0, "in_app_created": 0}

    employee_targets = get_employee_paid_notification_targets(payroll_period)
    notifications = []
    emails_sent = 0

    for target in employee_targets:
        line = target["line"]
        employee = target["employee"]
        payslip_url = reverse("payroll:employee_line_payslip", kwargs={"pk": line.pk})
        payslip_pdf_url = reverse("payroll:employee_line_payslip_pdf", kwargs={"pk": line.pk})
        preferences = get_notification_preferences_for_user(target["user"]) if target["user"] else None
        allow_in_app = preferences.payroll_employee_in_app_enabled if preferences else False
        allow_email = preferences.payroll_employee_email_enabled if preferences else True
        include_pdf_link = preferences.payroll_employee_include_pdf_link if preferences else True

        if target["user"] and allow_in_app:
            notifications.append(
                InAppNotification(
                    recipient=target["user"],
                    title=f"Your payslip is ready for {payroll_period.title}",
                    body=(
                        f"Your payroll for {payroll_period.title} has been marked as paid. "
                        + (
                            "You can now open your payslip and download the PDF copy."
                            if include_pdf_link
                            else "You can now open your payslip from your self-service workspace."
                        )
                    ),
                    category=InAppNotification.CATEGORY_PAYROLL,
                    level=InAppNotification.LEVEL_SUCCESS,
                    action_url=payslip_url,
                )
            )

        if target["email"] and allow_email:
            email_lines = [
                f"Hello {employee.full_name},",
                "",
                f"Your payroll for {payroll_period.title} has been marked as paid.",
                f"View your payslip: {payslip_url}",
            ]
            if include_pdf_link:
                email_lines.append(f"Download PDF: {payslip_pdf_url}")
            sent_count = send_mail(
                subject=f"Your Payslip Is Ready: {payroll_period.title}",
                message="\n".join(email_lines),
                from_email=None,
                recipient_list=[target["email"]],
                fail_silently=False,
            )
            emails_sent += sent_count

    if notifications:
        InAppNotification.objects.bulk_create(notifications)

    logger.info(
        "Employee payslip delivery completed for payroll period '%s'. In-app notifications: %s. Emails sent: %s.",
        payroll_period.title,
        len(notifications),
        emails_sent,
    )
    return {"emails_sent": emails_sent, "in_app_created": len(notifications)}


def send_payroll_status_notification(payroll_period, target_status):
    recipient_users = list(get_payroll_status_notification_users(target_status))
    recipients = sorted(
        {
            user.email
            for user in recipient_users
            if user.email and get_notification_preferences_for_user(user).payroll_management_email_enabled
        }
    )
    notification_count = create_payroll_status_notifications(payroll_period, target_status, recipient_users)
    logger.info(
        "Payroll period '%s' moved to %s. Email recipients: %s. In-app notifications: %s",
        payroll_period.title,
        target_status,
        recipients,
        notification_count,
    )
    if not recipients:
        return 0

    status_label = payroll_period.get_status_display()
    subject = f"Payroll Update: {payroll_period.title} is now {status_label}"
    pay_date_label = payroll_period.pay_date.isoformat() if payroll_period.pay_date else "Not scheduled"
    message = "\n".join(
        [
            f"Payroll period: {payroll_period.title}",
            f"Company: {payroll_period.company.name}",
            f"Status: {status_label}",
            f"Period: {payroll_period.period_start.isoformat()} to {payroll_period.period_end.isoformat()}",
            f"Pay date: {pay_date_label}",
            "",
            f"Open in NourAxis: {reverse('payroll:period_detail', kwargs={'pk': payroll_period.pk})}",
        ]
    )
    sent_count = send_mail(
        subject=subject,
        message=message,
        from_email=None,
        recipient_list=recipients,
        fail_silently=False,
    )
    logger.info(
        "Payroll status email sent for '%s' to %s recipient(s).",
        payroll_period.title,
        sent_count,
    )
    return sent_count


def build_payroll_lines_for_period(payroll_period):
    created_count = 0
    updated_count = 0

    profiles = PayrollProfile.objects.select_related("employee", "company").filter(
        company=payroll_period.company,
        status=PayrollProfile.STATUS_ACTIVE,
    )

    for profile in profiles:
        attendance_entries = list(
            EmployeeAttendanceLedger.objects.filter(
                employee=profile.employee,
                attendance_date__gte=payroll_period.period_start,
                attendance_date__lte=payroll_period.period_end,
            ).order_by("attendance_date", "id")
        )
        overtime_minutes = sum(entry.overtime_minutes or 0 for entry in attendance_entries)
        unpaid_leave_hours = sum(
            entry.scheduled_hours or Decimal("0.00")
            for entry in attendance_entries
            if entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE
        )
        punctuality_minutes = sum(
            (entry.late_minutes or 0) + (entry.early_departure_minutes or 0)
            for entry in attendance_entries
        )
        geo_verified_days = sum(
            1
            for entry in attendance_entries
            if entry.check_in_latitude is not None and entry.check_in_longitude is not None
        )
        payroll_note_parts = [f"Generated from payroll profile for {profile.employee.full_name}."]
        if attendance_entries:
            payroll_note_parts.append(f"Attendance rows linked: {len(attendance_entries)} day(s).")
        if overtime_minutes:
            overtime_hours = (Decimal(overtime_minutes) / Decimal("60")).quantize(Decimal("0.01"))
            overtime_amount = calculate_overtime_amount(profile.base_salary, overtime_minutes)
            payroll_note_parts.append(
                f"Overtime logged: {overtime_hours} hour(s)."
            )
            payroll_note_parts.append(
                f"Overtime amount calculated from base salary: {overtime_amount}."
            )
        else:
            overtime_amount = Decimal("0.00")
        if punctuality_minutes:
            payroll_note_parts.append(f"Late / early minutes logged: {punctuality_minutes} minute(s).")
        if geo_verified_days:
            payroll_note_parts.append(f"Map location captured on {geo_verified_days} attendance day(s).")

        allowances = (profile.housing_allowance or Decimal("0.00")) + (profile.transport_allowance or Decimal("0.00"))
        fixed_deduction = profile.fixed_deduction or Decimal("0.00")
        unpaid_leave_deduction = calculate_unpaid_leave_deduction(profile.base_salary, unpaid_leave_hours)
        if unpaid_leave_hours:
            unpaid_leave_days = (unpaid_leave_hours / Decimal("8.00")).quantize(Decimal("0.01"))
            payroll_note_parts.append(
                f"Unpaid leave logged: {unpaid_leave_days} day(s) / {unpaid_leave_hours.quantize(Decimal('0.01'))} hour(s)."
            )
            payroll_note_parts.append(
                f"Unpaid leave deduction calculated from base salary: {unpaid_leave_deduction}."
            )
        deductions = fixed_deduction + unpaid_leave_deduction
        net_pay = (profile.base_salary or Decimal("0.00")) + allowances + overtime_amount - deductions

        payroll_line, created = PayrollLine.objects.update_or_create(
            payroll_period=payroll_period,
            employee=profile.employee,
            defaults={
                "base_salary": profile.base_salary or Decimal("0.00"),
                "allowances": allowances,
                "deductions": deductions,
                "overtime_amount": overtime_amount,
                "net_pay": net_pay,
                "notes": " ".join(payroll_note_parts),
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

        active_obligations = PayrollObligation.objects.filter(
            employee=profile.employee,
            company=payroll_period.company,
            status=PayrollObligation.STATUS_ACTIVE,
            start_date__lte=payroll_period.period_end,
        )
        for obligation in active_obligations:
            if not obligation.can_apply_installment:
                continue
            adjustment, adjustment_created = PayrollAdjustment.objects.get_or_create(
                payroll_line=payroll_line,
                payroll_obligation=obligation,
                defaults={
                    "title": f"{obligation.get_obligation_type_display()} installment",
                    "adjustment_type": PayrollAdjustment.TYPE_DEDUCTION,
                    "amount": obligation.installment_amount,
                    "notes": obligation.title,
                },
            )
            if adjustment_created:
                obligation.paid_installments += 1
                if obligation.remaining_installments == 0:
                    obligation.status = PayrollObligation.STATUS_COMPLETED
                obligation.save(update_fields=["paid_installments", "status", "updated_at"])
        refresh_payroll_line_totals(payroll_line)

    return created_count, updated_count


def refresh_payroll_line_totals(payroll_line):
    payroll_line.net_pay = payroll_line.calculate_net_pay()
    payroll_line.save(update_fields=["net_pay", "updated_at"])
    return payroll_line


def can_edit_payroll_period(payroll_period):
    return payroll_period.status in {
        PayrollPeriod.STATUS_DRAFT,
        PayrollPeriod.STATUS_REVIEW,
    }


def serialize_payroll_adjustment_snapshot(adjustment):
    return {
        "title": adjustment.title,
        "adjustment_type": adjustment.adjustment_type,
        "adjustment_type_label": adjustment.get_adjustment_type_display(),
        "amount": str(adjustment.amount or Decimal("0.00")),
        "notes": adjustment.notes or "",
        "bonus_type_label": (
            adjustment.payroll_bonus.get_bonus_type_display()
            if adjustment.payroll_bonus_id
            else ""
        ),
        "obligation_type_label": (
            adjustment.payroll_obligation.get_obligation_type_display()
            if adjustment.payroll_obligation_id
            else ""
        ),
    }


def build_payroll_line_snapshot(line):
    employee = line.employee
    payroll_period = line.payroll_period
    adjustments = list(
        line.adjustments.select_related("payroll_bonus", "payroll_obligation").all().order_by("adjustment_type", "title", "id")
    )
    return {
        "employee": {
            "employee_id": employee.employee_id or "",
            "full_name": employee.full_name,
            "job_title": employee.job_title.name if employee.job_title_id else "",
            "branch": employee.branch.name if employee.branch_id else "",
        },
        "period": {
            "title": payroll_period.title,
            "company_name": payroll_period.company.name if payroll_period.company_id else "",
            "status": payroll_period.status,
            "status_label": payroll_period.get_status_display(),
            "period_start": payroll_period.period_start.isoformat() if payroll_period.period_start else "",
            "period_end": payroll_period.period_end.isoformat() if payroll_period.period_end else "",
            "pay_date": payroll_period.pay_date.isoformat() if payroll_period.pay_date else "",
        },
        "line": {
            "base_salary": str(line.base_salary or Decimal("0.00")),
            "allowances": str(line.allowances or Decimal("0.00")),
            "overtime_amount": str(line.overtime_amount or Decimal("0.00")),
            "gross_total": str(line.gross_total),
            "deductions": str(line.deductions or Decimal("0.00")),
            "adjustment_allowances_total": str(line.adjustment_allowances_total),
            "adjustment_deductions_total": str(line.adjustment_deductions_total),
            "total_deductions_value": str(line.total_deductions_value),
            "net_pay": str(line.net_pay or Decimal("0.00")),
            "notes": line.notes or "",
            "breakdown": build_payroll_line_breakdown(line),
        },
        "adjustments": [
            serialize_payroll_adjustment_snapshot(adjustment)
            for adjustment in adjustments
        ],
    }


def snapshot_payroll_period(payroll_period):
    snapshot_time = timezone.now()
    payroll_period.approved_at = snapshot_time
    payroll_period.save(update_fields=["approved_at", "updated_at"])

    lines = payroll_period.lines.select_related(
        "employee",
        "employee__job_title",
        "employee__branch",
        "payroll_period",
        "payroll_period__company",
    ).prefetch_related(
        "adjustments",
        "adjustments__payroll_bonus",
        "adjustments__payroll_obligation",
    )
    for line in lines:
        line.snapshot_payload = build_payroll_line_snapshot(line)
        line.snapshot_taken_at = snapshot_time
        line.save(update_fields=["snapshot_payload", "snapshot_taken_at", "updated_at"])


def clear_payroll_period_snapshots(payroll_period):
    payroll_period.approved_at = None
    payroll_period.save(update_fields=["approved_at", "updated_at"])
    payroll_period.lines.update(snapshot_payload=None, snapshot_taken_at=None)


def update_payroll_period_status(payroll_period, target_status):
    valid_transitions = {
        PayrollPeriod.STATUS_DRAFT: {PayrollPeriod.STATUS_REVIEW},
        PayrollPeriod.STATUS_REVIEW: {PayrollPeriod.STATUS_DRAFT, PayrollPeriod.STATUS_APPROVED},
        PayrollPeriod.STATUS_APPROVED: {PayrollPeriod.STATUS_REVIEW, PayrollPeriod.STATUS_PAID},
        PayrollPeriod.STATUS_PAID: {PayrollPeriod.STATUS_APPROVED},
    }
    allowed_targets = valid_transitions.get(payroll_period.status, set())
    if target_status not in allowed_targets:
        return False

    with transaction.atomic():
        payroll_period.status = target_status
        payroll_period.save(update_fields=["status", "updated_at"])
        if target_status == PayrollPeriod.STATUS_APPROVED:
            snapshot_payroll_period(payroll_period)
        elif target_status in {PayrollPeriod.STATUS_DRAFT, PayrollPeriod.STATUS_REVIEW}:
            clear_payroll_period_snapshots(payroll_period)
        if target_status in {
            PayrollPeriod.STATUS_REVIEW,
            PayrollPeriod.STATUS_APPROVED,
            PayrollPeriod.STATUS_PAID,
        }:
            send_payroll_status_notification(payroll_period, target_status)
        if target_status == PayrollPeriod.STATUS_PAID:
            send_employee_paid_payslip_notifications(payroll_period)
    return True


@login_required
def payroll_home(request):
    if not can_access_payroll_workspace(request.user):
        raise PermissionDenied("You do not have permission to access the payroll workspace.")

    period_form = PayrollPeriodForm()
    generation_form = PayrollLineGenerationForm()
    obligation_form = PayrollObligationForm()
    bonus_form = PayrollBonusForm()

    if request.method == "POST":
        action = (request.POST.get("payroll_action") or "").strip()

        if action == "create_period":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to create payroll periods.")
            period_form = PayrollPeriodForm(request.POST)
            if period_form.is_valid():
                payroll_period = period_form.save()
                messages.success(request, f"Payroll period '{payroll_period.title}' created successfully.")
                return redirect("payroll:home")
            messages.error(request, "Please review the payroll period form and try again.")

        elif action == "generate_lines":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to generate payroll lines.")
            generation_form = PayrollLineGenerationForm(request.POST)
            if generation_form.is_valid():
                payroll_period = generation_form.cleaned_data["payroll_period"]
                if not can_edit_payroll_period(payroll_period):
                    messages.error(
                        request,
                        f"Payroll lines cannot be regenerated because '{payroll_period.title}' is already {payroll_period.get_status_display().lower()}.",
                    )
                    return redirect("payroll:period_detail", pk=payroll_period.pk)
                created_count, updated_count = build_payroll_lines_for_period(payroll_period)
                messages.success(
                    request,
                    f"Payroll lines processed for '{payroll_period.title}'. Created: {created_count}, updated: {updated_count}.",
                )
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            messages.error(request, "Choose a payroll period before generating lines.")
        elif action == "create_obligation":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to create payroll obligations.")
            obligation_form = PayrollObligationForm(request.POST)
            if obligation_form.is_valid():
                obligation = obligation_form.save()
                messages.success(request, f"{obligation.get_obligation_type_display()} created for {obligation.employee.full_name}.")
                return redirect("payroll:home")
            messages.error(request, "Please review the loan or advance form and try again.")
        elif action == "create_bonus":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to create bonus balances.")
            bonus_form = PayrollBonusForm(request.POST)
            if bonus_form.is_valid():
                bonus = bonus_form.save()
                messages.success(request, f"Bonus balance created for {bonus.employee.full_name}.")
                return redirect("payroll:home")
            messages.error(request, "Please review the bonus form and try again.")
        elif action == "update_obligation_status":
            obligation = get_object_or_404(PayrollObligation, pk=request.POST.get("obligation_id"))
            target_status = (request.POST.get("target_status") or "").strip()
            if target_status in {
                PayrollObligation.STATUS_ACTIVE,
                PayrollObligation.STATUS_HOLD,
                PayrollObligation.STATUS_COMPLETED,
            }:
                obligation.status = target_status
                obligation.save(update_fields=["status", "updated_at"])
                messages.success(request, f"{obligation.title} updated to {obligation.get_status_display()}.")
                return redirect("payroll:home")
            messages.error(request, "Invalid obligation status change requested.")

    payroll_profiles = PayrollProfile.objects.select_related("employee", "company")
    payroll_periods = PayrollPeriod.objects.select_related("company")
    recent_periods = payroll_periods.order_by("-period_start", "-id")[:6]
    payroll_lines = PayrollLine.objects.select_related("employee", "payroll_period").order_by("-created_at")[:8]
    payroll_adjustments = PayrollAdjustment.objects.select_related(
        "payroll_line",
        "payroll_line__employee",
        "payroll_line__payroll_period",
        "payroll_bonus",
    ).order_by("-updated_at", "-id")[:8]
    payroll_obligations = PayrollObligation.objects.select_related("employee", "company").order_by("-updated_at", "-id")[:8]
    payroll_bonuses = PayrollBonus.objects.select_related("employee", "company").order_by("-updated_at", "-id")[:8]
    employees_without_payroll = Employee.objects.filter(payroll_profile__isnull=True).select_related(
        "company", "branch", "job_title"
    ).order_by("full_name")[:8]
    company_summary = payroll_periods.values("company__name").annotate(
        period_total=Count("id"),
    ).order_by("-period_total", "company__name")[:6]

    totals = payroll_lines.aggregate(
        total_net=Sum("net_pay"),
        total_allowances=Sum("allowances"),
        total_deductions=Sum("deductions"),
    )
    allowance_adjustments_total = sum(
        adjustment.amount or Decimal("0.00")
        for adjustment in PayrollAdjustment.objects.filter(adjustment_type=PayrollAdjustment.TYPE_ALLOWANCE)
    )
    deduction_adjustments_total = sum(
        adjustment.amount or Decimal("0.00")
        for adjustment in PayrollAdjustment.objects.filter(adjustment_type=PayrollAdjustment.TYPE_DEDUCTION)
    )
    active_obligation_total = PayrollObligation.objects.filter(status=PayrollObligation.STATUS_ACTIVE).count()
    outstanding_obligation_balance = sum(
        obligation.remaining_balance
        for obligation in PayrollObligation.objects.filter(status=PayrollObligation.STATUS_ACTIVE)
    )
    active_bonus_total = PayrollBonus.objects.filter(status=PayrollBonus.STATUS_ACTIVE).count()
    outstanding_bonus_balance = sum(
        bonus.remaining_balance
        for bonus in PayrollBonus.objects.filter(status=PayrollBonus.STATUS_ACTIVE)
    )

    focused_employee = None
    focused_payroll_profile = None
    focused_employee_profile_url = ""
    focused_employee_setup_url = ""
    focused_employee_recent_line_count = 0
    employee_focus_token = (request.GET.get("employee") or "").strip()
    if employee_focus_token.isdigit():
        focused_employee = Employee.objects.select_related("company", "branch", "job_title").filter(
            pk=int(employee_focus_token)
        ).first()
        if focused_employee:
            focused_payroll_profile = PayrollProfile.objects.select_related("company").filter(
                employee=focused_employee
            ).first()
            focused_employee_profile_url = (
                f"{reverse('employees:employee_detail', kwargs={'pk': focused_employee.pk})}"
                "?tab=payroll#employee-payroll-section"
            )
            focused_employee_setup_url = (
                f"{reverse('employees:employee_detail', kwargs={'pk': focused_employee.pk})}"
                "?tab=payroll&modal=payroll_information#employee-payroll-section"
            )
            focused_employee_recent_line_count = PayrollLine.objects.filter(employee=focused_employee).count()

    context = {
        "workspace_title": "Payroll Workspace",
        "payroll_profile_total": payroll_profiles.count(),
        "active_payroll_profile_total": payroll_profiles.filter(status=PayrollProfile.STATUS_ACTIVE).count(),
        "draft_period_total": payroll_periods.filter(status=PayrollPeriod.STATUS_DRAFT).count(),
        "approved_period_total": payroll_periods.filter(status=PayrollPeriod.STATUS_APPROVED).count(),
        "paid_period_total": payroll_periods.filter(status=PayrollPeriod.STATUS_PAID).count(),
        "employees_without_payroll_total": Employee.objects.filter(payroll_profile__isnull=True).count(),
        "recent_periods": recent_periods,
        "payroll_lines": payroll_lines,
        "payroll_adjustments": payroll_adjustments,
        "payroll_obligations": payroll_obligations,
        "payroll_bonuses": payroll_bonuses,
        "payroll_profiles": payroll_profiles.order_by("-updated_at")[:8],
        "employees_without_payroll": employees_without_payroll,
        "company_summary": company_summary,
        "total_net_pay": totals.get("total_net"),
        "total_allowances": totals.get("total_allowances"),
        "total_deductions": totals.get("total_deductions"),
        "allowance_adjustments_total": allowance_adjustments_total,
        "deduction_adjustments_total": deduction_adjustments_total,
        "active_obligation_total": active_obligation_total,
        "outstanding_obligation_balance": outstanding_obligation_balance,
        "active_bonus_total": active_bonus_total,
        "outstanding_bonus_balance": outstanding_bonus_balance,
        "focused_employee": focused_employee,
        "focused_payroll_profile": focused_payroll_profile,
        "focused_employee_profile_url": focused_employee_profile_url,
        "focused_employee_setup_url": focused_employee_setup_url,
        "focused_employee_recent_line_count": focused_employee_recent_line_count,
        "period_form": period_form,
        "generation_form": generation_form,
        "obligation_form": obligation_form,
        "bonus_form": bonus_form,
        "can_prepare_payroll": can_prepare_payroll(request.user),
        "can_approve_payroll": can_approve_payroll(request.user),
        "can_mark_payroll_paid": can_mark_payroll_paid(request.user),
    }
    return render(request, "payroll/home.html", context)


@login_required
def payroll_period_detail(request, pk):
    if not can_access_payroll_workspace(request.user):
        raise PermissionDenied("You do not have permission to access the payroll workspace.")

    payroll_period = get_object_or_404(
        PayrollPeriod.objects.select_related("company").prefetch_related("lines", "lines__employee", "lines__adjustments"),
        pk=pk,
    )
    lines = payroll_period.lines.select_related("employee").order_by("employee__full_name")

    if request.method == "POST":
        action = (request.POST.get("payroll_action") or "").strip()

        if action == "update_line":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to edit payroll lines.")
            if not can_edit_payroll_period(payroll_period):
                messages.error(
                    request,
                    f"Payroll lines are locked because '{payroll_period.title}' is already {payroll_period.get_status_display().lower()}.",
                )
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            line = get_object_or_404(PayrollLine, pk=request.POST.get("line_id"), payroll_period=payroll_period)
            form = PayrollLineForm(request.POST, instance=line)
            if form.is_valid():
                updated_line = form.save()
                messages.success(request, f"Payroll line updated for {updated_line.employee.full_name}.")
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            messages.error(request, f"Please review the payroll line for {line.employee.full_name}.")
        elif action == "add_adjustment":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to add payroll adjustments.")
            if not can_edit_payroll_period(payroll_period):
                messages.error(
                    request,
                    f"Payroll adjustments are locked because '{payroll_period.title}' is already {payroll_period.get_status_display().lower()}.",
                )
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            line = get_object_or_404(PayrollLine, pk=request.POST.get("line_id"), payroll_period=payroll_period)
            adjustment_form = PayrollAdjustmentForm(request.POST)
            if adjustment_form.is_valid():
                adjustment = adjustment_form.save(commit=False)
                adjustment.payroll_line = line
                adjustment.save()
                refresh_payroll_line_totals(line)
                messages.success(request, f"Adjustment added for {line.employee.full_name}.")
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            messages.error(request, f"Please review the adjustment form for {line.employee.full_name}.")
            form = None
        elif action == "apply_bonus":
            if not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to apply bonus balances.")
            if not can_edit_payroll_period(payroll_period):
                messages.error(
                    request,
                    f"Bonus application is locked because '{payroll_period.title}' is already {payroll_period.get_status_display().lower()}.",
                )
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            line = get_object_or_404(PayrollLine, pk=request.POST.get("line_id"), payroll_period=payroll_period)
            bonus_apply_form = PayrollBonusApplyForm(request.POST, employee=line.employee)
            if bonus_apply_form.is_valid():
                payroll_bonus = bonus_apply_form.cleaned_data["payroll_bonus"]
                amount = bonus_apply_form.cleaned_data["amount"]
                notes = (bonus_apply_form.cleaned_data.get("notes") or "").strip()
                PayrollAdjustment.objects.create(
                    payroll_line=line,
                    payroll_bonus=payroll_bonus,
                    title=payroll_bonus.title,
                    adjustment_type=PayrollAdjustment.TYPE_ALLOWANCE,
                    amount=amount,
                    notes=notes or f"{payroll_bonus.get_bonus_type_display()} bonus applied from balance.",
                )
                payroll_bonus.paid_amount = (payroll_bonus.paid_amount or Decimal("0.00")) + amount
                if payroll_bonus.remaining_balance <= Decimal("0.00"):
                    payroll_bonus.status = PayrollBonus.STATUS_COMPLETED
                payroll_bonus.save(update_fields=["paid_amount", "status", "updated_at"])
                refresh_payroll_line_totals(line)
                messages.success(request, f"Bonus applied for {line.employee.full_name}.")
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            messages.error(request, f"Please review the bonus application for {line.employee.full_name}.")
            form = None
        elif action == "change_period_status":
            target_status = (request.POST.get("target_status") or "").strip()
            if target_status == PayrollPeriod.STATUS_REVIEW and not can_prepare_payroll(request.user):
                raise PermissionDenied("You do not have permission to submit payroll for review.")
            if target_status == PayrollPeriod.STATUS_DRAFT and not can_return_payroll_to_draft(request.user):
                raise PermissionDenied("You do not have permission to return payroll to draft.")
            if target_status == PayrollPeriod.STATUS_APPROVED and not can_approve_payroll(request.user):
                raise PermissionDenied("You do not have permission to approve payroll.")
            if target_status == PayrollPeriod.STATUS_PAID and not can_mark_payroll_paid(request.user):
                raise PermissionDenied("You do not have permission to mark payroll as paid.")
            if update_payroll_period_status(payroll_period, target_status):
                messages.success(request, f"Payroll period moved to {payroll_period.get_status_display()}.")
                return redirect("payroll:period_detail", pk=payroll_period.pk)
            messages.error(request, "This payroll status change is not allowed.")
            form = None
        else:
            form = None
    else:
        form = None

    line_editor_rows = [
        {
            "line": line,
            "form": form if form is not None and getattr(form.instance, "pk", None) == line.pk else PayrollLineForm(instance=line),
            "adjustment_form": PayrollAdjustmentForm(),
            "bonus_apply_form": PayrollBonusApplyForm(employee=line.employee),
            "breakdown": build_payroll_line_breakdown(line),
        }
        for line in lines
    ]

    totals = lines.aggregate(
        total_base=Sum("base_salary"),
        total_allowances=Sum("allowances"),
        total_deductions=Sum("deductions"),
        total_net=Sum("net_pay"),
    )
    period_adjustments = PayrollAdjustment.objects.filter(payroll_line__payroll_period=payroll_period).select_related(
        "payroll_line",
        "payroll_line__employee",
        "payroll_bonus",
    ).order_by("payroll_line__employee__full_name", "adjustment_type", "title")

    context = {
        "payroll_period": payroll_period,
        "lines": lines,
        "total_base": totals.get("total_base"),
        "total_allowances": totals.get("total_allowances"),
        "total_deductions": totals.get("total_deductions"),
        "total_net": totals.get("total_net"),
        "line_editor_rows": line_editor_rows,
        "period_adjustments": period_adjustments,
        "can_prepare_payroll": can_prepare_payroll(request.user),
        "can_return_payroll_to_draft": can_return_payroll_to_draft(request.user),
        "can_approve_payroll": can_approve_payroll(request.user),
        "can_mark_payroll_paid": can_mark_payroll_paid(request.user),
        "can_edit_payroll_period": can_prepare_payroll(request.user) and can_edit_payroll_period(payroll_period),
    }
    return render(request, "payroll/period_detail.html", context)


@login_required
def payroll_line_payslip(request, pk):
    if not can_access_payroll_workspace(request.user):
        raise PermissionDenied("You do not have permission to access the payroll workspace.")

    payroll_line = get_object_or_404(
        PayrollLine.objects.select_related("employee", "employee__company", "employee__branch", "employee__job_title", "payroll_period", "payroll_period__company").prefetch_related("adjustments", "adjustments__payroll_obligation", "adjustments__payroll_bonus"),
        pk=pk,
    )
    context = build_payslip_context(payroll_line)
    return render(request, "payroll/payslip.html", context)


@login_required
def payroll_line_payslip_pdf(request, pk):
    if not can_access_payroll_workspace(request.user):
        raise PermissionDenied("You do not have permission to access the payroll workspace.")

    payroll_line = get_object_or_404(
        PayrollLine.objects.select_related(
            "employee",
            "employee__company",
            "employee__branch",
            "employee__job_title",
            "payroll_period",
            "payroll_period__company",
        ).prefetch_related("adjustments", "adjustments__payroll_obligation", "adjustments__payroll_bonus"),
        pk=pk,
    )
    context = build_payslip_context(payroll_line)
    employee_name = (
        context["payslip_employee"].get("full_name")
        if context["use_snapshot"]
        else payroll_line.employee.full_name
    ) or "employee"
    safe_employee_name = employee_name.replace(" ", "_")
    filename = f"payslip_{safe_employee_name}_{payroll_line.payroll_period.title.replace(' ', '_')}.pdf"
    return render_payslip_pdf_response("payroll/payslip_pdf.html", context, filename)


@login_required
def employee_payroll_line_payslip(request, pk):
    payroll_line = get_object_or_404(
        PayrollLine.objects.select_related(
            "employee",
            "employee__user",
            "employee__company",
            "employee__branch",
            "employee__job_title",
            "payroll_period",
            "payroll_period__company",
        ).prefetch_related("adjustments", "adjustments__payroll_obligation", "adjustments__payroll_bonus"),
        pk=pk,
    )
    if not (
        can_access_payroll_workspace(request.user)
        or can_access_payroll_line_as_employee(request.user, payroll_line)
    ):
        raise PermissionDenied("You do not have permission to access this payslip.")

    context = build_payslip_context(payroll_line)
    return render(request, "payroll/payslip.html", context)


@login_required
def employee_payroll_line_payslip_pdf(request, pk):
    payroll_line = get_object_or_404(
        PayrollLine.objects.select_related(
            "employee",
            "employee__user",
            "employee__company",
            "employee__branch",
            "employee__job_title",
            "payroll_period",
            "payroll_period__company",
        ).prefetch_related("adjustments", "adjustments__payroll_obligation", "adjustments__payroll_bonus"),
        pk=pk,
    )
    if not (
        can_access_payroll_workspace(request.user)
        or can_access_payroll_line_as_employee(request.user, payroll_line)
    ):
        raise PermissionDenied("You do not have permission to access this payslip PDF.")

    context = build_payslip_context(payroll_line)
    employee_name = (
        context["payslip_employee"].get("full_name")
        if context["use_snapshot"]
        else payroll_line.employee.full_name
    ) or "employee"
    safe_employee_name = employee_name.replace(" ", "_")
    filename = f"my_payslip_{safe_employee_name}_{payroll_line.payroll_period.title.replace(' ', '_')}.pdf"
    return render_payslip_pdf_response("payroll/payslip_pdf.html", context, filename)
