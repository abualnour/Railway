from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from employees.access import is_admin_compatible as is_admin_compatible_role
from employees.models import Employee, EmployeeAttendanceLedger

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
            payroll_note_parts.append(
                f"Overtime logged: {(Decimal(overtime_minutes) / Decimal('60')).quantize(Decimal('0.01'))} hour(s)."
            )
        if punctuality_minutes:
            payroll_note_parts.append(f"Late / early minutes logged: {punctuality_minutes} minute(s).")
        if geo_verified_days:
            payroll_note_parts.append(f"Map location captured on {geo_verified_days} attendance day(s).")

        allowances = (profile.housing_allowance or Decimal("0.00")) + (profile.transport_allowance or Decimal("0.00"))
        deductions = profile.fixed_deduction or Decimal("0.00")
        net_pay = (profile.base_salary or Decimal("0.00")) + allowances - deductions

        payroll_line, created = PayrollLine.objects.update_or_create(
            payroll_period=payroll_period,
            employee=profile.employee,
            defaults={
                "base_salary": profile.base_salary or Decimal("0.00"),
                "allowances": allowances,
                "deductions": deductions,
                "overtime_amount": Decimal("0.00"),
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
    payroll_period.status = target_status
    payroll_period.save(update_fields=["status", "updated_at"])
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
    gross_total = payroll_line.gross_total
    total_deductions_value = payroll_line.total_deductions_value
    employee_bonus_balances = PayrollBonus.objects.filter(employee=payroll_line.employee).order_by("-award_date", "-id")
    outstanding_bonus_balance = sum(
        bonus.remaining_balance
        for bonus in employee_bonus_balances.filter(status=PayrollBonus.STATUS_ACTIVE)
    )
    context = {
        "payroll_line": payroll_line,
        "gross_total": gross_total,
        "total_deductions_value": total_deductions_value,
        "payslip_adjustments": payroll_line.adjustments.all(),
        "employee_bonus_balances": employee_bonus_balances,
        "outstanding_bonus_balance": outstanding_bonus_balance,
    }
    return render(request, "payroll/payslip.html", context)
