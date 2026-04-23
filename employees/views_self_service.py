from .views_shared import *
from .views_directory import *

# Self-service pages and branch schedule builder flows.

@login_required
def self_service_profile_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )

    if should_use_management_own_profile(request.user, employee):
        return redirect(get_workspace_profile_url(request.user, employee))

    context = build_self_service_page_context(
        request,
        employee,
        current_section="profile",
    )
    return render(request, "employees/self_service_profile.html", context)


@login_required
def self_service_leave_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )

    context = build_self_service_page_context(
        request,
        employee,
        current_section="leave",
    )
    return render(request, "employees/self_service_leave.html", context)


def build_self_service_overtime_context(request, employee, *, form=None):
    overtime_requests = list(
        employee.overtime_requests.select_related("reviewed_by").order_by("-date", "-created_at", "-id")
    )
    context = build_self_service_page_context(
        request,
        employee,
        current_section="overtime",
    )
    context["overtime_request_form"] = form or EmployeeOvertimeRequestForm(
        initial={"date": timezone.localdate()}
    )
    context["overtime_requests"] = overtime_requests
    context["overtime_request_total"] = len(overtime_requests)
    context["overtime_pending_count"] = sum(
        1 for overtime_request in overtime_requests if overtime_request.status == OvertimeRequest.STATUS_PENDING
    )
    context["overtime_approved_count"] = sum(
        1 for overtime_request in overtime_requests if overtime_request.status == OvertimeRequest.STATUS_APPROVED
    )
    context["overtime_rejected_count"] = sum(
        1 for overtime_request in overtime_requests if overtime_request.status == OvertimeRequest.STATUS_REJECTED
    )
    return context


def build_self_service_expense_context(request, employee, *, form=None):
    from finance.forms import ExpenseClaimForm
    from finance.models import ExpenseClaim

    expense_claims = list(
        employee.expense_claims.select_related("reviewed_by").order_by("-expense_date", "-created_at", "-id")
    )
    context = build_self_service_page_context(
        request,
        employee,
        current_section="expenses",
    )
    context["expense_claim_form"] = form or ExpenseClaimForm(initial={"expense_date": timezone.localdate()})
    context["expense_claims"] = expense_claims
    context["expense_claim_total"] = len(expense_claims)
    context["expense_draft_count"] = sum(
        1 for claim in expense_claims if claim.status == ExpenseClaim.STATUS_DRAFT
    )
    context["expense_submitted_count"] = sum(
        1 for claim in expense_claims if claim.status == ExpenseClaim.STATUS_SUBMITTED
    )
    context["expense_approved_count"] = sum(
        1 for claim in expense_claims if claim.status == ExpenseClaim.STATUS_APPROVED
    )
    context["expense_rejected_count"] = sum(
        1 for claim in expense_claims if claim.status == ExpenseClaim.STATUS_REJECTED
    )
    context["expense_paid_count"] = sum(
        1 for claim in expense_claims if claim.status == ExpenseClaim.STATUS_PAID
    )
    return context


@login_required
def overtime_request_list(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee overtime workspace.",
            employee=employee,
        )

    context = build_self_service_overtime_context(request, employee)
    return render(request, "employees/self_service_overtime.html", context)


@login_required
def expense_claim_list(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee expense workspace.",
            employee=employee,
        )

    context = build_self_service_expense_context(request, employee)
    return render(request, "employees/self_service_expenses.html", context)


@login_required
@require_POST
def overtime_request_create(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to submit overtime requests from this account.",
            employee=employee,
        )

    form = EmployeeOvertimeRequestForm(request.POST)
    if form.is_valid():
        overtime_request = form.save(commit=False)
        overtime_request.employee = employee
        overtime_request.status = OvertimeRequest.STATUS_PENDING
        overtime_request.save()

        create_employee_history(
            employee=employee,
            title="Overtime request submitted",
            description=(
                f"Submitted overtime request for {overtime_request.hours_requested} hour(s) "
                f"on {overtime_request.date:%B %d, %Y}. Reason: {overtime_request.reason}"
            ),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=overtime_request.date,
        )
        messages.success(request, "Overtime request submitted successfully.")
        return redirect("employees:overtime_request_list")

    messages.error(request, "Please review the overtime request form and try again.")
    context = build_self_service_overtime_context(request, employee, form=form)
    return render(request, "employees/self_service_overtime.html", context, status=400)


