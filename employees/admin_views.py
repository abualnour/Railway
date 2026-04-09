from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .admin_forms import EmployeeAdminActionCenterFilterForm
from .forms import (
    EmployeeActionRecordForm,
    EmployeeAttendanceLedgerForm,
    EmployeeDocumentForm,
    EmployeeHistoryForm,
    EmployeeLeaveForm,
)
from .models import Employee, EmployeeAttendanceLedger, EmployeeHistory, EmployeeLeave
from .views import (
    build_action_record_summary,
    build_attendance_ledger_summary,
    build_document_summary,
    build_leave_request_summary,
    can_add_manual_history,
    can_create_action_records,
    can_manage_attendance_records,
    can_manage_employee_documents,
    can_request_leave,
    create_employee_history,
    deny_employee_access,
    get_actor_label,
    is_management_user,
)

ACTION_FORM_CONFIG = {
    EmployeeAdminActionCenterFilterForm.ACTION_DOCUMENT: {
        "title": "Upload Document",
        "subtitle": "Attach a document to the selected employee from one centralized management page.",
        "button_label": "Upload Document",
    },
    EmployeeAdminActionCenterFilterForm.ACTION_LEAVE: {
        "title": "Create Leave Request",
        "subtitle": "Create an employee leave request from management side while keeping the employee profile clean.",
        "button_label": "Create Leave Request",
    },
    EmployeeAdminActionCenterFilterForm.ACTION_ACTION_RECORD: {
        "title": "Create Attendance / Incident Record",
        "subtitle": "Register warnings, incidents, commendations, memo entries, and attendance-related action records.",
        "button_label": "Create Action Record",
    },
    EmployeeAdminActionCenterFilterForm.ACTION_ATTENDANCE: {
        "title": "Add Attendance Ledger Entry",
        "subtitle": "Create the real daily attendance ledger entry for the selected employee.",
        "button_label": "Create Attendance Entry",
    },
    EmployeeAdminActionCenterFilterForm.ACTION_HISTORY: {
        "title": "Add Timeline Entry",
        "subtitle": "Add a manual HR note or timeline event without crowding the employee detail page.",
        "button_label": "Add Timeline Entry",
    },
}


def get_manageable_employee_queryset(user):
    if not is_management_user(user):
        return Employee.objects.none()

    return Employee.objects.select_related(
        "company",
        "department",
        "branch",
        "section",
        "job_title",
    ).order_by("employee_id", "full_name")


def get_selected_action(value):
    valid_values = {choice[0] for choice in EmployeeAdminActionCenterFilterForm.ACTION_CHOICES}
    if value in valid_values:
        return value
    return EmployeeAdminActionCenterFilterForm.ACTION_DOCUMENT


def get_action_form(action_type, employee=None, data=None, files=None):
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_DOCUMENT:
        return EmployeeDocumentForm(data=data, files=files)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_LEAVE:
        return EmployeeLeaveForm(data=data)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ACTION_RECORD:
        return EmployeeActionRecordForm(data=data)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ATTENDANCE:
        return EmployeeAttendanceLedgerForm(data=data, employee=employee)
    return EmployeeHistoryForm(data=data)


def get_permission_for_action(user, employee, action_type):
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_DOCUMENT:
        return can_manage_employee_documents(user, employee)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_LEAVE:
        return can_request_leave(user, employee)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ACTION_RECORD:
        return can_create_action_records(user)
    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ATTENDANCE:
        return can_manage_attendance_records(user)
    return can_add_manual_history(user)


def build_action_center_metrics(employee):
    if not employee:
        return {}

    return {
        "documents_count": employee.documents.count(),
        "pending_leave_count": employee.leave_records.filter(status=EmployeeLeave.STATUS_PENDING).count(),
        "action_record_count": employee.action_records.count(),
        "attendance_count": employee.attendance_ledgers.count(),
        "history_count": employee.history_entries.count(),
    }


