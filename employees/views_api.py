from .views_shared import *
from .views_directory import *

# AJAX dependency endpoints and employee request overview screens.

@login_required
def get_departments_by_company(request):
    if not can_access_employee_form_dependencies(request.user):
        return deny_json_access()

    # Shared company assignment rule:
    # departments remain organization-owned records, but employee forms may
    # reuse the same active departments across different selected companies.
    departments = (
        Department.objects.filter(is_active=True)
        .select_related("company")
        .order_by("company__name", "name")
    )
    results = [
        {"id": department.id, "name": department.name}
        for department in departments
    ]

    return JsonResponse({"results": results})


@login_required
def get_branches_by_company(request):
    if not can_access_employee_form_dependencies(request.user):
        return deny_json_access()

    # Shared company assignment rule:
    # branches remain organization-owned records, but employee forms may
    # reuse the same active branches across different selected companies.
    branches = (
        Branch.objects.filter(is_active=True)
        .select_related("company")
        .order_by("company__name", "name")
    )
    results = [
        {"id": branch.id, "name": branch.name}
        for branch in branches
    ]

    return JsonResponse({"results": results})


@login_required
def get_sections_by_department(request):
    if not can_access_employee_form_dependencies(request.user):
        return deny_json_access()

    department_id = request.GET.get("department_id")
    results = []

    if department_id:
        sections = Section.objects.filter(department_id=department_id, is_active=True).order_by("name")
        results = [{"id": section.id, "name": section.name} for section in sections]

    return JsonResponse({"results": results})


@login_required
def get_job_titles_by_context(request):
    if not can_access_employee_form_dependencies(request.user):
        return deny_json_access()

    department_id = request.GET.get("department_id")
    section_id = request.GET.get("section_id")
    results = []

    if department_id:
        job_titles = JobTitle.objects.filter(
            department_id=department_id,
            is_active=True,
        )

        if section_id:
            job_titles = job_titles.filter(Q(section_id=section_id) | Q(section__isnull=True))
        else:
            job_titles = job_titles.filter(section__isnull=True)

        job_titles = job_titles.order_by("name")
        results = [{"id": job_title.id, "name": job_title.name} for job_title in job_titles]

    return JsonResponse({"results": results})



def get_employee_professional_snapshot(employee):
    return {
        "company": getattr(getattr(employee, "company", None), "name", "") or "",
        "department": getattr(getattr(employee, "department", None), "name", "") or "",
        "branch": getattr(getattr(employee, "branch", None), "name", "") or "",
        "section": getattr(getattr(employee, "section", None), "name", "") or "",
        "job_title": getattr(getattr(employee, "job_title", None), "name", "") or "",
        "hire_date": getattr(employee, "hire_date", None),
        "department_manager": get_department_manager_display(employee),
        "branch_supervisor": get_branch_supervisor_display(employee),
        "team_leader": get_team_leader_display(employee),
    }


def build_employee_request_overview(leave_record):
    supporting_documents = list(
        leave_record.supporting_documents.all().order_by("-uploaded_at", "-id")
    )
    latest_related_date = leave_record.updated_at or leave_record.created_at

    for document in supporting_documents:
        document_date = getattr(document, "updated_at", None) or getattr(document, "created_at", None)
        if document_date and (latest_related_date is None or document_date > latest_related_date):
            latest_related_date = document_date

    employee = leave_record.employee
    submitted_at = timezone.localtime(leave_record.created_at) if leave_record.created_at else None
    submitted_date = submitted_at.date() if submitted_at else leave_record.start_date

    return {
        "leave_record": leave_record,
        "workflow_owner_label": get_leave_current_stage_owner_label(leave_record),
        "employee": employee,
        "professional_snapshot": get_employee_professional_snapshot(employee),
        "supporting_documents": supporting_documents,
        "supporting_documents_count": len(supporting_documents),
        "latest_related_date": latest_related_date,
        "submitted_at": submitted_at,
        "submitted_date": submitted_date,
    }


def get_request_week_start(target_date):
    if not target_date:
        return None

    saturday_weekday = 5
    offset = (target_date.weekday() - saturday_weekday) % 7
    return target_date - timedelta(days=offset)


