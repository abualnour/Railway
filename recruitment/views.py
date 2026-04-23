from datetime import timedelta
import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from employees.access import is_admin_compatible as is_admin_compatible_role, is_hr_user as is_hr_user_role
from employees.models import Employee, EmployeeRequiredSubmission
from notifications.models import InAppNotification, build_in_app_notification
from notifications.views import persist_in_app_notifications

from .forms import (
    CandidateAttachmentForm,
    CandidateFilterForm,
    CandidateForm,
    CandidateHireForm,
    CandidateInterviewForm,
    JobPostingForm,
)
from .models import Candidate, CandidateAttachment, CandidateInterview, CandidateStageAction, JobPosting


def can_manage_recruitment(user):
    return bool(
        user
        and user.is_authenticated
        and (is_admin_compatible_role(user) or is_hr_user_role(user))
    )


def get_recruitment_recipients(exclude_users=None):
    user_model = get_user_model()
    excluded_user_ids = {
        user.pk
        for user in exclude_users or []
        if user and getattr(user, "pk", None) is not None
    }
    recipients = []
    for user in user_model.objects.filter(is_active=True).order_by("id"):
        if user.pk in excluded_user_ids:
            continue
        if can_manage_recruitment(user):
            recipients.append(user)
    return recipients


def notify_recruitment_team(*, title, body, action_url="", level=InAppNotification.LEVEL_INFO, exclude_users=None):
    notifications = []
    for recipient in get_recruitment_recipients(exclude_users=exclude_users):
        notification = build_in_app_notification(
            recipient=recipient,
            title=title,
            body=body,
            category=InAppNotification.CATEGORY_HR,
            action_url=action_url,
            level=level,
            exclude_users=exclude_users,
        )
        if notification is not None:
            notifications.append(notification)
    return persist_in_app_notifications(notifications)


def _notification_exists_today(*, recipient, title, action_url, reference_date):
    return InAppNotification.objects.filter(
        recipient=recipient,
        category=InAppNotification.CATEGORY_HR,
        title=title,
        action_url=action_url,
        created_at__date=reference_date,
    ).exists()


def trigger_recruitment_alerts(reference_date=None):
    reference_date = reference_date or timezone.localdate()
    now = timezone.now()
    interview_cutoff = now + timedelta(days=1)
    offer_cutoff = reference_date + timedelta(days=7)
    aging_threshold_days = 14
    notifications = []

    upcoming_interviews = CandidateInterview.objects.select_related(
        "candidate",
        "candidate__job_posting",
        "candidate__job_posting__branch",
        "interviewer",
    ).filter(
        scheduled_at__gte=now,
        scheduled_at__lte=interview_cutoff,
    ).order_by("scheduled_at", "id")

    for interview in upcoming_interviews:
        action_url = reverse("recruitment:candidate_detail", kwargs={"pk": interview.candidate_id})
        title = f"Interview due soon for {interview.candidate.full_name}"
        body = (
            f"{interview.get_interview_type_display()} interview for {interview.candidate.full_name} "
            f"is scheduled on {timezone.localtime(interview.scheduled_at).strftime('%B %d, %Y %I:%M %p')} "
            f"for {interview.candidate.job_posting.title}."
        )
        for recipient in get_recruitment_recipients():
            if _notification_exists_today(recipient=recipient, title=title, action_url=action_url, reference_date=reference_date):
                continue
            notification = build_in_app_notification(
                recipient=recipient,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_HR,
                action_url=action_url,
                level=InAppNotification.LEVEL_WARNING,
            )
            if notification is not None:
                notifications.append(notification)

    expiring_offers = Candidate.objects.select_related("job_posting", "job_posting__branch").filter(
        status=Candidate.STATUS_OFFER,
        offer_expiry_date__isnull=False,
        offer_expiry_date__gte=reference_date,
        offer_expiry_date__lte=offer_cutoff,
    ).order_by("offer_expiry_date", "full_name", "id")

    for candidate in expiring_offers:
        days_remaining = (candidate.offer_expiry_date - reference_date).days
        action_url = reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk})
        title = f"Offer expiring soon for {candidate.full_name}"
        body = (
            f"The offer for {candidate.full_name} expires on "
            f"{candidate.offer_expiry_date.strftime('%B %d, %Y')} "
            f"({days_remaining} days remaining) for {candidate.job_posting.title}."
        )
        for recipient in get_recruitment_recipients():
            if _notification_exists_today(recipient=recipient, title=title, action_url=action_url, reference_date=reference_date):
                continue
            notification = build_in_app_notification(
                recipient=recipient,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_HR,
                action_url=action_url,
                level=InAppNotification.LEVEL_WARNING,
            )
            if notification is not None:
                notifications.append(notification)

    aging_candidates = Candidate.objects.select_related("job_posting", "job_posting__branch").filter(
        status__in=[Candidate.STATUS_APPLIED, Candidate.STATUS_SCREENING, Candidate.STATUS_INTERVIEW],
        applied_at__date__lte=reference_date - timedelta(days=aging_threshold_days),
    ).order_by("applied_at", "full_name", "id")

    for candidate in aging_candidates:
        action_url = reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk})
        title = f"Candidate aging alert for {candidate.full_name}"
        body = (
            f"{candidate.full_name} has been in the pipeline for {candidate.days_in_pipeline} days "
            f"at {candidate.get_status_display()} for {candidate.job_posting.title}."
        )
        for recipient in get_recruitment_recipients():
            if _notification_exists_today(recipient=recipient, title=title, action_url=action_url, reference_date=reference_date):
                continue
            notification = build_in_app_notification(
                recipient=recipient,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_HR,
                action_url=action_url,
                level=InAppNotification.LEVEL_WARNING,
            )
            if notification is not None:
                notifications.append(notification)

    return persist_in_app_notifications(notifications)