@login_required
@require_POST
def expense_claim_create(request):
    from finance.forms import ExpenseClaimForm
    from finance.models import ExpenseClaim

    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to submit expense claims from this account.",
            employee=employee,
        )

    form = ExpenseClaimForm(request.POST, request.FILES)
    if form.is_valid():
        expense_claim = form.save(commit=False)
        expense_claim.employee = employee
        if expense_claim.status == ExpenseClaim.STATUS_SUBMITTED:
            expense_claim.submitted_at = timezone.now()
        expense_claim.full_clean()
        expense_claim.save()

        create_employee_history(
            employee=employee,
            title="Expense claim submitted" if expense_claim.status == ExpenseClaim.STATUS_SUBMITTED else "Expense claim draft saved",
            description=(
                f"{expense_claim.title}: {expense_claim.amount} {expense_claim.currency} "
                f"for {expense_claim.get_category_display()} on {expense_claim.expense_date:%B %d, %Y}."
            ),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=expense_claim.expense_date,
        )
        messages.success(request, "Expense claim saved successfully.")
        return redirect("employees:expense_claim_list")

    messages.error(request, "Please review the expense claim form and try again.")
    context = build_self_service_expense_context(request, employee, form=form)
    return render(request, "employees/self_service_expenses.html", context, status=400)


@login_required
def self_service_documents_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )

    context = build_self_service_page_context(
        request,
        employee,
        current_section="documents",
    )
    return render(request, "employees/self_service_documents.html", context)


@login_required
def self_service_working_time_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )

    context = build_self_service_page_context(
        request,
        employee,
        current_section="working_time",
    )
    return render(request, "employees/self_service_working_time.html", context)


@login_required
def self_service_branch_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )
    if not can_view_branch_self_service(employee):
        messages.error(request, "This employee is not linked to any branch yet.")
        return redirect("employees:self_service_profile")

    week_value = (request.POST.get("week") or request.GET.get("week") or "").strip()
    selected_week_start = get_schedule_week_start(timezone.localdate())
    if week_value:
        try:
            selected_week_start = get_schedule_week_start(date.fromisoformat(week_value))
        except ValueError:
            messages.warning(request, "Invalid week selected. Showing the current branch week instead.")

    context = build_self_service_page_context(
        request,
        employee,
        current_section="branch",
    )
    context.update(build_branch_team_structure(employee))
    context.update(build_branch_weekly_schedule_summary(employee.branch, selected_week_start))
    context.update(
        build_branch_workspace_context(
            employee.branch,
            request.user,
            employee=employee,
            week_start=selected_week_start,
        )
    )
    context.update(build_employee_schedule_snapshot(employee))
    context["branch"] = employee.branch
    context["selected_week_start"] = selected_week_start
    context["can_manage_branch_weekly_schedule"] = can_manage_branch_weekly_schedule(request.user, employee.branch)
    context["branch_post_form"] = BranchPostForm(
        branch=employee.branch,
        can_manage=context["can_manage_branch_workspace"],
    )
    context["branch_workspace_detail_url"] = reverse(
        "operations:branch_workspace_detail",
        kwargs={"branch_id": employee.branch_id},
    )
    context["branch_workspace_schedule_url"] = reverse("employees:self_service_weekly_schedule")
    return render(request, "employees/self_service_branch.html", context)


def get_branch_standard_duty_option_seed_data():
    return [
        {"label": "9 am to 5 pm", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "09:00", "end": "17:00", "bg": "#ef4444", "text": "#f8fafc", "order": 1},
        {"label": "2 pm to 10 pm", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "14:00", "end": "22:00", "bg": "#2563eb", "text": "#f8fafc", "order": 2},
        {"label": "3 pm to 11 pm", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "15:00", "end": "23:00", "bg": "#7c3aed", "text": "#f8fafc", "order": 3},
        {"label": "4 pm to 12 am", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "16:00", "end": "23:59", "bg": "#8b5cf6", "text": "#f8fafc", "order": 4},
        {"label": "1 pm to 9 pm", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "13:00", "end": "21:00", "bg": "#0ea5e9", "text": "#f8fafc", "order": 5},
        {"label": "12 pm to 8 pm", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "12:00", "end": "20:00", "bg": "#3b82f6", "text": "#f8fafc", "order": 6},
        {"label": "off", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_OFF, "start": None, "end": None, "bg": "#facc15", "text": "#111827", "order": 7},
        {"label": "extra off", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_EXTRA_OFF, "start": None, "end": None, "bg": "#eab308", "text": "#111827", "order": 8},
        {"label": "sick leave", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM, "start": None, "end": None, "bg": "#22c55e", "text": "#052e16", "order": 9},
        {"label": "emergency leave", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM, "start": None, "end": None, "bg": "#f97316", "text": "#fff7ed", "order": 10},
        {"label": "vacation", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM, "start": None, "end": None, "bg": "#14b8a6", "text": "#f0fdfa", "order": 11},
        {"label": "support", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM, "start": None, "end": None, "bg": "#64748b", "text": "#f8fafc", "order": 12},
        {"label": "Morning shift", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "09:00", "end": "17:00", "bg": "#f59e0b", "text": "#111827", "order": 13},
        {"label": "Middle shift", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "13:00", "end": "21:00", "bg": "#06b6d4", "text": "#083344", "order": 14},
        {"label": "Evening shift", "duty_type": BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT, "start": "15:00", "end": "23:00", "bg": "#8b5cf6", "text": "#f8fafc", "order": 15},
    ]


