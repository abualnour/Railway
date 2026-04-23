from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Company


class ReviewCycle(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_ACTIVE = "active"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_ACTIVE, "Active"),
        (STATUS_CLOSED, "Closed"),
    ]

    title = models.CharField(max_length=255)
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="review_cycles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-id"]

    def __str__(self):
        return f"{self.title} - {self.company.name}"

    def clean(self):
        errors = {}
        if self.period_end and self.period_start and self.period_end < self.period_start:
            errors["period_end"] = "Review cycle end date cannot be earlier than the start date."
        if errors:
            raise ValidationError(errors)

    @property
    def is_locked(self):
        return self.status == self.STATUS_CLOSED

    def clone_as_draft(self):
        return ReviewCycle.objects.create(
            title=f"{self.title} (Copy)",
            period_start=self.period_start,
            period_end=self.period_end,
            status=self.STATUS_DRAFT,
            company=self.company,
        )


class PerformanceReview(models.Model):
    RATING_UNSATISFACTORY = "1"
    RATING_NEEDS_IMPROVEMENT = "2"
    RATING_MEETS_EXPECTATIONS = "3"
    RATING_EXCEEDS_EXPECTATIONS = "4"
    RATING_OUTSTANDING = "5"

    OVERALL_RATING_CHOICES = [
        (RATING_UNSATISFACTORY, "1 - Unsatisfactory"),
        (RATING_NEEDS_IMPROVEMENT, "2 - Needs Improvement"),
        (RATING_MEETS_EXPECTATIONS, "3 - Meets Expectations"),
        (RATING_EXCEEDS_EXPECTATIONS, "4 - Exceeds Expectations"),
        (RATING_OUTSTANDING, "5 - Outstanding"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_ACKNOWLEDGED = "acknowledged"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_ACKNOWLEDGED, "Acknowledged"),
    ]

    cycle = models.ForeignKey(
        ReviewCycle,
        on_delete=models.CASCADE,
        related_name="performance_reviews",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="performance_reviews",
    )
    reviewer = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="reviews_given",
    )
    overall_rating = models.CharField(
        max_length=2,
        choices=OVERALL_RATING_CHOICES,
        default=RATING_MEETS_EXPECTATIONS,
    )
    strengths = models.TextField()
    areas_for_improvement = models.TextField()
    goals_next_period = models.TextField()
    employee_comments = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="created_performance_reviews",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-cycle__period_start", "-updated_at", "-id"]
        unique_together = ("cycle", "employee")

    def __str__(self):
        return f"{self.employee.full_name} - {self.cycle.title}"

    def clean(self):
        errors = {}
        if self.cycle_id and self.employee_id and self.employee.company_id != self.cycle.company_id:
            errors["cycle"] = "The selected review cycle must belong to the employee's company."
        if self.employee_id and self.reviewer_id and self.employee_id == self.reviewer_id:
            errors["reviewer"] = "Reviewer cannot be the same employee being reviewed."
        if self.reviewer_id and self.employee_id and self.reviewer.company_id != self.employee.company_id:
            errors["reviewer"] = "Reviewer must belong to the same company as the employee."
        if errors:
            raise ValidationError(errors)

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def acknowledge(self, *, employee_comments=""):
        self.status = self.STATUS_ACKNOWLEDGED
        if employee_comments:
            self.employee_comments = employee_comments
        self.acknowledged_at = timezone.now()
        self.save(update_fields=["status", "employee_comments", "acknowledged_at", "updated_at"])

    @property
    def is_locked(self):
        return bool(self.cycle_id and self.cycle.status == ReviewCycle.STATUS_CLOSED)


class PerformanceReviewComment(models.Model):
    review = models.ForeignKey(
        PerformanceReview,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="performance_review_comments",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.author_display_name} - {self.review}"

    @property
    def author_display_name(self):
        return self.author.get_full_name() or getattr(self.author, "username", "System")
