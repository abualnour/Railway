from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Branch, Department


def candidate_cv_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.job_posting.title or f"job-{instance.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.full_name or f"candidate-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/cvs/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


def candidate_attachment_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.candidate.job_posting.title or f"job-{instance.candidate.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.candidate.full_name or f"candidate-{instance.candidate_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/attachments/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


def candidate_offer_letter_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    posting_slug = (instance.job_posting.title or f"job-{instance.job_posting_id}").strip().replace(" ", "-").lower()
    candidate_slug = (instance.full_name or f"candidate-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"recruitment/offers/{posting_slug}/{candidate_slug}/{unique_name}{extension}"


class JobPosting(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    title = models.CharField(max_length=255)
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="job_postings",
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="job_postings",
    )
    description = models.TextField()
    requirements = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    posted_date = models.DateField(default=timezone.localdate)
    closing_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_job_postings",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-posted_date", "-created_at", "title"]

    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        if self.branch_id and self.department_id and self.branch.company_id != self.department.company_id:
            errors["branch"] = "Selected branch must belong to the same company as the department."
        if self.closing_date and self.posted_date and self.closing_date < self.posted_date:
            errors["closing_date"] = "Closing date cannot be earlier than the posted date."
        if errors:
            raise ValidationError(errors)


class Candidate(models.Model):
    STATUS_APPLIED = "applied"
    STATUS_SCREENING = "screening"
    STATUS_INTERVIEW = "interview"
    STATUS_OFFER = "offer"
    STATUS_HIRED = "hired"
    STATUS_REJECTED = "rejected"

    STATUS_CHOICES = [
        (STATUS_APPLIED, "Applied"),
        (STATUS_SCREENING, "Screening"),
        (STATUS_INTERVIEW, "Interview"),
        (STATUS_OFFER, "Offer"),
        (STATUS_HIRED, "Hired"),
        (STATUS_REJECTED, "Rejected"),
    ]

    OFFER_STATUS_NOT_SENT = "not_sent"
    OFFER_STATUS_PENDING = "pending"
    OFFER_STATUS_ACCEPTED = "accepted"
    OFFER_STATUS_DECLINED = "declined"

    OFFER_STATUS_CHOICES = [
        (OFFER_STATUS_NOT_SENT, "Not Sent"),
        (OFFER_STATUS_PENDING, "Pending Response"),
        (OFFER_STATUS_ACCEPTED, "Accepted"),
        (OFFER_STATUS_DECLINED, "Declined"),
    ]

    job_posting = models.ForeignKey(
        JobPosting,
        on_delete=models.CASCADE,
        related_name="candidates",
    )
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50)
    nationality = models.CharField(max_length=100)
    cv_file = models.FileField(upload_to=candidate_cv_upload_to)
    cover_letter = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_APPLIED)
    applied_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)
    offer_letter_file = models.FileField(
        upload_to=candidate_offer_letter_upload_to,
        null=True,
        blank=True,
    )
    offer_sent_date = models.DateField(null=True, blank=True)
    offer_expiry_date = models.DateField(null=True, blank=True)
    offer_status = models.CharField(
        max_length=20,
        choices=OFFER_STATUS_CHOICES,
        default=OFFER_STATUS_NOT_SENT,
    )
    offer_decision_at = models.DateTimeField(null=True, blank=True)
    offer_decision_note = models.TextField(blank=True)
    recruiter_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="owned_recruitment_candidates",
        null=True,
        blank=True,
    )
    hired_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="recruitment_candidates",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-applied_at", "full_name"]

    def __str__(self):
        return f"{self.full_name} - {self.job_posting.title}"

    @property
    def latest_interview(self):
        return self.interviews.order_by("-scheduled_at", "-id").first()

    @property
    def days_in_pipeline(self):
        applied_date = timezone.localtime(self.applied_at).date() if self.applied_at else timezone.localdate()
        return max((timezone.localdate() - applied_date).days, 0)

    def clean(self):
        errors = {}
        if self.offer_sent_date and self.offer_expiry_date and self.offer_expiry_date < self.offer_sent_date:
            errors["offer_expiry_date"] = "Offer expiry date cannot be earlier than the offer sent date."
        if self.offer_status in {self.OFFER_STATUS_ACCEPTED, self.OFFER_STATUS_DECLINED} and not self.offer_decision_at:
            self.offer_decision_at = timezone.now()
        if errors:
            raise ValidationError(errors)


class CandidateStageAction(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="stage_actions",
    )
    stage = models.CharField(max_length=50)
    action_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="candidate_stage_actions",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.candidate.full_name} - {self.stage}"


class CandidateInterview(models.Model):
    INTERVIEW_TYPE_PHONE = "phone"
    INTERVIEW_TYPE_VIDEO = "video"
    INTERVIEW_TYPE_IN_PERSON = "in_person"

    INTERVIEW_TYPE_CHOICES = [
        (INTERVIEW_TYPE_PHONE, "Phone"),
        (INTERVIEW_TYPE_VIDEO, "Video"),
        (INTERVIEW_TYPE_IN_PERSON, "In Person"),
    ]

    RECOMMENDATION_STRONG_YES = "strong_yes"
    RECOMMENDATION_YES = "yes"
    RECOMMENDATION_HOLD = "hold"
    RECOMMENDATION_NO = "no"

    RECOMMENDATION_CHOICES = [
        (RECOMMENDATION_STRONG_YES, "Strong Yes"),
        (RECOMMENDATION_YES, "Yes"),
        (RECOMMENDATION_HOLD, "Hold"),
        (RECOMMENDATION_NO, "No"),
    ]

    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="interviews",
    )
    scheduled_at = models.DateTimeField()
    interview_type = models.CharField(max_length=20, choices=INTERVIEW_TYPE_CHOICES, default=INTERVIEW_TYPE_IN_PERSON)
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="candidate_interviews",
        null=True,
        blank=True,
    )
    location = models.CharField(max_length=255, blank=True)
    note = models.TextField(blank=True)
    outcome = models.TextField(blank=True)
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    recommendation = models.CharField(
        max_length=20,
        choices=RECOMMENDATION_CHOICES,
        blank=True,
        default="",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scheduled_at", "id"]

    def __str__(self):
        return f"{self.candidate.full_name} interview on {self.scheduled_at:%Y-%m-%d %H:%M}"

    def clean(self):
        errors = {}
        if self._state.adding and self.scheduled_at and self.scheduled_at < timezone.now():
            errors["scheduled_at"] = "Interview time cannot be in the past."
        if self.score is not None and self.score > 100:
            errors["score"] = "Interview score cannot be greater than 100."
        if errors:
            raise ValidationError(errors)


class CandidateInterviewFeedback(models.Model):
    interview = models.ForeignKey(
        CandidateInterview,
        on_delete=models.CASCADE,
        related_name="feedback_entries",
    )
    interviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="candidate_interview_feedback",
    )
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    recommendation = models.CharField(
        max_length=20,
        choices=CandidateInterview.RECOMMENDATION_CHOICES,
        blank=True,
    )
    strengths = models.TextField(blank=True)
    concerns = models.TextField(blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        unique_together = ("interview", "interviewer")

    def __str__(self):
        return f"{self.interview.candidate.full_name} feedback by {self.interviewer}"

    def clean(self):
        errors = {}
        if self.score is not None and self.score > 100:
            errors["score"] = "Feedback score cannot be greater than 100."
        if errors:
            raise ValidationError(errors)


class CandidateAttachment(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    title = models.CharField(max_length=255)
    file = models.FileField(upload_to=candidate_attachment_upload_to)
    notes = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="candidate_attachments",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.candidate.full_name} - {self.title}"