def save_action_from_center(request, employee, action_type, form):
    actor_label = get_actor_label(request.user)

    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_DOCUMENT:
        document = form.save(commit=False)
        document.employee = employee
        document.save()

        create_employee_history(
            employee=employee,
            title=f"Document uploaded: {document.title or document.filename}",
            description=build_document_summary(document),
            event_type=EmployeeHistory.EVENT_DOCUMENT,
            created_by=actor_label,
            is_system_generated=True,
            event_date=document.issue_date or document.uploaded_at.date(),
        )
        messages.success(request, "Document uploaded successfully.")
        return

    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_LEAVE:
        leave_record = form.save(commit=False)
        leave_record.employee = employee
        leave_record.requested_by = request.user
        leave_record.created_by = actor_label
        leave_record.updated_by = actor_label
        leave_record.save()

        create_employee_history(
            employee=employee,
            title=f"Leave requested: {leave_record.get_leave_type_display()}",
            description=build_leave_request_summary(leave_record),
            event_type=EmployeeHistory.EVENT_STATUS,
            created_by=actor_label,
            is_system_generated=True,
            event_date=leave_record.start_date,
        )
        messages.success(request, "Leave request created successfully.")
        return

    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ACTION_RECORD:
        action_record = form.save(commit=False)
        action_record.employee = employee
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
        messages.success(request, "Attendance / incident record added successfully.")
        return

    if action_type == EmployeeAdminActionCenterFilterForm.ACTION_ATTENDANCE:
        attendance_entry = form.save(commit=False)
        attendance_entry.employee = employee
        attendance_entry.source = EmployeeAttendanceLedger.SOURCE_MANUAL
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
        messages.success(request, "Attendance ledger entry added successfully.")
        return

    history_entry = form.save(commit=False)
    history_entry.employee = employee
    history_entry.created_by = actor_label
    history_entry.is_system_generated = False
    history_entry.save()
    messages.success(request, "Timeline entry added successfully.")


@login_required
def employee_admin_action_center(request):
    if not is_management_user(request.user):
        return deny_employee_access(
            request,
            "You do not have permission to access the employee action center.",
        )

    employee_queryset = get_manageable_employee_queryset(request.user)

    employee_value = request.POST.get("employee_id") or request.GET.get("employee")
    selected_employee = None
    if employee_value:
        selected_employee = get_object_or_404(employee_queryset, pk=employee_value)

    selected_action = get_selected_action(request.POST.get("action_type") or request.GET.get("action"))

    if request.method == "POST":
        if not selected_employee:
            messages.error(request, "Please select an employee before submitting an action.")
            return redirect(reverse("employees:employee_admin_action_center"))

        if not get_permission_for_action(request.user, selected_employee, selected_action):
            return deny_employee_access(
                request,
                "You do not have permission to create this action for the selected employee.",
                employee=selected_employee,
            )

        active_form = get_action_form(
            selected_action,
            employee=selected_employee,
            data=request.POST,
            files=request.FILES,
        )

        if active_form.is_valid():
            save_action_from_center(request, selected_employee, selected_action, active_form)
            return redirect(
                f"{reverse('employees:employee_admin_action_center')}?employee={selected_employee.pk}&action={selected_action}"
            )
    else:
        active_form = get_action_form(selected_action, employee=selected_employee)

    selection_form = EmployeeAdminActionCenterFilterForm(
        data={
            "employee": selected_employee.pk if selected_employee else "",
            "action_type": selected_action,
        },
        employee_queryset=employee_queryset,
    )

    context = {
        "page_title": "Employee Action Center",
        "page_subtitle": "Centralized management page for employee documents, leave requests, attendance ledger entries, action records, and timeline notes.",
        "selection_form": selection_form,
        "selected_employee": selected_employee,
        "selected_action": selected_action,
        "active_form": active_form,
        "action_config": ACTION_FORM_CONFIG[selected_action],
        "action_choices": EmployeeAdminActionCenterFilterForm.ACTION_CHOICES,
        "selected_employee_metrics": build_action_center_metrics(selected_employee),
        "back_to_employee_url": reverse("employees:employee_detail", kwargs={"pk": selected_employee.pk})
        if selected_employee
        else None,
    }
    return render(request, "employees/employee_action_center.html", context)