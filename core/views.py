from datetime import datetime, timedelta
from decimal import Decimal
import re
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import TemplateView

from openpyxl import Workbook
from openpyxl.styles import Font

from employees.models import Employee, EmployeeAttendanceLedger, EmployeeLeave
from organization.models import (
    Branch,
    BranchDocument,
    BranchDocumentRequirement,
    Company,
    Department,
    JobTitle,
    Section,
)

class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = "core/dashboard_home.html"

    def get_employee_profile(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return None
        return (
            Employee.objects.filter(user=user)
            .select_related("company", "department", "branch", "section", "job_title")
            .first()
        )

    def is_admin_compatible(self, user):
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_superuser", False):
            return True
        role_value = (getattr(user, "role", "") or "").strip().lower()
        if role_value in {"hr", "supervisor", "operations_manager", "employee"}:
            return False
        return bool(getattr(user, "is_staff", False))

    def is_hr_user(self, user):
        return bool(user and user.is_authenticated and getattr(user, "is_hr", False))

    def is_supervisor_user(self, user):
        return bool(user and user.is_authenticated and getattr(user, "is_supervisor", False))

    def is_operations_manager_user(self, user):
        return bool(user and user.is_authenticated and getattr(user, "is_operations_manager", False))

    def is_employee_role_user(self, user):
        return bool(user and user.is_authenticated and getattr(user, "is_employee_role", False))

    def is_management_user(self, user):
        return bool(
            user
            and user.is_authenticated
            and (
                self.is_admin_compatible(user)
                or self.is_hr_user(user)
                or self.is_supervisor_user(user)
                or self.is_operations_manager_user(user)
            )
        )

    def can_access_dashboard(self, user):
        return self.is_management_user(user)

    def handle_no_permission(self):
        user = getattr(self.request, "user", None)

        if not user or not user.is_authenticated:
            return super().handle_no_permission()

        messages.error(self.request, "You do not have permission to access the dashboard.")

        linked_employee = self.get_employee_profile()
        if linked_employee:
            return redirect("employees:employee_detail", pk=linked_employee.pk)

        raise PermissionDenied("You do not have permission to access the dashboard.")

    def dispatch(self, request, *args, **kwargs):
        if not self.can_access_dashboard(request.user):
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

    def get_scoped_branch(self, user, employee_profile):
        if (
            self.is_supervisor_user(user)
            and not self.is_admin_compatible(user)
            and not self.is_hr_user(user)
            and not self.is_operations_manager_user(user)
        ):
            return getattr(employee_profile, "branch", None)
        return None

    def is_branch_scoped_supervisor(self, user, scoped_branch):
        return bool(
            self.is_supervisor_user(user)
            and not self.is_admin_compatible(user)
            and not self.is_hr_user(user)
            and not self.is_operations_manager_user(user)
            and scoped_branch is not None
        )

    def build_branch_team_groups(self, employee):
        if not employee or not employee.branch_id:
            return []
        branch_team_members = list(
            Employee.objects.select_related("job_title", "section", "branch")
            .filter(branch_id=employee.branch_id, is_active=True)
            .order_by("full_name")
        )
        groups = {"Supervisor": [], "Team Leader": [], "Team Members": []}
        for member in branch_team_members:
            title = (member.job_title.name if member.job_title else "").lower()
            if "supervisor" in title:
                groups["Supervisor"].append(member)
            elif "team leader" in title or title == "leader" or title.endswith(" leader"):
                groups["Team Leader"].append(member)
            else:
                groups["Team Members"].append(member)
        return [{"label": label, "members": members} for label, members in groups.items() if members]

    def get_request_state_label(self, leave_record):
        if leave_record.status == EmployeeLeave.STATUS_APPROVED:
            return "Final Approved"
        if leave_record.status == EmployeeLeave.STATUS_REJECTED:
            return "Final Rejected"
        if leave_record.status == EmployeeLeave.STATUS_CANCELLED:
            return "Cancelled / Recalled"
        if leave_record.current_stage == EmployeeLeave.STAGE_SUPERVISOR_REVIEW:
            return "Waiting for Supervisor"
        if leave_record.current_stage == EmployeeLeave.STAGE_OPERATIONS_REVIEW:
            return "Approved by Supervisor • Waiting for Operations"
        if leave_record.current_stage == EmployeeLeave.STAGE_HR_REVIEW:
            return "Approved by Operations • Waiting for HR"
        return leave_record.get_status_display()

    def get_request_state_badge_class(self, leave_record):
        if leave_record.status == EmployeeLeave.STATUS_APPROVED:
            return "badge-success"
        if leave_record.status in {EmployeeLeave.STATUS_REJECTED, EmployeeLeave.STATUS_CANCELLED}:
            return "badge-danger"
        if leave_record.current_stage == EmployeeLeave.STAGE_SUPERVISOR_REVIEW:
            return "badge-warning"
        return "badge-primary"

    def build_metrics(self, queryset):
        total_employees = queryset.count()
        active_employees = queryset.filter(is_active=True).count()
        inactive_employees = queryset.filter(is_active=False).count()
        recent_hires_30_days = queryset.filter(
            hire_date__gte=timezone.localdate() - timedelta(days=30)
        ).count()

        def ratio(value):
            if not total_employees:
                return Decimal("0.0")
            return (Decimal(value) * Decimal("100") / Decimal(total_employees)).quantize(
                Decimal("0.1")
            )

        return {
            "total_employees": total_employees,
            "active_employees": active_employees,
            "inactive_employees": inactive_employees,
            "recent_hires_30_days": recent_hires_30_days,
            "active_ratio": ratio(active_employees),
            "inactive_ratio": ratio(inactive_employees),
            "total_companies": Company.objects.filter(is_active=True).count(),
            "total_departments": Department.objects.filter(is_active=True).count(),
            "total_branches": Branch.objects.filter(is_active=True).count(),
            "total_sections": Section.objects.filter(is_active=True).count(),
            "total_job_titles": JobTitle.objects.filter(is_active=True).count(),
        }

    def get_requirement_status_payload(self, selected_document):
        if not selected_document:
            return {"state_key": "missing", "status_label": "Missing"}
        if selected_document.is_expired:
            return {"state_key": "expired", "status_label": "Expired"}
        if selected_document.is_expiring_soon:
            return {"state_key": "expiring_soon", "status_label": "Expiring Soon"}
        if selected_document.expiry_date:
            return {"state_key": "valid", "status_label": "Valid"}
        return {"state_key": "recorded", "status_label": "Recorded"}

    def get_branch_compliance_status_payload(self, summary):
        requirement_total = summary.get("requirement_total", 0)
        missing_total = summary.get("missing_total", 0)
        expired_total = summary.get("expired_total", 0)
        expiring_soon_total = summary.get("expiring_soon_total", 0)
        compliant_total = summary.get("compliant_total", 0)

        if requirement_total == 0:
            return {
                "label": "No Checklist",
                "badge_class": "badge-light",
                "help_text": "No active required checklist items configured yet.",
            }
        if missing_total or expired_total:
            return {
                "label": "Critical",
                "badge_class": "badge-danger",
                "help_text": "At least one required document is missing or expired.",
            }
        if expiring_soon_total:
            return {
                "label": "Needs Attention",
                "badge_class": "badge-warning",
                "help_text": "Required documents exist, but one or more will expire soon.",
            }
        if compliant_total >= requirement_total:
            return {
                "label": "Compliant",
                "badge_class": "badge-success",
                "help_text": "All required checklist items are currently covered.",
            }
        return {
            "label": "In Review",
            "badge_class": "badge-primary",
            "help_text": "Checklist is partially covered and should be reviewed.",
        }

    def build_branch_compliance_dashboard(self):
        branches = list(
            Branch.objects.filter(is_active=True)
            .select_related("company")
            .annotate(
                employee_total=Count("employees", distinct=True),
                document_total=Count("documents", distinct=True),
            )
            .order_by("company__name", "name")
        )
        branch_ids = [branch.pk for branch in branches]

        requirements = list(
            BranchDocumentRequirement.objects.filter(branch_id__in=branch_ids, is_active=True)
            .select_related("branch", "branch__company")
            .order_by("branch__company__name", "branch__name", "document_type", "title")
        )
        documents = list(
            BranchDocument.objects.filter(branch_id__in=branch_ids)
            .select_related("branch", "branch__company")
            .order_by("branch_id", "document_type", "-issue_date", "-pk")
        )

        requirements_by_branch = {}
        for requirement in requirements:
            requirements_by_branch.setdefault(requirement.branch_id, []).append(requirement)

        documents_by_branch = {}
        for document in documents:
            documents_by_branch.setdefault(document.branch_id, []).append(document)

        rows = []
        summary = {
            "branch_total": len(branches),
            "requirement_total": 0,
            "missing_total": 0,
            "expired_total": 0,
            "expiring_soon_total": 0,
            "compliant_total": 0,
            "critical_total": 0,
            "needs_attention_total": 0,
            "compliant_branch_total": 0,
            "no_checklist_total": 0,
        }

        for branch in branches:
            latest_documents_by_type = {}
            for document in documents_by_branch.get(branch.pk, []):
                latest_documents_by_type.setdefault(document.document_type, document)

            requirement_total = 0
            missing_total = 0
            expired_total = 0
            expiring_soon_total = 0
            compliant_total = 0

            for requirement in requirements_by_branch.get(branch.pk, []):
                if not requirement.is_mandatory:
                    continue
                requirement_total += 1
                selected_document = latest_documents_by_type.get(requirement.document_type)
                status_payload = self.get_requirement_status_payload(selected_document)
                if status_payload["state_key"] == "missing":
                    missing_total += 1
                elif status_payload["state_key"] == "expired":
                    expired_total += 1
                elif status_payload["state_key"] == "expiring_soon":
                    expiring_soon_total += 1
                elif status_payload["state_key"] in {"valid", "recorded"}:
                    compliant_total += 1

            compliance_percentage = (
                int(round((compliant_total / requirement_total) * 100)) if requirement_total else 0
            )
            status_payload = self.get_branch_compliance_status_payload(
                {
                    "requirement_total": requirement_total,
                    "missing_total": missing_total,
                    "expired_total": expired_total,
                    "expiring_soon_total": expiring_soon_total,
                    "compliant_total": compliant_total,
                }
            )
            row = {
                "branch_id": branch.pk,
                "branch_name": branch.name,
                "company_name": branch.company.name if getattr(branch, "company_id", None) else "—",
                "employee_total": getattr(branch, "employee_total", 0),
                "document_total": getattr(branch, "document_total", 0),
                "requirement_total": requirement_total,
                "missing_total": missing_total,
                "expired_total": expired_total,
                "expiring_soon_total": expiring_soon_total,
                "compliant_total": compliant_total,
                "compliance_percentage": compliance_percentage,
                "status_label": status_payload["label"],
                "status_badge_class": status_payload["badge_class"],
                "status_help_text": status_payload["help_text"],
                "detail_url": f"/organization/branches/{branch.pk}/",
                "document_center_url": f"/organization/branch-documents/?branch={branch.pk}",
            }
            rows.append(row)
            summary["requirement_total"] += requirement_total
            summary["missing_total"] += missing_total
            summary["expired_total"] += expired_total
            summary["expiring_soon_total"] += expiring_soon_total
            summary["compliant_total"] += compliant_total
            if row["status_label"] == "Critical":
                summary["critical_total"] += 1
            elif row["status_label"] == "Needs Attention":
                summary["needs_attention_total"] += 1
            elif row["status_label"] == "Compliant":
                summary["compliant_branch_total"] += 1
            elif row["status_label"] == "No Checklist":
                summary["no_checklist_total"] += 1

        metric_cards = [
            {
                "label": "Branches",
                "value": summary["branch_total"],
                "help_text": "Active branch records in compliance monitoring.",
                "card_class": "dashboard-core-metric-card",
            },
            {
                "label": "Compliant",
                "value": summary["compliant_branch_total"],
                "help_text": "Branches with all required checklist items covered.",
                "card_class": "dashboard-core-metric-card dashboard-core-metric-success",
            },
            {
                "label": "Needs Attention",
                "value": summary["needs_attention_total"],
                "help_text": "Branches with required documents expiring soon.",
                "card_class": "dashboard-core-metric-card dashboard-core-metric-warning",
            },
            {
                "label": "Critical",
                "value": summary["critical_total"],
                "help_text": "Branches with missing or expired required documents.",
                "card_class": "dashboard-core-metric-card dashboard-core-metric-danger",
            },
        ]

        quick_stats = [
            {"label": "Missing Items", "value": summary["missing_total"]},
            {"label": "Expired Items", "value": summary["expired_total"]},
            {"label": "Expiring Soon", "value": summary["expiring_soon_total"]},
            {"label": "No Checklist", "value": summary["no_checklist_total"]},
            {"label": "Covered Items", "value": summary["compliant_total"]},
        ]

        quick_links = [
            {"label": "Open Branch Compliance Overview", "url": "/organization/branches/"},
            {"label": "Open Branch Documents Center", "url": "/organization/branch-documents/"},
        ]

        critical_rows = [row for row in rows if row["status_label"] == "Critical"][:5]
        expiring_rows = [row for row in rows if row["expiring_soon_total"] > 0][:5]

        return {
            "summary": summary,
            "metric_cards": metric_cards,
            "quick_stats": quick_stats,
            "critical_rows": critical_rows,
            "expiring_rows": expiring_rows,
            "quick_links": quick_links,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        employee_profile = self.get_employee_profile()
        scoped_branch = self.get_scoped_branch(user, employee_profile)
        supervisor_setup_required = bool(
            self.is_supervisor_user(user) and employee_profile and scoped_branch is None
        )
        supervisor_scope_missing = supervisor_setup_required

        is_employee_self_service_dashboard = bool(
            self.is_employee_role_user(user)
            and employee_profile
            and not (
                self.is_admin_compatible(user)
                or self.is_hr_user(user)
                or self.is_operations_manager_user(user)
                or scoped_branch
            )
        )

        if is_employee_self_service_dashboard:
            leave_qs = employee_profile.leave_records.all().order_by("-created_at", "-id")
            request_state_records = []
            for leave_record in leave_qs[:10]:
                request_state_records.append(
                    {
                        "record": leave_record,
                        "state_label": self.get_request_state_label(leave_record),
                        "state_badge_class": self.get_request_state_badge_class(leave_record),
                    }
                )

            context.update(
                {
                    "is_employee_self_service_dashboard": True,
                    "employee": employee_profile,
                    "pending_request_count": leave_qs.filter(status=EmployeeLeave.STATUS_PENDING).count(),
                    "approved_request_count": leave_qs.filter(status=EmployeeLeave.STATUS_APPROVED).count(),
                    "rejected_request_count": leave_qs.filter(status=EmployeeLeave.STATUS_REJECTED).count(),
                    "cancelled_request_count": leave_qs.filter(status=EmployeeLeave.STATUS_CANCELLED).count(),
                    "branch_team_groups": self.build_branch_team_groups(employee_profile),
                    "request_state_records": request_state_records,
                }
            )
            return context

        employee_queryset = Employee.objects.select_related(
            "company", "department", "branch", "section", "job_title"
        ).all()
        if scoped_branch:
            employee_queryset = employee_queryset.filter(branch_id=scoped_branch.id)

        recent_employees = list(employee_queryset.order_by("-created_at", "-id")[:8])
        recent_hires = list(
            employee_queryset.filter(hire_date__isnull=False).order_by("-hire_date", "-id")[:8]
        )
        employees_by_company = list(
            employee_queryset.exclude(company__isnull=True)
            .values("company__name")
            .annotate(total=Count("id"))
            .order_by("-total", "company__name")[:8]
        )
        employees_by_branch = list(
            employee_queryset.exclude(branch__isnull=True)
            .values("branch__name")
            .annotate(total=Count("id"))
            .order_by("-total", "branch__name")[:8]
        )
        employees_by_department = list(
            employee_queryset.exclude(department__isnull=True)
            .values("department__name")
            .annotate(total=Count("id"))
            .order_by("-total", "department__name")[:8]
        )

        can_view_organization_setup = bool(
            self.is_admin_compatible(user)
            or self.is_hr_user(user)
            or self.is_operations_manager_user(user)
        )
        branch_compliance_dashboard = (
            self.build_branch_compliance_dashboard() if can_view_organization_setup else None
        )

        context.update(
            {
                "is_employee_self_service_dashboard": False,
                "is_branch_scoped_supervisor": scoped_branch is not None,
                "scoped_branch": scoped_branch,
                "metrics": self.build_metrics(employee_queryset),
                "recent_employees": recent_employees,
                "recent_hires": recent_hires,
                "employees_by_company": employees_by_company,
                "employees_by_branch": employees_by_branch,
                "employees_by_department": employees_by_department,
                "can_view_employee_directory": bool(
                    self.is_admin_compatible(user)
                    or self.is_hr_user(user)
                    or self.is_operations_manager_user(user)
                    or scoped_branch
                ),
                "can_view_organization_setup": can_view_organization_setup,
                "show_branch_compliance_dashboard": bool(
                    can_view_organization_setup and not scoped_branch
                ),
                "branch_compliance_dashboard": branch_compliance_dashboard,
                "supervisor_setup_required": supervisor_setup_required,
                "supervisor_scope_missing": supervisor_scope_missing,
            }
        )
        return context


class BackupCenterView(LoginRequiredMixin, TemplateView):
    template_name = "core/backup_center.html"
    backup_table_limit = 20

    def dispatch(self, request, *args, **kwargs):
        if not self.can_access_backup_center(request.user):
            messages.error(request, "Only the top admin can access the Backup & Export Center.")
            if request.user.is_authenticated:
                return redirect("home")
            raise PermissionDenied("You do not have permission to access the Backup & Export Center.")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        action = (request.POST.get("action") or "create_backup").strip()

        if action == "create_backup":
            note = (request.POST.get("backup_note") or "").strip()
            try:
                backup_file = self.create_backup(note=note)
            except Exception as exc:
                messages.error(request, f"Backup creation failed: {exc}")
            else:
                messages.success(request, f"Backup created successfully: {backup_file.name}")
            return redirect("backup_center")

        if action == "export_employee_master":
            return self.export_employee_master_data()

        if action == "export_attendance":
            return self.export_attendance_data(
                start_date=parse_date((request.POST.get("attendance_start_date") or "").strip()) if (request.POST.get("attendance_start_date") or "").strip() else None,
                end_date=parse_date((request.POST.get("attendance_end_date") or "").strip()) if (request.POST.get("attendance_end_date") or "").strip() else None,
            )

        if action == "export_leave_records":
            return self.export_leave_data(
                start_date=parse_date((request.POST.get("leave_start_date") or "").strip()) if (request.POST.get("leave_start_date") or "").strip() else None,
                end_date=parse_date((request.POST.get("leave_end_date") or "").strip()) if (request.POST.get("leave_end_date") or "").strip() else None,
            )

        if action == "export_backup_audit":
            return self.export_backup_audit_data()

        messages.error(request, "Unknown utility action requested.")
        return redirect("backup_center")

    def can_access_backup_center(self, user):
        return bool(user and user.is_authenticated and getattr(user, "is_superuser", False))

    def get_backup_root(self):
        backup_root = Path(settings.HR_BACKUP_ROOT)
        backup_root.mkdir(parents=True, exist_ok=True)
        return backup_root

    def sanitize_note(self, note):
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", note.strip())
        cleaned = re.sub(r"-+", "-", cleaned).strip("-")
        return cleaned[:50]

    def get_include_paths(self):
        include_items = []
        for relative_item in getattr(settings, "HR_BACKUP_INCLUDE_PATHS", []):
            candidate = settings.BASE_DIR / relative_item
            if candidate.exists():
                include_items.append(candidate)
        return include_items

    def should_skip_dir(self, dir_name):
        excluded = set(getattr(settings, "HR_BACKUP_EXCLUDE_DIR_NAMES", set()))
        return dir_name in excluded

    def should_skip_file(self, file_path):
        excluded_suffixes = set(getattr(settings, "HR_BACKUP_EXCLUDE_FILE_SUFFIXES", set()))
        return file_path.suffix.lower() in excluded_suffixes

    def iter_backup_files(self, path):
        if path.is_file():
            if not self.should_skip_file(path):
                yield path
            return

        for child in path.iterdir():
            if child.is_dir():
                if self.should_skip_dir(child.name):
                    continue
                yield from self.iter_backup_files(child)
            elif child.is_file() and not self.should_skip_file(child):
                yield child

    def create_backup(self, note=""):
        backup_root = self.get_backup_root()
        timestamp = timezone.localtime().strftime("%Y-%m-%d_%H-%M-%S")
        safe_note = self.sanitize_note(note)
        filename = f"hr_backup_{timestamp}"
        if safe_note:
            filename = f"{filename}_{safe_note}"
        backup_file = backup_root / f"{filename}.zip"

        include_paths = self.get_include_paths()
        if not include_paths:
            raise ValueError("No valid backup include paths were found in settings.py.")

        with zipfile.ZipFile(backup_file, "w", compression=zipfile.ZIP_DEFLATED) as zip_handle:
            manifest_lines = [
                "HR System Backup Manifest",
                f"Created at: {timezone.localtime().strftime('%Y-%m-%d %H:%M:%S %Z')}",
                f"Created by: {self.request.user.get_username()}",
                f"Backup file: {backup_file.name}",
                f"Backup root: {backup_root}",
                f"Note: {safe_note or '—'}",
                "",
                "Included paths:",
            ]
            for include_path in include_paths:
                manifest_lines.append(f"- {include_path.relative_to(settings.BASE_DIR)}")

            for include_path in include_paths:
                if include_path.is_file():
                    archive_name = include_path.relative_to(settings.BASE_DIR)
                    zip_handle.write(include_path, arcname=str(archive_name))
                    continue

                for child_file in self.iter_backup_files(include_path):
                    archive_name = child_file.relative_to(settings.BASE_DIR)
                    zip_handle.write(child_file, arcname=str(archive_name))

            zip_handle.writestr("backup_manifest.txt", "\n".join(manifest_lines))

        return backup_file

    def get_latest_backups(self):
        backup_root = self.get_backup_root()
        backups = []
        for path in backup_root.glob("*.zip"):
            stat = path.stat()
            backups.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
                    "size_bytes": stat.st_size,
                    "size_mb": f"{stat.st_size / (1024 * 1024):.2f}",
                }
            )
        backups.sort(key=lambda item: item["modified_at"], reverse=True)
        return backups

    def get_employee_export_queryset(self):
        return Employee.objects.select_related(
            "user",
            "company",
            "department",
            "branch",
            "section",
            "job_title",
        ).order_by("employee_id", "full_name")

    def get_attendance_export_queryset(self, start_date=None, end_date=None):
        queryset = EmployeeAttendanceLedger.objects.select_related(
            "employee",
            "employee__company",
            "employee__department",
            "employee__branch",
            "employee__section",
            "employee__job_title",
            "linked_leave",
            "linked_action_record",
        ).order_by("-attendance_date", "employee__employee_id", "-id")
        if start_date:
            queryset = queryset.filter(attendance_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(attendance_date__lte=end_date)
        return queryset

    def get_leave_export_queryset(self, start_date=None, end_date=None):
        queryset = EmployeeLeave.objects.select_related(
            "employee",
            "employee__company",
            "employee__department",
            "employee__branch",
            "employee__section",
            "employee__job_title",
            "requested_by",
            "reviewed_by",
            "approved_by",
            "rejected_by",
            "cancelled_by",
            "supervisor_reviewed_by",
            "operations_reviewed_by",
            "hr_reviewed_by",
        ).order_by("-start_date", "employee__employee_id", "-id")
        if start_date:
            queryset = queryset.filter(start_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(end_date__lte=end_date)
        return queryset

    def style_sheet(self, worksheet, headers):
        header_font = Font(bold=True)
        for index, header in enumerate(headers, start=1):
            cell = worksheet.cell(row=1, column=index)
            cell.font = header_font
            column_letter = worksheet.cell(row=1, column=index).column_letter
            worksheet.column_dimensions[column_letter].width = max(16, min(len(str(header)) + 4, 30))
        worksheet.freeze_panes = "A2"

    def build_workbook_response(self, workbook, filename):
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        workbook.save(response)
        return response

    def export_employee_master_data(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Employees"

        headers = [
            "Employee ID",
            "Full Name",
            "Login Email",
            "Contact Email",
            "Phone",
            "Company",
            "Department",
            "Branch",
            "Section",
            "Job Title",
            "Hire Date",
            "Employment Status",
            "Operationally Active",
            "Passport Issue Date",
            "Passport Expiry Date",
            "Civil ID Issue Date",
            "Civil ID Expiry Date",
            "Salary",
            "Notes",
            "Created At",
            "Updated At",
        ]
        worksheet.append(headers)

        for employee in self.get_employee_export_queryset():
            worksheet.append([
                employee.employee_id,
                employee.full_name,
                getattr(employee.user, "email", "") or "",
                employee.email or "",
                employee.phone or "",
                employee.company.name if employee.company_id else "",
                employee.department.name if employee.department_id else "",
                employee.branch.name if employee.branch_id else "",
                employee.section.name if employee.section_id else "",
                employee.job_title.name if employee.job_title_id else "",
                employee.hire_date.isoformat() if employee.hire_date else "",
                employee.get_employment_status_display(),
                "Yes" if employee.is_active else "No",
                employee.passport_issue_date.isoformat() if employee.passport_issue_date else "",
                employee.passport_expiry_date.isoformat() if employee.passport_expiry_date else "",
                employee.civil_id_issue_date.isoformat() if employee.civil_id_issue_date else "",
                employee.civil_id_expiry_date.isoformat() if employee.civil_id_expiry_date else "",
                str(employee.salary) if employee.salary is not None else "",
                employee.notes or "",
                timezone.localtime(employee.created_at).strftime("%Y-%m-%d %H:%M:%S") if employee.created_at else "",
                timezone.localtime(employee.updated_at).strftime("%Y-%m-%d %H:%M:%S") if employee.updated_at else "",
            ])

        self.style_sheet(worksheet, headers)
        filename = f"employee_master_data_{timezone.localtime().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        return self.build_workbook_response(workbook, filename)

    def export_attendance_data(self, start_date=None, end_date=None):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Attendance"

        headers = [
            "Attendance Date",
            "Employee ID",
            "Employee Name",
            "Company",
            "Department",
            "Branch",
            "Section",
            "Job Title",
            "Day Status",
            "Clock In",
            "Clock Out",
            "Scheduled Hours",
            "Worked Hours",
            "Late Minutes",
            "Early Departure Minutes",
            "Overtime Minutes",
            "Paid Day",
            "Source",
            "Linked Leave",
            "Linked Action Record",
            "Notes",
            "Created By",
            "Updated By",
            "Created At",
            "Updated At",
        ]
        worksheet.append(headers)

        for entry in self.get_attendance_export_queryset(start_date=start_date, end_date=end_date):
            worksheet.append([
                entry.attendance_date.isoformat() if entry.attendance_date else "",
                entry.employee.employee_id if entry.employee_id else "",
                entry.employee.full_name if entry.employee_id else "",
                entry.employee.company.name if entry.employee and entry.employee.company_id else "",
                entry.employee.department.name if entry.employee and entry.employee.department_id else "",
                entry.employee.branch.name if entry.employee and entry.employee.branch_id else "",
                entry.employee.section.name if entry.employee and entry.employee.section_id else "",
                entry.employee.job_title.name if entry.employee and entry.employee.job_title_id else "",
                entry.get_day_status_display(),
                entry.clock_in_time.strftime("%H:%M") if entry.clock_in_time else "",
                entry.clock_out_time.strftime("%H:%M") if entry.clock_out_time else "",
                str(entry.scheduled_hours),
                str(entry.worked_hours),
                entry.late_minutes,
                entry.early_departure_minutes,
                entry.overtime_minutes,
                "Yes" if entry.is_paid_day else "No",
                entry.get_source_display(),
                entry.linked_leave.get_leave_type_display() if entry.linked_leave_id else "",
                getattr(entry.linked_action_record, "title", "") if entry.linked_action_record_id else "",
                entry.notes or "",
                entry.created_by or "",
                entry.updated_by or "",
                timezone.localtime(entry.created_at).strftime("%Y-%m-%d %H:%M:%S") if entry.created_at else "",
                timezone.localtime(entry.updated_at).strftime("%Y-%m-%d %H:%M:%S") if entry.updated_at else "",
            ])

        self.style_sheet(worksheet, headers)
        suffix_parts = []
        if start_date:
            suffix_parts.append(f"from_{start_date.isoformat()}")
        if end_date:
            suffix_parts.append(f"to_{end_date.isoformat()}")
        suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
        filename = f"attendance_export{suffix}_{timezone.localtime().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        return self.build_workbook_response(workbook, filename)

    def export_leave_data(self, start_date=None, end_date=None):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Leave Records"

        headers = [
            "Employee ID",
            "Employee Name",
            "Company",
            "Department",
            "Branch",
            "Section",
            "Job Title",
            "Leave Type",
            "Start Date",
            "End Date",
            "Total Days",
            "Status",
            "Current Stage",
            "Reason",
            "Approval Note",
            "Requested By",
            "Reviewed By",
            "Approved By",
            "Rejected By",
            "Cancelled By",
            "Supervisor Reviewed By",
            "Operations Reviewed By",
            "HR Reviewed By",
            "Supervisor Review Note",
            "Operations Review Note",
            "HR Review Note",
            "Finalized At",
            "Created At",
            "Updated At",
        ]
        worksheet.append(headers)

        for leave_record in self.get_leave_export_queryset(start_date=start_date, end_date=end_date):
            worksheet.append([
                leave_record.employee.employee_id if leave_record.employee_id else "",
                leave_record.employee.full_name if leave_record.employee_id else "",
                leave_record.employee.company.name if leave_record.employee and leave_record.employee.company_id else "",
                leave_record.employee.department.name if leave_record.employee and leave_record.employee.department_id else "",
                leave_record.employee.branch.name if leave_record.employee and leave_record.employee.branch_id else "",
                leave_record.employee.section.name if leave_record.employee and leave_record.employee.section_id else "",
                leave_record.employee.job_title.name if leave_record.employee and leave_record.employee.job_title_id else "",
                leave_record.get_leave_type_display(),
                leave_record.start_date.isoformat() if leave_record.start_date else "",
                leave_record.end_date.isoformat() if leave_record.end_date else "",
                leave_record.total_days,
                leave_record.get_status_display(),
                leave_record.get_current_stage_display(),
                leave_record.reason or "",
                leave_record.approval_note or "",
                leave_record.requested_by.get_username() if leave_record.requested_by_id else "",
                leave_record.reviewed_by.get_username() if leave_record.reviewed_by_id else "",
                leave_record.approved_by.get_username() if leave_record.approved_by_id else "",
                leave_record.rejected_by.get_username() if leave_record.rejected_by_id else "",
                leave_record.cancelled_by.get_username() if leave_record.cancelled_by_id else "",
                leave_record.supervisor_reviewed_by.get_username() if leave_record.supervisor_reviewed_by_id else "",
                leave_record.operations_reviewed_by.get_username() if leave_record.operations_reviewed_by_id else "",
                leave_record.hr_reviewed_by.get_username() if leave_record.hr_reviewed_by_id else "",
                leave_record.supervisor_review_note or "",
                leave_record.operations_review_note or "",
                leave_record.hr_review_note or "",
                timezone.localtime(leave_record.finalized_at).strftime("%Y-%m-%d %H:%M:%S") if leave_record.finalized_at else "",
                timezone.localtime(leave_record.created_at).strftime("%Y-%m-%d %H:%M:%S") if leave_record.created_at else "",
                timezone.localtime(leave_record.updated_at).strftime("%Y-%m-%d %H:%M:%S") if leave_record.updated_at else "",
            ])

        self.style_sheet(worksheet, headers)
        suffix_parts = []
        if start_date:
            suffix_parts.append(f"from_{start_date.isoformat()}")
        if end_date:
            suffix_parts.append(f"to_{end_date.isoformat()}")
        suffix = "_" + "_".join(suffix_parts) if suffix_parts else ""
        filename = f"leave_records_export{suffix}_{timezone.localtime().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        return self.build_workbook_response(workbook, filename)

    def export_backup_audit_data(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Backup Audit"

        headers = [
            "Backup File Name",
            "Created At",
            "Size (Bytes)",
            "Size (MB)",
            "Save Path",
        ]
        worksheet.append(headers)

        for backup in self.get_latest_backups():
            worksheet.append([
                backup["name"],
                backup["modified_at"].strftime("%Y-%m-%d %H:%M:%S"),
                backup["size_bytes"],
                backup["size_mb"],
                backup["path"],
            ])

        self.style_sheet(worksheet, headers)
        filename = f"backup_audit_{timezone.localtime().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        return self.build_workbook_response(workbook, filename)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        include_paths = self.get_include_paths()
        latest_backups = self.get_latest_backups()
        context.update(
            {
                "backup_root": self.get_backup_root(),
                "include_paths": [str(path.relative_to(settings.BASE_DIR)) for path in include_paths],
                "latest_backups": latest_backups[: self.backup_table_limit],
                "backup_count": len(latest_backups),
                "has_backups": bool(latest_backups),
                "employee_export_count": self.get_employee_export_queryset().count(),
                "attendance_export_count": EmployeeAttendanceLedger.objects.count(),
                "leave_export_count": EmployeeLeave.objects.count(),
                "today": timezone.localdate(),
            }
        )
        return context
