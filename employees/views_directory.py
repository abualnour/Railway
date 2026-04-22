from .views_shared import *

# Directory, detail, and structural employee views.

class EmployeeListView(LoginRequiredMixin, ListView):
    model = Employee
    template_name = "employees/employee_list.html"
    context_object_name = "employees"
    paginate_by = 5

    def dispatch(self, request, *args, **kwargs):
        if can_view_employee_directory(request.user):
            return super().dispatch(request, *args, **kwargs)

        if is_supervisor_user(request.user):
            messages.error(
                request,
                "Supervisor access requires linking this login account to an employee profile with an assigned branch.",
            )
            return redirect("dashboard_home")

        linked_employee = get_user_employee_profile(request.user)
        if linked_employee:
            return redirect("employees:employee_detail", pk=linked_employee.pk)

        raise PermissionDenied("You do not have permission to view the employee directory.")

    def get_queryset(self):
        queryset = get_employee_directory_queryset_for_user(
            self.request.user,
            Employee.objects.select_related(
                "user",
                "company",
                "department",
                "branch",
                "section",
                "job_title",
            ).order_by("employee_id", "full_name"),
        )

        search = self.request.GET.get("search", "").strip()
        company_id = self.request.GET.get("company", "").strip()
        department_id = self.request.GET.get("department", "").strip()
        branch_id = self.request.GET.get("branch", "").strip()
        section_id = self.request.GET.get("section", "").strip()
        job_title_id = self.request.GET.get("job_title", "").strip()
        status = self.request.GET.get("status", "").strip()

        if search:
            queryset = queryset.filter(
                Q(full_name__icontains=search)
                | Q(employee_id__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
            )

        if company_id:
            queryset = queryset.filter(company_id=company_id)

        if department_id:
            queryset = queryset.filter(department_id=department_id)

        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)

        if section_id:
            queryset = queryset.filter(section_id=section_id)

        if job_title_id:
            queryset = queryset.filter(job_title_id=job_title_id)

        if status == "active":
            queryset = queryset.filter(is_active=True)
        elif status == "inactive":
            queryset = queryset.filter(is_active=False)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        filtered_queryset = self.get_queryset()
        overall_queryset = Employee.objects.all()

        context["search_value"] = self.request.GET.get("search", "").strip()
        context["selected_company"] = self.request.GET.get("company", "").strip()
        context["selected_department"] = self.request.GET.get("department", "").strip()
        context["selected_branch"] = self.request.GET.get("branch", "").strip()
        context["selected_section"] = self.request.GET.get("section", "").strip()
        context["selected_job_title"] = self.request.GET.get("job_title", "").strip()
        context["selected_status"] = self.request.GET.get("status", "").strip()

        scoped_branch = get_user_scope_branch(self.request.user)
        if is_branch_scoped_supervisor(self.request.user) and scoped_branch:
            context["companies"] = Company.objects.filter(id=scoped_branch.company_id, is_active=True).order_by("name")
            context["departments"] = (
                Department.objects.filter(company_id=scoped_branch.company_id, is_active=True)
                .select_related("company")
                .order_by("company__name", "name")
            )
            context["branches"] = (
                Branch.objects.filter(id=scoped_branch.id, is_active=True)
                .select_related("company")
                .order_by("company__name", "name")
            )
            context["sections"] = (
                Section.objects.filter(department__company_id=scoped_branch.company_id, is_active=True)
                .select_related("department", "department__company")
                .order_by("department__company__name", "department__name", "name")
            )
            context["job_titles"] = (
                JobTitle.objects.filter(department__company_id=scoped_branch.company_id, is_active=True)
                .select_related("department", "department__company", "section")
                .order_by("department__company__name", "department__name", "name")
            )
        else:
            context["companies"] = Company.objects.filter(is_active=True).order_by("name")
            context["departments"] = (
                Department.objects.filter(is_active=True)
                .select_related("company")
                .order_by("company__name", "name")
            )
            context["branches"] = (
                Branch.objects.filter(is_active=True)
                .select_related("company")
                .order_by("company__name", "name")
            )
            context["sections"] = (
                Section.objects.filter(is_active=True)
                .select_related("department", "department__company")
                .order_by("department__company__name", "department__name", "name")
            )
            context["job_titles"] = (
                JobTitle.objects.filter(is_active=True)
                .select_related("department", "department__company", "section")
                .order_by("department__company__name", "department__name", "name")
            )
        context["employment_status_choices"] = Employee.EMPLOYMENT_STATUS_CHOICES

        context["filtered_total"] = filtered_queryset.count()
        context["filtered_active"] = filtered_queryset.filter(is_active=True).count()
        context["filtered_inactive"] = filtered_queryset.filter(is_active=False).count()
        context["overall_total"] = overall_queryset.count()
        context["can_manage_employees"] = can_create_or_edit_employees(self.request.user)
        context["can_edit_employee_records"] = can_create_or_edit_employees(self.request.user)
        context["can_delete_employee_records"] = can_delete_employee(self.request.user)
        context["is_branch_scoped_supervisor"] = is_branch_scoped_supervisor(self.request.user)
        context["scoped_branch"] = get_user_scope_branch(self.request.user)

        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        context["pagination_querystring"] = query_params.urlencode()

        page_obj = context.get("page_obj")
        if page_obj:
            paginator = page_obj.paginator
            current_page = page_obj.number
            total_pages = paginator.num_pages
            page_numbers = {1, total_pages}

            for page_number in range(current_page - 1, current_page + 2):
                if 1 <= page_number <= total_pages:
                    page_numbers.add(page_number)

            sorted_pages = sorted(page_numbers)
            pagination_items = []
            previous_page = None

            for page_number in sorted_pages:
                if previous_page is not None and page_number - previous_page > 1:
                    pagination_items.append({"type": "ellipsis"})
                pagination_items.append(
                    {
                        "type": "page",
                        "number": page_number,
                        "is_current": page_number == current_page,
                    }
                )
                previous_page = page_number

            context["pagination_items"] = pagination_items

        return context


def get_department_manager_employee(employee):
    if not employee or not employee.department_id:
        return None

    return (
        Employee.objects.select_related("job_title", "branch", "department", "section", "company")
        .filter(department_id=employee.department_id, is_active=True, job_title__isnull=False)
        .filter(job_title__name__iregex=r"(?i)manager")
        .exclude(pk=getattr(employee, "pk", None))
        .order_by("full_name")
        .first()
    )


def get_department_manager_display(employee):
    manager_employee = get_department_manager_employee(employee)
    if manager_employee:
        return manager_employee.full_name

    department = getattr(employee, "department", None)
    manager_name = getattr(department, "manager_name", "") or ""
    return manager_name.strip()


def get_branch_supervisor_display(employee):
    supervisor_employee = get_employee_supervisor(employee)
    if supervisor_employee:
        return supervisor_employee.full_name

    section = getattr(employee, "section", None)
    supervisor_name = getattr(section, "supervisor_name", "") or ""
    return supervisor_name.strip()


def get_team_leader_display(employee):
    team_leader_employee = get_employee_team_leader(employee)
    if team_leader_employee:
        return team_leader_employee.full_name
    return ""


def get_employee_supervisor(employee):
    if not employee.branch_id:
        return None

    return (
        Employee.objects.select_related("job_title", "branch", "department", "section", "company")
        .filter(branch_id=employee.branch_id, is_active=True, job_title__isnull=False)
        .filter(job_title__name__iregex=r"(?i)supervisor")
        .exclude(pk=employee.pk)
        .order_by("full_name")
        .first()
    )




def get_short_structure_label(value):
    if value in [None, ""]:
        return "—"

    if hasattr(value, "name"):
        display_value = (getattr(value, "name", "") or "").strip()
    else:
        display_value = str(value).strip()

    if not display_value:
        return "—"

    parts = [part.strip() for part in re.split(r"\s*-\s*", display_value) if part.strip()]
    if len(parts) > 1:
        return parts[-1]

    if hasattr(value, "department") and getattr(value, "department", None):
        department_name = (getattr(value.department, "name", "") or "").strip()
        if department_name:
            lowered_display = display_value.lower()
            lowered_department = department_name.lower()

            if lowered_display.startswith(lowered_department + " "):
                shortened_value = display_value[len(department_name):].strip()
                if shortened_value:
                    return shortened_value

            if lowered_display.startswith(lowered_department + "-"):
                shortened_value = display_value[len(department_name):].lstrip("-").strip()
                if shortened_value:
                    return shortened_value

    return display_value

def get_employee_team_leader(employee):
    if not employee or not employee.branch_id:
        return None

    leadership_queryset = Employee.objects.select_related(
        "job_title",
        "branch",
        "department",
        "section",
        "company",
    ).filter(
        branch_id=employee.branch_id,
        is_active=True,
        job_title__isnull=False,
    ).filter(
        Q(job_title__name__iregex=r"(?i)team\s*leader")
        | Q(job_title__name__iregex=r"(?i)leader")
    )

    if employee.section_id:
        same_section_team_leader = (
            leadership_queryset
            .filter(section_id=employee.section_id)
            .order_by(
                Case(
                    When(pk=employee.pk, then=0),
                    default=1,
                    output_field=IntegerField(),
                ),
                "full_name",
            )
            .first()
        )
        if same_section_team_leader:
            return same_section_team_leader

    return leadership_queryset.order_by(
        Case(
            When(pk=employee.pk, then=0),
            default=1,
            output_field=IntegerField(),
        ),
        "full_name",
    ).first()


def build_branch_team_structure(employee):
    if not employee.branch_id:
        return {"branch_team_members": [], "branch_team_groups": [], "branch_team_total": 0}

    branch_team_queryset = (
        Employee.objects.select_related("job_title", "branch", "department", "section", "company")
        .filter(branch_id=employee.branch_id, is_active=True)
        .order_by("full_name")
    )
    branch_team_members = list(branch_team_queryset)

    leadership_patterns = [
        ("Supervisor", [r"(?i)supervisor"]),
        ("Team Leader", [r"(?i)team\s*leader", r"(?i)leader"]),
        ("Team Members", []),
    ]

    grouped = []
    used_ids = set()

    for label, patterns in leadership_patterns:
        if patterns:
            members = []
            for member in branch_team_members:
                job_title_name = (member.job_title.name if member.job_title else "") or ""
                if any(re.search(pattern, job_title_name) for pattern in patterns):
                    members.append(member)
                    used_ids.add(member.pk)
        else:
            members = [member for member in branch_team_members if member.pk not in used_ids]

        if members:
            grouped.append({"label": label, "members": members})

    return {
        "branch_team_members": branch_team_members,
        "branch_team_groups": grouped,
        "branch_team_total": len(branch_team_members),
    }


