from django.db import models
from django.utils import timezone

from organization.models import Company


class HRPolicy(models.Model):
    CATEGORY_POLICY = "policy"
    CATEGORY_BENEFIT = "benefit"
    CATEGORY_COMPLIANCE = "compliance"
    CATEGORY_ONBOARDING = "onboarding"

    CATEGORY_CHOICES = [
        (CATEGORY_POLICY, "Policy"),
        (CATEGORY_BENEFIT, "Benefit"),
        (CATEGORY_COMPLIANCE, "Compliance"),
        (CATEGORY_ONBOARDING, "Onboarding"),
    ]

    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="hr_policies",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default=CATEGORY_POLICY)
    description = models.TextField(blank=True)
    effective_date = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]
        indexes = [
            models.Index(fields=["company", "category", "is_active"]),
            models.Index(fields=["is_active", "effective_date"]),
        ]
        verbose_name = "HR Policy"
        verbose_name_plural = "HR Policies"

    def __str__(self):
        company_name = self.company.name if self.company else "Global"
        return f"{self.title} ({company_name})"


class HRAnnouncement(models.Model):
    AUDIENCE_ALL = "all"
    AUDIENCE_EMPLOYEES = "employees"
    AUDIENCE_MANAGEMENT = "management"
    AUDIENCE_HR = "hr"

    AUDIENCE_CHOICES = [
        (AUDIENCE_ALL, "All Users"),
        (AUDIENCE_EMPLOYEES, "Employees"),
        (AUDIENCE_MANAGEMENT, "Management"),
        (AUDIENCE_HR, "HR Team"),
    ]

    title = models.CharField(max_length=200)
    audience = models.CharField(max_length=30, choices=AUDIENCE_CHOICES, default=AUDIENCE_ALL)
    message = models.TextField()
    published_at = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-id"]
        indexes = [
            models.Index(fields=["audience", "is_active", "-published_at"]),
        ]
        verbose_name = "HR Announcement"
        verbose_name_plural = "HR Announcements"

    def __str__(self):
        return self.title