def create_onboarding_submission_requests(*, employee, created_by, hire_date, job_posting_title):
    due_date = (hire_date or timezone.localdate()) + timedelta(days=14)
    onboarding_requests = [
        (
            EmployeeRequiredSubmission.REQUEST_TYPE_CIVIL_ID_COPY,
            "Onboarding: Civil ID Copy",
            "Upload a clear copy of your Civil ID for onboarding verification.",
        ),
        (
            EmployeeRequiredSubmission.REQUEST_TYPE_PASSPORT_COPY,
            "Onboarding: Passport Copy",
            "Upload a clear copy of your passport for the employee file.",
        ),
        (
            EmployeeRequiredSubmission.REQUEST_TYPE_CONTRACT_COPY,
            "Onboarding: Signed Contract Copy",
            "Upload the signed contract copy to complete the onboarding record.",
        ),
        (
            EmployeeRequiredSubmission.REQUEST_TYPE_MEDICAL_DOCUMENT,
            "Onboarding: Medical Document",
            "Upload the required medical onboarding document or clearance.",
        ),
    ]

    created_requests = []
    for request_type, title, instructions in onboarding_requests:
        existing_request = employee.required_submissions.filter(
            request_type=request_type,
            title=title,
            status__in={
                EmployeeRequiredSubmission.STATUS_REQUESTED,
                EmployeeRequiredSubmission.STATUS_SUBMITTED,
                EmployeeRequiredSubmission.STATUS_NEEDS_CORRECTION,
            },
        ).exists()
        if existing_request:
            continue

        created_requests.append(
            EmployeeRequiredSubmission.objects.create(
                employee=employee,
                created_by=created_by,
                title=title,
                request_type=request_type,
                priority=EmployeeRequiredSubmission.PRIORITY_HIGH,
                status=EmployeeRequiredSubmission.STATUS_REQUESTED,
                instructions=(
                    f"{instructions} This onboarding checklist item was created automatically "
                    f"from the recruitment hire conversion for {job_posting_title}."
                ),
                due_date=due_date,
            )
        )

    return created_requests


class RecruitmentAccessMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not can_manage_recruitment(request.user):
            raise PermissionDenied("You do not have permission to access recruitment.")
        return super().dispatch(request, *args, **kwargs)