def _parse_seed_time(value):
    if not value:
        return None
    return datetime.strptime(value, "%H:%M").time()


def seed_branch_standard_duty_options(branch):
    created = 0
    updated = 0
    for row in get_branch_standard_duty_option_seed_data():
        option, was_created = BranchWeeklyDutyOption.objects.get_or_create(
            branch=branch,
            label=row["label"],
            defaults={
                "duty_type": row["duty_type"],
                "default_start_time": _parse_seed_time(row["start"]),
                "default_end_time": _parse_seed_time(row["end"]),
                "background_color": row["bg"],
                "text_color": row["text"],
                "display_order": row["order"],
                "is_active": True,
            },
        )
        if was_created:
            created += 1
            continue

        changed = False
        # Safe live fix:
        # keep custom colors that managers already changed manually.
        # Seed should refresh structure/order/timing only for existing rows.
        for field_name, value in {
            "duty_type": row["duty_type"],
            "default_start_time": _parse_seed_time(row["start"]),
            "default_end_time": _parse_seed_time(row["end"]),
            "display_order": row["order"],
            "is_active": True,
        }.items():
            if getattr(option, field_name) != value:
                setattr(option, field_name, value)
                changed = True

        if changed:
            option.save()
            sync_schedule_entries_for_duty_option(option)
            updated += 1
    return created, updated


def sync_schedule_entries_for_duty_option(duty_option):
    if not duty_option:
        return
    update_kwargs = {
        "duty_type": duty_option.duty_type,
        "shift_label": duty_option.label,
        "updated_by": "Duty Shift Master",
    }
    if duty_option.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT:
        update_kwargs["start_time"] = duty_option.default_start_time
        update_kwargs["end_time"] = duty_option.default_end_time
    else:
        update_kwargs["start_time"] = None
        update_kwargs["end_time"] = None
    BranchWeeklyScheduleEntry.objects.filter(duty_option=duty_option).update(**update_kwargs)


def build_manual_schedule_builder_rows(*, team_schedule_rows, week_days):
    rows = []
    for row in team_schedule_rows:
        employee = row.get("employee")
        if not employee:
            continue
        cells = []
        for current_date, cell in zip(week_days, row.get("cells", [])):
            entry = cell.get("entry")
            cells.append(
                {
                    "date": current_date,
                    "field_name": f"manual_duty_{employee.id}_{current_date.isoformat()}",
                    "selected_duty_option_id": str(entry.duty_option_id) if entry and entry.duty_option_id else "",
                    "entry": entry,
                }
            )
        rows.append(
            {
                "employee": employee,
                "pending_off_total": row.get("pending_off_total", 0),
                "pending_off_field_name": f"manual_pending_off_{employee.id}",
                "cells": cells,
            }
        )
    return rows


