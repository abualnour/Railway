from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, RegexValidator
from django.db import models

from employees.models import Employee


def expense_receipt_upload_path(instance, filename):
    from pathlib import Path
    from uuid import uuid4

    extension = Path(filename).suffix.lower()
    employee_id = instance.employee.employee_id if instance.employee_id else "unassigned"
    return f"finance/expense-claims/{employee_id}/{uuid4().hex}{extension}"


class ExpenseClaim(models.Model):
    CATEGORY_TRAVEL = "travel"
    CATEGORY_ACCOMMODATION = "accommodation"
    CATEGORY_MEALS = "meals"
    CATEGORY_SUPPLIES = "supplies"
    CATEGORY_COMMUNICATION = "communication"
    CATEGORY_OTHER = "other"

    CATEGORY_CHOICES = [
        (CATEGORY_TRAVEL, "Travel"),
        (CATEGORY_ACCOMMODATION, "Accommodation"),
        (CATEGORY_MEALS, "Meals"),
        (CATEGORY_SUPPLIES, "Supplies"),
        (CATEGORY_COMMUNICATION, "Communication"),
        (CATEGORY_OTHER, "Other"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_PAID, "Paid"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="expense_claims",
    )
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default=CATEGORY_OTHER)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(
        max_length=3,
        default="KWD",
        validators=[
            RegexValidator(
                regex=r"^[A-Z]{3}$",
                message="Currency must be a 3-letter ISO code.",
            )
        ],
    )
    expense_date = models.DateField()
    receipt_file = models.FileField(
        upload_to=expense_receipt_upload_path,
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf", "jpg", "jpeg", "png", "webp"]
            )
        ],
    )
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="reviewed_expense_claims",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-expense_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["employee", "status", "-expense_date"]),
            models.Index(fields=["status", "-created_at"]),
        ]
        verbose_name = "Expense Claim"
        verbose_name_plural = "Expense Claims"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title} ({self.amount} {self.currency})"

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors["amount"] = "Expense amount must be greater than zero."
        if errors:
            raise ValidationError(errors)

# Create your models here.
