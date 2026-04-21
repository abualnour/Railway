from .views_shared import *
from .views_directory import *
from .views_self_service import *

# Employee lifecycle, documents, leave, attendance, and management workflows.

class EmployeeCreateView(LoginRequiredMixin, CreateView):
    model = Employee
    form_class = EmployeeForm
    template_name = "employees/employee_form.html"
    success_url = reverse_lazy("employees:employee_list")

    def dispatch(self, request, *args, **kwargs):
        if not can_create_or_edit_employees(request.user):
            return deny_employee_access(request, "You do not have permission to create employee profiles.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)

        create_employee_history(
            employee=self.object,
            title="Employee profile created",
            description="Employee record was created in the HR system.",
            event_type=EmployeeHistory.EVENT_PROFILE,
            created_by=get_actor_label(self.request.user),
            is_system_generated=True,
            event_date=self.object.hire_date or timezone.localdate(),
        )

        messages.success(self.request, "Employee created successfully.")
        return response
    def form_invalid(self, form):
        messages.error(self.request, "Employee could not be saved. Please review the form errors and try again.")
        return super().form_invalid(form)


    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Employee"
        context["submit_label"] = "Create Employee"
        return context


class EmployeeUpdateView(LoginRequiredMixin, UpdateView):
    model = Employee
    form_class = EmployeeForm
    template_name = "employees/employee_form.html"
    success_url = reverse_lazy("employees:employee_list")

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not can_create_or_edit_employees(request.user):
            return deny_employee_access(
                request,
                "You do not have permission to update employee profiles.",
                employee=self.object,
            )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        original_employee = Employee.objects.get(pk=self.object.pk)
        response = super().form_valid(form)

        create_employee_history(
            employee=self.object,
            title="Employee profile updated",
            description=build_employee_change_summary(original_employee, self.object),
            event_type=EmployeeHistory.EVENT_PROFILE,
            created_by=get_actor_label(self.request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )

        for history_message in getattr(form, "account_history_messages", []):
            create_employee_history(
                employee=self.object,
                title=history_message,
                description=history_message,
                event_type=EmployeeHistory.EVENT_PROFILE,
                created_by=get_actor_label(self.request.user),
                is_system_generated=True,
                event_date=timezone.localdate(),
            )

        messages.success(self.request, "Employee updated successfully.")
        return response
    def form_invalid(self, form):
        messages.error(self.request, "Employee could not be updated. Please review the form errors and try again.")
        return super().form_invalid(form)
    
    def get_success_url(self):
        return reverse("employees:employee_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Edit Employee"
        context["submit_label"] = "Save Changes"
        return context


class EmployeeTransferView(LoginRequiredMixin, UpdateView):
    model = Employee
    form_class = EmployeeTransferForm
    template_name = "employees/employee_transfer.html"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not can_transfer_employee(request.user):
            return deny_employee_access(
                request,
                "You do not have permission to transfer employee placements.",
                employee=self.object,
            )
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        original_employee = Employee.objects.get(pk=self.object.pk)
        response = super().form_valid(form)

        transfer_note = form.cleaned_data.get("notes", "")
        create_employee_history(
            employee=self.object,
            title="Employee placement transferred",
            description=build_employee_transfer_summary(original_employee, self.object, transfer_note=transfer_note),
            event_type=EmployeeHistory.EVENT_TRANSFER,
            created_by=get_actor_label(self.request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )

        messages.success(self.request, "Employee placement updated successfully.")
        return response

    def get_success_url(self):
        return reverse("employees:employee_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Transfer Employee"
        context["submit_label"] = "Save Placement Change"
        return context


class EmployeeDeleteView(LoginRequiredMixin, ProtectedDeleteMixin, DeleteView):
    model = Employee
    template_name = "employees/employee_confirm_delete.html"
    success_url = reverse_lazy("employees:employee_list")

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not can_delete_employee(request.user):
            return deny_employee_access(
                request,
                "You do not have permission to delete employee profiles.",
                employee=self.object,
            )
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        employee_name = self.object.full_name
        response = super().delete(request, *args, **kwargs)
        messages.success(request, f"Employee '{employee_name}' deleted successfully.")
        return response


@login_required
@require_POST
def employee_status_update(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_change_employee_status(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to change employee status.",
            employee=employee,
        )

    target_status = request.POST.get("target_status", "").strip()
    valid_statuses = {value for value, _label in Employee.EMPLOYMENT_STATUS_CHOICES}
    if target_status not in valid_statuses:
        messages.error(request, "Invalid employee status action.")
        return redirect("employees:employee_detail", pk=employee.pk)

    employee.employment_status = target_status
    employee.is_active = target_status != Employee.EMPLOYMENT_STATUS_INACTIVE
    employee.save(update_fields=["employment_status", "is_active", "updated_at"])

    create_employee_history(
        employee=employee,
        title="Employee status updated",
        description=f"Employee status changed to {employee.get_employment_status_display()}.",
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=get_actor_label(request.user),
        is_system_generated=True,
        event_date=timezone.localdate(),
    )
    notify_employee_status_updated(employee, actor_label=get_actor_label(request.user))

    messages.success(request, "Employee status updated successfully.")
    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
def employee_document_view(request, employee_pk, document_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    document = get_object_or_404(EmployeeDocument, pk=document_pk, employee=employee)

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this employee document.",
            employee=employee,
        )

    return build_browser_file_response(document.file, force_download=False)


@login_required
def employee_document_download(request, employee_pk, document_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    document = get_object_or_404(EmployeeDocument, pk=document_pk, employee=employee)

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to download this employee document.",
            employee=employee,
        )

    return build_browser_file_response(document.file, force_download=True)


@login_required
def employee_required_submission_response_view(request, request_pk):
    submission_request = get_object_or_404(
        EmployeeRequiredSubmission.objects.select_related("employee"),
        pk=request_pk,
    )
    employee = submission_request.employee

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this submitted file.",
            employee=employee,
        )

    return build_browser_file_response(submission_request.response_file, force_download=False)


@login_required
def employee_required_submission_response_download(request, request_pk):
    submission_request = get_object_or_404(
        EmployeeRequiredSubmission.objects.select_related("employee"),
        pk=request_pk,
    )
    employee = submission_request.employee

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to download this submitted file.",
            employee=employee,
        )

    return build_browser_file_response(submission_request.response_file, force_download=True)


@login_required
def employee_document_request_response_view(request, request_pk):
    document_request = get_object_or_404(
        EmployeeDocumentRequest.objects.select_related("employee"),
        pk=request_pk,
    )
    employee = document_request.employee

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to view this reply file.",
            employee=employee,
        )

    return build_browser_file_response(document_request.response_file, force_download=False)


@login_required
def employee_document_request_response_download(request, request_pk):
    document_request = get_object_or_404(
        EmployeeDocumentRequest.objects.select_related("employee"),
        pk=request_pk,
    )
    employee = document_request.employee

    if not can_view_employee_profile(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to download this reply file.",
            employee=employee,
        )

    return build_browser_file_response(document_request.response_file, force_download=True)



@login_required
def employee_document_update(request, employee_pk, document_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    document = get_object_or_404(EmployeeDocument, pk=document_pk, employee=employee)

    if not can_manage_employee_documents(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to update employee documents.",
            employee=employee,
        )

    if request.method == "POST":
        form = EmployeeDocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            document = form.save()

            create_employee_history(
                employee=employee,
                title=f"Document updated: {document.title or document.filename}",
                description=build_document_summary(document),
                event_type=EmployeeHistory.EVENT_DOCUMENT,
                created_by=get_actor_label(request.user),
                is_system_generated=True,
                event_date=document.issue_date or timezone.localdate(),
            )
            messages.success(request, "Document updated successfully.")
    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_document_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_manage_employee_documents(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to upload employee documents.",
            employee=employee,
        )

    form = EmployeeDocumentForm(request.POST, request.FILES)

    if form.is_valid():
        document = form.save(commit=False)
        document.employee = employee
        document.save()

        create_employee_history(
            employee=employee,
            title=f"Document uploaded: {document.title or document.filename}",
            description=build_document_summary(document),
            event_type=EmployeeHistory.EVENT_DOCUMENT,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=document.issue_date or document.uploaded_at.date(),
        )

        messages.success(request, "Document uploaded successfully.")
    else:
        messages.error(request, "Please review the document form and try again.")

    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_document_delete(request, employee_pk, document_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    document = get_object_or_404(EmployeeDocument, pk=document_pk, employee=employee)

    if not can_manage_employee_documents(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to delete employee documents.",
            employee=employee,
        )

    document_label = document.title or getattr(document, "filename", "") or str(document)
    document.delete()

    create_employee_history(
        employee=employee,
        title=f"Document deleted: {document_label}",
        description="Employee document was deleted from the employee profile.",
        event_type=EmployeeHistory.EVENT_DOCUMENT,
        created_by=get_actor_label(request.user),
        is_system_generated=True,
        event_date=timezone.localdate(),
    )

    messages.success(request, "Document deleted successfully.")
    return redirect("employees:employee_detail", pk=employee.pk)



@login_required
@require_POST
def employee_required_submission_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_manage_employee_required_submissions(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to create employee required submission requests.",
            employee=employee,
        )

    form = EmployeeRequiredSubmissionCreateForm(request.POST)
    if form.is_valid():
        submission_request = form.save(commit=False)
        submission_request.employee = employee
        submission_request.created_by = request.user
        submission_request.status = EmployeeRequiredSubmission.STATUS_REQUESTED
        submission_request.reviewed_by = None
        submission_request.review_note = ""
        submission_request.reviewed_at = None
        submission_request.submitted_at = None
        submission_request.save()

        create_employee_history(
            employee=employee,
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
        messages.success(request, "Required employee submission request created successfully.")
    else:
        first_error = "Please review the required submission request form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect(
        get_safe_next_url(
            request,
            reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
        )
    )


@login_required
@require_POST
def employee_required_submission_submit(request, request_pk):
    submission_request = get_object_or_404(
        EmployeeRequiredSubmission.objects.select_related('employee', 'created_by', 'reviewed_by'),
        pk=request_pk,
    )
    employee = submission_request.employee

    if not can_submit_employee_required_submission(request.user, submission_request):
        return deny_employee_access(
            request,
            "You do not have permission to submit this required employee request.",
            employee=employee,
        )

    form = EmployeeRequiredSubmissionResponseForm(
        request.POST,
        request.FILES,
        instance=submission_request,
    )
    if form.is_valid():
        submission_request = form.save(commit=False)
        submission_request.status = EmployeeRequiredSubmission.STATUS_SUBMITTED
        submission_request.submitted_at = timezone.now()
        submission_request.reviewed_by = None
        submission_request.reviewed_at = None
        submission_request.review_note = ""
        submission_request.save()

        request_type_document_map = {
            EmployeeRequiredSubmission.REQUEST_TYPE_PASSPORT_COPY: EmployeeDocument.DOCUMENT_TYPE_ID,
            EmployeeRequiredSubmission.REQUEST_TYPE_CIVIL_ID_COPY: EmployeeDocument.DOCUMENT_TYPE_ID,
            EmployeeRequiredSubmission.REQUEST_TYPE_CONTRACT_COPY: EmployeeDocument.DOCUMENT_TYPE_CONTRACT,
            EmployeeRequiredSubmission.REQUEST_TYPE_MEDICAL_DOCUMENT: EmployeeDocument.DOCUMENT_TYPE_MEDICAL,
            EmployeeRequiredSubmission.REQUEST_TYPE_CERTIFICATE: EmployeeDocument.DOCUMENT_TYPE_CERTIFICATE,
            EmployeeRequiredSubmission.REQUEST_TYPE_GENERAL_DOCUMENT: EmployeeDocument.DOCUMENT_TYPE_GENERAL,
            EmployeeRequiredSubmission.REQUEST_TYPE_OTHER: EmployeeDocument.DOCUMENT_TYPE_OTHER,
        }

        fulfilled_document = EmployeeDocument.objects.create(
            employee=employee,
            title=submission_request.title,
            document_type=request_type_document_map.get(
                submission_request.request_type,
                EmployeeDocument.DOCUMENT_TYPE_GENERAL,
            ),
            reference_number=submission_request.response_reference_number or "",
            issue_date=submission_request.response_issue_date,
            expiry_date=submission_request.response_expiry_date,
            is_required=True,
            file=submission_request.response_file,
            description=(submission_request.employee_note or submission_request.instructions or "").strip(),
        )
        submission_request.fulfilled_document = fulfilled_document
        submission_request.save(update_fields=['fulfilled_document', 'updated_at'])

        create_employee_history(
            employee=employee,
            title=f"Employee submitted requested file: {submission_request.title}",
            description=(
                f"Request Type: {submission_request.get_request_type_display()}. "
                f"Status: {submission_request.get_status_display()}. "
                + (
                    f"Reference Number: {submission_request.response_reference_number}. "
                    if submission_request.response_reference_number else ""
                )
                + (f"Employee Note: {submission_request.employee_note}" if submission_request.employee_note else "")
            ).strip(),
            event_type=EmployeeHistory.EVENT_DOCUMENT,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        notify_required_submission_submitted(submission_request)
        messages.success(request, "Requested file submitted successfully.")
    else:
        first_error = "Please review the requested file submission form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect(
        get_safe_next_url(
            request,
            reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
        )
    )


@login_required
@require_POST
def employee_required_submission_review(request, request_pk):
    submission_request = get_object_or_404(
        EmployeeRequiredSubmission.objects.select_related('employee', 'created_by', 'reviewed_by'),
        pk=request_pk,
    )
    employee = submission_request.employee

    if not can_review_employee_required_submission(request.user, submission_request):
        return deny_employee_access(
            request,
            "You do not have permission to review this required employee request.",
            employee=employee,
        )

    form = EmployeeRequiredSubmissionReviewForm(request.POST, instance=submission_request)
    if form.is_valid():
        updated_request = form.save(commit=False)
        updated_request.reviewed_by = request.user
        updated_request.reviewed_at = timezone.now()

        if updated_request.status == EmployeeRequiredSubmission.STATUS_COMPLETED and not updated_request.submitted_at:
            updated_request.submitted_at = timezone.now()

        updated_request.save()

        create_employee_history(
            employee=employee,
            title=f"Required employee submission reviewed: {updated_request.title}",
            description=(
                f"Review Status: {updated_request.get_status_display()}. "
                + (f"Review Note: {updated_request.review_note}" if updated_request.review_note else "")
            ).strip(),
            event_type=EmployeeHistory.EVENT_DOCUMENT,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        notify_required_submission_reviewed(updated_request)
        messages.success(request, "Required employee submission reviewed successfully.")
    else:
        first_error = "Please review the submission review form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect('employees:employee_detail', pk=employee.pk)

@login_required
@require_POST
def employee_document_request_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_create_employee_document_request(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to request management documents for this employee profile.",
            employee=employee,
        )

    form = EmployeeDocumentRequestCreateForm(request.POST)
    if form.is_valid():
        document_request = form.save(commit=False)
        document_request.employee = employee
        document_request.created_by = request.user
        document_request.status = EmployeeDocumentRequest.STATUS_REQUESTED
        document_request.submitted_at = timezone.now()
        document_request.save()

        create_employee_history(
            employee=employee,
            title=f"Document requested: {document_request.title}",
            description=build_employee_document_request_summary(document_request),
            event_type=EmployeeHistory.EVENT_NOTE,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        notify_document_request_submitted(document_request)

        messages.success(request, "Document request submitted successfully.")
    else:
        first_error = "Please review the document request form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect(
        get_safe_next_url(
            request,
            reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
        )
    )


@login_required
@require_POST
def employee_document_request_review(request, request_pk):
    document_request = get_object_or_404(
        EmployeeDocumentRequest.objects.select_related("employee", "reviewed_by", "created_by", "delivered_document"),
        pk=request_pk,
    )
    employee = document_request.employee

    if not can_review_employee_document_request(request.user, document_request):
        return deny_employee_access(
            request,
            "You do not have permission to review this employee document request.",
            employee=employee,
        )

    form = EmployeeDocumentRequestReviewForm(request.POST, request.FILES, instance=document_request)
    if form.is_valid():
        previous_status = document_request.get_status_display()
        updated_request = form.save(commit=False)
        updated_request.reviewed_by = request.user
        updated_request.reviewed_at = timezone.now()

        if updated_request.status == EmployeeDocumentRequest.STATUS_COMPLETED:
            if not updated_request.completed_at:
                updated_request.completed_at = timezone.now()
        else:
            updated_request.completed_at = None

        updated_request.save()

        if updated_request.response_file and updated_request.status in {
            EmployeeDocumentRequest.STATUS_APPROVED,
            EmployeeDocumentRequest.STATUS_COMPLETED,
        }:
            delivered_document = updated_request.delivered_document
            if delivered_document is None:
                delivered_document = EmployeeDocument(
                    employee=employee,
                    title=updated_request.default_document_title,
                    document_type=updated_request.mapped_document_type,
                    file=updated_request.response_file,
                    description=updated_request.management_note or f"Delivered from employee document request: {updated_request.get_request_type_display()}.",
                )
            else:
                delivered_document.employee = employee
                delivered_document.title = updated_request.default_document_title
                delivered_document.document_type = updated_request.mapped_document_type
                delivered_document.file = updated_request.response_file
                delivered_document.description = updated_request.management_note or delivered_document.description

            delivered_document.save()

            if updated_request.delivered_document_id != delivered_document.pk:
                updated_request.delivered_document = delivered_document
                updated_request.save(update_fields=["delivered_document", "updated_at"])

        create_employee_history(
            employee=employee,
            title=f"Document request reviewed: {updated_request.title}",
            description=build_employee_document_request_review_summary(
                document_request=updated_request,
                previous_status=previous_status,
                new_status=updated_request.get_status_display(),
                management_note=updated_request.management_note,
            ),
            event_type=EmployeeHistory.EVENT_NOTE,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=timezone.localdate(),
        )
        notify_document_request_status_change(updated_request)

        messages.success(request, "Employee document request updated successfully.")
    else:
        first_error = "Please review the employee document request review form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect("employees:employee_requests_overview")


@login_required
@require_POST
def employee_document_request_cancel(request, request_pk):
    document_request = get_object_or_404(EmployeeDocumentRequest.objects.select_related("employee"), pk=request_pk)
    employee = document_request.employee

    if not can_cancel_employee_document_request(request.user, document_request):
        return deny_employee_access(
            request,
            "You do not have permission to cancel this document request.",
            employee=employee,
        )

    previous_status = document_request.get_status_display()
    document_request.status = EmployeeDocumentRequest.STATUS_CANCELLED
    document_request.reviewed_at = timezone.now()
    document_request.reviewed_by = request.user
    document_request.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])

    create_employee_history(
        employee=employee,
        title=f"Document request cancelled: {document_request.title}",
        description=build_employee_document_request_review_summary(
            document_request=document_request,
            previous_status=previous_status,
            new_status=document_request.get_status_display(),
            management_note="Cancelled by employee.",
        ),
        event_type=EmployeeHistory.EVENT_NOTE,
        created_by=get_actor_label(request.user),
        is_system_generated=True,
        event_date=timezone.localdate(),
    )
    notify_document_request_status_change(document_request)

    messages.success(request, "Document request cancelled successfully.")
    return redirect(
        get_safe_next_url(
            request,
            reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
        )
    )


@login_required
@require_POST
def employee_leave_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_request_leave(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to create leave requests for this employee.",
            employee=employee,
        )

    if is_self_employee(request.user, employee):
        form = EmployeeSelfServiceLeaveRequestForm(request.POST, request.FILES)
    else:
        form = EmployeeLeaveForm(request.POST)

    if form.is_valid():
        leave_record = form.save(commit=False)
        leave_record.employee = employee
        leave_record.requested_by = request.user
        leave_record.created_by = get_actor_label(request.user)
        leave_record.updated_by = get_actor_label(request.user)
        leave_record.status = EmployeeLeave.STATUS_PENDING
        leave_record.current_stage = EmployeeLeave.STAGE_SUPERVISOR_REVIEW
        leave_record.save()

        supporting_document = None
        attachment_file = form.cleaned_data.get("attachment_file") if hasattr(form, "cleaned_data") else None

        if attachment_file:
            attachment_title = form.cleaned_data.get("attachment_title") or (
                f"{leave_record.get_leave_type_display()} Supporting Document"
            )
            supporting_document = EmployeeDocument.objects.create(
                employee=employee,
                linked_leave=leave_record,
                title=attachment_title,
                document_type=form.cleaned_data.get("attachment_document_type") or EmployeeDocument.DOCUMENT_TYPE_OTHER,
                reference_number=form.cleaned_data.get("attachment_reference_number", ""),
                issue_date=form.cleaned_data.get("attachment_issue_date"),
                expiry_date=form.cleaned_data.get("attachment_expiry_date"),
                file=attachment_file,
                description=form.cleaned_data.get("attachment_description", ""),
            )

        leave_history_description = build_leave_request_summary(leave_record)
        if supporting_document:
            leave_history_description += f" Supporting document uploaded: {supporting_document.title or supporting_document.filename}."

        create_employee_history(
            employee=employee,
            title=f"Leave requested: {leave_record.get_leave_type_display()}",
            description=leave_history_description,
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=get_actor_label(request.user),
            is_system_generated=True,
            event_date=leave_record.start_date,
        )
        notify_leave_request_submitted(leave_record)

        if supporting_document:
            create_employee_history(
                employee=employee,
                title=f"Document uploaded: {supporting_document.title or supporting_document.filename}",
                description=build_document_summary(supporting_document),
                event_type=EmployeeHistory.EVENT_DOCUMENT,
                created_by=get_actor_label(request.user),
                is_system_generated=True,
                event_date=supporting_document.issue_date or timezone.localdate(),
            )

        messages.success(request, "Leave request submitted successfully.")
    else:
        first_error = "Please review the leave request form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_leave_approve(request, employee_pk, leave_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    leave_record = get_object_or_404(EmployeeLeave, pk=leave_pk, employee=employee)

    if not can_review_leave(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to approve leave requests.",
            employee=employee,
        )

    if is_branch_scoped_supervisor(request.user) and not can_supervisor_view_employee(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to review leave requests outside your branch.",
            employee=employee,
        )

    if leave_record.status != EmployeeLeave.STATUS_PENDING:
        messages.error(request, "Only pending leave requests can be approved from this workflow action.")
        return redirect("employees:employee_detail", pk=employee.pk)

    if not can_user_review_leave_stage(request.user, leave_record):
        messages.error(
            request,
            f"This leave request is currently assigned to {get_leave_current_stage_owner_label(leave_record)} and cannot be approved from your workflow step.",
        )
        return redirect("employees:employee_detail", pk=employee.pk)

    previous_status = leave_record.get_status_display()
    approval_note = (request.POST.get("approval_note") or "").strip()
    actor_label = get_actor_label(request.user)
    current_time = timezone.now()

    leave_record.reviewed_by = request.user
    leave_record.rejected_by = None
    leave_record.cancelled_by = None
    leave_record.approval_note = approval_note
    leave_record.updated_by = actor_label

    history_title = f"Leave approved: {leave_record.get_leave_type_display()}"
    success_message = "Leave request approved successfully and the workflow was updated."

    if is_branch_scoped_supervisor(request.user):
        leave_record.status = EmployeeLeave.STATUS_PENDING
        leave_record.current_stage = EmployeeLeave.STAGE_OPERATIONS_REVIEW
        leave_record.supervisor_reviewed_by = request.user
        leave_record.supervisor_reviewed_at = current_time
        leave_record.supervisor_review_note = approval_note
        history_title = f"Leave moved to operations review: {leave_record.get_leave_type_display()}"
        success_message = "Leave request reviewed and moved to Operations for the next stage."
    elif is_operations_manager_user(request.user):
        leave_record.status = EmployeeLeave.STATUS_PENDING
        leave_record.current_stage = EmployeeLeave.STAGE_HR_REVIEW
        leave_record.operations_reviewed_by = request.user
        leave_record.operations_reviewed_at = current_time
        leave_record.operations_review_note = approval_note
        history_title = f"Leave moved to HR review: {leave_record.get_leave_type_display()}"
        success_message = "Leave request reviewed and moved to HR for final review."
    else:
        leave_record.status = EmployeeLeave.STATUS_APPROVED
        leave_record.current_stage = EmployeeLeave.STAGE_FINAL_APPROVED
        leave_record.approved_by = request.user
        leave_record.hr_reviewed_by = request.user
        leave_record.hr_reviewed_at = current_time
        leave_record.hr_review_note = approval_note
        leave_record.finalized_at = current_time

    leave_record.save()

    create_employee_history(
        employee=employee,
        title=history_title,
        description=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=actor_label,
        is_system_generated=True,
        event_date=leave_record.start_date,
    )
    notify_leave_request_status_change(
        leave_record,
        title=history_title,
        body=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
        notify_next_stage=leave_record.status == EmployeeLeave.STATUS_PENDING,
    )

    messages.success(request, success_message)
    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_leave_reject(request, employee_pk, leave_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    leave_record = get_object_or_404(EmployeeLeave, pk=leave_pk, employee=employee)

    if not can_review_leave(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to reject leave requests.",
            employee=employee,
        )

    if is_branch_scoped_supervisor(request.user) and not can_supervisor_view_employee(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to review leave requests outside your branch.",
            employee=employee,
        )

    if leave_record.status != EmployeeLeave.STATUS_PENDING:
        messages.error(request, "Only pending leave requests can be rejected from this workflow action.")
        return redirect("employees:employee_detail", pk=employee.pk)

    if not can_user_review_leave_stage(request.user, leave_record):
        messages.error(
            request,
            f"This leave request is currently assigned to {get_leave_current_stage_owner_label(leave_record)} and cannot be rejected from your workflow step.",
        )
        return redirect("employees:employee_detail", pk=employee.pk)

    previous_status = leave_record.get_status_display()
    approval_note = (request.POST.get("approval_note") or "").strip()
    actor_label = get_actor_label(request.user)
    current_time = timezone.now()

    leave_record.status = EmployeeLeave.STATUS_REJECTED
    leave_record.current_stage = EmployeeLeave.STAGE_FINAL_REJECTED
    leave_record.reviewed_by = request.user
    leave_record.rejected_by = request.user
    leave_record.approved_by = None
    leave_record.cancelled_by = None
    leave_record.approval_note = approval_note
    leave_record.updated_by = actor_label
    leave_record.finalized_at = current_time

    if is_branch_scoped_supervisor(request.user):
        leave_record.supervisor_reviewed_by = request.user
        leave_record.supervisor_reviewed_at = current_time
        leave_record.supervisor_review_note = approval_note
    elif is_operations_manager_user(request.user):
        leave_record.operations_reviewed_by = request.user
        leave_record.operations_reviewed_at = current_time
        leave_record.operations_review_note = approval_note
    else:
        leave_record.hr_reviewed_by = request.user
        leave_record.hr_reviewed_at = current_time
        leave_record.hr_review_note = approval_note

    leave_record.save()

    create_employee_history(
        employee=employee,
        title=f"Leave rejected: {leave_record.get_leave_type_display()}",
        description=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=actor_label,
        is_system_generated=True,
        event_date=leave_record.start_date,
    )
    notify_leave_request_status_change(
        leave_record,
        title=f"Leave rejected: {leave_record.get_leave_type_display()}",
        body=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
    )

    messages.success(request, "Leave request rejected and closed as a final workflow outcome.")
    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_leave_cancel(request, employee_pk, leave_pk):
    employee = get_object_or_404(Employee, pk=employee_pk)
    leave_record = get_object_or_404(EmployeeLeave, pk=leave_pk, employee=employee)

    if not can_cancel_leave(request.user, leave_record):
        return deny_employee_access(
            request,
            "You do not have permission to cancel this leave request.",
            employee=employee,
        )

    if is_branch_scoped_supervisor(request.user) and not can_supervisor_view_employee(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to review leave requests outside your branch.",
            employee=employee,
        )

    previous_status = leave_record.get_status_display()
    approval_note = (request.POST.get("approval_note") or "").strip()
    actor_label = get_actor_label(request.user)
    current_time = timezone.now()

    leave_record.status = EmployeeLeave.STATUS_CANCELLED
    leave_record.current_stage = EmployeeLeave.STAGE_CANCELLED
    leave_record.reviewed_by = request.user if can_review_leave(request.user) else leave_record.reviewed_by
    leave_record.approved_by = None
    leave_record.rejected_by = None
    leave_record.cancelled_by = request.user
    leave_record.approval_note = approval_note
    leave_record.updated_by = actor_label
    leave_record.finalized_at = current_time
    leave_record.save()

    create_employee_history(
        employee=employee,
        title=f"Leave cancelled: {leave_record.get_leave_type_display()}",
        description=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=actor_label,
        is_system_generated=True,
        event_date=leave_record.start_date,
    )
    notify_leave_request_status_change(
        leave_record,
        title=f"Leave cancelled: {leave_record.get_leave_type_display()}",
        body=build_leave_status_summary(
            leave_record=leave_record,
            previous_status=previous_status,
            new_status=leave_record.get_status_display(),
            approval_note=approval_note,
        ),
    )

    messages.success(request, "Leave request cancelled successfully.")
    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_action_record_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_create_action_records(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to create attendance / incident / discipline records.",
            employee=employee,
        )

    if is_branch_scoped_supervisor(request.user) and not can_supervisor_view_employee(request.user, employee):
        return deny_employee_access(
            request,
            "You do not have permission to create action records outside your branch scope.",
            employee=employee,
        )

    form = EmployeeActionRecordForm(request.POST)

    if form.is_valid():
        action_record = form.save(commit=False)
        action_record.employee = employee
        actor_label = get_actor_label(request.user)
        action_record.created_by = actor_label
        action_record.updated_by = actor_label
        action_record.save()

        create_employee_history(
            employee=employee,
            title=f"Action record added: {action_record.title}",
            description=build_action_record_summary(action_record),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=actor_label,
            is_system_generated=True,
            event_date=action_record.action_date,
        )
        notify_employee_action_record_created(employee, action_record)

        messages.success(request, "Attendance / incident record added successfully.")
    else:
        first_error = "Please review the attendance / incident form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_attendance_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_manage_attendance_records(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to create attendance ledger entries.",
            employee=employee,
        )

    form = EmployeeAttendanceLedgerForm(request.POST, employee=employee)

    if form.is_valid():
        attendance_entry = form.save(commit=False)
        attendance_entry.employee = employee
        attendance_entry.source = EmployeeAttendanceLedger.SOURCE_MANUAL
        actor_label = get_actor_label(request.user)
        attendance_entry.created_by = actor_label
        attendance_entry.updated_by = actor_label
        attendance_entry.save()

        create_employee_history(
            employee=employee,
            title=f"Attendance ledger entry added: {attendance_entry.attendance_date}",
            description=build_attendance_ledger_summary(attendance_entry),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=actor_label,
            is_system_generated=True,
            event_date=attendance_entry.attendance_date,
        )
        notify_employee_attendance_record_created(employee, attendance_entry)

        messages.success(request, "Attendance ledger entry added successfully.")
    else:
        first_error = "Please review the attendance ledger form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)

    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@require_POST
def employee_history_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if not can_add_manual_history(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to add timeline history entries.",
            employee=employee,
        )

    form = EmployeeHistoryForm(request.POST)

    if form.is_valid():
        history_entry = form.save(commit=False)
        history_entry.employee = employee
        history_entry.created_by = get_actor_label(request.user)
        history_entry.save()
        messages.success(request, "Timeline entry added successfully.")
    else:
        messages.error(request, "Please review the timeline entry form and try again.")

    return redirect("employees:employee_detail", pk=employee.pk)


@login_required
@login_required
@require_POST
def employee_attendance_correction_create(request, attendance_pk):
    attendance_entry = get_object_or_404(
        EmployeeAttendanceLedger.objects.select_related("employee"),
        pk=attendance_pk,
    )
    employee = attendance_entry.employee

    if not can_manage_attendance_records(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to request attendance corrections.",
            employee=employee,
        )

    next_url = (request.POST.get("next") or reverse("employees:attendance_management")).strip()
    form = EmployeeAttendanceCorrectionForm(request.POST, attendance_entry=attendance_entry)

    if form.is_valid():
        correction = form.save(commit=False)
        actor_label = get_actor_label(request.user)
        correction.linked_attendance = attendance_entry
        correction.employee = employee
        correction.requested_by = request.user
        correction.created_by = actor_label
        correction.updated_by = actor_label
        correction.save()

        create_employee_history(
            employee=employee,
            title=f"Attendance correction requested: {attendance_entry.attendance_date}",
            description=build_attendance_correction_summary(correction),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=actor_label,
            is_system_generated=True,
            event_date=attendance_entry.attendance_date,
        )
        notify_attendance_correction_submitted(correction)
        messages.success(request, "Attendance correction request created successfully.")
    else:
        first_error = "Please review the attendance correction form and try again."
        if form.errors:
            first_field_errors = next(iter(form.errors.values()))
            if first_field_errors:
                first_error = first_field_errors[0]
        messages.error(request, first_error)
        separator = "&" if "?" in next_url else "?"
        next_url = f"{next_url}{separator}correct={attendance_entry.pk}"

    return redirect(next_url)


@login_required
@require_POST
def employee_attendance_correction_apply(request, correction_pk):
    correction = get_object_or_404(
        EmployeeAttendanceCorrection.objects.select_related("employee", "linked_attendance"),
        pk=correction_pk,
    )
    employee = correction.employee

    if not can_manage_attendance_records(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to apply attendance corrections.",
            employee=employee,
        )

    next_url = (request.POST.get("next") or reverse("employees:attendance_management")).strip()

    if correction.status != EmployeeAttendanceCorrection.STATUS_PENDING:
        messages.error(request, "Only pending attendance corrections can be applied.")
        return redirect(next_url)

    attendance_entry = correction.linked_attendance
    actor_label = get_actor_label(request.user)
    review_notes = (request.POST.get("review_notes") or "").strip()

    attendance_entry.day_status = correction.requested_day_status
    attendance_entry.clock_in_time = correction.requested_clock_in_time
    attendance_entry.clock_out_time = correction.requested_clock_out_time
    attendance_entry.scheduled_hours = correction.requested_scheduled_hours
    attendance_entry.late_minutes = correction.requested_late_minutes
    attendance_entry.early_departure_minutes = correction.requested_early_departure_minutes
    attendance_entry.overtime_minutes = correction.requested_overtime_minutes
    attendance_entry.notes = correction.requested_notes
    attendance_entry.source = EmployeeAttendanceLedger.SOURCE_MANUAL
    attendance_entry.updated_by = actor_label
    attendance_entry.save()

    correction.status = EmployeeAttendanceCorrection.STATUS_APPLIED
    correction.review_notes = review_notes
    correction.reviewed_by = request.user
    correction.applied_at = timezone.now()
    correction.updated_by = actor_label
    correction.save()

    create_employee_history(
        employee=employee,
        title=f"Attendance correction applied: {attendance_entry.attendance_date}",
        description=build_attendance_correction_summary(correction),
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=actor_label,
        is_system_generated=True,
        event_date=attendance_entry.attendance_date,
    )
    notify_attendance_correction_reviewed(correction)

    messages.success(request, "Attendance correction applied successfully.")
    return redirect(next_url)


@login_required
@require_POST
def employee_attendance_correction_reject(request, correction_pk):
    correction = get_object_or_404(
        EmployeeAttendanceCorrection.objects.select_related("employee", "linked_attendance"),
        pk=correction_pk,
    )
    employee = correction.employee

    if not can_manage_attendance_records(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to reject attendance corrections.",
            employee=employee,
        )

    next_url = (request.POST.get("next") or reverse("employees:attendance_management")).strip()

    if correction.status != EmployeeAttendanceCorrection.STATUS_PENDING:
        messages.error(request, "Only pending attendance corrections can be rejected.")
        return redirect(next_url)

    correction.status = EmployeeAttendanceCorrection.STATUS_REJECTED
    correction.review_notes = (request.POST.get("review_notes") or "").strip()
    correction.reviewed_by = request.user
    correction.updated_by = get_actor_label(request.user)
    correction.save()

    create_employee_history(
        employee=employee,
        title=f"Attendance correction rejected: {correction.linked_attendance.attendance_date}",
        description=build_attendance_correction_summary(correction),
        event_type=EmployeeHistory.EVENT_STATUS,
        created_by=get_actor_label(request.user),
        is_system_generated=True,
        event_date=correction.linked_attendance.attendance_date,
    )
    notify_attendance_correction_reviewed(correction)

    messages.success(request, "Attendance correction rejected successfully.")
    return redirect(next_url)


def build_attendance_history_management_context(request, *, supervisor_history_only=False):
    filter_state = build_attendance_management_filter_state(request, user=request.user)
    scoped_employee_queryset = get_employee_directory_queryset_for_user(
        request.user,
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        ).all(),
    )

    attendance_queryset = EmployeeAttendanceLedger.objects.select_related(
        "employee",
        "employee__company",
        "employee__branch",
        "employee__department",
        "employee__section",
        "employee__job_title",
        "linked_leave",
        "linked_action_record",
    ).filter(employee__in=scoped_employee_queryset)

    if filter_state["search_value"]:
        search_value = filter_state["search_value"]
        attendance_queryset = attendance_queryset.filter(
            Q(employee__full_name__icontains=search_value)
            | Q(employee__employee_id__icontains=search_value)
            | Q(employee__email__icontains=search_value)
            | Q(notes__icontains=search_value)
            | Q(created_by__icontains=search_value)
            | Q(updated_by__icontains=search_value)
        )

    if filter_state["employee"]:
        attendance_queryset = attendance_queryset.filter(employee=filter_state["employee"])
    if filter_state["company"]:
        attendance_queryset = attendance_queryset.filter(employee__company=filter_state["company"])
    if filter_state["branch"]:
        attendance_queryset = attendance_queryset.filter(employee__branch=filter_state["branch"])
    if filter_state["department"]:
        attendance_queryset = attendance_queryset.filter(employee__department=filter_state["department"])
    if filter_state["section"]:
        attendance_queryset = attendance_queryset.filter(employee__section=filter_state["section"])
    if filter_state["day_status"]:
        attendance_queryset = attendance_queryset.filter(day_status=filter_state["day_status"])
    if filter_state["start_date"]:
        attendance_queryset = attendance_queryset.filter(attendance_date__gte=filter_state["start_date"])
    if filter_state["end_date"]:
        attendance_queryset = attendance_queryset.filter(attendance_date__lte=filter_state["end_date"])

    attendance_queryset = attendance_queryset.order_by("-attendance_date", "employee__full_name", "-id")
    attendance_entries = list(attendance_queryset)
    attendance_summary = build_attendance_summary(attendance_entries)
    pending_event_queryset = EmployeeAttendanceEvent.objects.select_related(
        "employee",
        "employee__company",
        "employee__branch",
        "employee__department",
        "employee__section",
        "employee__job_title",
    ).filter(
        employee__in=scoped_employee_queryset,
        synced_ledger__isnull=True,
    )

    if filter_state["search_value"]:
        search_value = filter_state["search_value"]
        pending_event_queryset = pending_event_queryset.filter(
            Q(employee__full_name__icontains=search_value)
            | Q(employee__employee_id__icontains=search_value)
            | Q(employee__email__icontains=search_value)
            | Q(notes__icontains=search_value)
        )

    if filter_state["employee"]:
        pending_event_queryset = pending_event_queryset.filter(employee=filter_state["employee"])
    if filter_state["company"]:
        pending_event_queryset = pending_event_queryset.filter(employee__company=filter_state["company"])
    if filter_state["branch"]:
        pending_event_queryset = pending_event_queryset.filter(employee__branch=filter_state["branch"])
    if filter_state["department"]:
        pending_event_queryset = pending_event_queryset.filter(employee__department=filter_state["department"])
    if filter_state["section"]:
        pending_event_queryset = pending_event_queryset.filter(employee__section=filter_state["section"])
    if filter_state["day_status"] and filter_state["day_status"] != EmployeeAttendanceLedger.DAY_STATUS_PRESENT:
        pending_event_queryset = pending_event_queryset.none()
    if filter_state["start_date"]:
        pending_event_queryset = pending_event_queryset.filter(attendance_date__gte=filter_state["start_date"])
    if filter_state["end_date"]:
        pending_event_queryset = pending_event_queryset.filter(attendance_date__lte=filter_state["end_date"])

    pending_event_entries = list(
        pending_event_queryset.order_by("-attendance_date", "employee__full_name", "-id")
    )
    attendance_display_records = sorted(
        [*attendance_entries, *pending_event_entries],
        key=lambda entry: (
            -(entry.attendance_date.toordinal() if entry.attendance_date else 0),
            (entry.employee.full_name or "").lower(),
            -(entry.pk or 0),
        ),
    )

    snapshot_date = filter_state["end_date"] or filter_state["start_date"] or timezone.localdate()
    snapshot_is_single_day = bool(
        filter_state["start_date"]
        and filter_state["end_date"]
        and filter_state["start_date"] == filter_state["end_date"]
    )
    if snapshot_is_single_day:
        attendance_snapshot_note = "Daily attendance snapshot for the selected day."
    elif filter_state["start_date"] or filter_state["end_date"]:
        attendance_snapshot_note = "Daily attendance snapshot based on the end date of the current filtered period."
    else:
        attendance_snapshot_note = "Daily attendance snapshot for today when no fixed date range is selected."

    snapshot_employee_queryset = get_employee_directory_queryset_for_user(
        request.user,
        Employee.objects.select_related(
            "company",
            "branch",
            "department",
            "section",
            "job_title",
        ).all(),
    )

    if filter_state["search_value"]:
        snapshot_search_value = filter_state["search_value"]
        snapshot_employee_queryset = snapshot_employee_queryset.filter(
            Q(full_name__icontains=snapshot_search_value)
            | Q(employee_id__icontains=snapshot_search_value)
            | Q(email__icontains=snapshot_search_value)
            | Q(phone__icontains=snapshot_search_value)
        )

    if filter_state["employee"]:
        snapshot_employee_queryset = snapshot_employee_queryset.filter(pk=filter_state["employee"].pk)
    if filter_state["company"]:
        snapshot_employee_queryset = snapshot_employee_queryset.filter(company=filter_state["company"])
    if filter_state["branch"]:
        snapshot_employee_queryset = snapshot_employee_queryset.filter(branch=filter_state["branch"])
    if filter_state["department"]:
        snapshot_employee_queryset = snapshot_employee_queryset.filter(department=filter_state["department"])
    if filter_state["section"]:
        snapshot_employee_queryset = snapshot_employee_queryset.filter(section=filter_state["section"])

    snapshot_employee_queryset = snapshot_employee_queryset.filter(is_active=True).filter(
        Q(hire_date__isnull=True) | Q(hire_date__lte=snapshot_date)
    )

    snapshot_scope_employees = list(snapshot_employee_queryset.order_by("full_name", "employee_id"))
    snapshot_scope_employee_ids = [employee.pk for employee in snapshot_scope_employees]

    snapshot_recorded_queryset = EmployeeAttendanceLedger.objects.select_related(
        "employee",
        "employee__branch",
        "employee__department",
        "employee__section",
        "employee__job_title",
    ).filter(
        employee_id__in=snapshot_scope_employee_ids,
        attendance_date=snapshot_date,
    )
    snapshot_recorded_entries = list(
        snapshot_recorded_queryset.order_by("employee__full_name", "employee__employee_id", "-id")
    )
    snapshot_recorded_employee_ids = {entry.employee_id for entry in snapshot_recorded_entries}
    snapshot_pending_event_employee_ids = set(
        EmployeeAttendanceEvent.objects.filter(
            employee_id__in=snapshot_scope_employee_ids,
            attendance_date=snapshot_date,
            synced_ledger__isnull=True,
        ).values_list("employee_id", flat=True)
    )
    snapshot_recorded_employee_ids.update(snapshot_pending_event_employee_ids)

    snapshot_unrecorded_employees = [
        employee for employee in snapshot_scope_employees if employee.pk not in snapshot_recorded_employee_ids
    ]

    approved_leave_ids = set(
        EmployeeLeave.objects.filter(
            employee_id__in=[employee.pk for employee in snapshot_unrecorded_employees],
            status=EmployeeLeave.STATUS_APPROVED,
            start_date__lte=snapshot_date,
            end_date__gte=snapshot_date,
        ).values_list("employee_id", flat=True)
    )

    policy_weekly_off_ids = set()
    policy_holiday_ids = set()
    if is_policy_holiday(snapshot_date):
        policy_holiday_ids = {employee.pk for employee in snapshot_unrecorded_employees}
    elif is_policy_weekly_off_day(snapshot_date):
        policy_weekly_off_ids = {employee.pk for employee in snapshot_unrecorded_employees}

    attendance_snapshot_missing_employees = [
        employee
        for employee in snapshot_unrecorded_employees
        if employee.pk not in approved_leave_ids
        and employee.pk not in policy_weekly_off_ids
        and employee.pk not in policy_holiday_ids
    ]
    attendance_snapshot_leave_covered_employees = [
        employee for employee in snapshot_unrecorded_employees if employee.pk in approved_leave_ids
    ]
    attendance_snapshot_weekly_off_employees = [
        employee
        for employee in snapshot_unrecorded_employees
        if employee.pk in policy_weekly_off_ids and employee.pk not in approved_leave_ids
    ]
    attendance_snapshot_holiday_employees = [
        employee
        for employee in snapshot_unrecorded_employees
        if employee.pk in policy_holiday_ids and employee.pk not in approved_leave_ids
    ]

    paginator = Paginator(attendance_display_records, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    pagination_items = build_attendance_history_pagination(page_obj)

    correction_queryset = EmployeeAttendanceCorrection.objects.select_related(
        "employee",
        "linked_attendance",
        "requested_by",
        "reviewed_by",
    ).filter(employee__in=scoped_employee_queryset)

    if filter_state["search_value"]:
        search_value = filter_state["search_value"]
        correction_queryset = correction_queryset.filter(
            Q(employee__full_name__icontains=search_value)
            | Q(employee__employee_id__icontains=search_value)
            | Q(request_reason__icontains=search_value)
            | Q(requested_notes__icontains=search_value)
            | Q(review_notes__icontains=search_value)
        )

    if filter_state["employee"]:
        correction_queryset = correction_queryset.filter(employee=filter_state["employee"])
    if filter_state["company"]:
        correction_queryset = correction_queryset.filter(employee__company=filter_state["company"])
    if filter_state["branch"]:
        correction_queryset = correction_queryset.filter(employee__branch=filter_state["branch"])
    if filter_state["department"]:
        correction_queryset = correction_queryset.filter(employee__department=filter_state["department"])
    if filter_state["section"]:
        correction_queryset = correction_queryset.filter(employee__section=filter_state["section"])
    if filter_state["day_status"]:
        correction_queryset = correction_queryset.filter(requested_day_status=filter_state["day_status"])
    if filter_state["start_date"]:
        correction_queryset = correction_queryset.filter(linked_attendance__attendance_date__gte=filter_state["start_date"])
    if filter_state["end_date"]:
        correction_queryset = correction_queryset.filter(linked_attendance__attendance_date__lte=filter_state["end_date"])

    correction_queryset = correction_queryset.order_by("-created_at", "-id")
    correction_records = list(correction_queryset[:50]) if not supervisor_history_only else []

    selected_attendance_record = None
    correction_form = None
    correction_target = request.GET.get("correct", "").strip()
    if correction_target and not supervisor_history_only:
        try:
            target_pk = int(correction_target)
        except ValueError:
            target_pk = None
        if target_pk:
            selected_attendance_record = attendance_queryset.filter(pk=target_pk).first()
            if selected_attendance_record:
                correction_form = EmployeeAttendanceCorrectionForm(
                    attendance_entry=selected_attendance_record,
                    initial={
                        "requested_day_status": selected_attendance_record.day_status,
                        "requested_clock_in_time": selected_attendance_record.clock_in_time,
                        "requested_clock_out_time": selected_attendance_record.clock_out_time,
                        "requested_scheduled_hours": selected_attendance_record.scheduled_hours,
                        "requested_late_minutes": selected_attendance_record.late_minutes,
                        "requested_early_departure_minutes": selected_attendance_record.early_departure_minutes,
                        "requested_overtime_minutes": selected_attendance_record.overtime_minutes,
                        "requested_notes": selected_attendance_record.notes,
                    },
                )

    querystring_data = request.GET.copy()
    querystring_data.pop("page", None)
    action_querystring_data = querystring_data.copy()
    action_querystring_data.pop("correct", None)
    attendance_management_querystring = querystring_data.urlencode()
    attendance_management_base_querystring = action_querystring_data.urlencode()
    attendance_route_name = (
        "employees:supervisor_attendance_history"
        if supervisor_history_only
        else "employees:attendance_management"
    )
    attendance_management_base_url = reverse(attendance_route_name)
    if attendance_management_base_querystring:
        attendance_management_base_url = (
            f"{attendance_management_base_url}?{attendance_management_base_querystring}"
        )

    scoped_branch = get_user_scope_branch(request.user)
    page_title = "Attendance History"
    page_subtitle = (
        "Management attendance history for filtering, auditing, and reviewing all employee attendance records inside your existing management scope."
    )
    ledger_subtitle = "Filtered company-wide attendance records with quick access back to each employee profile."
    empty_message = "Adjust the filters or start creating attendance ledger entries from employee profiles."
    back_button_label = "Back to Directory"

    if supervisor_history_only and scoped_branch:
        page_title = "Team Attendance History"
        page_subtitle = (
            f"Supervisor attendance history for {scoped_branch.name}. Only team members inside your current supervisor scope appear here."
        )
        ledger_subtitle = "Branch-scoped attendance history with click-only detail sections, reduced initial load, and no management-wide controls."
        empty_message = "No attendance history matched the current team filters."
        back_button_label = "Back to Team Directory"

    context = {
        "attendance_page_obj": page_obj,
        "attendance_records": page_obj.object_list,
        "attendance_pagination_items": pagination_items,
        "attendance_filter_form": filter_state["form"],
        "attendance_period_label": filter_state["period_label"],
        "attendance_filter_applied": filter_state["is_applied"],
        "attendance_management_querystring": attendance_management_querystring,
        "attendance_management_base_querystring": attendance_management_base_querystring,
        "attendance_management_base_url": attendance_management_base_url,
        "attendance_employee_count": len(
            {
                *[entry.employee_id for entry in attendance_entries],
                *[entry.employee_id for entry in pending_event_entries],
            }
        ),
        "attendance_day_status_choices": EmployeeAttendanceLedger.DAY_STATUS_CHOICES,
        "selected_attendance_record": selected_attendance_record,
        "attendance_correction_form": correction_form,
        "attendance_correction_records": correction_records,
        "attendance_correction_pending_count": correction_queryset.filter(status=EmployeeAttendanceCorrection.STATUS_PENDING).count() if not supervisor_history_only else 0,
        "attendance_correction_applied_count": correction_queryset.filter(status=EmployeeAttendanceCorrection.STATUS_APPLIED).count() if not supervisor_history_only else 0,
        "attendance_correction_rejected_count": correction_queryset.filter(status=EmployeeAttendanceCorrection.STATUS_REJECTED).count() if not supervisor_history_only else 0,
        "attendance_snapshot_date": snapshot_date,
        "attendance_snapshot_note": attendance_snapshot_note,
        "attendance_snapshot_scope_count": len(snapshot_scope_employees),
        "attendance_snapshot_recorded_count": len(snapshot_recorded_employee_ids),
        "attendance_snapshot_missing_count": len(attendance_snapshot_missing_employees),
        "attendance_snapshot_leave_covered_count": len(attendance_snapshot_leave_covered_employees),
        "attendance_snapshot_weekly_off_count": len(attendance_snapshot_weekly_off_employees),
        "attendance_snapshot_holiday_count": len(attendance_snapshot_holiday_employees),
        "attendance_snapshot_missing_employees": attendance_snapshot_missing_employees[:12],
        "attendance_snapshot_missing_more_count": max(len(attendance_snapshot_missing_employees) - 12, 0),
        "attendance_snapshot_is_single_day": snapshot_is_single_day,
        "attendance_live_open_count": len(pending_event_entries),
        "half_day_attendance_count": sum(1 for entry in attendance_entries if entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_PRESENT and entry.worked_hours and entry.worked_hours < entry.scheduled_hours),
        "early_exit_flag_count": sum(1 for entry in attendance_entries if (entry.early_departure_minutes or 0) > 0),
        "overtime_ready_count": sum(1 for entry in attendance_entries if (entry.overtime_minutes or 0) > 0),
        "attendance_history_is_supervisor_scope": supervisor_history_only,
        "attendance_history_page_title": page_title,
        "attendance_history_page_subtitle": page_subtitle,
        "attendance_history_snapshot_title": "Team Snapshot" if supervisor_history_only else "Daily Attendance Snapshot",
        "attendance_history_ledger_subtitle": ledger_subtitle,
        "attendance_history_back_button_label": back_button_label,
        "attendance_history_empty_message": empty_message,
        "attendance_history_can_request_correction": not supervisor_history_only,
        "attendance_history_can_view_corrections": not supervisor_history_only,
        "attendance_history_route_name": attendance_route_name,
        "attendance_history_show_compact_summary": supervisor_history_only,
    }
    context.update(attendance_summary)

    return context


@login_required
def attendance_management(request):
    if not can_view_attendance_management(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to access attendance management.",
        )

    context = build_attendance_history_management_context(request, supervisor_history_only=False)
    return render(request, "employees/attendance_management.html", context)


@login_required
def branch_schedule_overview(request):
    if not can_view_branch_schedule_overview(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to access branch schedules overview.",
        )

    today = timezone.localdate()
    week_value = (request.GET.get("week") or "").strip()
    if week_value:
        try:
            selected_week_start = get_schedule_week_start(date.fromisoformat(week_value))
        except ValueError:
            selected_week_start = get_schedule_week_start(today)
    else:
        selected_week_start = get_schedule_week_start(today)

    week_end = selected_week_start + timedelta(days=6)
    search_query = (request.GET.get("search") or "").strip()
    selected_day_status = (request.GET.get("day_status") or "").strip()
    selected_branch_token = (request.GET.get("branch") or "").strip()

    branches = list(
        Branch.objects.select_related("company")
        .filter(is_active=True)
        .annotate(active_employee_total=Count("employees", filter=Q(employees__is_active=True), distinct=True))
        .order_by("company__name", "name")
    )
    selected_branch = next((branch for branch in branches if str(branch.pk) == selected_branch_token), None)
    if selected_branch is None and branches:
        selected_branch = branches[0]
        selected_branch_token = str(selected_branch.pk)

    schedule_count_map = {
        row["branch_id"]: row
        for row in (
            BranchWeeklyScheduleEntry.objects.filter(week_start=selected_week_start)
            .values("branch_id")
            .annotate(
                schedule_total=Count("id"),
                completed_total=Count("id", filter=Q(status=BranchWeeklyScheduleEntry.STATUS_COMPLETED)),
                planned_total=Count("id", filter=Q(status=BranchWeeklyScheduleEntry.STATUS_PLANNED)),
                in_progress_total=Count("id", filter=Q(status=BranchWeeklyScheduleEntry.STATUS_IN_PROGRESS)),
                on_hold_total=Count("id", filter=Q(status=BranchWeeklyScheduleEntry.STATUS_ON_HOLD)),
            )
        )
    }
    attendance_count_map = {
        row["employee__branch_id"]: row
        for row in (
            EmployeeAttendanceLedger.objects.filter(
                attendance_date__gte=selected_week_start,
                attendance_date__lte=week_end,
                employee__branch__isnull=False,
            )
            .values("employee__branch_id")
            .annotate(
                attendance_total=Count("id"),
                exception_total=Count(
                    "id",
                    filter=Q(
                        day_status__in=[
                            EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
                            EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
                            EmployeeAttendanceLedger.DAY_STATUS_OTHER,
                        ]
                    ),
                ),
            )
        )
    }

    branch_cards = []
    for branch in branches:
        branch_query = request.GET.copy()
        branch_query["branch"] = str(branch.pk)
        branch_cards.append(
            {
                "branch": branch,
                "is_selected": bool(selected_branch and branch.pk == selected_branch.pk),
                "schedule_total": schedule_count_map.get(branch.pk, {}).get("schedule_total", 0),
                "completed_total": schedule_count_map.get(branch.pk, {}).get("completed_total", 0),
                "attendance_total": attendance_count_map.get(branch.pk, {}).get("attendance_total", 0),
                "exception_total": attendance_count_map.get(branch.pk, {}).get("exception_total", 0),
                "select_url": (
                    f"{reverse('employees:branch_schedule_overview')}?{branch_query.urlencode()}"
                    if branch_query
                    else reverse("employees:branch_schedule_overview")
                ),
            }
        )

    overview_summary = {
        "team_members": [],
        "team_schedule_rows": [],
        "schedule_entries": [],
        "week_days": build_schedule_week_days(selected_week_start),
        "schedule_total": 0,
        "completed_total": 0,
        "in_progress_total": 0,
        "planned_total": 0,
        "on_hold_total": 0,
    }
    filtered_schedule_rows = []
    attendance_records = []
    attendance_total = 0
    attendance_exception_total = 0
    attendance_present_total = 0
    attendance_leave_total = 0
    attendance_weekly_off_total = 0
    attendance_holiday_total = 0
    selected_week_holidays = []

    if selected_branch:
        overview_summary = build_branch_weekly_schedule_summary(selected_branch, selected_week_start)
        filtered_schedule_rows = list(overview_summary["team_schedule_rows"])
        if search_query:
            normalized_query = search_query.casefold()
            filtered_schedule_rows = [
                row
                for row in filtered_schedule_rows
                if normalized_query in (row["employee"].full_name or "").casefold()
                or normalized_query in (row["employee"].employee_id or "").casefold()
                or normalized_query in (getattr(getattr(row["employee"], "job_title", None), "name", "") or "").casefold()
            ]

        attendance_queryset = EmployeeAttendanceLedger.objects.select_related(
            "employee",
            "employee__company",
            "employee__department",
            "employee__branch",
            "employee__section",
            "employee__job_title",
        ).filter(
            employee__branch=selected_branch,
            attendance_date__gte=selected_week_start,
            attendance_date__lte=week_end,
        )
        if search_query:
            attendance_queryset = attendance_queryset.filter(
                Q(employee__full_name__icontains=search_query)
                | Q(employee__employee_id__icontains=search_query)
                | Q(employee__job_title__name__icontains=search_query)
            )
        if selected_day_status:
            attendance_queryset = attendance_queryset.filter(day_status=selected_day_status)

        attendance_queryset = attendance_queryset.order_by("attendance_date", "employee__full_name", "id")
        attendance_total = attendance_queryset.count()
        attendance_exception_total = attendance_queryset.filter(
            day_status__in=[
                EmployeeAttendanceLedger.DAY_STATUS_ABSENT,
                EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
                EmployeeAttendanceLedger.DAY_STATUS_OTHER,
            ]
        ).count()
        attendance_present_total = attendance_queryset.filter(day_status=EmployeeAttendanceLedger.DAY_STATUS_PRESENT).count()
        attendance_leave_total = attendance_queryset.filter(
            day_status__in=[
                EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
                EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
                EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE,
            ]
        ).count()
        attendance_weekly_off_total = attendance_queryset.filter(
            day_status=EmployeeAttendanceLedger.DAY_STATUS_WEEKLY_OFF
        ).count()
        attendance_holiday_total = attendance_queryset.filter(
            day_status=EmployeeAttendanceLedger.DAY_STATUS_HOLIDAY
        ).count()
        attendance_records = list(attendance_queryset[:200])

        try:
            from workcalendar.services import get_holidays_for_range

            selected_week_holidays = get_holidays_for_range(selected_week_start, week_end)
        except Exception:
            selected_week_holidays = []

    previous_week_start = selected_week_start - timedelta(days=7)
    next_week_start = selected_week_start + timedelta(days=7)
    filter_query = request.GET.copy()

    def build_overview_url(**updates):
        query = filter_query.copy()
        for key, value in updates.items():
            if value in (None, ""):
                query.pop(key, None)
            else:
                query[key] = value
        querystring = query.urlencode()
        return (
            f"{reverse('employees:branch_schedule_overview')}?{querystring}"
            if querystring
            else reverse("employees:branch_schedule_overview")
        )

    selected_branch_workspace_url = (
        reverse("operations:branch_workspace_detail", kwargs={"branch_id": selected_branch.pk})
        if selected_branch
        else ""
    )
    attendance_management_url = ""
    if selected_branch:
        attendance_query = (
            f"branch={selected_branch.pk}"
            f"&start_date={selected_week_start.isoformat()}"
            f"&end_date={week_end.isoformat()}"
            f"&filter_type=custom"
        )
        if search_query:
            attendance_query += f"&search={search_query}"
        attendance_management_url = f"{reverse('employees:attendance_management')}?{attendance_query}"

    context = {
        "selected_week_start": selected_week_start,
        "week_end": week_end,
        "today": today,
        "previous_week_start": previous_week_start,
        "next_week_start": next_week_start,
        "selected_branch": selected_branch,
        "selected_branch_token": selected_branch_token,
        "branches": branches,
        "branch_cards": branch_cards,
        "search_query": search_query,
        "selected_day_status": selected_day_status,
        "day_status_filter_choices": [("", "All day statuses"), *EmployeeAttendanceLedger.DAY_STATUS_CHOICES],
        "overview_summary": overview_summary,
        "team_schedule_rows": filtered_schedule_rows,
        "selected_week_holidays": selected_week_holidays,
        "attendance_records": attendance_records,
        "attendance_total": attendance_total,
        "attendance_exception_total": attendance_exception_total,
        "attendance_present_total": attendance_present_total,
        "attendance_leave_total": attendance_leave_total,
        "attendance_weekly_off_total": attendance_weekly_off_total,
        "attendance_holiday_total": attendance_holiday_total,
        "selected_branch_workspace_url": selected_branch_workspace_url,
        "attendance_management_url": attendance_management_url,
        "previous_week_url": build_overview_url(week=previous_week_start.isoformat()),
        "next_week_url": build_overview_url(week=next_week_start.isoformat()),
        "current_week_url": build_overview_url(week=get_schedule_week_start(today).isoformat()),
        "clear_filters_url": reverse("employees:branch_schedule_overview"),
    }
    return render(request, "employees/branch_schedule_overview.html", context)


@login_required
def supervisor_attendance_history(request):
    if not is_branch_scoped_supervisor(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to access team attendance history.",
        )

    context = build_attendance_history_management_context(request, supervisor_history_only=True)
    return render(request, "employees/attendance_management.html", context)


