from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from employees.models import Employee


class CompanyAsset(models.Model):
    CATEGORY_LAPTOP = "laptop"
    CATEGORY_PHONE = "phone"
    CATEGORY_VEHICLE = "vehicle"
    CATEGORY_UNIFORM = "uniform"
    CATEGORY_KEY = "key"
    CATEGORY_TOOL = "tool"
    CATEGORY_OTHER = "other"

    CATEGORY_CHOICES = [
        (CATEGORY_LAPTOP, "Laptop"),
        (CATEGORY_PHONE, "Phone"),
        (CATEGORY_VEHICLE, "Vehicle"),
        (CATEGORY_UNIFORM, "Uniform"),
        (CATEGORY_KEY, "Key"),
        (CATEGORY_TOOL, "Tool"),
        (CATEGORY_OTHER, "Other"),
    ]

    CONDITION_NEW = "new"
    CONDITION_GOOD = "good"
    CONDITION_FAIR = "fair"
    CONDITION_DAMAGED = "damaged"

    CONDITION_CHOICES = [
        (CONDITION_NEW, "New"),
        (CONDITION_GOOD, "Good"),
        (CONDITION_FAIR, "Fair"),
        (CONDITION_DAMAGED, "Damaged"),
    ]

    asset_code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER)
    serial_number = models.CharField(max_length=100, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default=CONDITION_GOOD)
    notes = models.TextField(blank=True)
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_code", "name"]
        indexes = [
            models.Index(fields=["category", "is_available"]),
            models.Index(fields=["condition", "is_available"]),
            models.Index(fields=["serial_number"]),
        ]
        verbose_name = "Company Asset"
        verbose_name_plural = "Company Assets"

    def __str__(self):
        return f"{self.asset_code} - {self.name}"

    @property
    def current_assignee(self):
        assignment = self.assignments.select_related("employee").filter(returned_date__isnull=True).first()
        return assignment.employee if assignment else None


class AssetAssignment(models.Model):
    asset = models.ForeignKey(
        CompanyAsset,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="asset_assignments",
    )
    assigned_date = models.DateField()
    returned_date = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="asset_assignments_created",
    )
    condition_on_assign = models.CharField(
        max_length=20,
        choices=CompanyAsset.CONDITION_CHOICES,
        default=CompanyAsset.CONDITION_GOOD,
    )
    condition_on_return = models.CharField(
        max_length=20,
        choices=CompanyAsset.CONDITION_CHOICES,
        blank=True,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_date", "-id"]
        indexes = [
            models.Index(fields=["asset", "returned_date"]),
            models.Index(fields=["employee", "-assigned_date"]),
            models.Index(fields=["assigned_by", "-created_at"]),
        ]
        verbose_name = "Asset Assignment"
        verbose_name_plural = "Asset Assignments"

    def __str__(self):
        return f"{self.asset.asset_code} assigned to {self.employee.full_name}"

    @property
    def is_active(self):
        return self.returned_date is None

    def clean(self):
        errors = {}
        if self.returned_date and self.assigned_date and self.returned_date < self.assigned_date:
            errors["returned_date"] = "Returned date cannot be earlier than assigned date."
        if not self.pk and self.asset_id:
            active_assignment_exists = AssetAssignment.objects.filter(
                asset_id=self.asset_id,
                returned_date__isnull=True,
            ).exists()
            if active_assignment_exists:
                errors["asset"] = "This asset already has an active assignment."
        if self.returned_date and not self.condition_on_return:
            errors["condition_on_return"] = "Condition on return is required when an asset is returned."
        if errors:
            raise ValidationError(errors)

# Create your models here.