class JobPostingListView(RecruitmentAccessMixin, ListView):
    model = JobPosting
    template_name = "recruitment/job_posting_list.html"
    context_object_name = "job_postings"

    def get_queryset(self):
        queryset = JobPosting.objects.select_related("department", "department__company", "branch", "created_by").annotate(
            candidate_total=Count("candidates")
        )
        status = (self.request.GET.get("status") or "").strip()
        search = (self.request.GET.get("search") or "").strip()
        if status:
            queryset = queryset.filter(status=status)
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(department__name__icontains=search)
                | Q(branch__name__icontains=search)
            )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        candidate_queryset = Candidate.objects.select_related("job_posting", "job_posting__branch", "job_posting__department")
        upcoming_interviews = CandidateInterview.objects.select_related("candidate", "interviewer").filter(
            scheduled_at__gte=timezone.now()
        ).order_by("scheduled_at")[:6]
        expiring_offers = candidate_queryset.filter(
            status=Candidate.STATUS_OFFER,
            offer_expiry_date__isnull=False,
            offer_expiry_date__gte=today,
            offer_expiry_date__lte=today + timedelta(days=7),
        ).order_by("offer_expiry_date", "full_name")[:6]
        aging_candidates = candidate_queryset.filter(
            status__in=[Candidate.STATUS_APPLIED, Candidate.STATUS_SCREENING, Candidate.STATUS_INTERVIEW],
            applied_at__date__lte=today - timedelta(days=14),
        ).order_by("applied_at", "full_name")[:6]
        status_totals = {
            Candidate.STATUS_APPLIED: candidate_queryset.filter(status=Candidate.STATUS_APPLIED).count(),
            Candidate.STATUS_SCREENING: candidate_queryset.filter(status=Candidate.STATUS_SCREENING).count(),
            Candidate.STATUS_INTERVIEW: candidate_queryset.filter(status=Candidate.STATUS_INTERVIEW).count(),
            Candidate.STATUS_OFFER: candidate_queryset.filter(status=Candidate.STATUS_OFFER).count(),
            Candidate.STATUS_HIRED: candidate_queryset.filter(status=Candidate.STATUS_HIRED).count(),
            Candidate.STATUS_REJECTED: candidate_queryset.filter(status=Candidate.STATUS_REJECTED).count(),
        }
        max_status_total = max(status_totals.values()) if status_totals else 0
        funnel_metrics = [
            {
                "label": "Applied",
                "count": status_totals[Candidate.STATUS_APPLIED],
                "width": int((status_totals[Candidate.STATUS_APPLIED] / max_status_total) * 100) if max_status_total else 0,
            },
            {
                "label": "Screening",
                "count": status_totals[Candidate.STATUS_SCREENING],
                "width": int((status_totals[Candidate.STATUS_SCREENING] / max_status_total) * 100) if max_status_total else 0,
            },
            {
                "label": "Interview",
                "count": status_totals[Candidate.STATUS_INTERVIEW],
                "width": int((status_totals[Candidate.STATUS_INTERVIEW] / max_status_total) * 100) if max_status_total else 0,
            },
            {
                "label": "Offer",
                "count": status_totals[Candidate.STATUS_OFFER],
                "width": int((status_totals[Candidate.STATUS_OFFER] / max_status_total) * 100) if max_status_total else 0,
            },
            {
                "label": "Hired",
                "count": status_totals[Candidate.STATUS_HIRED],
                "width": int((status_totals[Candidate.STATUS_HIRED] / max_status_total) * 100) if max_status_total else 0,
            },
        ]
        branch_funnel = list(
            candidate_queryset.values("job_posting__branch__name")
            .annotate(
                total=Count("id"),
                hired=Count("id", filter=Q(status=Candidate.STATUS_HIRED)),
                offers=Count("id", filter=Q(status=Candidate.STATUS_OFFER)),
            )
            .order_by("-total", "job_posting__branch__name")[:5]
        )
        for branch_summary in branch_funnel:
            total = branch_summary["total"] or 0
            branch_summary["name"] = branch_summary.pop("job_posting__branch__name") or "Unassigned Branch"
            branch_summary["hire_rate"] = int((branch_summary["hired"] / total) * 100) if total else 0

        interview_score_summary = candidate_queryset.aggregate(
            average_score=Avg("interviews__score"),
            scored_interview_total=Count("interviews__id", filter=Q(interviews__score__isnull=False)),
        )
        hired_total = status_totals[Candidate.STATUS_HIRED]
        active_pipeline_total = max(candidate_queryset.exclude(status=Candidate.STATUS_REJECTED).count(), 0)
        context.update(
            {
                "job_posting_status_choices": JobPosting.STATUS_CHOICES,
                "selected_status": (self.request.GET.get("status") or "").strip(),
                "search_query": (self.request.GET.get("search") or "").strip(),
                "job_posting_total": JobPosting.objects.count(),
                "open_job_posting_total": JobPosting.objects.filter(status=JobPosting.STATUS_OPEN).count(),
                "active_candidate_total": candidate_queryset.exclude(status=Candidate.STATUS_REJECTED).count(),
                "interview_candidate_total": candidate_queryset.filter(status=Candidate.STATUS_INTERVIEW).count(),
                "offer_candidate_total": candidate_queryset.filter(status=Candidate.STATUS_OFFER).count(),
                "hired_candidate_total": candidate_queryset.filter(status=Candidate.STATUS_HIRED).count(),
                "rejected_candidate_total": status_totals[Candidate.STATUS_REJECTED],
                "expiring_offer_total": expiring_offers.count(),
                "aging_candidate_total": aging_candidates.count(),
                "closing_soon_total": JobPosting.objects.filter(
                    status=JobPosting.STATUS_OPEN,
                    closing_date__isnull=False,
                    closing_date__gte=today,
                    closing_date__lte=today + timedelta(days=14),
                ).count(),
                "upcoming_interviews": upcoming_interviews,
                "expiring_offers": expiring_offers,
                "aging_candidates": aging_candidates,
                "funnel_metrics": funnel_metrics,
                "branch_funnel": branch_funnel,
                "average_interview_score": interview_score_summary["average_score"],
                "scored_interview_total": interview_score_summary["scored_interview_total"] or 0,
                "hire_conversion_rate": int((hired_total / active_pipeline_total) * 100) if active_pipeline_total else 0,
            }
        )
        return context