@login_required
def self_service_weekly_schedule_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )
    if not can_view_branch_self_service(employee):
        messages.error(request, "This employee is not linked to any branch yet.")
        return redirect("employees:self_service_profile")

    week_value = (request.GET.get("week") or request.POST.get("week") or "").strip()
    selected_week_start = get_schedule_week_start(timezone.localdate())
    if week_value:
        try:
            selected_week_start = get_schedule_week_start(date.fromisoformat(week_value))
        except ValueError:
            messages.warning(request, "Invalid week selected. Showing the current branch week instead.")

    branch = employee.branch
    can_manage_schedule = can_manage_branch_weekly_schedule(request.user, branch)
    import_form = BranchWeeklyScheduleImportForm()

    if request.method == "POST" and can_manage_schedule:
        action = (request.POST.get("schedule_action") or "").strip()
        redirect_url = f"{reverse('employees:self_service_weekly_schedule')}?week={selected_week_start.isoformat()}"

        if action == "import_schedule":
            import_form = BranchWeeklyScheduleImportForm(request.POST, request.FILES)
            if import_form.is_valid():
                import_result = import_branch_weekly_schedule_file(
                    branch=branch,
                    week_start=selected_week_start,
                    uploaded_file=import_form.cleaned_data["import_file"],
                    actor_label=get_actor_label(request.user),
                    replace_existing=import_form.cleaned_data.get("replace_existing", False),
                )
                if import_result["imported_count"]:
                    mode_label = "replaced" if import_result.get("replace_existing") else "merged into"
                    messages.success(request, f"Imported {import_result['imported_count']} schedule row(s) and {mode_label} the selected branch week.")
                elif import_result.get("replace_existing"):
                    messages.warning(request, "The current week was cleared, but no non-empty duty cells were imported from the file.")
                else:
                    messages.warning(request, "No schedule rows were imported. If you want the uploaded file to fully replace the current sheet, keep 'Replace current week schedule before import' checked.")
                if import_result.get("skipped_empty_cells"):
                    messages.info(request, f"Skipped {import_result['skipped_empty_cells']} empty schedule cell(s). Empty cells only clear old values when replacement mode is enabled.")
                if import_result["errors"]:
                    messages.warning(request, "Some rows were skipped during import: " + " | ".join(import_result["errors"][:5]))
                changed_employees = list(
                    Employee.objects.filter(pk__in=import_result.get("changed_employee_ids", [])).order_by("full_name", "employee_id")
                )
                if changed_employees:
                    notify_schedule_week_updated(
                        branch,
                        selected_week_start,
                        changed_employees,
                        actor_label=get_actor_label(request.user),
                        detail_text="Please review your updated branch week plan.",
                    )
                return redirect(redirect_url)
            messages.error(request, "Please upload a valid .xlsx or .csv file for schedule import.")

        if action == "export_schedule":
            workbook = build_branch_schedule_export_workbook(branch, selected_week_start, include_existing_entries=True)
            response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = f'attachment; filename="{branch.name.lower().replace(" ", "-")}-schedule-{selected_week_start.isoformat()}.xlsx"'
            workbook.save(response)
            return response

        if action == "export_schedule_template":
            workbook = build_branch_schedule_export_workbook(branch, selected_week_start, include_existing_entries=False)
            response = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            response["Content-Disposition"] = f'attachment; filename="{branch.name.lower().replace(" ", "-")}-schedule-template-{selected_week_start.isoformat()}.xlsx"'
            workbook.save(response)
            return response

        if action == "seed_standard_duty_options":
            created_count, updated_count = seed_branch_standard_duty_options(branch)
            messages.success(request, f"Loaded the standard duty list. Created {created_count} and refreshed {updated_count} existing duty option(s).")
            return redirect(redirect_url)

        if action == "create_duty_option":
            duty_option_create_form = BranchWeeklyDutyOptionForm(request.POST)
            if duty_option_create_form.is_valid():
                new_option = duty_option_create_form.save(commit=False)
                new_option.branch = branch
                if not new_option.display_order:
                    new_option.display_order = BranchWeeklyDutyOption.objects.filter(branch=branch).count() + 1
                new_option.save()
                messages.success(request, f"Created duty option '{new_option.label}'.")
                return redirect(redirect_url)
            messages.error(request, "Please review the new duty option details.")

        if action == "update_duty_option_master":
            duty_option = get_object_or_404(BranchWeeklyDutyOption, pk=request.POST.get("duty_option_id"), branch=branch)
            master_form = BranchWeeklyDutyOptionForm(request.POST, instance=duty_option)
            if master_form.is_valid():
                updated_option = master_form.save()
                sync_schedule_entries_for_duty_option(updated_option)
                messages.success(request, f"Updated duty option '{updated_option.label}'.")
                return redirect(redirect_url)
            messages.error(request, f"Please review the duty option '{duty_option.label}'.")

        if action == "delete_duty_option":
            duty_option = get_object_or_404(BranchWeeklyDutyOption, pk=request.POST.get("duty_option_id"), branch=branch)
            linked_entries = BranchWeeklyScheduleEntry.objects.filter(duty_option=duty_option)
            linked_entries.update(
                duty_option=None,
                duty_type=duty_option.duty_type,
                shift_label=duty_option.label,
                start_time=duty_option.default_start_time if duty_option.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT else None,
                end_time=duty_option.default_end_time if duty_option.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT else None,
                updated_by=get_actor_label(request.user),
            )
            deleted_label = duty_option.label
            duty_option.delete()
            messages.success(request, f"Deleted duty option '{deleted_label}'. Existing schedule rows kept their copied label and timing.")
            return redirect(redirect_url)

        if action == "reset_duty_option_style":
            duty_option = get_object_or_404(BranchWeeklyDutyOption, pk=request.POST.get("duty_option_id"), branch=branch)
            duty_option.background_color = ""
            duty_option.text_color = ""
            duty_option.save(update_fields=["background_color", "text_color", "updated_at"])
            sync_schedule_entries_for_duty_option(duty_option)
            messages.success(request, f"Reset colors for duty option '{duty_option.label}'.")
            return redirect(redirect_url)

        if action == "update_schedule_theme":
            schedule_theme, _created = BranchWeeklyScheduleTheme.objects.get_or_create(branch=branch)
            schedule_theme_form = BranchWeeklyScheduleThemeForm(request.POST, instance=schedule_theme)
            if schedule_theme_form.is_valid():
                schedule_theme_form.save()
                messages.success(request, "Updated schedule table colors.")
                return redirect(redirect_url)
            messages.error(request, "Please review the schedule table colors.")

        if action == "reset_schedule_theme":
            schedule_theme, _created = BranchWeeklyScheduleTheme.objects.get_or_create(branch=branch)
            schedule_theme.employee_column_bg = "#101828"
            schedule_theme.employee_column_text = "#f8fafc"
            schedule_theme.job_title_column_bg = "#111827"
            schedule_theme.job_title_column_text = "#f8fafc"
            schedule_theme.pending_off_column_bg = "#172033"
            schedule_theme.pending_off_column_text = "#f8fafc"
            schedule_theme.day_header_bg = "#1d293d"
            schedule_theme.day_header_text = "#f8fafc"
            schedule_theme.save()
            messages.success(request, "Reset the schedule table theme.")
            return redirect(redirect_url)

        if action == "save_manual_schedule_builder":
            week_days = build_schedule_week_days(selected_week_start)
            active_options = {
                str(option.id): option
                for option in BranchWeeklyDutyOption.objects.filter(branch=branch, is_active=True)
            }
            branch_employees = list(Employee.objects.filter(branch=branch, is_active=True).order_by("full_name", "employee_id"))
            existing_entries = {
                (entry.employee_id, entry.schedule_date): entry
                for entry in BranchWeeklyScheduleEntry.objects.filter(branch=branch, week_start=selected_week_start)
            }
            saved_count = 0
            cleared_count = 0
            pending_updates = 0
            invalid_pending = []
            changed_employee_ids = set()

            for member in branch_employees:
                pending_field = f"manual_pending_off_{member.id}"
                pending_raw = (request.POST.get(pending_field) or "").strip()
                if pending_raw == "":
                    pending_deleted, _details = BranchWeeklyPendingOff.objects.filter(
                        branch=branch,
                        employee=member,
                        week_start=selected_week_start,
                    ).delete()
                    if pending_deleted:
                        changed_employee_ids.add(member.id)
                else:
                    try:
                        pending_value = int(pending_raw)
                        if pending_value < 0:
                            raise ValueError
                        BranchWeeklyPendingOff.objects.update_or_create(
                            branch=branch,
                            employee=member,
                            week_start=selected_week_start,
                            defaults={
                                "pending_off_count": pending_value,
                                "created_by": get_actor_label(request.user),
                                "updated_by": get_actor_label(request.user),
                            },
                        )
                        pending_updates += 1
                        changed_employee_ids.add(member.id)
                    except ValueError:
                        invalid_pending.append(member.full_name)

                for current_date in week_days:
                    field_name = f"manual_duty_{member.id}_{current_date.isoformat()}"
                    selected_option_id = (request.POST.get(field_name) or "").strip()
                    existing_entry = existing_entries.get((member.id, current_date))
                    if not selected_option_id:
                        if existing_entry:
                            existing_entry.delete()
                            cleared_count += 1
                            changed_employee_ids.add(member.id)
                        continue
                    duty_option = active_options.get(selected_option_id)
                    if duty_option is None:
                        continue
                    defaults = {
                        "week_start": selected_week_start,
                        "duty_option": duty_option,
                        "title": existing_entry.title if existing_entry else "",
                        "order_note": existing_entry.order_note if existing_entry else "",
                        "status": existing_entry.status if existing_entry else BranchWeeklyScheduleEntry.STATUS_PLANNED,
                        "created_by": existing_entry.created_by if existing_entry and existing_entry.created_by else get_actor_label(request.user),
                        "updated_by": get_actor_label(request.user),
                    }
                    BranchWeeklyScheduleEntry.objects.update_or_create(
                        branch=branch,
                        employee=member,
                        schedule_date=current_date,
                        defaults=defaults,
                    )
                    saved_count += 1
                    changed_employee_ids.add(member.id)
            if invalid_pending:
                messages.warning(request, "Some pending off values were ignored because they were invalid numbers: " + ", ".join(invalid_pending[:5]))
            changed_employees = [member for member in branch_employees if member.id in changed_employee_ids]
            if changed_employees:
                notify_schedule_week_updated(
                    branch,
                    selected_week_start,
                    changed_employees,
                    actor_label=get_actor_label(request.user),
                    detail_text="Please review the latest schedule builder changes.",
                )
            messages.success(request, f"Saved manual schedule builder changes. Updated {saved_count} cell(s), cleared {cleared_count} cell(s), and refreshed {pending_updates} pending-off value(s).")
            return redirect(redirect_url)

        if action == "update_employee_order":
            active_employee_ids = [employee_id for employee_id in request.POST.getlist("ordered_employee_ids") if employee_id and employee_id.isdigit()]
            seen_ids = set()
            ordered_ids = []
            for employee_id in active_employee_ids:
                if employee_id not in seen_ids:
                    ordered_ids.append(int(employee_id))
                    seen_ids.add(employee_id)

            branch_employees = {member.id: member for member in Employee.objects.filter(branch=branch, is_active=True)}
            fallback_ids = [member_id for member_id in branch_employees.keys() if member_id not in ordered_ids]
            final_order_ids = ordered_ids + sorted(
                fallback_ids,
                key=lambda member_id: (branch_employees[member_id].full_name.lower(), branch_employees[member_id].employee_id.lower()),
            )

            for index, employee_id in enumerate(final_order_ids, start=1):
                BranchScheduleGridRow.objects.update_or_create(branch=branch, row_index=index, defaults={"employee_id": employee_id})
            messages.success(request, "Updated employee row order for the schedule table.")
            return redirect(redirect_url)

    previous_week_start = selected_week_start - timedelta(days=7)
    next_week_start = selected_week_start + timedelta(days=7)
    selected_week_end = selected_week_start + timedelta(days=6)
    from workcalendar.services import get_holidays_for_range
    selected_week_holidays = get_holidays_for_range(selected_week_start, selected_week_end)

    context = build_self_service_page_context(request, employee, current_section="weekly_schedule")
    context.update(build_branch_weekly_schedule_summary(branch, selected_week_start))
    context["branch"] = branch
    context["selected_week_start"] = selected_week_start
    context["selected_week_holidays"] = selected_week_holidays
    context["previous_week_start"] = previous_week_start
    context["next_week_start"] = next_week_start
    context["today"] = timezone.localdate()
    context["can_manage_branch_weekly_schedule"] = can_manage_schedule
    context.update(build_employee_schedule_snapshot(employee))
    context["schedule_import_form"] = import_form
    schedule_theme, _created = BranchWeeklyScheduleTheme.objects.get_or_create(branch=branch)
    context["schedule_theme"] = schedule_theme
    context["schedule_theme_form"] = BranchWeeklyScheduleThemeForm(instance=schedule_theme)
    duty_options_qs = BranchWeeklyDutyOption.objects.filter(branch=branch).order_by("display_order", "label", "id")
    context["duty_option_create_form"] = BranchWeeklyDutyOptionForm()
    context["manual_duty_options"] = list(duty_options_qs.filter(is_active=True))
    context["duty_option_style_forms"] = [
        {
            "option": duty_option,
            "master_form": BranchWeeklyDutyOptionForm(instance=duty_option),
            "style_form": BranchWeeklyDutyOptionStyleForm(instance=duty_option),
            "timing_form": BranchWeeklyDutyOptionTimingForm(instance=duty_option),
        }
        for duty_option in duty_options_qs
    ]
    context["manual_schedule_rows"] = build_manual_schedule_builder_rows(
        team_schedule_rows=context.get("team_schedule_rows", []),
        week_days=context.get("week_days", []),
    )
    context["employee_order_rows"] = [
        {"employee": row["employee"], "position": forloop_index}
        for forloop_index, row in enumerate(context.get("team_schedule_rows", []), start=1)
        if row.get("employee")
    ]
    return render(request, "employees/self_service_weekly_schedule.html", context)