FREE_SCHEDULE_GRID_COLUMN_COUNT = 10
FREE_SCHEDULE_GRID_DAY_THEMES = {
    1: "sunday",
    2: "monday",
    3: "tuesday",
    4: "wednesday",
    5: "thursday",
    6: "friday",
    7: "saturday",
    8: "notes",
    9: "orders",
    10: "followup",
}
FREE_SCHEDULE_SHIFT_OPTIONS = [
    "",
    "9 am to 5 pm",
    "2 pm to 10 pm",
    "3 pm to 11 pm",
    "Off",
    "Extra Off",
    "Morning",
    "Evening",
    "Split Shift",
]


def build_branch_schedule_free_grid(branch):
    if not branch:
        return {
            "free_grid_columns": [],
            "free_grid_headers": [],
            "free_grid_rows": [],
            "free_grid_filled_cells": 0,
        }

    team_members = list(Employee.objects.select_related("job_title").filter(branch=branch, is_active=True).order_by("full_name", "employee_id"))
    employee_options = [
        {
            "id": member.id,
            "label": member.full_name,
            "job_title": getattr(getattr(member, "job_title", None), "name", "") or "",
        }
        for member in team_members
    ]
    employee_map = {member.id: member for member in team_members}
    row_total = len(team_members)
    existing_rows = {
        row.row_index: row
        for row in BranchScheduleGridRow.objects.select_related("employee", "employee__job_title").filter(
            branch=branch,
            row_index__lte=max(row_total, 1),
        )
    }
    existing_headers = {
        header.column_index: header.label
        for header in BranchScheduleGridHeader.objects.filter(branch=branch)
    }
    existing_cells = {
        (cell.row_index, cell.column_index): cell.value
        for cell in BranchScheduleGridCell.objects.filter(branch=branch, row_index__lte=max(row_total, 1))
    }
    columns = [
        {
            "index": index,
            "label": f"Column {index}",
            "theme": FREE_SCHEDULE_GRID_DAY_THEMES.get(index, "generic"),
        }
        for index in range(1, FREE_SCHEDULE_GRID_COLUMN_COUNT + 1)
    ]
    free_grid_headers = [
        {
            "column_index": 0,
            "input_name": "header_0",
            "value": existing_headers.get(0, FREE_SCHEDULE_GRID_DEFAULT_HEADERS[0]),
            "default_label": FREE_SCHEDULE_GRID_DEFAULT_HEADERS[0],
        },
        {
            "column_index": 1,
            "input_name": "header_1",
            "value": existing_headers.get(1, FREE_SCHEDULE_GRID_DEFAULT_HEADERS[1]),
            "default_label": FREE_SCHEDULE_GRID_DEFAULT_HEADERS[1],
        },
    ] + [
        {
            "column_index": column["index"] + 1,
            "input_name": f"header_{column['index'] + 1}",
            "value": existing_headers.get(
                column["index"] + 1,
                FREE_SCHEDULE_GRID_DEFAULT_HEADERS.get(column["index"] + 1, column["label"]),
            ),
            "default_label": FREE_SCHEDULE_GRID_DEFAULT_HEADERS.get(column["index"] + 1, column["label"]),
            "theme": column["theme"],
        }
        for column in columns
    ]
    roster_day_columns = [column for column in columns if column["theme"] in {
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    }]
    roster_extra_columns = [column for column in columns if column["theme"] not in {
        "sunday",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
    }]
    rows = []
    filled_cells = 0

    for row_index in range(1, row_total + 1):
        assigned_row = existing_rows.get(row_index)
        assigned_employee = getattr(assigned_row, "employee", None)
        cells = []
        for column in columns:
            cell_value = existing_cells.get((row_index, column["index"]), "")
            if cell_value:
                filled_cells += 1
            cells.append(
                {
                    "column_index": column["index"],
                    "value": cell_value,
                    "input_name": f"grid_{row_index}_{column['index']}",
                    "row_index": row_index,
                    "theme": column["theme"],
                }
            )

        rows.append(
            {
                "row_index": row_index,
                "employee": assigned_employee,
                "employee_select_name": f"row_employee_{row_index}",
                "employee_job_title": getattr(getattr(assigned_employee, "job_title", None), "name", "") or "",
                "employee_options": employee_options,
                "cells": cells,
            }
        )

    return {
        "free_grid_columns": columns,
        "free_grid_headers": free_grid_headers,
        "free_grid_rows": rows,
        "free_grid_filled_cells": filled_cells,
        "free_grid_row_total": row_total,
        "free_grid_employee_map": employee_map,
        "roster_day_columns": roster_day_columns,
        "roster_extra_columns": roster_extra_columns,
        "free_grid_shift_options": FREE_SCHEDULE_SHIFT_OPTIONS,
    }


def build_schedule_week_days(week_start):
    if not week_start:
        return []
    return [week_start + timedelta(days=index) for index in range(7)]


def get_pending_off_days_for_week(employee, week_start, week_end, pending_off_map=None):
    if not employee or not week_start or not week_end:
        return 0

    if pending_off_map and employee.id in pending_off_map:
        return pending_off_map[employee.id]

    pending_leave_records = employee.leave_records.filter(
        status=EmployeeLeave.STATUS_PENDING,
        start_date__lte=week_end,
        end_date__gte=week_start,
    )
    total_pending_days = 0

    for leave_record in pending_leave_records:
        overlap_start = max(week_start, leave_record.start_date)
        overlap_end = min(week_end, leave_record.end_date)
        if overlap_start <= overlap_end:
            total_pending_days += count_policy_working_days(overlap_start, overlap_end)

    return total_pending_days


def build_branch_weekly_schedule_summary(branch, week_start):
    if not branch or not week_start:
        return {
            "team_members": [],
            "team_schedule_rows": [],
            "schedule_entries": [],
            "week_days": [],
            "schedule_total": 0,
            "completed_total": 0,
            "in_progress_total": 0,
            "planned_total": 0,
            "on_hold_total": 0,
        }

    week_end = week_start + timedelta(days=6)
    team_members = list(
        Employee.objects.select_related("job_title", "section")
        .filter(branch=branch, is_active=True)
        .order_by("full_name", "employee_id")
    )
    row_order_map = {
        row.employee_id: row.row_index
        for row in BranchScheduleGridRow.objects.filter(branch=branch, employee__isnull=False).select_related("employee")
    }
    team_members.sort(
        key=lambda member: (
            row_order_map.get(member.id, 9999),
            member.full_name.lower(),
            member.employee_id.lower(),
        )
    )
    week_days = build_schedule_week_days(week_start)
    schedule_entries = list(
        BranchWeeklyScheduleEntry.objects.select_related(
            "employee",
            "employee__job_title",
            "employee__section",
            "duty_option",
        )
        .filter(branch=branch, week_start=week_start)
        .order_by("schedule_date", "employee__full_name", "id")
    )
    pending_off_map = {
        record.employee_id: record.pending_off_count
        for record in BranchWeeklyPendingOff.objects.filter(branch=branch, week_start=week_start)
    }

    entries_by_employee_and_date = {}
    for entry in schedule_entries:
        entries_by_employee_and_date[(entry.employee_id, entry.schedule_date)] = entry

    team_schedule_rows = []
    for member in team_members:
        row_cells = []
        member_entries = []
        for current_date in week_days:
            current_entry = entries_by_employee_and_date.get((member.id, current_date))
            row_cells.append(
                {
                    "date": current_date,
                    "entry": current_entry,
                    "has_entry": current_entry is not None,
                    "edit_url": f"{reverse('employees:self_service_weekly_schedule')}?week={week_start.isoformat()}&employee={member.id}&day={current_date.isoformat()}",
                }
            )
            if current_entry is not None:
                member_entries.append(current_entry)

        team_schedule_rows.append(
            {
                "employee": member,
                "entries": member_entries,
                "cells": row_cells,
                "entry_total": len(member_entries),
                "pending_off_total": get_pending_off_days_for_week(
                    member,
                    week_start,
                    week_end,
                    pending_off_map=pending_off_map,
                ),
                "completed_total": sum(
                    1 for entry in member_entries if entry.status == BranchWeeklyScheduleEntry.STATUS_COMPLETED
                ),
                "pending_total": sum(
                    1
                    for entry in member_entries
                    if entry.status in {
                        BranchWeeklyScheduleEntry.STATUS_PLANNED,
                        BranchWeeklyScheduleEntry.STATUS_IN_PROGRESS,
                        BranchWeeklyScheduleEntry.STATUS_ON_HOLD,
                    }
                ),
            }
        )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "team_members": team_members,
        "team_schedule_rows": team_schedule_rows,
        "schedule_entries": schedule_entries,
        "week_days": week_days,
        "schedule_total": len(schedule_entries),
        "completed_total": sum(
            1 for entry in schedule_entries if entry.status == BranchWeeklyScheduleEntry.STATUS_COMPLETED
        ),
        "in_progress_total": sum(
            1 for entry in schedule_entries if entry.status == BranchWeeklyScheduleEntry.STATUS_IN_PROGRESS
        ),
        "planned_total": sum(
            1 for entry in schedule_entries if entry.status == BranchWeeklyScheduleEntry.STATUS_PLANNED
        ),
        "on_hold_total": sum(
            1 for entry in schedule_entries if entry.status == BranchWeeklyScheduleEntry.STATUS_ON_HOLD
        ),
    }


SCHEDULE_IMPORT_COLUMNS = [
    "employee_id",
    "employee_name",
    "schedule_date",
    "duty_label",
    "custom_label",
    "shift_label",
    "start_time",
    "end_time",
    "status",
    "order_note",
]

