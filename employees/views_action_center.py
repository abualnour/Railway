from .views_shared import *
from .views_directory import *
from .views_management import *

# Management action center modal forms and update endpoints.

class ActionCenterEmployeeProfileForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "full_name",
            "photo",
            "email",
            "phone",
            "birth_date",
            "marital_status",
            "nationality",
            "hire_date",
            "passport_reference_number",
            "passport_issue_date",
            "passport_expiry_date",
            "civil_id_reference_number",
            "civil_id_issue_date",
            "civil_id_expiry_date",
            "is_kuwaiti_national",
            "pifss_registration_number",
            "salary",
            "notes",
        ]
        widgets = {
            "birth_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "hire_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "passport_issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "passport_expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "civil_id_issue_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "civil_id_expiry_date": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for date_field_name in [
            "birth_date",
            "hire_date",
            "passport_issue_date",
            "passport_expiry_date",
            "civil_id_issue_date",
            "civil_id_expiry_date",
        ]:
            if date_field_name in self.fields:
                self.fields[date_field_name].input_formats = ["%Y-%m-%d"]

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, forms.FileInput):
                widget.attrs["class"] = "form-control"
            else:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} form-control".strip()

    def clean(self):
        cleaned_data = super().clean()

        birth_date = cleaned_data.get("birth_date")
        passport_issue_date = cleaned_data.get("passport_issue_date")
        passport_expiry_date = cleaned_data.get("passport_expiry_date")
        civil_id_issue_date = cleaned_data.get("civil_id_issue_date")
        civil_id_expiry_date = cleaned_data.get("civil_id_expiry_date")

        if birth_date and birth_date > timezone.localdate():
            self.add_error("birth_date", "Birth date cannot be in the future.")

        if passport_issue_date and passport_expiry_date and passport_issue_date > passport_expiry_date:
            self.add_error(
                "passport_expiry_date",
                "Passport expiry date must be on or after the passport issue date.",
            )

        if civil_id_issue_date and civil_id_expiry_date and civil_id_issue_date > civil_id_expiry_date:
            self.add_error(
                "civil_id_expiry_date",
                "Civil ID expiry date must be on or after the Civil ID issue date.",
            )

        if cleaned_data.get("is_kuwaiti_national") and not (cleaned_data.get("pifss_registration_number") or "").strip():
            self.add_error(
                "pifss_registration_number",
                "PIFSS registration number is required for Kuwaiti nationals.",
            )

        return cleaned_data



class EmployeeInformationModalForm(ActionCenterEmployeeProfileForm):
    class Meta(ActionCenterEmployeeProfileForm.Meta):
        fields = [
            "full_name",
            "photo",
            "email",
            "phone",
            "birth_date",
            "marital_status",
            "nationality",
            "hire_date",
            "is_kuwaiti_national",
            "pifss_registration_number",
            "salary",
        ]


class EmployeeIdentityModalForm(ActionCenterEmployeeProfileForm):
    class Meta(ActionCenterEmployeeProfileForm.Meta):
        fields = [
            "passport_reference_number",
            "passport_issue_date",
            "passport_expiry_date",
            "civil_id_reference_number",
            "civil_id_issue_date",
            "civil_id_expiry_date",
        ]


def build_employee_payroll_modal_summary(old_profile, new_profile):
    changes = []
    tracked_fields = [
        ("company", "Payroll company"),
        ("base_salary", "Base salary"),
        ("housing_allowance", "Housing allowance"),
        ("transport_allowance", "Transport allowance"),
        ("fixed_deduction", "Fixed deduction"),
        ("pifss_employee_rate", "PIFSS employee rate"),
        ("pifss_employer_rate", "PIFSS employer rate"),
        ("bank_name", "Bank name"),
        ("iban", "IBAN"),
        ("status", "Payroll status"),
    ]

    for field_name, label in tracked_fields:
        old_value = getattr(old_profile, field_name, None) if old_profile else None
        new_value = getattr(new_profile, field_name, None)
        if old_value != new_value:
            changes.append(
                f"{label} changed from {format_history_value(old_value)} to {format_history_value(new_value)}."
            )

    return " ".join(changes) if changes else "Payroll profile details were updated from the employee profile."