@login_required
def self_service_my_schedule_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )
    if not can_view_branch_self_service(employee):
        messages.error(request, "This employee is not linked to any branch yet.")
        return redirect("employees:self_service_profile")

    context = build_self_service_page_context(
        request,
        employee,
        current_section="my_schedule",
    )
    from workcalendar.services import get_holidays_for_range
    this_week_start = get_schedule_week_start(timezone.localdate())
    next_week_start = this_week_start + timedelta(days=7)
    context["my_schedule_this_week_holidays"] = get_holidays_for_range(this_week_start, this_week_start + timedelta(days=6))
    context["my_schedule_next_week_holidays"] = get_holidays_for_range(next_week_start, next_week_start + timedelta(days=6))
    context.update(build_employee_schedule_snapshot(employee))
    context["branch"] = employee.branch
    return render(request, "employees/self_service_my_schedule.html", context)


@login_required
def self_service_attendance_page(request):
    employee = get_user_employee_profile(request.user)
    if employee is None:
        raise PermissionDenied("No employee profile is connected to this account.")
    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee profile.",
            employee=employee,
        )

    today = timezone.localdate()
    branch = getattr(employee, "branch", None)
    schedule_snapshot = build_employee_schedule_snapshot(employee, reference_date=today)
    attendance_today_schedule_entry = schedule_snapshot.get("my_schedule_today_entry")
    attendance_today_schedule_label = schedule_snapshot.get("my_schedule_today_label") or "No branch duty assigned"
    attendance_today_schedule_time = (
        attendance_today_schedule_entry.formatted_time_range
        if attendance_today_schedule_entry
        else ""
    )
    attendance_blocked_for_today = bool(
        attendance_today_schedule_entry
        and attendance_today_schedule_entry.duty_type
        in {
            BranchWeeklyScheduleEntry.DUTY_TYPE_OFF,
            BranchWeeklyScheduleEntry.DUTY_TYPE_EXTRA_OFF,
            BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM,
        }
    )
    attendance_shift_locked_value = ""
    if attendance_today_schedule_entry and attendance_today_schedule_entry.duty_type == BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT:
        attendance_shift_locked_value = resolve_attendance_shift_value(
            label=attendance_today_schedule_entry.shift_label or attendance_today_schedule_label,
            start_time=attendance_today_schedule_entry.start_time,
            end_time=attendance_today_schedule_entry.end_time,
        )
    attendance_shift_locked = bool(attendance_shift_locked_value)
    shift_choices = build_self_service_shift_choices(branch)
    branch_has_attendance_location_config = bool(
        branch and getattr(branch, "has_attendance_location_config", False)
    )
    attendance_event = (
        employee.attendance_events.filter(attendance_date=today).select_related("synced_ledger").first()
    )

    if request.method == "POST":
        action = (request.POST.get("attendance_action") or "").strip()
        form_initial = {"shift": attendance_shift_locked_value} if attendance_shift_locked_value else None
        form = EmployeeSelfServiceAttendanceForm(
            request.POST,
            initial=form_initial,
            shift_choices=shift_choices,
            shift_locked=attendance_shift_locked,
        )
        if not branch_has_attendance_location_config:
            form.add_error(
                None,
                "Your branch does not have a fixed attendance point configured yet. Please contact HR or Operations.",
            )
        elif attendance_blocked_for_today:
            form.add_error(
                None,
                f"Attendance is blocked today because your assigned duty is {attendance_today_schedule_label}.",
            )
        elif action not in {"check_in", "check_out"}:
            form.add_error(None, "Unknown attendance action requested.")

        if form.is_valid():
            actor_label = get_actor_label(request.user) or employee.full_name
            validation_result = get_branch_attendance_validation_result(
                employee,
                form.cleaned_data["latitude"],
                form.cleaned_data["longitude"],
            )
            if not validation_result["is_configured"]:
                form.add_error(None, validation_result["error_message"])
            elif not validation_result["is_inside_radius"]:
                form.add_error(
                    None,
                    (
                        f"Attendance denied. You are {validation_result['distance_meters']} m away from "
                        f"{validation_result['branch'].name}. Allowed radius is "
                        f"{validation_result['allowed_radius_meters']} m."
                    ),
                )

        if form.is_valid():
            actor_label = get_actor_label(request.user) or employee.full_name
            validation_result = get_branch_attendance_validation_result(
                employee,
                form.cleaned_data["latitude"],
                form.cleaned_data["longitude"],
            )
            now = timezone.localtime()
            attendance_event, _created = EmployeeAttendanceEvent.objects.get_or_create(
                employee=employee,
                attendance_date=today,
                defaults={
                    "shift": form.cleaned_data["shift"],
                },
            )
            attendance_event.shift = attendance_event.shift or form.cleaned_data["shift"]
            if action == "check_in":
                if attendance_event.check_in_at:
                    messages.warning(request, "Check-in is already registered for today.")
                else:
                    attendance_event.shift = form.cleaned_data["shift"]
                    attendance_event.check_in_at = now
                    attendance_event.check_in_latitude = form.cleaned_data.get("latitude")
                    attendance_event.check_in_longitude = form.cleaned_data.get("longitude")
                    attendance_event.check_in_location_label = validation_result["branch_location_label"]
                    attendance_event.check_in_address = validation_result["validation_summary"]
                    attendance_event.branch_latitude_used = validation_result["branch_latitude"]
                    attendance_event.branch_longitude_used = validation_result["branch_longitude"]
                    attendance_event.attendance_radius_meters_used = validation_result["allowed_radius_meters"]
                    attendance_event.check_in_distance_meters = validation_result["distance_meters"]
                    attendance_event.check_in_location_validation_status = validation_result["validation_status"]
                    attendance_event.notes = form.cleaned_data.get("notes") or ""
                    attendance_event.status = EmployeeAttendanceEvent.STATUS_OPEN
                    attendance_event.save()
                    messages.success(
                        request,
                        (
                            f"Check-in registered successfully. Device location validated at "
                            f"{validation_result['distance_meters']} m from the branch point."
                        ),
                    )
            elif action == "check_out":
                if not attendance_event.check_in_at:
                    messages.error(request, "Please check in first before checking out.")
                elif attendance_event.check_out_at:
                    messages.warning(request, "Check-out is already registered for today.")
                else:
                    attendance_event.check_out_at = now
                    attendance_event.check_out_latitude = form.cleaned_data.get("latitude")
                    attendance_event.check_out_longitude = form.cleaned_data.get("longitude")
                    attendance_event.check_out_location_label = validation_result["branch_location_label"]
                    attendance_event.check_out_address = validation_result["validation_summary"]
                    attendance_event.branch_latitude_used = validation_result["branch_latitude"]
                    attendance_event.branch_longitude_used = validation_result["branch_longitude"]
                    attendance_event.attendance_radius_meters_used = validation_result["allowed_radius_meters"]
                    attendance_event.check_out_distance_meters = validation_result["distance_meters"]
                    attendance_event.check_out_location_validation_status = validation_result["validation_status"]
                    if form.cleaned_data.get("notes"):
                        attendance_event.notes = form.cleaned_data["notes"]
                    attendance_event.status = EmployeeAttendanceEvent.STATUS_COMPLETED
                    attendance_event.save()
                    synced_ledger = sync_attendance_event_to_ledger(attendance_event, actor_label=actor_label)
                    if synced_ledger:
                        create_employee_history(
                            employee=employee,
                            title="Self-service attendance completed",
                            description=(
                                f"Check-in: {timezone.localtime(attendance_event.check_in_at):%I:%M %p}. "
                                f"Check-out: {timezone.localtime(attendance_event.check_out_at):%I:%M %p}. "
                                f"Shift: {synced_ledger.get_shift_display()}. "
                                f"Check-in distance: {attendance_event.check_in_distance_meters or 0} m. "
                                f"Check-out distance: {attendance_event.check_out_distance_meters or 0} m."
                            ),
                            event_type=EmployeeHistory.EVENT_STATUS,
                            created_by=actor_label,
                            is_system_generated=True,
                            event_date=today,
                        )
                    messages.success(
                        request,
                        (
                            f"Check-out registered and synced to attendance management. Device location validated at "
                            f"{validation_result['distance_meters']} m from the branch point."
                        ),
                    )
            return redirect("employees:self_service_attendance")
        messages.error(request, "Please review the attendance details and try again.")
    else:
        initial = {}
        if attendance_shift_locked_value:
            initial["shift"] = attendance_shift_locked_value
        elif attendance_event and attendance_event.shift:
            initial["shift"] = attendance_event.shift
        form = EmployeeSelfServiceAttendanceForm(
            initial=initial,
            shift_choices=shift_choices,
            shift_locked=attendance_shift_locked,
        )

    attendance_history_queryset = employee.attendance_events.select_related("synced_ledger").order_by(
        "-attendance_date",
        "-check_in_at",
        "-id",
    )
    attendance_history_paginator = Paginator(attendance_history_queryset, 8)
    attendance_history_page_obj = attendance_history_paginator.get_page(request.GET.get("page"))
    attendance_history_query_params = request.GET.copy()
    attendance_history_query_params.pop("page", None)

    context = build_self_service_page_context(
        request,
        employee,
        current_section="attendance",
    )
    context["attendance_event_today"] = attendance_event
    context["attendance_self_service_form"] = form
    context["recent_attendance_events"] = list(attendance_history_page_obj.object_list)
    context["recent_attendance_page_obj"] = attendance_history_page_obj
    context["recent_attendance_pagination_items"] = build_attendance_history_pagination(
        attendance_history_page_obj
    )
    context["recent_attendance_querystring"] = attendance_history_query_params.urlencode()
    context["attendance_branch"] = branch
    context["attendance_branch_has_location_config"] = branch_has_attendance_location_config
    context["attendance_branch_latitude"] = getattr(branch, "attendance_latitude", None)
    context["attendance_branch_longitude"] = getattr(branch, "attendance_longitude", None)
    context["attendance_branch_radius_meters"] = getattr(branch, "attendance_radius_meters", None)
    context["attendance_today_schedule_entry"] = attendance_today_schedule_entry
    context["attendance_today_schedule_label"] = attendance_today_schedule_label
    context["attendance_today_schedule_time"] = attendance_today_schedule_time
    context["attendance_shift_locked"] = attendance_shift_locked
    context["attendance_blocked_for_today"] = attendance_blocked_for_today
    context["today"] = today
    return render(request, "employees/self_service_attendance.html", context)