def build_request_overview_groups(request_cards):
    today = timezone.localdate()
    current_week_start = get_request_week_start(today)
    week_map = {}

    for item in request_cards:
        submitted_date = item.get("submitted_date") or today
        week_start = get_request_week_start(submitted_date) or current_week_start
        week_entry = week_map.setdefault(
            week_start,
            {
                "week_start": week_start,
                "week_end": week_start + timedelta(days=6),
                "day_map": {},
                "request_total": 0,
                "document_total": 0,
            },
        )

        day_entry = week_entry["day_map"].setdefault(
            submitted_date,
            {
                "date": submitted_date,
                "items": [],
                "request_total": 0,
                "document_total": 0,
            },
        )

        day_entry["items"].append(item)
        day_entry["request_total"] += 1
        day_entry["document_total"] += item.get("supporting_documents_count", 0)

        week_entry["request_total"] += 1
        week_entry["document_total"] += item.get("supporting_documents_count", 0)

    grouped_weeks = []
    for week_start in sorted(week_map.keys(), reverse=True):
        week_entry = week_map[week_start]
        ordered_days = []

        for request_date in sorted(week_entry["day_map"].keys(), reverse=True):
            day_entry = week_entry["day_map"][request_date]
            ordered_days.append(
                {
                    "date": request_date,
                    "label": request_date.strftime("%A, %B %d, %Y"),
                    "short_label": request_date.strftime("%b %d"),
                    "request_total": day_entry["request_total"],
                    "document_total": day_entry["document_total"],
                    "items": day_entry["items"],
                    "is_today": request_date == today,
                    "is_open": False,
                }
            )

        grouped_weeks.append(
            {
                "key": week_start.isoformat(),
                "week_start": week_entry["week_start"],
                "week_end": week_entry["week_end"],
                "label": f"{week_entry['week_start'].strftime('%b %d, %Y')} → {week_entry['week_end'].strftime('%b %d, %Y')}",
                "request_total": week_entry["request_total"],
                "document_total": week_entry["document_total"],
                "days": ordered_days,
                "is_current_week": week_start == current_week_start,
                "is_open": False,
            }
        )

    return grouped_weeks