def build_employee_information_modal_summary(old_employee, new_employee):
    changes = []
    tracked_fields = [
        ("full_name", "Full name"),
        ("email", "Email"),
        ("phone", "Phone"),
        ("birth_date", "Birth date"),
        ("marital_status", "Marital status"),
        ("nationality", "Nationality"),
        ("hire_date", "Hire date"),
        ("is_kuwaiti_national", "Kuwaiti national status"),
        ("pifss_registration_number", "PIFSS registration number"),
        ("salary", "Salary"),
    ]

    for field_name, label in tracked_fields:
        old_value = getattr(old_employee, field_name)
        new_value = getattr(new_employee, field_name)
        if old_value != new_value:
            changes.append(
                f"{label} changed from {format_history_value(old_value)} to {format_history_value(new_value)}."
            )

    if getattr(old_employee, "photo", None) != getattr(new_employee, "photo", None):
        changes.append("Profile photo was updated.")

    return " ".join(changes) if changes else "Employee information was updated from the profile modal."


def build_employee_identity_modal_summary(old_employee, new_employee):
    changes = []
    tracked_fields = [
        ("passport_reference_number", "Passport reference number"),
        ("passport_issue_date", "Passport issue date"),
        ("passport_expiry_date", "Passport expiry date"),
        ("civil_id_reference_number", "Civil ID reference number"),
        ("civil_id_issue_date", "Civil ID issue date"),
        ("civil_id_expiry_date", "Civil ID expiry date"),
    ]

    for field_name, label in tracked_fields:
        old_value = getattr(old_employee, field_name)
        new_value = getattr(new_employee, field_name)
        if old_value != new_value:
            changes.append(
                f"{label} changed from {format_history_value(old_value)} to {format_history_value(new_value)}."
            )

    return " ".join(changes) if changes else "Passport and Civil ID details were updated from the profile modal."


def render_employee_detail_with_modal_forms(request, employee, **kwargs):
    detail_view = EmployeeDetailView()
    detail_view.request = request
    detail_view.object = employee
    detail_view.kwargs = {"pk": employee.pk}
    detail_view.args = ()
    context = detail_view.get_context_data(**kwargs)
    return render(request, detail_view.template_name, context)