class JobPostingCreateView(RecruitmentAccessMixin, CreateView):
    model = JobPosting
    form_class = JobPostingForm
    template_name = "recruitment/job_posting_form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Job posting created successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("recruitment:job_posting_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Create Job Posting"
        context["submit_label"] = "Create Job Posting"
        return context


class JobPostingDetailView(RecruitmentAccessMixin, DetailView):
    model = JobPosting
    template_name = "recruitment/job_posting_detail.html"
    context_object_name = "job_posting"

    def get_queryset(self):
        return JobPosting.objects.select_related("department", "department__company", "branch", "created_by").prefetch_related(
            "candidates",
            "candidates__stage_actions",
            "candidates__interviews",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        candidates = self.object.candidates.all().order_by("-applied_at")
        context["candidate_filter_form"] = CandidateFilterForm(self.request.GET or None)
        context["filtered_candidates"] = candidates
        return context


class JobPostingUpdateView(RecruitmentAccessMixin, UpdateView):
    model = JobPosting
    form_class = JobPostingForm
    template_name = "recruitment/job_posting_form.html"

    def form_valid(self, form):
        messages.success(self.request, "Job posting updated successfully.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("recruitment:job_posting_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Update Job Posting"
        context["submit_label"] = "Save Changes"
        return context


class JobPostingDeleteView(RecruitmentAccessMixin, DeleteView):
    model = JobPosting
    template_name = "recruitment/job_posting_confirm_delete.html"
    success_url = reverse_lazy("recruitment:job_posting_list")

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Job posting deleted successfully.")
        return super().delete(request, *args, **kwargs)


class CandidateCreateView(RecruitmentAccessMixin, CreateView):
    model = Candidate
    form_class = CandidateForm
    template_name = "recruitment/candidate_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.job_posting = get_object_or_404(JobPosting.objects.select_related("department", "branch"), pk=kwargs["job_posting_pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.job_posting = self.job_posting
        response = super().form_valid(form)
        CandidateStageAction.objects.create(
            candidate=self.object,
            stage=self.object.status,
            action_by=self.request.user,
            note="Candidate application was added to the recruitment pipeline.",
        )
        notify_recruitment_team(
            title=f"New candidate added for {self.job_posting.title}",
            body=(
                f"{self.object.full_name} was added to the recruitment pipeline for "
                f"{self.job_posting.title} in {self.job_posting.branch.name}."
            ),
            action_url=reverse("recruitment:candidate_detail", kwargs={"pk": self.object.pk}),
            exclude_users=[self.request.user],
        )
        messages.success(self.request, "Candidate added successfully.")
        return response

    def get_success_url(self):
        return reverse("recruitment:candidate_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job_posting"] = self.job_posting
        context["page_title"] = "Add Candidate"
        context["submit_label"] = "Add Candidate"
        return context


class CandidateDetailView(RecruitmentAccessMixin, DetailView):
    model = Candidate
    template_name = "recruitment/candidate_detail.html"
    context_object_name = "candidate"

    def get_queryset(self):
        return Candidate.objects.select_related(
            "job_posting",
            "job_posting__department",
            "job_posting__department__company",
            "job_posting__branch",
            "hired_employee",
        ).prefetch_related(
            "stage_actions",
            "stage_actions__action_by",
            "interviews",
            "interviews__interviewer",
            "attachments",
            "attachments__uploaded_by",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["interview_form"] = kwargs.get("interview_form") or CandidateInterviewForm()
        context["attachment_form"] = kwargs.get("attachment_form") or CandidateAttachmentForm()
        context["hire_form"] = kwargs.get("hire_form") or CandidateHireForm(candidate=self.object)
        context["interviews"] = self.object.interviews.select_related("interviewer").order_by("scheduled_at", "id")
        context["attachments"] = self.object.attachments.select_related("uploaded_by").order_by("-created_at", "-id")
        return context


class CandidateUpdateView(RecruitmentAccessMixin, UpdateView):
    model = Candidate
    form_class = CandidateForm
    template_name = "recruitment/candidate_form.html"

    def form_valid(self, form):
        previous_candidate = Candidate.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        stage_change_messages = []
        if previous_candidate.status != self.object.status:
            CandidateStageAction.objects.create(
                candidate=self.object,
                stage=self.object.status,
                action_by=self.request.user,
                note=(
                    f"Candidate status changed from "
                    f"{previous_candidate.get_status_display()} to {self.object.get_status_display()}."
                    + (f" Notes: {self.object.notes}" if self.object.notes else "")
                ),
            )
            stage_change_messages.append(
                f"{self.object.full_name} moved from {previous_candidate.get_status_display()} "
                f"to {self.object.get_status_display()} for {self.object.job_posting.title}."
            )
        if not previous_candidate.offer_letter_file and self.object.offer_letter_file:
            CandidateStageAction.objects.create(
                candidate=self.object,
                stage=Candidate.STATUS_OFFER,
                action_by=self.request.user,
                note="Offer letter file was added to the candidate record.",
            )
            stage_change_messages.append(f"An offer letter was added for {self.object.full_name}.")
        if stage_change_messages:
            notify_recruitment_team(
                title=f"Candidate workflow updated for {self.object.full_name}",
                body=" ".join(stage_change_messages),
                action_url=reverse("recruitment:candidate_detail", kwargs={"pk": self.object.pk}),
                exclude_users=[self.request.user],
            )
        messages.success(self.request, "Candidate updated successfully.")
        return response

    def get_success_url(self):
        return reverse("recruitment:candidate_detail", kwargs={"pk": self.object.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["job_posting"] = self.object.job_posting
        context["page_title"] = "Update Candidate"
        context["submit_label"] = "Save Candidate"
        return context


class CandidateDeleteView(RecruitmentAccessMixin, DeleteView):
    model = Candidate
    template_name = "recruitment/candidate_confirm_delete.html"

    def get_success_url(self):
        return reverse("recruitment:job_posting_detail", kwargs={"pk": self.object.job_posting_id})

    def delete(self, request, *args, **kwargs):
        messages.success(request, "Candidate deleted successfully.")
        return super().delete(request, *args, **kwargs)


class CandidateListView(RecruitmentAccessMixin, ListView):
    model = Candidate
    template_name = "recruitment/candidate_list.html"
    context_object_name = "candidates"

    def get_queryset(self):
        queryset = Candidate.objects.select_related(
            "job_posting",
            "job_posting__department",
            "job_posting__department__company",
            "job_posting__branch",
            "hired_employee",
        )
        self.filter_form = CandidateFilterForm(self.request.GET or None)
        if self.filter_form.is_valid():
            search = (self.filter_form.cleaned_data.get("search") or "").strip()
            status = self.filter_form.cleaned_data.get("status")
            department = self.filter_form.cleaned_data.get("department")
            branch = self.filter_form.cleaned_data.get("branch")
            job_posting = self.filter_form.cleaned_data.get("job_posting")

            if search:
                queryset = queryset.filter(
                    Q(full_name__icontains=search)
                    | Q(email__icontains=search)
                    | Q(phone__icontains=search)
                    | Q(nationality__icontains=search)
                    | Q(job_posting__title__icontains=search)
                )
            if status:
                queryset = queryset.filter(status=status)
            if department:
                queryset = queryset.filter(job_posting__department=department)
            if branch:
                queryset = queryset.filter(job_posting__branch=branch)
            if job_posting:
                queryset = queryset.filter(job_posting=job_posting)

        return queryset.order_by("-applied_at", "full_name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = getattr(self, "filter_form", CandidateFilterForm())
        return context


class RecruitmentCandidatesExportView(RecruitmentAccessMixin, View):
    def get(self, request):
        queryset = Candidate.objects.select_related(
            "job_posting",
            "job_posting__department",
            "job_posting__branch",
            "hired_employee",
        ).order_by("-applied_at", "full_name")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="recruitment-candidates.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Candidate",
                "Status",
                "Job Posting",
                "Department",
                "Branch",
                "Email",
                "Phone",
                "Nationality",
                "Applied At",
                "Days In Pipeline",
                "Offer Sent Date",
                "Offer Expiry Date",
                "Hired Employee",
            ]
        )
        for candidate in queryset:
            writer.writerow(
                [
                    candidate.full_name,
                    candidate.get_status_display(),
                    candidate.job_posting.title,
                    candidate.job_posting.department.name,
                    candidate.job_posting.branch.name,
                    candidate.email,
                    candidate.phone,
                    candidate.nationality,
                    timezone.localtime(candidate.applied_at).strftime("%Y-%m-%d %H:%M") if candidate.applied_at else "",
                    candidate.days_in_pipeline,
                    candidate.offer_sent_date or "",
                    candidate.offer_expiry_date or "",
                    candidate.hired_employee.employee_id if candidate.hired_employee_id else "",
                ]
            )
        return response


class RecruitmentJobPostingsExportView(RecruitmentAccessMixin, View):
    def get(self, request):
        queryset = JobPosting.objects.select_related("department", "department__company", "branch").annotate(
            candidate_total=Count("candidates"),
            hired_total=Count("candidates", filter=Q(candidates__status=Candidate.STATUS_HIRED)),
            offer_total=Count("candidates", filter=Q(candidates__status=Candidate.STATUS_OFFER)),
        ).order_by("-posted_date", "title")

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="recruitment-job-postings.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "Job Posting",
                "Status",
                "Company",
                "Department",
                "Branch",
                "Posted Date",
                "Closing Date",
                "Candidates",
                "Offers",
                "Hired",
            ]
        )
        for posting in queryset:
            writer.writerow(
                [
                    posting.title,
                    posting.get_status_display(),
                    posting.department.company.name,
                    posting.department.name,
                    posting.branch.name,
                    posting.posted_date or "",
                    posting.closing_date or "",
                    posting.candidate_total,
                    posting.offer_total,
                    posting.hired_total,
                ]
            )
        return response


class CandidateInterviewCreateView(RecruitmentAccessMixin, View):
    def post(self, request, pk):
        candidate = get_object_or_404(
            Candidate.objects.select_related("job_posting", "job_posting__department", "job_posting__branch"),
            pk=pk,
        )
        form = CandidateInterviewForm(request.POST)
        if form.is_valid():
            interview = form.save(commit=False)
            interview.candidate = candidate
            interview.save()
            CandidateStageAction.objects.create(
                candidate=candidate,
                stage=f"interview:{interview.interview_type}",
                action_by=request.user,
                note=(
                    f"Interview scheduled for {interview.scheduled_at:%B %d, %Y %I:%M %p}."
                    + (f" Score target: {interview.score}/100." if interview.score is not None else "")
                    + (f" Recommendation: {interview.get_recommendation_display()}." if interview.recommendation else "")
                    + (f" Location: {interview.location}." if interview.location else "")
                ),
            )
            if candidate.status in {Candidate.STATUS_APPLIED, Candidate.STATUS_SCREENING}:
                candidate.status = Candidate.STATUS_INTERVIEW
                candidate.save(update_fields=["status"])
            notify_recruitment_team(
                title=f"Interview scheduled for {candidate.full_name}",
                body=(
                    f"{interview.get_interview_type_display()} interview scheduled for "
                    f"{candidate.full_name} on {interview.scheduled_at:%B %d, %Y %I:%M %p}."
                ),
                action_url=reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}),
                exclude_users=[request.user],
            )
            messages.success(request, "Interview scheduled successfully.")
            return HttpResponseRedirect(reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}))

        view = CandidateDetailView()
        view.setup(request, pk=pk)
        view.object = candidate
        context = view.get_context_data(interview_form=form)
        return view.render_to_response(context)