SCHEDULE_IMPORT_HEADER_ALIASES = {
    "employee code": "employee_id",
    "employee_code": "employee_id",
    "employee id": "employee_id",
    "employee": "employee_name",
    "employee name": "employee_name",
    "date": "schedule_date",
    "duty": "duty_label",
    "duty option": "duty_label",
    "duty_option": "duty_label",
    "shift": "shift_label",
    "shift label": "shift_label",
    "shift_label": "shift_label",
    "custom duty": "custom_label",
    "custom_label": "custom_label",
    "start": "start_time",
    "start time": "start_time",
    "start_time": "start_time",
    "end": "end_time",
    "end time": "end_time",
    "end_time": "end_time",
    "note": "order_note",
    "notes": "order_note",
    "order": "order_note",
    "order note": "order_note",
    "order_note": "order_note",
    "pending off": "pending_off",
    "pending_off": "pending_off",
}

SCHEDULE_WEEKDAY_NAMES = [
    "sunday",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
]


def normalize_schedule_import_header(value):
    cleaned = ((value or "").strip().lower()).replace("-", " ").replace("/", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return SCHEDULE_IMPORT_HEADER_ALIASES.get(cleaned, cleaned.replace(" ", "_"))


def parse_schedule_import_date(value):
    if value in [None, ""]:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    formats = ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%m/%d/%Y")
    for pattern in formats:
        try:
            return timezone.datetime.strptime(text, pattern).date()
        except ValueError:
            continue

    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_schedule_import_time(value):
    if value in [None, ""]:
        return None
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return value

    text = str(value).strip()
    if not text:
        return None

    for pattern in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return timezone.datetime.strptime(text, pattern).time()
        except ValueError:
            continue
    return None


def infer_shift_times_from_label(label):
    text = (label or "").strip()
    if not text:
        return None, None

    range_match = re.match(r"^\s*(.+?)\s+to\s+(.+?)\s*$", text, flags=re.IGNORECASE)
    if not range_match:
        return None, None

    start_time = parse_schedule_import_time(range_match.group(1))
    end_time = parse_schedule_import_time(range_match.group(2))
    return start_time, end_time


def get_schedule_import_raw_rows(uploaded_file):
    filename = (uploaded_file.name or "").lower()

    if filename.endswith(".csv"):
        decoded = uploaded_file.read().decode("utf-8-sig")
        return list(csv.reader(io.StringIO(decoded)))

    workbook = load_workbook(uploaded_file, data_only=True)
    worksheet = workbook.active
    return list(worksheet.iter_rows(values_only=True))


def is_branch_schedule_matrix_format(raw_rows):
    if len(raw_rows) < 2:
        return False

    header_row = [normalize_schedule_import_header(value) for value in raw_rows[0]]
    weekday_hits = sum(1 for value in header_row if value in SCHEDULE_WEEKDAY_NAMES)
    return "employee_id" in header_row and weekday_hits >= 5


def build_schedule_import_rows_from_matrix(raw_rows):
    header_row = list(raw_rows[0])
    date_row = list(raw_rows[1]) if len(raw_rows) > 1 else []
    normalized_headers = [normalize_schedule_import_header(value) for value in header_row]

    employee_id_index = normalized_headers.index("employee_id")
    pending_off_index = normalized_headers.index("pending_off") if "pending_off" in normalized_headers else -1
    employee_name_index = -1
    weekday_column_map = {}

    for index, header in enumerate(normalized_headers):
        if header in SCHEDULE_WEEKDAY_NAMES:
            weekday_column_map[index] = header

    for index, header in enumerate(normalized_headers):
        if index in weekday_column_map or index == employee_id_index or index == pending_off_index:
            continue
        header_text = str(header_row[index] or "").strip()
        if header_text:
            employee_name_index = index
            break

    rows = []
    for raw_row in raw_rows[2:]:
        if not raw_row:
            continue

        employee_id_value = str(raw_row[employee_id_index] or "").strip() if employee_id_index < len(raw_row) else ""
        employee_name_value = str(raw_row[employee_name_index] or "").strip() if employee_name_index >= 0 and employee_name_index < len(raw_row) else ""
        pending_off_value = str(raw_row[pending_off_index] or "").strip() if pending_off_index >= 0 and pending_off_index < len(raw_row) else ""

        if not employee_id_value and not employee_name_value:
            continue

        for column_index, weekday_name in weekday_column_map.items():
            schedule_date = parse_schedule_import_date(date_row[column_index] if column_index < len(date_row) else None)
            duty_value = str(raw_row[column_index] or "").strip() if column_index < len(raw_row) else ""
            if not schedule_date and not duty_value:
                continue

            rows.append(
                {
                    "employee_id": employee_id_value,
                    "employee_name": employee_name_value,
                    "schedule_date": schedule_date,
                    "duty_label": duty_value,
                    "custom_label": "",
                    "shift_label": duty_value,
                    "start_time": "",
                    "end_time": "",
                    "status": BranchWeeklyScheduleEntry.STATUS_PLANNED,
                    "order_note": "",
                    "pending_off": pending_off_value,
                    "weekday_name": weekday_name,
                }
            )

    return rows


def get_schedule_import_rows(uploaded_file):
    raw_rows = get_schedule_import_raw_rows(uploaded_file)
    if not raw_rows:
        return []

    if is_branch_schedule_matrix_format(raw_rows):
        return build_schedule_import_rows_from_matrix(raw_rows)

    headers = [normalize_schedule_import_header(value) for value in raw_rows[0]]
    rows = []
    for raw_row in raw_rows[1:]:
        row = {}
        for index, header in enumerate(headers):
            if not header:
                continue
            row[header] = raw_row[index] if index < len(raw_row) else ""
        rows.append(row)
    return rows


def get_or_create_branch_duty_option_for_import(branch, row, duty_option_map):
    duty_label = str(row.get("duty_label") or row.get("shift_label") or row.get("custom_label") or "").strip()
    if not duty_label:
        return None

    key = duty_label.lower()
    existing_option = duty_option_map.get(key)
    if existing_option:
        return existing_option

    start_time = parse_schedule_import_time(row.get("start_time"))
    end_time = parse_schedule_import_time(row.get("end_time"))
    if not (start_time and end_time):
        inferred_start_time, inferred_end_time = infer_shift_times_from_label(duty_label)
        start_time = start_time or inferred_start_time
        end_time = end_time or inferred_end_time
    lowered = duty_label.lower()

    if lowered in {"off", "day off"}:
        duty_type = BranchWeeklyScheduleEntry.DUTY_TYPE_OFF
        start_time = None
        end_time = None
    elif lowered in {"extra off", "extra_off"}:
        duty_type = BranchWeeklyScheduleEntry.DUTY_TYPE_EXTRA_OFF
        start_time = None
        end_time = None
    elif start_time and end_time:
        duty_type = BranchWeeklyScheduleEntry.DUTY_TYPE_SHIFT
    else:
        duty_type = BranchWeeklyScheduleEntry.DUTY_TYPE_CUSTOM
        start_time = None
        end_time = None

    created_option = BranchWeeklyDutyOption.objects.create(
        branch=branch,
        label=duty_label,
        duty_type=duty_type,
        default_start_time=start_time,
        default_end_time=end_time,
        display_order=BranchWeeklyDutyOption.objects.filter(branch=branch).count() + 1,
        is_active=True,
    )
    duty_option_map[key] = created_option
    return created_option


def import_branch_weekly_schedule_file(*, branch, week_start, uploaded_file, actor_label="", replace_existing=False):
    week_end = week_start + timedelta(days=6)
    team_members = list(Employee.objects.filter(branch=branch, is_active=True).order_by("full_name", "employee_id"))
    employee_map = {member.employee_id.strip().lower(): member for member in team_members if member.employee_id}
    duty_option_map = {
        option.label.strip().lower(): option
        for option in BranchWeeklyDutyOption.objects.filter(branch=branch)
    }
    pending_off_updates = {}

    rows = get_schedule_import_rows(uploaded_file)
    imported_count = 0
    errors = []
    skipped_empty_cells = 0
    changed_employee_ids = set()

    if replace_existing:
        changed_employee_ids.update(
            BranchWeeklyScheduleEntry.objects.filter(branch=branch, week_start=week_start).values_list("employee_id", flat=True)
        )
        BranchWeeklyScheduleEntry.objects.filter(branch=branch, week_start=week_start).delete()
        BranchWeeklyPendingOff.objects.filter(branch=branch, week_start=week_start).delete()

    for row_number, row in enumerate(rows, start=2):
        employee_id_value = str(row.get("employee_id") or "").strip().lower()
        schedule_date = parse_schedule_import_date(row.get("schedule_date"))

        if not employee_id_value and not schedule_date:
            continue

        employee = employee_map.get(employee_id_value)
        if not employee:
            errors.append(f"Row {row_number}: employee_id '{row.get('employee_id')}' was not found in this branch.")
            continue

        pending_off_value = str(row.get("pending_off") or "").strip()
        if pending_off_value.isdigit():
            pending_off_updates[employee.id] = int(pending_off_value)

        if not schedule_date:
            errors.append(f"Row {row_number}: schedule_date is missing or invalid.")
            continue

        if schedule_date < week_start or schedule_date > week_end:
            errors.append(f"Row {row_number}: schedule_date {schedule_date} is outside the selected week.")
            continue

        duty_label = str(row.get("duty_label") or row.get("shift_label") or row.get("custom_label") or "").strip()
        if not duty_label:
            skipped_empty_cells += 1
            continue

        duty_option = get_or_create_branch_duty_option_for_import(branch, row, duty_option_map)
        if not duty_option:
            errors.append(f"Row {row_number}: duty_label or shift_label is required.")
            continue

        status_value = str(row.get("status") or "").strip().lower() or BranchWeeklyScheduleEntry.STATUS_PLANNED
        valid_statuses = {choice[0] for choice in BranchWeeklyScheduleEntry.STATUS_CHOICES}
        if status_value not in valid_statuses:
            status_value = BranchWeeklyScheduleEntry.STATUS_PLANNED

        BranchWeeklyScheduleEntry.objects.update_or_create(
            branch=branch,
            employee=employee,
            schedule_date=schedule_date,
            defaults={
                "week_start": week_start,
                "duty_option": duty_option,
                "title": str(row.get("custom_label") or "").strip(),
                "order_note": str(row.get("order_note") or "").strip(),
                "status": status_value,
                "created_by": actor_label,
                "updated_by": actor_label,
            },
        )
        changed_employee_ids.add(employee.id)
        imported_count += 1

    for employee_id, pending_off_count in pending_off_updates.items():
        BranchWeeklyPendingOff.objects.update_or_create(
            branch=branch,
            employee_id=employee_id,
            week_start=week_start,
            defaults={
                "pending_off_count": pending_off_count,
                "created_by": actor_label,
                "updated_by": actor_label,
            },
        )
        changed_employee_ids.add(employee_id)

    return {
        "imported_count": imported_count,
        "errors": errors,
        "parsed_row_count": len(rows),
        "skipped_empty_cells": skipped_empty_cells,
        "replace_existing": replace_existing,
        "changed_employee_ids": sorted(changed_employee_ids),
    }


def build_branch_schedule_export_workbook(branch, week_start, *, include_existing_entries=True):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Branch Schedule"

    team_members = list(
        Employee.objects.select_related("job_title")
        .filter(branch=branch, is_active=True)
        .order_by("full_name", "employee_id")
    )
    entry_map = {}
    if include_existing_entries:
        entry_map = {
            (entry.employee_id, entry.schedule_date): entry
            for entry in BranchWeeklyScheduleEntry.objects.select_related("duty_option").filter(
                branch=branch,
                week_start=week_start,
            )
        }
    pending_off_map = {
        record.employee_id: record.pending_off_count
        for record in BranchWeeklyPendingOff.objects.filter(branch=branch, week_start=week_start)
    }

    week_days = build_schedule_week_days(week_start)
    header_row = [
        week_start.strftime("%B"),
        "Employee Code",
        branch.name,
        "Pending off",
    ] + [day.strftime("%A") for day in week_days]
    date_row = ["", "", "", ""] + [f"{day.day}-{day.strftime('%b-%Y')}" if hasattr(day, "strftime") else "" for day in week_days]

    worksheet.append(header_row)
    worksheet.append(date_row)

    for member in team_members:
        row_values = [
            "",
            member.employee_id,
            member.full_name,
            pending_off_map.get(member.id, 0),
        ]
        for schedule_date in week_days:
            entry = entry_map.get((member.id, schedule_date))
            if entry:
                row_values.append(entry.sheet_value)
            else:
                row_values.append("")
        worksheet.append(row_values)

    instructions = workbook.create_sheet("Instructions")
    instructions.append(["Section", "Meaning"])
    instructions.append(["Row 1", "Main roster header. Keep weekday columns in the same order."])
    instructions.append(["Row 2", "Date row. Keep dates inside the selected branch week."])
    instructions.append(["Employee Code", "Required. Must match a branch employee code in the app."])
    instructions.append([branch.name, "Employee name column for visual use."])
    instructions.append(["Pending off", "Optional number for pending off days in that week."])
    instructions.append(["Day cells", "Use values like 2 pm to 10 pm, 9 am to 5 pm, off, extra off, or any custom duty label."])
    instructions.append(["Import result", "The app stores imported values in BranchWeeklyScheduleEntry and BranchWeeklyPendingOff."])
    return workbook




DOCUMENT_GROUP_LABELS = {
    "passport": "Passport",
    "civil_id": "Civil ID",
    "leave": "Leave Documents",
    "cv": "CV / Resume",
    "warning": "Warnings / Disciplinary",
    "resignation": "Resignations",
    "clearance": "Clearance",
    "transfer": "Transfers / Placement Change",
    "contract": "Contracts",
    "medical": "Medical",
    "payroll": "Payroll",
    "certificate": "Certificates",
    "other": "Other Documents",
}


def normalize_document_text(document):
    parts = [
        getattr(document, "title", "") or "",
        getattr(document, "description", "") or "",
        getattr(document, "reference_number", "") or "",
        getattr(document, "filename", "") or "",
        getattr(document, "get_document_type_display", lambda: "")() or "",
    ]
    return " ".join(parts).strip().lower()


def classify_employee_document(document):
    text = normalize_document_text(document)

    if "passport" in text:
        return "passport"
    if "civil id" in text or "civilid" in text or "civil-id" in text or re.search(r"\bcivil\b", text):
        return "civil_id"
    if getattr(document, "linked_leave_id", None):
        return "leave"
    if "resume" in text or re.search(r"\bcv\b", text):
        return "cv"
    if "warning" in text or "disciplinary" in text or "memo" in text:
        return "warning"
    if "resignation" in text or "termination" in text:
        return "resignation"
    if "clearance" in text:
        return "clearance"
    if "transfer" in text or "placement" in text or "movement" in text:
        return "transfer"
    if document.document_type == EmployeeDocument.DOCUMENT_TYPE_CONTRACT:
        return "contract"
    if document.document_type == EmployeeDocument.DOCUMENT_TYPE_MEDICAL:
        return "medical"
    if document.document_type == EmployeeDocument.DOCUMENT_TYPE_PAYROLL:
        return "payroll"
    if document.document_type == EmployeeDocument.DOCUMENT_TYPE_CERTIFICATE:
        return "certificate"
    return "other"


def build_identity_document_statuses(employee):
    all_documents = list(employee.documents.all())
    statuses = []
    today = timezone.localdate()
    direct_field_map = {
        "passport": ("passport_issue_date", "passport_expiry_date"),
        "civil_id": ("civil_id_issue_date", "civil_id_expiry_date"),
    }

    for key, label in [("passport", "Passport"), ("civil_id", "Civil ID")]:
        matching_documents = [document for document in all_documents if classify_employee_document(document) == key]
        preferred_documents = sorted(
            matching_documents,
            key=lambda document: (
                0 if document.expiry_date else 1,
                -(document.uploaded_at.timestamp() if getattr(document, "uploaded_at", None) else 0),
                -document.pk,
            ),
        )
        selected_document = preferred_documents[0] if preferred_documents else None

        issue_attr, expiry_attr = direct_field_map[key]
        direct_issue_date = getattr(employee, issue_attr, None)
        direct_expiry_date = getattr(employee, expiry_attr, None)

        reference_attr_map = {
            "passport": "passport_reference_number",
            "civil_id": "civil_id_reference_number",
        }
        direct_reference_number = getattr(employee, reference_attr_map.get(key, ""), "") or ""

        issue_date = direct_issue_date or (selected_document.issue_date if selected_document else None)
        expiry_date = direct_expiry_date or (selected_document.expiry_date if selected_document else None)
        reference_number = direct_reference_number or (selected_document.reference_number if selected_document else "")

        if expiry_date:
            days_until_expiry = (expiry_date - today).days
            if days_until_expiry < 0:
                state_key = "expired"
                status_label = "Expired"
                badge_class = "badge-danger"
                days_display = f"{abs(days_until_expiry)} day(s) overdue"
            elif days_until_expiry <= 30:
                state_key = "expiring_soon"
                status_label = "Expiring Soon"
                badge_class = "badge-primary"
                days_display = f"{days_until_expiry} day(s) remaining"
            else:
                state_key = "valid"
                status_label = "Valid"
                badge_class = "badge-success"
                days_display = f"{days_until_expiry} day(s) remaining"
        elif issue_date:
            state_key = "missing"
            status_label = "No Expiry Date"
            badge_class = "badge"
            days_display = "No expiry date"
        elif selected_document:
            state_key = "missing"
            status_label = selected_document.compliance_status_label
            badge_class = selected_document.compliance_badge_class
            days_display = "No expiry date"
        else:
            state_key = "missing"
            status_label = "Not Recorded"
            badge_class = "badge"
            days_display = "No record"

        statuses.append(
            {
                "key": key,
                "label": label,
                "document": selected_document,
                "reference_number": reference_number,
                "issue_date": issue_date,
                "expiry_date": expiry_date,
                "status_label": status_label,
                "badge_class": badge_class,
                "days_remaining_display": days_display,
                "state_key": state_key,
            }
        )

    return statuses


def build_document_group_cards(documents):
    grouped_documents = {}

    for document in documents:
        group_key = classify_employee_document(document)
        grouped_documents.setdefault(group_key, []).append(document)

    ordered_cards = []
    ordered_keys = [
        "passport",
        "civil_id",
        "leave",
        "cv",
        "warning",
        "resignation",
        "clearance",
        "transfer",
        "contract",
        "medical",
        "payroll",
        "certificate",
        "other",
    ]

    for group_key in ordered_keys:
        group_documents = grouped_documents.get(group_key, [])
        if not group_documents:
            continue

        ordered_cards.append(
            {
                "key": group_key,
                "label": DOCUMENT_GROUP_LABELS.get(group_key, "Documents"),
                "count": len(group_documents),
                "documents": group_documents,
                "has_expired": any(document.is_expired for document in group_documents),
                "has_expiring_soon": any(document.is_expiring_soon for document in group_documents),
            }
        )

    return ordered_cards


def build_management_document_group_cards(documents, latest_limit=3, expanded_group_keys=None):
    grouped_documents = {}
    expanded_group_keys = set(expanded_group_keys or [])

    for document in documents:
        group_key = classify_employee_document(document)
        grouped_documents.setdefault(group_key, []).append(document)

    ordered_cards = []
    ordered_keys = [
        "passport",
        "civil_id",
        "leave",
        "cv",
        "warning",
        "resignation",
        "clearance",
        "transfer",
        "contract",
        "medical",
        "payroll",
        "certificate",
        "other",
    ]

    for group_key in ordered_keys:
        group_documents = grouped_documents.get(group_key, [])
        if not group_documents:
            continue

        is_expanded = group_key in expanded_group_keys
        visible_documents = group_documents if is_expanded else group_documents[:latest_limit]

        ordered_cards.append(
            {
                "key": group_key,
                "label": DOCUMENT_GROUP_LABELS.get(group_key, "Documents"),
                "count": len(group_documents),
                "documents": visible_documents,
                "hidden_count": 0 if is_expanded else max(len(group_documents) - latest_limit, 0),
                "is_expanded": is_expanded,
                "has_expired": any(document.is_expired for document in group_documents),
                "has_expiring_soon": any(document.is_expiring_soon for document in group_documents),
                "latest_document": group_documents[0],
            }
        )

    return ordered_cards


def get_summary_value(summary, key, default=None):
    if summary is None:
        return default
    if isinstance(summary, dict):
        return summary.get(key, default)
    return getattr(summary, key, default)


def build_employee_detail_tab_url(employee, *, tab="overview", modal="", anchor=""):
    base_url = reverse("employees:employee_detail", kwargs={"pk": employee.pk})
    query_bits = []
    if tab:
        query_bits.append(f"tab={tab}")
    if modal:
        query_bits.append(f"modal={modal}")
    query_string = f"?{'&'.join(query_bits)}" if query_bits else ""
    anchor_string = f"#{anchor}" if anchor else ""
    return f"{base_url}{query_string}{anchor_string}"


def build_employee_360_overview_cards(
    employee,
    attendance_summary,
    working_time_summary,
    identity_document_statuses,
    leave_records,
    required_submission_requests,
    employee_document_requests,
    payroll_profile,
    payroll_lines,
    payroll_obligations,
    action_records,
):
    today = timezone.localdate()
    attendance_total = attendance_summary.get("attendance_total") or 0
    present_total = attendance_summary.get("present_attendance_count") or 0
    attendance_rate = int(round((present_total / attendance_total) * 100)) if attendance_total else 0
    compliance_alert_total = sum(
        1 for status in identity_document_statuses if status["state_key"] in {"expired", "expiring_soon", "missing"}
    )
    overdue_submission_total = sum(1 for item in required_submission_requests if item.is_overdue)
    open_action_total = sum(
        1 for action_record in action_records if action_record.status in {EmployeeActionRecord.STATUS_OPEN, EmployeeActionRecord.STATUS_UNDER_REVIEW}
    )
    active_obligations = [
        obligation for obligation in payroll_obligations if obligation.status == obligation.STATUS_ACTIVE
    ]
    outstanding_obligation_balance = sum(
        (obligation.remaining_balance or Decimal("0.00")) for obligation in active_obligations
    )
    approved_leave_days_year = sum(
        leave_record.total_days
        for leave_record in leave_records
        if leave_record.status == EmployeeLeave.STATUS_APPROVED
        and (
            leave_record.start_date.year == today.year
            or leave_record.end_date.year == today.year
        )
    )
    pending_requests_total = sum(
        1
        for item in employee_document_requests
        if item.status in {EmployeeDocumentRequest.STATUS_REQUESTED, EmployeeDocumentRequest.STATUS_APPROVED}
    )

    return [
        {
            "label": "Service Duration",
            "value": get_summary_value(working_time_summary, "service_duration_display") or "Not set",
            "meta": f"Hired {employee.hire_date:%b %d, %Y}" if employee.hire_date else "Hire date not recorded",
            "tone": "neutral",
        },
        {
            "label": "Attendance Reliability",
            "value": f"{attendance_rate}%",
            "meta": f"{present_total} present day(s) across {attendance_total} attendance record(s)",
            "tone": "good" if attendance_rate >= 90 else "warning" if attendance_rate >= 75 else "danger",
        },
        {
            "label": "Compliance Alerts",
            "value": str(compliance_alert_total + overdue_submission_total),
            "meta": f"{compliance_alert_total} ID alert(s), {overdue_submission_total} overdue submission(s)",
            "tone": "good" if (compliance_alert_total + overdue_submission_total) == 0 else "danger",
        },
        {
            "label": "Payroll Status",
            "value": payroll_profile.get_status_display() if payroll_profile else "Setup Needed",
            "meta": (
                f"Latest net pay {payroll_lines[0].net_pay}" if payroll_lines else
                f"Estimated net {payroll_profile.estimated_net_salary}" if payroll_profile else
                "No payroll lines generated yet"
            ),
            "tone": "good" if payroll_profile and payroll_profile.status == payroll_profile.STATUS_ACTIVE else "warning",
        },
        {
            "label": "Leave This Year",
            "value": str(approved_leave_days_year),
            "meta": f"{sum(1 for item in leave_records if item.status == EmployeeLeave.STATUS_PENDING)} pending request(s) now",
            "tone": "neutral",
        },
        {
            "label": "Open Workforce Items",
            "value": str(open_action_total + pending_requests_total),
            "meta": f"{open_action_total} action item(s), {pending_requests_total} document request(s)",
            "tone": "warning" if (open_action_total + pending_requests_total) else "good",
        },
        {
            "label": "Active Deductions",
            "value": str(len(active_obligations)),
            "meta": f"Outstanding balance {outstanding_obligation_balance}",
            "tone": "warning" if active_obligations else "neutral",
        },
        {
            "label": "Available Annual Leave",
            "value": str(get_summary_value(working_time_summary, "annual_leave_available_after_planning_days", 0) or 0),
            "meta": "Balance after taken and future approved leave",
            "tone": "good",
        },
    ]


def build_employee_360_signal_cards(
    attendance_summary,
    working_time_summary,
    identity_document_statuses,
    leave_records,
    payroll_profile,
    payroll_lines,
    payroll_obligations,
):
    attendance_total = attendance_summary.get("attendance_total") or 0
    present_total = attendance_summary.get("present_attendance_count") or 0
    absence_total = attendance_summary.get("absence_attendance_count") or 0
    attendance_rate = int(round((present_total / attendance_total) * 100)) if attendance_total else 0
    compliance_attention = [
        status for status in identity_document_statuses if status["state_key"] in {"expired", "expiring_soon", "missing"}
    ]
    latest_payroll_line = payroll_lines[0] if payroll_lines else None
    active_obligations = [
        obligation for obligation in payroll_obligations if obligation.status == obligation.STATUS_ACTIVE
    ]
    leave_mix = {
        "annual": get_summary_value(working_time_summary, "annual_leave_days", 0) or 0,
        "sick": get_summary_value(working_time_summary, "sick_leave_days", 0) or 0,
        "unpaid": get_summary_value(working_time_summary, "unpaid_leave_days", 0) or 0,
        "emergency": get_summary_value(working_time_summary, "emergency_leave_days", 0) or 0,
        "other": get_summary_value(working_time_summary, "other_leave_days", 0) or 0,
    }
    dominant_leave_key = max(leave_mix, key=leave_mix.get) if any(leave_mix.values()) else ""
    dominant_leave_label_map = {
        "annual": "Annual leave",
        "sick": "Sick leave",
        "unpaid": "Unpaid leave",
        "emergency": "Emergency leave",
        "other": "Other leave",
    }

    return [
        {
            "title": "Attendance Signal",
            "value": f"{attendance_rate}%",
            "description": (
                f"{present_total} present day(s), {absence_total} absence day(s), "
                f"{attendance_summary.get('total_late_minutes') or 0} late minute(s)."
            ),
            "tone": "good" if attendance_rate >= 90 else "warning" if attendance_rate >= 75 else "danger",
        },
        {
            "title": "Leave Trend",
            "value": str(get_summary_value(working_time_summary, "approved_leave_days", 0) or 0),
            "description": (
                f"Approved leave days total. Strongest pattern: "
                f"{dominant_leave_label_map.get(dominant_leave_key, 'No dominant leave pattern yet')}."
            ),
            "tone": "neutral",
        },
        {
            "title": "Compliance Readiness",
            "value": str(len(compliance_attention)),
            "description": (
                "Passport, Civil ID, and requested submissions are under control."
                if not compliance_attention
                else f"{len(compliance_attention)} identity/compliance alert(s) need follow-up."
            ),
            "tone": "good" if not compliance_attention else "danger",
        },
        {
            "title": "Payroll Stability",
            "value": payroll_profile.get_status_display() if payroll_profile else "Pending",
            "description": (
                f"Latest net pay {latest_payroll_line.net_pay}. {len(active_obligations)} active obligation(s)."
                if latest_payroll_line
                else "Payroll profile is visible, but no payroll line has been generated yet."
                if payroll_profile
                else "Payroll profile setup has not been completed yet."
            ),
            "tone": "good" if payroll_profile and payroll_profile.status == payroll_profile.STATUS_ACTIVE else "warning",
        },
    ]


def build_employee_leave_trend_rows(leave_records):
    leave_type_totals = {
        EmployeeLeave.LEAVE_TYPE_ANNUAL: 0,
        EmployeeLeave.LEAVE_TYPE_SICK: 0,
        EmployeeLeave.LEAVE_TYPE_UNPAID: 0,
        EmployeeLeave.LEAVE_TYPE_EMERGENCY: 0,
        EmployeeLeave.LEAVE_TYPE_OTHER: 0,
    }
    leave_type_labels = dict(EmployeeLeave.LEAVE_TYPE_CHOICES)

    approved_total = 0
    pending_total = 0
    rejected_total = 0
    cancelled_total = 0

    for leave_record in leave_records:
        if leave_record.status == EmployeeLeave.STATUS_APPROVED:
            approved_total += leave_record.total_days
            leave_type_totals[leave_record.leave_type] = leave_type_totals.get(leave_record.leave_type, 0) + leave_record.total_days
        elif leave_record.status == EmployeeLeave.STATUS_PENDING:
            pending_total += leave_record.total_days
        elif leave_record.status == EmployeeLeave.STATUS_REJECTED:
            rejected_total += 1
        elif leave_record.status == EmployeeLeave.STATUS_CANCELLED:
            cancelled_total += 1

    rows = []
    for leave_type, total_days in leave_type_totals.items():
        rows.append(
            {
                "label": leave_type_labels.get(leave_type, leave_type.title()),
                "approved_days": total_days,
                "share": int(round((total_days / approved_total) * 100)) if approved_total else 0,
            }
        )

    return {
        "rows": rows,
        "approved_total": approved_total,
        "pending_total": pending_total,
        "rejected_total": rejected_total,
        "cancelled_total": cancelled_total,
    }


def build_employee_compliance_timeline(identity_document_statuses, documents, required_submission_requests):
    items = []

    for status in identity_document_statuses:
        items.append(
            {
                "title": status["label"],
                "subtitle": status["status_label"],
                "date": status["expiry_date"] or status["issue_date"],
                "date_label": (
                    f"Expiry {status['expiry_date']:%b %d, %Y}" if status["expiry_date"] else
                    f"Issued {status['issue_date']:%b %d, %Y}" if status["issue_date"] else
                    "No date recorded"
                ),
                "description": (
                    f"Reference {status['reference_number']}. {status['days_remaining_display']}"
                    if status["reference_number"] else status["days_remaining_display"]
                ),
                "tone": "good" if status["state_key"] == "valid" else "warning" if status["state_key"] == "expiring_soon" else "danger",
            }
        )

    for document in documents[:6]:
        items.append(
            {
                "title": document.title or document.filename,
                "subtitle": document.get_document_type_display(),
                "date": timezone.localtime(document.uploaded_at).date() if document.uploaded_at else None,
                "date_label": (
                    f"Uploaded {timezone.localtime(document.uploaded_at):%b %d, %Y}"
                    if document.uploaded_at else "Upload date unavailable"
                ),
                "description": document.description or "Document uploaded to employee file.",
                "tone": "danger" if document.is_expired else "warning" if document.is_expiring_soon else "neutral",
            }
        )

    for request_item in required_submission_requests[:6]:
        items.append(
            {
                "title": request_item.title,
                "subtitle": request_item.get_status_display(),
                "date": (
                    request_item.due_date
                    or (request_item.submitted_at.date() if request_item.submitted_at else timezone.localtime(request_item.created_at).date())
                ),
                "date_label": (
                    f"Due {request_item.due_date:%b %d, %Y}" if request_item.due_date else
                    f"Updated {timezone.localtime(request_item.updated_at):%b %d, %Y}"
                ),
                "description": request_item.instructions or "Compliance or file request raised from management workflow.",
                "tone": "danger" if request_item.is_overdue else "warning" if request_item.status != request_item.STATUS_COMPLETED else "good",
            }
        )

    items.sort(key=lambda item: item["date"] or date.min, reverse=True)
    return items[:10]


def build_employee_360_timeline_items(
    history_entries,
    leave_records,
    action_records,
    documents,
    employee_document_requests,
    required_submission_requests,
    payroll_lines,
):
    items = []

    for entry in history_entries:
        items.append(
            {
                "kind": "History",
                "title": entry.title,
                "date": entry.event_date or timezone.localtime(entry.created_at).date(),
                "date_label": (
                    f"{entry.event_date:%b %d, %Y}" if entry.event_date else f"{timezone.localtime(entry.created_at):%b %d, %Y}"
                ),
                "description": entry.description or "Profile event recorded in employee history.",
                "meta": entry.created_by or "System",
                "tone": "neutral",
            }
        )

    for leave_record in leave_records[:8]:
        items.append(
            {
                "kind": "Leave",
                "title": leave_record.get_leave_type_display(),
                "date": leave_record.start_date,
                "date_label": f"{leave_record.start_date:%b %d, %Y} to {leave_record.end_date:%b %d, %Y}",
                "description": leave_record.reason or f"{leave_record.total_days} day(s), status {leave_record.get_status_display().lower()}.",
                "meta": leave_record.get_status_display(),
                "tone": "good" if leave_record.status == leave_record.STATUS_APPROVED else "warning" if leave_record.status == leave_record.STATUS_PENDING else "danger",
            }
        )

    for action_record in action_records[:8]:
        items.append(
            {
                "kind": "Action",
                "title": action_record.title,
                "date": action_record.action_date,
                "date_label": f"{action_record.action_date:%b %d, %Y}",
                "description": action_record.description or action_record.get_action_type_display(),
                "meta": f"{action_record.get_status_display()} • {action_record.get_severity_display()}",
                "tone": "danger" if action_record.severity == action_record.SEVERITY_CRITICAL else "warning",
            }
        )

    for document in documents[:8]:
        items.append(
            {
                "kind": "Document",
                "title": document.title or document.filename,
                "date": timezone.localtime(document.uploaded_at).date() if document.uploaded_at else None,
                "date_label": f"{timezone.localtime(document.uploaded_at):%b %d, %Y}" if document.uploaded_at else "No upload date",
                "description": document.description or document.get_document_type_display(),
                "meta": document.get_document_type_display(),
                "tone": "danger" if document.is_expired else "warning" if document.is_expiring_soon else "neutral",
            }
        )

    for payroll_line in payroll_lines[:6]:
        period = payroll_line.payroll_period
        items.append(
            {
                "kind": "Payroll",
                "title": period.title,
                "date": period.pay_date or period.period_end or period.period_start,
                "date_label": (
                    f"Pay date {period.pay_date:%b %d, %Y}" if period.pay_date else
                    f"Period {period.period_start:%b %d, %Y} to {period.period_end:%b %d, %Y}"
                ),
                "description": f"Net pay {payroll_line.net_pay} from base {payroll_line.base_salary}.",
                "meta": period.get_status_display(),
                "tone": "good" if period.status == period.STATUS_PAID else "warning",
            }
        )

    for document_request in employee_document_requests[:6]:
        request_date = document_request.submitted_at.date() if document_request.submitted_at else timezone.localtime(document_request.created_at).date()
        items.append(
            {
                "kind": "Request",
                "title": document_request.title,
                "date": request_date,
                "date_label": f"{request_date:%b %d, %Y}",
                "description": document_request.request_note or document_request.get_request_type_display(),
                "meta": document_request.get_status_display(),
                "tone": "good" if document_request.status == document_request.STATUS_COMPLETED else "warning" if document_request.status in {document_request.STATUS_REQUESTED, document_request.STATUS_APPROVED} else "danger",
            }
        )

    for submission_request in required_submission_requests[:6]:
        items.append(
            {
                "kind": "Compliance",
                "title": submission_request.title,
                "date": submission_request.due_date or timezone.localtime(submission_request.created_at).date(),
                "date_label": (
                    f"Due {submission_request.due_date:%b %d, %Y}" if submission_request.due_date else
                    f"Created {timezone.localtime(submission_request.created_at):%b %d, %Y}"
                ),
                "description": submission_request.instructions or submission_request.get_request_type_display(),
                "meta": submission_request.get_status_display(),
                "tone": "danger" if submission_request.is_overdue else "warning" if submission_request.status != submission_request.STATUS_COMPLETED else "good",
            }
        )

    items.sort(key=lambda item: item["date"] or date.min, reverse=True)
    return items[:18]


def build_employee_profile_section_actions(employee):
    transfer_url = reverse("employees:employee_transfer", kwargs={"pk": employee.pk})

    return {
        "employee_information": {
            "label": "Edit section",
            "url": build_employee_detail_tab_url(
                employee,
                tab="overview",
                modal="employee_information",
                anchor="employee-information-section",
            ),
            "title": "Edit employee information",
            "modal_target": "employee-information-modal",
        },
        "identity_information": {
            "label": "Edit section",
            "url": build_employee_detail_tab_url(
                employee,
                tab="compliance",
                modal="identity_information",
                anchor="employee-information-section",
            ),
            "title": "Edit passport and civil ID details",
            "modal_target": "identity-information-modal",
        },
        "payroll_information": {
            "label": "Edit payroll",
            "url": build_employee_detail_tab_url(
                employee,
                tab="payroll",
                modal="payroll_information",
                anchor="employee-payroll-section",
            ),
            "title": "Edit payroll profile and salary settings",
            "modal_target": "payroll-information-modal",
        },
        "organization_information": {
            "label": "Edit section",
            "url": f"{transfer_url}#organization-information-section",
            "title": "Edit organization placement",
        },
    }


class EmployeeDetailView(LoginRequiredMixin, DetailView):
    model = Employee
    template_name = "employees/employee_detail.html"
    context_object_name = "employee"

    def dispatch(self, request, *args, **kwargs):
        employee = self.get_object()
        if not can_view_employee_profile(request.user, employee):
            return deny_employee_access(
                request,
                "You do not have permission to view this employee profile.",
                employee=employee,
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        employee = self.object
        current_user = self.request.user

        can_view_directory = can_view_employee_directory(current_user)
        can_manage_employees = can_create_or_edit_employees(current_user)
        can_edit_employee = can_create_or_edit_employees(current_user)
        can_delete_employee_flag = can_delete_employee(current_user)
        can_transfer_employee_flag = can_transfer_employee(current_user)
        can_change_status = can_change_employee_status(current_user)
        can_manage_documents = can_manage_employee_documents(current_user, employee)
        can_request_leave_flag = can_request_leave(current_user, employee)
        can_review_leave_flag = can_review_leave(current_user)
        can_manage_action_records = can_create_action_records(current_user)
        can_manage_attendance_records_flag = can_manage_attendance_records(current_user)
        can_add_history = can_add_manual_history(current_user)
        is_self_profile = is_self_employee(current_user, employee)
        is_self_service_view = is_self_profile and not can_view_management_employee_sections(current_user, employee)
        is_supervisor_own_profile_view = bool(
            is_self_profile
            and is_branch_scoped_supervisor(current_user)
            and can_view_management_employee_sections(current_user, employee)
        )
        is_operations_own_profile_view = False
        is_management_own_profile_view = bool(
            is_self_profile and should_use_management_own_profile(current_user, employee)
        )
        is_branch_scoped_supervisor_view = is_branch_scoped_supervisor(current_user) and not is_self_service_view
        is_self_focused_profile_view = bool(
            is_self_service_view or is_supervisor_own_profile_view
        )

        all_documents = list(employee.documents.select_related("linked_leave").all())

        if is_self_focused_profile_view:
            documents = [document for document in all_documents if document.linked_leave_id]
            leave_form = kwargs.get("leave_form") or EmployeeSelfServiceLeaveRequestForm()
        else:
            documents = all_documents
            leave_form = kwargs.get("leave_form") or EmployeeLeaveForm()

        identity_document_statuses = build_identity_document_statuses(employee)

        required_submission_queryset = employee.required_submissions.select_related(
            "created_by",
            "reviewed_by",
            "fulfilled_document",
        ).order_by("-updated_at", "-created_at", "-id")
        required_submission_requests = list(required_submission_queryset)
        required_submission_create_form = kwargs.get("required_submission_create_form") or EmployeeRequiredSubmissionCreateForm()
        required_submission_review_form = kwargs.get("required_submission_review_form") or EmployeeRequiredSubmissionReviewForm()
        required_submission_response_forms = {}
        for submission_request in required_submission_requests:
            if submission_request.can_employee_submit:
                response_form = EmployeeRequiredSubmissionResponseForm(instance=submission_request)
                required_submission_response_forms[submission_request.pk] = response_form
                submission_request.response_form = response_form
        required_submission_total = len(required_submission_requests)
        required_submission_requested_count = sum(
            1
            for submission_request in required_submission_requests
            if submission_request.status == EmployeeRequiredSubmission.STATUS_REQUESTED
        )
        required_submission_submitted_count = sum(
            1
            for submission_request in required_submission_requests
            if submission_request.status == EmployeeRequiredSubmission.STATUS_SUBMITTED
        )
        required_submission_completed_count = sum(
            1
            for submission_request in required_submission_requests
            if submission_request.status == EmployeeRequiredSubmission.STATUS_COMPLETED
        )
        required_submission_needs_correction_count = sum(
            1
            for submission_request in required_submission_requests
            if submission_request.status == EmployeeRequiredSubmission.STATUS_NEEDS_CORRECTION
        )
        required_submission_overdue_count = sum(
            1 for submission_request in required_submission_requests if submission_request.is_overdue
        )

        employee_document_request_queryset = employee.document_requests.select_related(
            "created_by",
            "reviewed_by",
            "delivered_document",
        ).order_by("-updated_at", "-created_at", "-id")
        employee_document_requests = list(employee_document_request_queryset)
        employee_document_request_create_form = kwargs.get("employee_document_request_create_form") or EmployeeDocumentRequestCreateForm()
        employee_document_request_review_form = kwargs.get("employee_document_request_review_form") or EmployeeDocumentRequestReviewForm()
        employee_document_request_total = len(employee_document_requests)
        employee_document_request_requested_count = sum(
            1
            for document_request in employee_document_requests
            if document_request.status == EmployeeDocumentRequest.STATUS_REQUESTED
        )
        employee_document_request_approved_count = sum(
            1
            for document_request in employee_document_requests
            if document_request.status == EmployeeDocumentRequest.STATUS_APPROVED
        )
        employee_document_request_completed_count = sum(
            1
            for document_request in employee_document_requests
            if document_request.status == EmployeeDocumentRequest.STATUS_COMPLETED
        )
        employee_document_request_rejected_count = sum(
            1
            for document_request in employee_document_requests
            if document_request.status == EmployeeDocumentRequest.STATUS_REJECTED
        )
        employee_document_request_cancelled_count = sum(
            1
            for document_request in employee_document_requests
            if document_request.status == EmployeeDocumentRequest.STATUS_CANCELLED
        )

        document_form = kwargs.get("document_form") or EmployeeDocumentForm()
        document_total = len(documents)
        required_document_count = sum(1 for document in documents if document.is_required)
        expired_document_count = sum(1 for document in documents if document.is_expired)
        expiring_soon_count = sum(1 for document in documents if document.is_expiring_soon)
        contract_records = list(employee.contracts.all())
        contract_form = kwargs.get("contract_form") or EmployeeContractForm()
        active_contract_count = sum(1 for contract in contract_records if contract.is_active)
        expiring_contract_count = sum(
            1
            for contract in contract_records
            if contract.days_until_expiry is not None and 0 <= contract.days_until_expiry <= 30
        )
        expired_contract_count = sum(
            1
            for contract in contract_records
            if contract.days_until_expiry is not None and contract.days_until_expiry < 0
        )
        for contract in contract_records:
            contract.edit_form = EmployeeContractForm(instance=contract)

        leave_records = list(employee.leave_records.all())
        for leave_record in leave_records:
            leave_record.workflow_owner_label = get_leave_current_stage_owner_label(leave_record)
        leave_total = len(leave_records)
        pending_leave_count = sum(
            1 for leave_record in leave_records if leave_record.status == EmployeeLeave.STATUS_PENDING
        )
        approved_leave_count = sum(
            1 for leave_record in leave_records if leave_record.status == EmployeeLeave.STATUS_APPROVED
        )

        action_records = list(
            employee.action_records.all().order_by("-action_date", "-id")
        )
        recent_action_records = action_records[:8]
        action_form = kwargs.get("action_form") or EmployeeActionRecordForm()
        action_record_total = len(action_records)
        open_action_record_count = sum(
            1 for action_record in action_records if action_record.status == EmployeeActionRecord.STATUS_OPEN
        )
        resolved_action_record_count = sum(
            1 for action_record in action_records if action_record.status == EmployeeActionRecord.STATUS_RESOLVED
        )
        critical_action_record_count = sum(
            1 for action_record in action_records if action_record.severity == EmployeeActionRecord.SEVERITY_CRITICAL
        )

        filter_state = build_attendance_filter_state(self.request)
        attendance_queryset = employee.attendance_ledgers.all()

        if filter_state["start_date"]:
            attendance_queryset = attendance_queryset.filter(attendance_date__gte=filter_state["start_date"])
        if filter_state["end_date"]:
            attendance_queryset = attendance_queryset.filter(attendance_date__lte=filter_state["end_date"])

        attendance_ledgers = list(attendance_queryset)
        attendance_form = kwargs.get("attendance_form") or EmployeeAttendanceLedgerForm(employee=employee)
        attendance_summary = build_attendance_summary(attendance_ledgers)

        sick_leave_day_count = sum(
            1
            for attendance_entry in attendance_ledgers
            if attendance_entry.day_status == EmployeeAttendanceLedger.DAY_STATUS_SICK_LEAVE
        )
        leave_day_count = sum(
            1
            for attendance_entry in attendance_ledgers
            if attendance_entry.day_status in {
                EmployeeAttendanceLedger.DAY_STATUS_PAID_LEAVE,
                EmployeeAttendanceLedger.DAY_STATUS_UNPAID_LEAVE,
            }
        )
        off_day_count = (
            attendance_summary["weekly_off_attendance_count"]
            + attendance_summary["holiday_attendance_count"]
        )
        worked_day_count = attendance_summary["present_attendance_count"]
        absence_day_count = attendance_summary["absence_attendance_count"]

        history_queryset = employee.history_entries.all()
        total_history_count = history_queryset.count()
        history_paginator = Paginator(history_queryset, 5)
        history_page_obj = history_paginator.get_page(self.request.GET.get("timeline_page"))
        history_entries = list(history_page_obj.object_list)
        visible_history_count = len(history_entries)
        has_more_history = history_paginator.num_pages > 1
        timeline_query = self.request.GET.copy()
        timeline_query.pop("timeline_page", None)
        timeline_base_query = timeline_query.urlencode()
        timeline_base_path = self.request.path
        if timeline_base_query:
            timeline_base_path = f"{timeline_base_path}?{timeline_base_query}"
        timeline_base_url = f"{timeline_base_path}#employee-timeline-section"
        timeline_first_url = ""
        timeline_previous_url = ""
        timeline_next_url = ""
        if history_page_obj.number > 1:
            first_query = self.request.GET.copy()
            first_query["timeline_page"] = 1
            timeline_first_url = f"{self.request.path}?{first_query.urlencode()}#employee-timeline-section"
        if history_page_obj.has_previous():
            previous_query = self.request.GET.copy()
            previous_query["timeline_page"] = history_page_obj.previous_page_number()
            timeline_previous_url = f"{self.request.path}?{previous_query.urlencode()}#employee-timeline-section"
        if history_page_obj.has_next():
            next_query = self.request.GET.copy()
            next_query["timeline_page"] = history_page_obj.next_page_number()
            timeline_next_url = f"{self.request.path}?{next_query.urlencode()}#employee-timeline-section"
        history_form = kwargs.get("history_form") or EmployeeHistoryForm()

        working_time_summary = build_employee_working_time_summary(employee)
        can_view_working_time_summary = (
            is_management_user(current_user)
            or can_supervisor_view_employee(current_user, employee)
            or is_self_employee(current_user, employee)
        )

        context["document_form"] = document_form
        context["documents"] = documents
        context["document_total"] = document_total
        context["required_document_count"] = required_document_count
        context["expired_document_count"] = expired_document_count
        context["expiring_soon_count"] = expiring_soon_count
        context["contract_records"] = contract_records
        context["contract_form"] = contract_form
        context["contract_total"] = len(contract_records)
        context["active_contract_count"] = active_contract_count
        context["expiring_contract_count"] = expiring_contract_count
        context["expired_contract_count"] = expired_contract_count
        context["identity_document_statuses"] = identity_document_statuses

        context["required_submission_create_form"] = required_submission_create_form
        context["required_submission_review_form"] = required_submission_review_form
        context["required_submission_response_forms"] = required_submission_response_forms
        context["required_submission_requests"] = required_submission_requests
        context["required_submission_total"] = required_submission_total
        context["required_submission_requested_count"] = required_submission_requested_count
        context["required_submission_submitted_count"] = required_submission_submitted_count
        context["required_submission_completed_count"] = required_submission_completed_count
        context["required_submission_needs_correction_count"] = required_submission_needs_correction_count
        context["required_submission_overdue_count"] = required_submission_overdue_count

        context["employee_document_request_create_form"] = employee_document_request_create_form
        context["employee_document_request_review_form"] = employee_document_request_review_form
        context["employee_document_requests"] = employee_document_requests
        context["employee_document_request_total"] = employee_document_request_total
        context["employee_document_request_requested_count"] = employee_document_request_requested_count
        context["employee_document_request_approved_count"] = employee_document_request_approved_count
        context["employee_document_request_completed_count"] = employee_document_request_completed_count
        context["employee_document_request_rejected_count"] = employee_document_request_rejected_count
        context["employee_document_request_cancelled_count"] = employee_document_request_cancelled_count

        context["leave_form"] = leave_form
        context["leave_records"] = leave_records
        context["leave_total"] = leave_total
        context["pending_leave_count"] = pending_leave_count
        context["approved_leave_count"] = approved_leave_count

        context["action_form"] = action_form
        context["action_records"] = action_records
        context["recent_action_records"] = recent_action_records
        context["action_record_total"] = action_record_total
        context["open_action_record_count"] = open_action_record_count
        context["resolved_action_record_count"] = resolved_action_record_count
        context["critical_action_record_count"] = critical_action_record_count

        context["attendance_ledgers"] = attendance_ledgers
        context["attendance_form"] = attendance_form
        context["attendance_filter_form"] = filter_state["form"]
        context["attendance_filter_type"] = filter_state["filter_type"]
        context["attendance_filter_start_date"] = filter_state["start_date"]
        context["attendance_filter_end_date"] = filter_state["end_date"]
        context["attendance_period_label"] = filter_state["period_label"]
        context["attendance_filter_applied"] = filter_state["is_applied"]

        context.update(attendance_summary)

        context["history_form"] = history_form
        context["history_entries"] = history_entries
        context["total_history_count"] = total_history_count
        context["visible_history_count"] = visible_history_count
        context["has_more_history"] = has_more_history
        context["history_page_obj"] = history_page_obj
        context["history_paginator"] = history_paginator
        context["timeline_base_url"] = timeline_base_url
        context["timeline_first_url"] = timeline_first_url
        context["timeline_previous_url"] = timeline_previous_url
        context["timeline_next_url"] = timeline_next_url

        context["working_time_summary"] = working_time_summary
        context["can_view_working_time_summary"] = can_view_working_time_summary
        context["worked_day_count"] = worked_day_count
        context["off_day_count"] = off_day_count
        context["leave_day_count"] = leave_day_count
        context["sick_leave_day_count"] = sick_leave_day_count
        context["absence_day_count"] = absence_day_count

        context["same_company_url"] = (
            f"{reverse_lazy('employees:employee_list')}?company={employee.company_id}"
            if employee.company_id and can_view_directory
            else None
        )
        context["same_department_url"] = (
            f"{reverse_lazy('employees:employee_list')}?department={employee.department_id}"
            if employee.department_id and can_view_directory
            else None
        )
        context["same_branch_url"] = (
            f"{reverse_lazy('employees:employee_list')}?branch={employee.branch_id}"
            if employee.branch_id and can_view_directory
            else None
        )
        context["same_section_url"] = (
            f"{reverse_lazy('employees:employee_list')}?section={employee.section_id}"
            if employee.section_id and can_view_directory
            else None
        )
        context["same_job_title_url"] = (
            f"{reverse_lazy('employees:employee_list')}?job_title={employee.job_title_id}"
            if employee.job_title_id and can_view_directory
            else None
        )
        context["similar_name_url"] = (
            f"{reverse_lazy('employees:employee_list')}?search={employee.full_name}"
            if employee.full_name and can_view_directory
            else None
        )

        context["can_view_directory"] = can_view_directory
        context["can_manage_employees"] = can_manage_employees
        context["can_edit_employee"] = can_edit_employee
        context["can_delete_employee"] = can_delete_employee_flag
        context["can_transfer_employee"] = can_transfer_employee_flag
        context["can_change_status"] = can_change_status
        context["employee_status_choices"] = Employee.EMPLOYMENT_STATUS_CHOICES
        context["can_manage_documents"] = can_manage_documents
        context["can_manage_contracts"] = can_edit_employee
        context["can_manage_employee_required_submissions"] = can_manage_employee_required_submissions(current_user, employee) and not is_self_profile
        context["can_use_profile_section_edit"] = can_edit_employee
        from .views_action_center import EmployeeIdentityModalForm, EmployeeInformationModalForm

        context["profile_section_actions"] = build_employee_profile_section_actions(employee) if can_edit_employee else {}
        context["employee_information_modal_form"] = kwargs.get("employee_information_modal_form") or EmployeeInformationModalForm(instance=employee)
        context["identity_information_modal_form"] = kwargs.get("identity_information_modal_form") or EmployeeIdentityModalForm(instance=employee)
        context["active_profile_modal"] = kwargs.get("active_profile_modal") or (self.request.GET.get("modal") or "").strip()
        context["can_request_leave"] = can_request_leave_flag
        context["can_review_leave"] = can_review_leave_flag
        context["can_manage_action_records"] = can_manage_action_records
        context["can_manage_attendance_records"] = can_manage_attendance_records_flag
        context["can_add_history"] = can_add_history
        context["is_self_service_view"] = is_self_service_view
        context["is_supervisor_own_profile_view"] = is_supervisor_own_profile_view
        context["is_operations_own_profile_view"] = is_operations_own_profile_view
        context["is_management_own_profile_view"] = is_management_own_profile_view
        context["is_self_focused_profile_view"] = is_self_focused_profile_view
        context["can_cancel_leave"] = True

        supervisor_employee = get_employee_supervisor(employee)
        team_leader_employee = get_employee_team_leader(employee)
        department_manager_display = get_department_manager_display(employee)
        branch_supervisor_display = get_branch_supervisor_display(employee)
        team_leader_display = get_team_leader_display(employee)
        branch_team_context = build_branch_team_structure(employee)

        context["employee_display_company"] = get_short_structure_label(employee.company)
        context["employee_display_department"] = get_short_structure_label(employee.department)
        context["employee_display_branch"] = get_short_structure_label(employee.branch)
        context["employee_display_section"] = get_short_structure_label(employee.section)
        context["employee_display_job_title"] = get_short_structure_label(employee.job_title)

        for group in branch_team_context["branch_team_groups"]:
            for member in group["members"]:
                member.short_job_title_display = get_short_structure_label(member.job_title)
                member.short_section_display = get_short_structure_label(member.section)
                member.short_branch_display = get_short_structure_label(member.branch)
                member.short_department_display = get_short_structure_label(member.department)
                member.short_company_display = get_short_structure_label(member.company)

        context["self_service_supervisor"] = supervisor_employee
        context["self_service_team_leader"] = team_leader_employee
        context["department_manager_display"] = department_manager_display
        context["branch_supervisor_display"] = branch_supervisor_display
        context["team_leader_display"] = team_leader_display
        context["is_branch_scoped_supervisor_view"] = is_branch_scoped_supervisor_view
        context["scoped_branch"] = get_user_scope_branch(current_user)
        context["branch_team_members"] = branch_team_context["branch_team_members"]
        context["branch_team_groups"] = branch_team_context["branch_team_groups"]
        context["branch_team_total"] = branch_team_context["branch_team_total"]
        context["self_service_request_records"] = leave_records
        context["self_service_pending_leave_count"] = pending_leave_count
        context["self_service_approved_leave_count"] = approved_leave_count
        context["self_service_rejected_leave_count"] = sum(
            1 for leave_record in leave_records if leave_record.status == EmployeeLeave.STATUS_REJECTED
        )
        context["self_service_cancelled_leave_count"] = sum(
            1 for leave_record in leave_records if leave_record.status == EmployeeLeave.STATUS_CANCELLED
        )
        context["self_service_document_request_records"] = employee_document_requests if is_self_focused_profile_view else []
        context["self_service_document_request_requested_count"] = employee_document_request_requested_count
        context["self_service_document_request_approved_count"] = employee_document_request_approved_count
        context["self_service_document_request_completed_count"] = employee_document_request_completed_count
        context["self_service_document_request_rejected_count"] = employee_document_request_rejected_count
        context["self_service_document_request_cancelled_count"] = employee_document_request_cancelled_count
        context["can_create_employee_document_request"] = can_create_employee_document_request(current_user, employee)
        context["can_cancel_employee_document_request"] = True

        PayrollProfile = apps.get_model("payroll", "PayrollProfile")
        PayrollLine = apps.get_model("payroll", "PayrollLine")
        PayrollObligation = apps.get_model("payroll", "PayrollObligation")
        payroll_profile = PayrollProfile.objects.select_related("company").filter(employee=employee).first()
        latest_payroll_lines = list(
            PayrollLine.objects.select_related("payroll_period")
            .filter(employee=employee)
            .order_by("-payroll_period__period_start", "-id")[:5]
        )
        payroll_obligations = list(
            PayrollObligation.objects.filter(employee=employee).order_by("-created_at", "-id")[:8]
        )
        employee_360_overview_cards = build_employee_360_overview_cards(
            employee,
            attendance_summary,
            working_time_summary,
            identity_document_statuses,
            leave_records,
            required_submission_requests,
            employee_document_requests,
            payroll_profile,
            latest_payroll_lines,
            payroll_obligations,
            action_records,
        )
        employee_360_signal_cards = build_employee_360_signal_cards(
            attendance_summary,
            working_time_summary,
            identity_document_statuses,
            leave_records,
            payroll_profile,
            latest_payroll_lines,
            payroll_obligations,
        )
        employee_leave_trends = build_employee_leave_trend_rows(leave_records)
        employee_compliance_timeline = build_employee_compliance_timeline(
            identity_document_statuses,
            all_documents,
            required_submission_requests,
        )
        employee_360_timeline_items = build_employee_360_timeline_items(
            history_entries,
            leave_records,
            action_records,
            all_documents,
            employee_document_requests,
            required_submission_requests,
            latest_payroll_lines,
        )
        context["employee_payroll_profile"] = payroll_profile
        context["employee_payroll_lines"] = latest_payroll_lines
        context["employee_payroll_line_count"] = len(latest_payroll_lines)
        context["employee_payroll_obligations"] = payroll_obligations
        context["employee_estimated_net_salary"] = payroll_profile.estimated_net_salary if payroll_profile else None
        context["employee_360_overview_url"] = build_employee_detail_tab_url(employee, tab="overview")
        context["employee_360_payroll_url"] = build_employee_detail_tab_url(
            employee,
            tab="payroll",
            anchor="employee-payroll-section",
        )
        employee_payroll_workspace_anchor = "payroll-profiles-section" if payroll_profile else "employees-missing-payroll-section"
        context["employee_payroll_workspace_url"] = (
            f"{reverse('payroll:home')}?employee={employee.pk}#{employee_payroll_workspace_anchor}"
        )
        context["employee_360_documents_url"] = build_employee_detail_tab_url(employee, tab="documents")
        context["employee_360_leave_url"] = build_employee_detail_tab_url(employee, tab="leave")
        context["employee_360_compliance_url"] = build_employee_detail_tab_url(employee, tab="compliance")
        context["employee_360_performance_url"] = build_employee_detail_tab_url(
            employee,
            tab="performance",
            anchor="employee-timeline-section",
        )
        context["employee_360_action_center_url"] = (
            f"{reverse('employees:employee_admin_action_center')}?employee={employee.pk}"
        )
        context["employee_360_attendance_management_url"] = (
            f"{reverse('employees:attendance_management')}?employee={employee.pk}"
        )
        context["employee_360_overview_cards"] = employee_360_overview_cards
        context["employee_360_signal_cards"] = employee_360_signal_cards
        context["employee_leave_trends"] = employee_leave_trends
        context["employee_compliance_timeline"] = employee_compliance_timeline
        context["employee_360_timeline_items"] = employee_360_timeline_items
        context["employee_payroll_profile_form"] = kwargs.get("employee_payroll_profile_form") or PayrollProfileForm(
            instance=payroll_profile,
            employee=employee,
        )

        return context