@login_required
@require_POST
def employee_profile_payroll_information_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_create_or_edit_employees(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to edit payroll details for this employee.",
            employee=employee,
        )

    PayrollProfile = apps.get_model("payroll", "PayrollProfile")
    existing_profile = PayrollProfile.objects.filter(employee=employee).first()
    original_snapshot = PayrollProfile.objects.get(pk=existing_profile.pk) if existing_profile else None
    form = PayrollProfileForm(request.POST, instance=existing_profile, employee=employee)

    if form.is_valid():
        payroll_profile = form.save(commit=False)
        payroll_profile.employee = employee
        if not payroll_profile.company_id and employee.company_id:
            payroll_profile.company_id = employee.company_id
        payroll_profile.save()
        create_employee_history(
            employee=employee,
            title="Payroll profile updated",
            description=build_employee_payroll_modal_summary(original_snapshot, payroll_profile),
            event_type=EmployeeHistory.EVENT_PROFILE,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        messages.success(request, "Payroll profile updated successfully.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': employee.pk})}#employee-payroll-section")

    messages.error(request, "Please correct the payroll profile fields and try again.")
    return render_employee_detail_with_modal_forms(
        request,
        employee,
        employee_payroll_profile_form=form,
        active_profile_modal="payroll_information",
    )


@login_required
@require_POST
def employee_profile_employee_information_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_create_or_edit_employees(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to edit this employee section.",
            employee=employee,
        )

    original_employee = Employee.objects.get(pk=employee.pk)
    form = EmployeeInformationModalForm(request.POST, request.FILES, instance=employee)

    if form.is_valid():
        form.save()
        create_employee_history(
            employee=employee,
            title="Employee information updated",
            description=build_employee_information_modal_summary(original_employee, employee),
            event_type=EmployeeHistory.EVENT_PROFILE,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        messages.success(request, "Employee information updated successfully.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': employee.pk})}#employee-information-section")

    messages.error(request, "Please correct the employee information fields and try again.")
    return render_employee_detail_with_modal_forms(
        request,
        employee,
        employee_information_modal_form=form,
        active_profile_modal="employee_information",
    )


@login_required
@require_POST
def employee_profile_identity_information_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_create_or_edit_employees(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to edit this employee section.",
            employee=employee,
        )

    original_employee = Employee.objects.get(pk=employee.pk)
    form = EmployeeIdentityModalForm(request.POST, instance=employee)

    if form.is_valid():
        form.save()
        create_employee_history(
            employee=employee,
            title="Identity information updated",
            description=build_employee_identity_modal_summary(original_employee, employee),
            event_type=EmployeeHistory.EVENT_PROFILE,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        messages.success(request, "Passport and Civil ID details updated successfully.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': employee.pk})}#employee-information-section")

    messages.error(request, "Please correct the passport and Civil ID fields and try again.")
    return render_employee_detail_with_modal_forms(
        request,
        employee,
        identity_information_modal_form=form,
        active_profile_modal="identity_information",
    )



@login_required
def employee_admin_action_center(request):
    if not is_management_user(request.user):
        raise PermissionDenied("You do not have permission to access the employee action center.")

    today = timezone.localdate()
    current_user = request.user

    employee_queryset = get_employee_directory_queryset_for_user(
        current_user,
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        ).all(),
    )

    search_query = ((request.POST.get("search") if request.method == "POST" else request.GET.get("search")) or "").strip()
    selected_employee = None
    selected_employee_param = ((request.POST.get("employee") if request.method == "POST" else request.GET.get("employee")) or "").strip()
    current_page_param = ((request.POST.get("page") if request.method == "POST" else request.GET.get("page")) or "1").strip()

    employee_picker_queryset = employee_queryset.order_by("full_name", "employee_id")
    if search_query:
        employee_picker_queryset = employee_picker_queryset.filter(
            Q(full_name__icontains=search_query)
            | Q(employee_id__icontains=search_query)
        )

    employee_picker_paginator = Paginator(employee_picker_queryset, 6)
    current_page_number = 1
    if current_page_param.isdigit():
        current_page_number = max(1, int(current_page_param))

    employee_picker_page = employee_picker_paginator.get_page(current_page_number)
    quick_employee_results = list(employee_picker_page.object_list)

    if selected_employee_param.isdigit():
        selected_employee = employee_queryset.filter(pk=int(selected_employee_param)).first()
    elif request.method != "POST" and employee_picker_paginator.count == 1:
        selected_employee = employee_picker_queryset.first()

    action_center_action_form = EmployeeActionRecordForm()
    action_center_required_submission_form = EmployeeRequiredSubmissionCreateForm()
    action_center_leave_form = EmployeeLeaveForm()
    action_center_attendance_form = EmployeeAttendanceLedgerForm(employee=selected_employee) if selected_employee else EmployeeAttendanceLedgerForm()
    action_center_transfer_form = EmployeeTransferForm(instance=selected_employee) if selected_employee else EmployeeTransferForm()
    action_center_profile_form = ActionCenterEmployeeProfileForm(instance=selected_employee) if selected_employee else ActionCenterEmployeeProfileForm()

    def build_action_center_redirect(employee_obj=None, search_value="", page_number=None):
        employee_obj = employee_obj or selected_employee
        params = []
        if search_value:
            params.append(f"search={search_value}")
        if employee_obj:
            params.append(f"employee={employee_obj.pk}")
        resolved_page = page_number or employee_picker_page.number
        if resolved_page:
            params.append(f"page={resolved_page}")
        base_url = reverse("employees:employee_admin_action_center")
        return f"{base_url}?{'&'.join(params)}" if params else base_url

    if request.method == "POST":
        if not selected_employee:
            messages.error(request, "Select an employee first before submitting an Action Center form.")
            return redirect(build_action_center_redirect(search_value=search_query))

        action_center_post = (request.POST.get("action_center_post") or "").strip()

        if action_center_post == "status_action":
            if not can_change_employee_status(current_user):
                return deny_employee_access(
                    request,
                    "You do not have permission to change employee status.",
                    employee=selected_employee,
                )

            target_status = (request.POST.get("target_status") or "").strip()
            valid_statuses = {value for value, _label in Employee.EMPLOYMENT_STATUS_CHOICES}
            if target_status not in valid_statuses:
                messages.error(request, "Invalid employee status action.")
            else:
                selected_employee.employment_status = target_status
                selected_employee.is_active = target_status != Employee.EMPLOYMENT_STATUS_INACTIVE
                selected_employee.save(update_fields=["employment_status", "is_active", "updated_at"])
                actor_label = get_actor_label(request.user)
                create_employee_history(
                    employee=selected_employee,
                    title="Employee status updated",
                    description=f"Employee status changed to {selected_employee.get_employment_status_display()} from the Action Center.",
                    event_type=EmployeeHistory.EVENT_STATUS,
                    created_by=actor_label,
                    is_system_generated=True,
                    event_date=timezone.localdate(),
                )
                notify_employee_status_updated(selected_employee, actor_label=actor_label)
                messages.success(request, "Employee status updated successfully from the Action Center.")
            return redirect(build_action_center_redirect(selected_employee, search_query))

        if action_center_post == "action_record":
            if not can_create_action_records(current_user):
                return deny_employee_access(
                    request,
                    "You do not have permission to create employee action records.",
                    employee=selected_employee,
                )

            action_center_action_form = EmployeeActionRecordForm(request.POST)
            if action_center_action_form.is_valid():
                action_record = action_center_action_form.save(commit=False)
                action_record.employee = selected_employee
                action_record.created_by = get_actor_label(request.user)
                action_record.updated_by = get_actor_label(request.user)
                action_record.save()
                create_employee_history(
                    employee=selected_employee,
                    title=f"Action record created: {action_record.title}",
                    description=(
                        f"Action Type: {action_record.get_action_type_display()}. "
                        f"Status: {action_record.get_status_display()}. "
                        f"Severity: {action_record.get_severity_display()}. "
                        + (f"Description: {action_record.description}" if action_record.description else "")
                    ).strip(),
                    event_type=EmployeeHistory.EVENT_NOTE,
                    created_by=get_actor_label(request.user),
                    is_system_generated=True,
                    event_date=action_record.action_date or timezone.localdate(),
                )
                notify_employee_action_record_created(selected_employee, action_record)
                messages.success(request, "Employee action record created successfully from the Action Center.")
                return redirect(build_action_center_redirect(selected_employee, search_query))

            messages.error(request, "Please review the action record form and try again.")

        elif action_center_post == "required_submission":
            if not can_manage_employee_required_submissions(current_user, selected_employee):
                return deny_employee_access(
                    request,
                    "You do not have permission to create employee required submission requests.",
                    employee=selected_employee,
                )

            action_center_required_submission_form = EmployeeRequiredSubmissionCreateForm(request.POST)
            if action_center_required_submission_form.is_valid():
                submission_request = action_center_required_submission_form.save(commit=False)
                submission_request.employee = selected_employee
                submission_request.created_by = request.user
                submission_request.status = EmployeeRequiredSubmission.STATUS_REQUESTED
                submission_request.reviewed_by = None
                submission_request.review_note = ""
                submission_request.reviewed_at = None
                submission_request.submitted_at = None
                submission_request.save()
                create_employee_history(
                    employee=selected_employee,
                    title=f"Required employee submission requested: {submission_request.title}",
                      description=(
                          f"Request Type: {submission_request.get_request_type_display()}. "
                          f"Priority: {submission_request.get_priority_display()}. "
                        + (
                            f"Due Date: {submission_request.due_date.strftime('%B %d, %Y')}. "
                            if submission_request.due_date else ""
                        )
                        + (f"Instructions: {submission_request.instructions}" if submission_request.instructions else "")
                    ).strip(),
                    event_type=EmployeeHistory.EVENT_DOCUMENT,
                    created_by=get_actor_label(request.user),
                    is_system_generated=True,
                    event_date=timezone.localdate(),
                )
                notify_required_submission_created(submission_request)
                messages.success(request, "Required employee submission request created successfully from the Action Center.")
                return redirect(build_action_center_redirect(selected_employee, search_query))

            first_error = "Please review the required submission request form and try again."
            if action_center_required_submission_form.errors:
                first_field_errors = next(iter(action_center_required_submission_form.errors.values()))
                if first_field_errors:
                    first_error = first_field_errors[0]
            messages.error(request, first_error)

        elif action_center_post == "leave_request":
            if not can_request_leave(current_user, selected_employee):
                return deny_employee_access(
                    request,
                    "You do not have permission to create leave requests for this employee.",
                    employee=selected_employee,
                )

            action_center_leave_form = EmployeeLeaveForm(request.POST)
            if action_center_leave_form.is_valid():
                leave_record = action_center_leave_form.save(commit=False)
                leave_record.employee = selected_employee
                leave_record.requested_by = request.user
                leave_record.created_by = get_actor_label(request.user)
                leave_record.updated_by = get_actor_label(request.user)
                leave_record.status = EmployeeLeave.STATUS_PENDING
                leave_record.current_stage = EmployeeLeave.STAGE_SUPERVISOR_REVIEW
                leave_record.save()
                create_employee_history(
                    employee=selected_employee,
                    title=f"Leave requested: {leave_record.get_leave_type_display()}",
                    description=build_leave_request_summary(leave_record),
                    event_type=EmployeeHistory.EVENT_STATUS,
                    created_by=get_actor_label(request.user),
                    is_system_generated=True,
                    event_date=leave_record.start_date,
                )
                notify_leave_request_submitted(leave_record)
                messages.success(request, "Leave request created successfully from the Action Center.")
                return redirect(build_action_center_redirect(selected_employee, search_query))

            first_error = "Please review the leave request form and try again."
            if action_center_leave_form.errors:
                first_field_errors = next(iter(action_center_leave_form.errors.values()))
                if first_field_errors:
                    first_error = first_field_errors[0]
            messages.error(request, first_error)

        elif action_center_post == "attendance_action":
            if not can_manage_attendance_records(current_user):
                return deny_employee_access(
                    request,
                    "You do not have permission to create attendance ledger entries.",
                    employee=selected_employee,
                )

            action_center_attendance_form = EmployeeAttendanceLedgerForm(request.POST, employee=selected_employee)
            if action_center_attendance_form.is_valid():
                attendance_entry = action_center_attendance_form.save(commit=False)
                attendance_entry.employee = selected_employee
                attendance_entry.source = EmployeeAttendanceLedger.SOURCE_MANUAL
                actor_label = get_actor_label(request.user)
                attendance_entry.created_by = actor_label
                attendance_entry.updated_by = actor_label
                attendance_entry.save()
                create_employee_history(
                    employee=selected_employee,
                    title=f"Attendance ledger entry added: {attendance_entry.attendance_date}",
                    description=build_attendance_ledger_summary(attendance_entry),
                    event_type=EmployeeHistory.EVENT_STATUS,
                    created_by=actor_label,
                    is_system_generated=True,
                    event_date=attendance_entry.attendance_date,
                )
                messages.success(request, "Attendance entry created successfully from the Action Center.")
                return redirect(build_action_center_redirect(selected_employee, search_query))

            first_error = "Please review the attendance form and try again."
            if action_center_attendance_form.errors:
                first_field_errors = next(iter(action_center_attendance_form.errors.values()))
                if first_field_errors:
                    first_error = first_field_errors[0]
            messages.error(request, first_error)

        elif action_center_post == "transfer_action":
            if not can_transfer_employee(current_user):
                return deny_employee_access(
                    request,
                    "You do not have permission to transfer employee placements.",
                    employee=selected_employee,
                )

            original_employee = Employee.objects.get(pk=selected_employee.pk)
            action_center_transfer_form = EmployeeTransferForm(request.POST, instance=selected_employee)
            if action_center_transfer_form.is_valid():
                transferred_employee = action_center_transfer_form.save()
                transfer_note = action_center_transfer_form.cleaned_data.get("notes", "")
                create_employee_history(
                    employee=transferred_employee,
                    title="Employee placement transferred",
                    description=build_employee_transfer_summary(original_employee, transferred_employee, transfer_note=transfer_note),
                    event_type=EmployeeHistory.EVENT_TRANSFER,
                    created_by=get_actor_label(request.user),
                    is_system_generated=True,
                    event_date=timezone.localdate(),
                )
                messages.success(request, "Employee placement updated successfully from the Action Center.")
                return redirect(build_action_center_redirect(transferred_employee, search_query))

            first_error = "Please review the transfer form and try again."
            if action_center_transfer_form.errors:
                first_field_errors = next(iter(action_center_transfer_form.errors.values()))
                if first_field_errors:
                    first_error = first_field_errors[0]
            messages.error(request, first_error)

        elif action_center_post == "profile_update":
            if not can_create_or_edit_employees(current_user):
                return deny_employee_access(
                    request,
                    "You do not have permission to update employee profile details.",
                    employee=selected_employee,
                )

            original_employee = Employee.objects.get(pk=selected_employee.pk)
            action_center_profile_form = ActionCenterEmployeeProfileForm(
                request.POST,
                request.FILES,
                instance=selected_employee,
            )
            if action_center_profile_form.is_valid():
                updated_employee = action_center_profile_form.save()
                create_employee_history(
                    employee=updated_employee,
                    title="Employee profile updated",
                    description=build_employee_change_summary(original_employee, updated_employee),
                    event_type=EmployeeHistory.EVENT_PROFILE,
                    created_by=get_actor_label(request.user),
                    is_system_generated=True,
                    event_date=timezone.localdate(),
                )
                messages.success(request, "Employee profile updated successfully from the Action Center.")
                return redirect(build_action_center_redirect(updated_employee, search_query))

            first_error = "Please review the profile update form and try again."
            if action_center_profile_form.errors:
                first_field_errors = next(iter(action_center_profile_form.errors.values()))
                if first_field_errors:
                    first_error = first_field_errors[0]
            messages.error(request, first_error)

        elif action_center_post:
            messages.error(request, "Unknown Action Center action requested.")
            return redirect(build_action_center_redirect(selected_employee, search_query))

    pending_leave_queryset = (
        get_leave_queryset_for_user(current_user, EmployeeLeave.objects.select_related("employee", "employee__branch"))
        .filter(status=EmployeeLeave.STATUS_PENDING)
        .order_by("-created_at", "-id")
    )
    supervisor_leave_queue_queryset = pending_leave_queryset.filter(
        current_stage=EmployeeLeave.STAGE_SUPERVISOR_REVIEW
    )
    operations_leave_queue_queryset = pending_leave_queryset.filter(
        current_stage=EmployeeLeave.STAGE_OPERATIONS_REVIEW
    )
    hr_leave_queue_queryset = pending_leave_queryset.filter(
        current_stage=EmployeeLeave.STAGE_HR_REVIEW
    )

    required_submission_queryset = EmployeeRequiredSubmission.objects.select_related(
        "employee",
        "employee__branch",
        "employee__department",
        "employee__company",
        "fulfilled_document",
    ).filter(employee__in=employee_queryset).order_by("-updated_at", "-created_at", "-id")
    outstanding_required_submission_queryset = required_submission_queryset.filter(
        status__in=[
            EmployeeRequiredSubmission.STATUS_REQUESTED,
            EmployeeRequiredSubmission.STATUS_NEEDS_CORRECTION,
        ]
    )
    submitted_required_submission_queryset = required_submission_queryset.filter(
        status=EmployeeRequiredSubmission.STATUS_SUBMITTED
    )

    attendance_queryset_today = EmployeeAttendanceLedger.objects.filter(
        employee__in=employee_queryset,
        attendance_date=today,
    )

    correction_queryset = (
        EmployeeAttendanceCorrection.objects.select_related("employee", "linked_attendance")
        .filter(employee__in=employee_queryset)
        .order_by("-created_at", "-id")
    )

    pending_correction_queryset = correction_queryset.filter(
        status=EmployeeAttendanceCorrection.STATUS_PENDING
    )

    id_attention_limit = today + timedelta(days=30)
    expiring_identity_queryset = employee_queryset.filter(
        is_active=True,
    ).filter(
        Q(passport_expiry_date__isnull=False, passport_expiry_date__lte=id_attention_limit)
        | Q(civil_id_expiry_date__isnull=False, civil_id_expiry_date__lte=id_attention_limit)
    ).order_by("passport_expiry_date", "civil_id_expiry_date", "full_name")

    attendance_exception_statuses = {
        EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
        EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
        EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
        EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
        EmployeeAttendanceLedger.DAY_STATUS_OTHER,
    }

    attendance_exception_queryset = (
        attendance_queryset_today.select_related("employee", "employee__branch")
        .filter(day_status__in=attendance_exception_statuses)
        .order_by("employee__full_name", "employee__employee_id", "-id")
    )

    absence_action_queryset_today = (
        EmployeeActionRecord.objects.select_related("employee", "employee__branch")
        .filter(
            employee__in=employee_queryset,
            employee__is_active=True,
            action_type=EmployeeActionRecord.ACTION_TYPE_ABSENCE,
            action_date=today,
        )
        .exclude(employee_id__in=attendance_exception_queryset.values_list("employee_id", flat=True))
        .order_by("employee__full_name", "employee__employee_id", "-id")
    )

    supervisor_stage_pending_count = supervisor_leave_queue_queryset.count()
    operations_stage_pending_count = operations_leave_queue_queryset.count()
    hr_stage_pending_count = hr_leave_queue_queryset.count()

    current_leave_review_stage_label = "No active leave review stage"
    my_leave_review_queryset = pending_leave_queryset.none()
    if is_branch_scoped_supervisor(current_user):
        current_leave_review_stage_label = "Supervisor review queue"
        my_leave_review_queryset = supervisor_leave_queue_queryset
    elif is_operations_manager_user(current_user):
        current_leave_review_stage_label = "Operations review queue"
        my_leave_review_queryset = operations_leave_queue_queryset
    elif is_hr_user(current_user) or is_admin_compatible(current_user):
        current_leave_review_stage_label = "HR final review queue"
        my_leave_review_queryset = hr_leave_queue_queryset

    def build_leave_queue_rows(queryset, limit=6):
        rows = []
        for leave_record in queryset[:limit]:
            rows.append(
                {
                    "title": leave_record.employee.full_name,
                    "subtitle": f"{leave_record.employee.employee_id} • {leave_record.get_leave_type_display()}",
                    "meta": f"{leave_record.start_date:%b %d, %Y} → {leave_record.end_date:%b %d, %Y}",
                    "workflow_owner": get_leave_current_stage_owner_label(leave_record),
                    "stage_label": leave_record.get_current_stage_display(),
                    "url": reverse("employees:employee_detail", kwargs={"pk": leave_record.employee.pk}),
                }
            )
        return rows

    def build_required_submission_queue_rows(queryset):
        rows = []
        for submission_request in queryset[:6]:
            rows.append(
                {
                    "title": submission_request.employee.full_name,
                    "subtitle": (
                        f"{submission_request.employee.employee_id} • "
                        f"{submission_request.get_request_type_display()}"
                    ),
                    "meta": (
                        f"Due: {submission_request.due_date:%b %d, %Y}"
                        if submission_request.due_date
                        else f"Status: {submission_request.get_status_display()}"
                    ),
                    "url": reverse("employees:employee_detail", kwargs={"pk": submission_request.employee.pk}),
                }
            )
        return rows

    def build_correction_queue_rows(queryset):
        rows = []
        for correction in queryset[:6]:
            rows.append(
                {
                    "title": correction.employee.full_name,
                    "subtitle": f"{correction.employee.employee_id} • {correction.linked_attendance.attendance_date:%b %d, %Y}",
                    "meta": f"Requested: {correction.get_requested_day_status_display()}",
                    "url": reverse("employees:attendance_management") + f"?correct={correction.linked_attendance.pk}",
                }
            )
        return rows

    def build_identity_attention_rows(queryset):
        rows = []
        for employee in queryset[:6]:
            expiry_values = []
            if employee.passport_expiry_date:
                expiry_values.append(f"Passport: {employee.passport_expiry_date:%b %d, %Y}")
            if employee.civil_id_expiry_date:
                expiry_values.append(f"Civil ID: {employee.civil_id_expiry_date:%b %d, %Y}")
            rows.append(
                {
                    "title": employee.full_name,
                    "subtitle": f"{employee.employee_id} • {employee.branch.name if employee.branch_id else '—'}",
                    "meta": " • ".join(expiry_values) if expiry_values else "Identity date needs review",
                    "url": reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
                }
            )
        return rows

    def build_attendance_exception_rows(attendance_queryset, absence_action_queryset):
        rows = []

        for attendance_entry in attendance_queryset[:6]:
            employee = attendance_entry.employee
            rows.append(
                {
                    "title": employee.full_name,
                    "subtitle": f"{employee.employee_id} • {employee.branch.name if employee.branch_id else '—'}",
                    "meta": f"{attendance_entry.get_day_status_display()} for {attendance_entry.attendance_date:%b %d, %Y}",
                    "url": reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
                }
            )

        remaining_slots = max(0, 6 - len(rows))
        if remaining_slots:
            for action_record in absence_action_queryset[:remaining_slots]:
                employee = action_record.employee
                rows.append(
                    {
                        "title": employee.full_name,
                        "subtitle": f"{employee.employee_id} • {employee.branch.name if employee.branch_id else '—'}",
                        "meta": f"Absence action recorded for {action_record.action_date:%b %d, %Y}",
                        "url": reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
                    }
                )

        return rows

    total_employees = employee_queryset.count()
    active_employees = employee_queryset.filter(is_active=True).count()
    inactive_employees = employee_queryset.filter(is_active=False).count()
    pending_leave_requests = pending_leave_queryset.count()
    outstanding_required_submission_count = outstanding_required_submission_queryset.count()
    submitted_required_submission_count = submitted_required_submission_queryset.count()
    today_attendance_records = attendance_queryset_today.count()
    pending_correction_count = pending_correction_queryset.count()
    expiring_identity_count = expiring_identity_queryset.count()
    attendance_exception_count = attendance_exception_queryset.count() + absence_action_queryset_today.count()

    context = {
        "search_query": search_query,
        "current_picker_page": employee_picker_page.number,
        "employee_picker_page": employee_picker_page,
        "employee_picker_paginator": employee_picker_paginator,
        "quick_employee_results": quick_employee_results,
        "selected_employee": selected_employee,
        "selected_employee_supervisor_display": (
            get_branch_supervisor_display(selected_employee) if selected_employee else ""
        ),
        "total_employees": total_employees,
        "active_employees": active_employees,
        "inactive_employees": inactive_employees,
        "pending_leave_requests": pending_leave_requests,
        "outstanding_required_submission_count": outstanding_required_submission_count,
        "submitted_required_submission_count": submitted_required_submission_count,
        "today_attendance_records": today_attendance_records,
        "pending_correction_count": pending_correction_count,
        "expiring_identity_count": expiring_identity_count,
        "attendance_exception_count": attendance_exception_count,
        "employment_status_choices": Employee.EMPLOYMENT_STATUS_CHOICES,
        "action_center_action_form": action_center_action_form,
        "action_center_required_submission_form": action_center_required_submission_form,
        "action_center_leave_form": action_center_leave_form,
        "action_center_attendance_form": action_center_attendance_form,
        "action_center_transfer_form": action_center_transfer_form,
        "action_center_profile_form": action_center_profile_form,
        "pending_leave_queue": build_leave_queue_rows(pending_leave_queryset),
        "my_leave_review_queue": build_leave_queue_rows(my_leave_review_queryset),
        "supervisor_leave_queue": build_leave_queue_rows(supervisor_leave_queue_queryset),
        "operations_leave_queue": build_leave_queue_rows(operations_leave_queue_queryset),
        "hr_leave_queue": build_leave_queue_rows(hr_leave_queue_queryset),
        "supervisor_stage_pending_count": supervisor_stage_pending_count,
        "operations_stage_pending_count": operations_stage_pending_count,
        "hr_stage_pending_count": hr_stage_pending_count,
        "my_leave_review_count": my_leave_review_queryset.count(),
        "current_leave_review_stage_label": current_leave_review_stage_label,
        "required_submission_queue": build_required_submission_queue_rows(outstanding_required_submission_queryset),
        "submitted_required_submission_queue": build_required_submission_queue_rows(submitted_required_submission_queryset),
        "pending_correction_queue": build_correction_queue_rows(pending_correction_queryset),
        "identity_attention_queue": build_identity_attention_rows(expiring_identity_queryset),
        "attendance_exception_queue": build_attendance_exception_rows(attendance_exception_queryset, absence_action_queryset_today),
        "today_label": today,
        "can_transfer_selected_employee": bool(selected_employee and can_transfer_employee(current_user)),
        "can_edit_selected_employee": bool(selected_employee and can_create_or_edit_employees(current_user)),
    }
    return render(request, "employees/employee_action_center.html", context)