class CandidateInterviewUpdateView(RecruitmentAccessMixin, UpdateView):
    model = CandidateInterview
    form_class = CandidateInterviewForm
    template_name = "recruitment/interview_form.html"
    context_object_name = "interview"

    def form_valid(self, form):
        previous_interview = CandidateInterview.objects.get(pk=self.object.pk)
        response = super().form_valid(form)
        CandidateStageAction.objects.create(
            candidate=self.object.candidate,
            stage=f"interview-update:{self.object.interview_type}",
            action_by=self.request.user,
            note=(
                f"Interview updated from {previous_interview.scheduled_at:%B %d, %Y %I:%M %p} "
                f"to {self.object.scheduled_at:%B %d, %Y %I:%M %p}."
                + (f" Score: {self.object.score}/100." if self.object.score is not None else "")
                + (f" Recommendation: {self.object.get_recommendation_display()}." if self.object.recommendation else "")
            ),
        )
        notify_recruitment_team(
            title=f"Interview updated for {self.object.candidate.full_name}",
            body=(
                f"The scheduled interview for {self.object.candidate.full_name} was updated to "
                f"{self.object.scheduled_at:%B %d, %Y %I:%M %p}."
            ),
            action_url=reverse("recruitment:candidate_detail", kwargs={"pk": self.object.candidate.pk}),
            exclude_users=[self.request.user],
        )
        messages.success(self.request, "Interview updated successfully.")
        return response

    def get_success_url(self):
        return reverse("recruitment:candidate_detail", kwargs={"pk": self.object.candidate_id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["candidate"] = self.object.candidate
        context["page_title"] = "Update Interview"
        context["submit_label"] = "Save Interview"
        return context


class CandidateInterviewDeleteView(RecruitmentAccessMixin, DeleteView):
    model = CandidateInterview
    template_name = "recruitment/interview_confirm_delete.html"
    context_object_name = "interview"

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        candidate = self.object.candidate
        scheduled_at_display = self.object.scheduled_at.strftime("%B %d, %Y %I:%M %p")
        CandidateStageAction.objects.create(
            candidate=candidate,
            stage="interview-delete",
            action_by=request.user,
            note=f"Interview scheduled for {scheduled_at_display} was removed from the pipeline.",
        )
        notify_recruitment_team(
            title=f"Interview removed for {candidate.full_name}",
            body=f"The scheduled interview for {candidate.full_name} on {scheduled_at_display} was removed.",
            action_url=reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}),
            exclude_users=[request.user],
            level=InAppNotification.LEVEL_WARNING,
        )
        messages.success(request, "Interview deleted successfully.")
        return super().delete(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("recruitment:candidate_detail", kwargs={"pk": self.object.candidate_id})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["candidate"] = self.object.candidate
        return context


class CandidateAttachmentCreateView(RecruitmentAccessMixin, View):
    def post(self, request, pk):
        candidate = get_object_or_404(Candidate.objects.select_related("job_posting", "job_posting__branch"), pk=pk)
        form = CandidateAttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            attachment = form.save(commit=False)
            attachment.candidate = candidate
            attachment.uploaded_by = request.user
            attachment.save()
            CandidateStageAction.objects.create(
                candidate=candidate,
                stage="attachment",
                action_by=request.user,
                note=f"Attachment '{attachment.title}' was uploaded to the candidate file.",
            )
            notify_recruitment_team(
                title=f"New attachment added for {candidate.full_name}",
                body=f"{attachment.title} was uploaded to the candidate file for {candidate.full_name}.",
                action_url=reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}),
                exclude_users=[request.user],
            )
            messages.success(request, "Attachment uploaded successfully.")
            return HttpResponseRedirect(reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}))

        view = CandidateDetailView()
        view.setup(request, pk=pk)
        view.object = candidate
        context = view.get_context_data(attachment_form=form)
        return view.render_to_response(context)