@login_required
def employee_requests_overview(request):
    if not can_view_employee_requests_overview(request.user):
        if is_supervisor_user(request.user):
            messages.error(
                request,
                "Supervisor request review requires linking this login account to an employee profile with an assigned branch.",
            )
            return redirect("dashboard_home")
        linked_employee = get_user_employee_profile(request.user)
        if linked_employee:
            messages.error(request, "You do not have permission to access employee requests overview.")
            return redirect("employees:employee_detail", pk=linked_employee.pk)
        raise PermissionDenied("You do not have permission to access employee requests overview.")

    leave_queryset = get_leave_queryset_for_user(
        request.user,
        EmployeeLeave.objects.select_related(
            "employee",
            "employee__company",
            "employee__department",
            "employee__branch",
            "employee__section",
            "employee__job_title",
            "requested_by",
            "approved_by",
            "rejected_by",
            "cancelled_by",
            "supervisor_reviewed_by",
            "operations_reviewed_by",
            "hr_reviewed_by",
        )
        .prefetch_related(
            Prefetch(
                "supporting_documents",
                queryset=EmployeeDocument.objects.select_related("employee", "linked_leave").order_by("-uploaded_at", "-id"),
            )
        )
        .order_by("-created_at", "-id"),
    )

    search_query = (request.GET.get("search") or "").strip()
    selected_status = (request.GET.get("status") or "").strip()
    selected_leave_type = (request.GET.get("leave_type") or "").strip()
    selected_company = (request.GET.get("company") or "").strip()
    selected_department = (request.GET.get("department") or "").strip()
    selected_branch = (request.GET.get("branch") or "").strip()

    if search_query:
        leave_queryset = leave_queryset.filter(
            Q(employee__full_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
            | Q(employee__email__icontains=search_query)
            | Q(reason__icontains=search_query)
            | Q(approval_note__icontains=search_query)
            | Q(supporting_documents__title__icontains=search_query)
            | Q(supporting_documents__description__icontains=search_query)
            | Q(supporting_documents__reference_number__icontains=search_query)
            | Q(supporting_documents__original_filename__icontains=search_query)
        ).distinct()

    if selected_status:
        leave_queryset = leave_queryset.filter(status=selected_status)
    if selected_leave_type:
        leave_queryset = leave_queryset.filter(leave_type=selected_leave_type)
    if selected_company:
        leave_queryset = leave_queryset.filter(employee__company_id=selected_company)
    if selected_department:
        leave_queryset = leave_queryset.filter(employee__department_id=selected_department)
    if selected_branch:
        leave_queryset = leave_queryset.filter(employee__branch_id=selected_branch)

    scoped_branch = get_user_scope_branch(request.user)
    branch_scoped_supervisor = is_branch_scoped_supervisor(request.user)
    if branch_scoped_supervisor and scoped_branch:
        leave_queryset = leave_queryset.filter(employee__branch_id=scoped_branch.id)
        selected_branch = str(scoped_branch.id)

    request_total = leave_queryset.count()
    pending_total = leave_queryset.filter(status=EmployeeLeave.STATUS_PENDING).count()
    approved_total = leave_queryset.filter(status=EmployeeLeave.STATUS_APPROVED).count()
    rejected_total = leave_queryset.filter(status=EmployeeLeave.STATUS_REJECTED).count()
    cancelled_total = leave_queryset.filter(status=EmployeeLeave.STATUS_CANCELLED).count()
    waiting_supervisor_total = leave_queryset.filter(
        status=EmployeeLeave.STATUS_PENDING,
        current_stage=EmployeeLeave.STAGE_SUPERVISOR_REVIEW,
    ).count()
    waiting_operations_total = leave_queryset.filter(
        status=EmployeeLeave.STATUS_PENDING,
        current_stage=EmployeeLeave.STAGE_OPERATIONS_REVIEW,
    ).count()
    waiting_hr_total = leave_queryset.filter(
        status=EmployeeLeave.STATUS_PENDING,
        current_stage=EmployeeLeave.STAGE_HR_REVIEW,
    ).count()
    my_stage_pending_total = sum(
        1
        for leave_record in leave_queryset.filter(status=EmployeeLeave.STATUS_PENDING)
        if can_user_review_leave_stage(request.user, leave_record)
    )
    documents_total = leave_queryset.aggregate(
        total=Count("supporting_documents", distinct=True)
    )["total"] or 0

    leave_paginator = Paginator(leave_queryset, 25)
    leave_page_obj = leave_paginator.get_page(request.GET.get("page"))
    leave_records = list(leave_page_obj.object_list)
    request_cards = [build_employee_request_overview(leave_record) for leave_record in leave_records]
    grouped_request_weeks = build_request_overview_groups(request_cards)
    query_params = request.GET.copy()
    query_params.pop("page", None)

    if branch_scoped_supervisor:
        current_leave_review_stage_label = "Supervisor Review Queue"
    elif is_operations_manager_user(request.user):
        current_leave_review_stage_label = "Operations Review Queue"
    elif is_hr_user(request.user):
        current_leave_review_stage_label = "HR Review Queue"
    else:
        current_leave_review_stage_label = "Management Review Queue"

    scoped_employee_queryset = get_employee_directory_queryset_for_user(
        request.user,
        Employee.objects.select_related(
            "company",
            "department",
            "branch",
            "section",
            "job_title",
        ).all(),
    )

    employee_document_queryset = EmployeeDocument.objects.select_related(
        "employee",
        "employee__company",
        "employee__department",
        "employee__branch",
        "employee__section",
        "employee__job_title",
        "linked_leave",
    ).filter(employee__in=scoped_employee_queryset)
    if search_query:
        employee_document_queryset = employee_document_queryset.filter(
            Q(employee__full_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
            | Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(reference_number__icontains=search_query)
            | Q(original_filename__icontains=search_query)
        )
    if selected_company:
        employee_document_queryset = employee_document_queryset.filter(employee__company_id=selected_company)
    if selected_department:
        employee_document_queryset = employee_document_queryset.filter(employee__department_id=selected_department)
    if selected_branch:
        employee_document_queryset = employee_document_queryset.filter(employee__branch_id=selected_branch)
    employee_document_queryset = employee_document_queryset.order_by("-uploaded_at", "-id")
    expanded_group_keys = {value for value in request.GET.getlist("expanded_group") if value}
    employee_documents = list(employee_document_queryset)
    latest_employee_document_groups = build_management_document_group_cards(
        employee_documents,
        expanded_group_keys=expanded_group_keys,
    )
    employee_documents_total = len(employee_documents)

    submission_queryset = EmployeeRequiredSubmission.objects.select_related(
        "employee",
        "employee__company",
        "employee__department",
        "employee__branch",
        "employee__section",
        "employee__job_title",
        "created_by",
        "reviewed_by",
    ).filter(employee__in=scoped_employee_queryset)
    if search_query:
        submission_queryset = submission_queryset.filter(
            Q(employee__full_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
            | Q(title__icontains=search_query)
            | Q(instructions__icontains=search_query)
            | Q(created_by__icontains=search_query)
        )
    if selected_company:
        submission_queryset = submission_queryset.filter(employee__company_id=selected_company)
    if selected_department:
        submission_queryset = submission_queryset.filter(employee__department_id=selected_department)
    if selected_branch:
        submission_queryset = submission_queryset.filter(employee__branch_id=selected_branch)
    submission_queryset = submission_queryset.order_by("-created_at", "-id")
    latest_submission_requests = list(submission_queryset[:12])
    submission_request_total = submission_queryset.count()
    submission_requested_total = submission_queryset.filter(status=EmployeeRequiredSubmission.STATUS_REQUESTED).count()
    submission_submitted_total = submission_queryset.filter(status=EmployeeRequiredSubmission.STATUS_SUBMITTED).count()
    submission_completed_total = submission_queryset.filter(status=EmployeeRequiredSubmission.STATUS_COMPLETED).count()

    employee_document_request_queryset = EmployeeDocumentRequest.objects.select_related(
        "employee",
        "employee__company",
        "employee__department",
        "employee__branch",
        "employee__section",
        "employee__job_title",
        "reviewed_by",
    ).filter(employee__in=scoped_employee_queryset)
    if search_query:
        employee_document_request_queryset = employee_document_request_queryset.filter(
            Q(employee__full_name__icontains=search_query)
            | Q(employee__employee_id__icontains=search_query)
            | Q(title__icontains=search_query)
            | Q(request_note__icontains=search_query)
            | Q(management_note__icontains=search_query)
        )
    if selected_company:
        employee_document_request_queryset = employee_document_request_queryset.filter(employee__company_id=selected_company)
    if selected_department:
        employee_document_request_queryset = employee_document_request_queryset.filter(employee__department_id=selected_department)
    if selected_branch:
        employee_document_request_queryset = employee_document_request_queryset.filter(employee__branch_id=selected_branch)
    employee_document_request_queryset = employee_document_request_queryset.order_by("-submitted_at", "-created_at", "-id")
    employee_document_requests = list(employee_document_request_queryset[:12])
    for document_request in employee_document_requests:
        document_request.review_form = (
            EmployeeDocumentRequestReviewForm(instance=document_request)
            if can_review_employee_document_request(request.user, document_request)
            else None
        )
    employee_document_request_total = employee_document_request_queryset.count()
    employee_document_request_requested_total = employee_document_request_queryset.filter(
        status=EmployeeDocumentRequest.STATUS_REQUESTED
    ).count()
    employee_document_request_approved_total = employee_document_request_queryset.filter(
        status=EmployeeDocumentRequest.STATUS_APPROVED
    ).count()
    employee_document_request_completed_total = employee_document_request_queryset.filter(
        status=EmployeeDocumentRequest.STATUS_COMPLETED
    ).count()
    employee_document_request_rejected_total = employee_document_request_queryset.filter(
        status=EmployeeDocumentRequest.STATUS_REJECTED
    ).count()
    employee_document_request_cancelled_total = employee_document_request_queryset.filter(
        status=EmployeeDocumentRequest.STATUS_CANCELLED
    ).count()

    context = {
        "request_total": request_total,
        "pending_total": pending_total,
        "approved_total": approved_total,
        "rejected_total": rejected_total,
        "cancelled_total": cancelled_total,
        "documents_total": documents_total,
        "my_stage_pending_total": my_stage_pending_total,
        "waiting_supervisor_total": waiting_supervisor_total,
        "waiting_operations_total": waiting_operations_total,
        "waiting_hr_total": waiting_hr_total,
        "current_leave_review_stage_label": current_leave_review_stage_label,
        "search_query": search_query,
        "selected_status": selected_status,
        "selected_leave_type": selected_leave_type,
        "selected_company": selected_company,
        "selected_department": selected_department,
        "selected_branch": selected_branch,
        "status_choices": EmployeeLeave.STATUS_CHOICES,
        "leave_type_choices": EmployeeLeave.LEAVE_TYPE_CHOICES,
        "companies": Company.objects.filter(is_active=True).order_by("name"),
        "departments": Department.objects.filter(is_active=True).select_related("company").order_by("company__name", "name"),
        "branches": Branch.objects.filter(is_active=True).select_related("company").order_by("company__name", "name"),
        "grouped_request_weeks": grouped_request_weeks,
        "leave_page_obj": leave_page_obj,
        "leave_paginator": leave_paginator,
        "leave_pagination_querystring": query_params.urlencode(),
        "scoped_branch": scoped_branch,
        "is_branch_scoped_supervisor": branch_scoped_supervisor,
        "can_review_leave": can_review_leave(request.user),
        "employee_documents_total": employee_documents_total,
        "latest_employee_document_groups": latest_employee_document_groups,
        "submission_request_total": submission_request_total,
        "submission_requested_total": submission_requested_total,
        "submission_submitted_total": submission_submitted_total,
        "submission_completed_total": submission_completed_total,
        "latest_submission_requests": latest_submission_requests,
        "employee_document_request_total": employee_document_request_total,
        "employee_document_request_requested_total": employee_document_request_requested_total,
        "employee_document_request_approved_total": employee_document_request_approved_total,
        "employee_document_request_completed_total": employee_document_request_completed_total,
        "employee_document_request_rejected_total": employee_document_request_rejected_total,
        "employee_document_request_cancelled_total": employee_document_request_cancelled_total,
        "employee_document_requests": employee_document_requests,
    }
    return render(request, "employees/employee_requests_overview.html", context)