class CandidateAttachmentDeleteView(RecruitmentAccessMixin, View):
    def post(self, request, pk, attachment_pk):
        attachment = get_object_or_404(
            CandidateAttachment.objects.select_related("candidate", "candidate__job_posting"),
            pk=attachment_pk,
            candidate_id=pk,
        )
        candidate = attachment.candidate
        attachment_title = attachment.title
        attachment.delete()
        CandidateStageAction.objects.create(
            candidate=candidate,
            stage="attachment-delete",
            action_by=request.user,
            note=f"Attachment '{attachment_title}' was removed from the candidate file.",
        )
        notify_recruitment_team(
            title=f"Attachment removed for {candidate.full_name}",
            body=f"{attachment_title} was removed from the candidate file for {candidate.full_name}.",
            action_url=reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}),
            exclude_users=[request.user],
            level=InAppNotification.LEVEL_WARNING,
        )
        messages.success(request, "Attachment removed successfully.")
        return HttpResponseRedirect(reverse("recruitment:candidate_detail", kwargs={"pk": candidate.pk}))


class CandidateHireConvertView(RecruitmentAccessMixin, View):
    def post(self, request, pk):
        candidate = get_object_or_404(
            Candidate.objects.select_related(
                "job_posting",
                "job_posting__department",
                "job_posting__department__company",
                "job_posting__branch",
                "hired_employee",
            ),
            pk=pk,
        )
        form = CandidateHireForm(request.POST, candidate=candidate)
        if form.is_valid():
            employee = Employee.objects.create(
                employee_id=form.cleaned_data["employee_id"],
                full_name=candidate.full_name,
                email=candidate.email,
                phone=candidate.phone,
                nationality=candidate.nationality,
                company=form.cleaned_data["company"],
                department=form.cleaned_data["department"],
                branch=form.cleaned_data["branch"],
                section=form.cleaned_data.get("section"),
                job_title=form.cleaned_data["job_title"],
                hire_date=form.cleaned_data["hire_date"],
                salary=form.cleaned_data.get("salary"),
                notes=((form.cleaned_data.get("notes") or "").strip() or f"Hired from recruitment pipeline for {candidate.job_posting.title}."),
                is_active=True,
                employment_status=Employee.EMPLOYMENT_STATUS_ACTIVE,
            )
            candidate.status = Candidate.STATUS_HIRED
            candidate.hired_employee = employee
            candidate.save(update_fields=["status", "hired_employee"])
            onboarding_requests = create_onboarding_submission_requests(
                employee=employee,
                created_by=request.user,
                hire_date=form.cleaned_data["hire_date"],
                job_posting_title=candidate.job_posting.title,
            )
            CandidateStageAction.objects.create(
                candidate=candidate,
                stage=Candidate.STATUS_HIRED,
                action_by=request.user,
                note=(
                    f"Candidate converted to employee record {employee.employee_id}."
                    f" {len(onboarding_requests)} onboarding request(s) were created."
                ),
            )
            notify_recruitment_team(
                title=f"Candidate hired into employee record: {candidate.full_name}",
                body=(
                    f"{candidate.full_name} was converted into employee {employee.employee_id}. "
                    f"{len(onboarding_requests)} onboarding checklist item(s) were created."
                ),
                action_url=reverse("employees:employee_detail", kwargs={"pk": employee.pk}),
                exclude_users=[request.user],
                level=InAppNotification.LEVEL_SUCCESS,
            )
            messages.success(request, "Candidate converted to employee successfully.")
            return HttpResponseRedirect(reverse("employees:employee_detail", kwargs={"pk": employee.pk}))

        view = CandidateDetailView()
        view.setup(request, pk=pk)
        view.object = candidate
        context = view.get_context_data(hire_form=form)
        return view.render_to_response(context)
