from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def company_logo_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    company_slug = (instance.name or f"company-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"companies/logos/{company_slug}/{unique_name}{extension}"


def branch_image_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    company_name = instance.company.name if getattr(instance, "company_id", None) and instance.company_id else f"company-{getattr(instance, 'company_id', 'new')}"
    company_slug = str(company_name).strip().replace(" ", "-").lower()
    branch_slug = (instance.name or f"branch-{instance.pk or 'new'}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"branches/images/{company_slug}/{branch_slug}/{unique_name}{extension}"


class Company(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)

    # Current active business field
    legal_name = models.CharField(max_length=255, blank=True)

    # Compatibility-only legacy fields kept to match existing database safely.
    # These are not part of the new core hierarchy design, but must remain
    # until database cleanup is intentionally performed later.
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=50, blank=True, default="")
    address = models.TextField(blank=True, default="")
    logo = models.ImageField(
        upload_to=company_logo_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )

    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["is_active", "name"]),
        ]
        verbose_name = "Company"
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name


class Branch(TimeStampedModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="branches",
    )
    name = models.CharField(max_length=255)
    city = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    attendance_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    attendance_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    attendance_radius_meters = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Allowed attendance radius in meters from the fixed branch point.",
    )
    image = models.ImageField(
        upload_to=branch_image_upload_to,
        blank=True,
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company__name", "name"]
        indexes = [
            models.Index(fields=["company", "is_active", "name"]),
            models.Index(fields=["city", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="org_branch_company_name_uniq",
            )
        ]
        verbose_name = "Branch"
        verbose_name_plural = "Branches"

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    def clean(self):
        errors = {}

        has_latitude = self.attendance_latitude is not None
        has_longitude = self.attendance_longitude is not None
        has_radius = self.attendance_radius_meters is not None

        if has_latitude or has_longitude or has_radius:
            if not (has_latitude and has_longitude and has_radius):
                message = "Latitude, longitude, and attendance radius must all be set together."
                if not has_latitude:
                    errors["attendance_latitude"] = message
                if not has_longitude:
                    errors["attendance_longitude"] = message
                if not has_radius:
                    errors["attendance_radius_meters"] = message

        if has_latitude and not (-90 <= self.attendance_latitude <= 90):
            errors["attendance_latitude"] = "Attendance latitude must stay between -90 and 90."

        if has_longitude and not (-180 <= self.attendance_longitude <= 180):
            errors["attendance_longitude"] = "Attendance longitude must stay between -180 and 180."

        if has_radius and self.attendance_radius_meters <= 0:
            errors["attendance_radius_meters"] = "Attendance radius must be greater than zero."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def has_attendance_location_config(self):
        return (
            self.attendance_latitude is not None
            and self.attendance_longitude is not None
            and self.attendance_radius_meters is not None
        )


class Department(TimeStampedModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="departments",
    )
    # Compatibility-only field.
    # Must remain for database safety, but it is NOT part of the active hierarchy.
    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="legacy_departments",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    manager_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["company__name", "name"]
        indexes = [
            models.Index(fields=["company", "is_active", "name"]),
            models.Index(fields=["branch", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="org_dept_company_name_uniq",
            )
        ]
        verbose_name = "Department"
        verbose_name_plural = "Departments"

    def __str__(self):
        return f"{self.company.name} - {self.name}"

    def clean(self):
        errors = {}

        if self.branch and self.branch.company_id != self.company_id:
            errors["branch"] = "Legacy branch must belong to the same company as the department."

        if errors:
            raise ValidationError(errors)


class Section(TimeStampedModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="sections",
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    supervisor_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["department__company__name", "department__name", "name"]
        indexes = [
            models.Index(fields=["department", "is_active", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "name"],
                name="org_section_dept_name_uniq",
            )
        ]
        verbose_name = "Section"
        verbose_name_plural = "Sections"

    def __str__(self):
        return f"{self.department.name} - {self.name}"

    @property
    def company(self):
        return self.department.company


class JobTitle(TimeStampedModel):
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="job_titles",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        related_name="job_titles",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = [
            "section__department__company__name",
            "section__department__name",
            "section__name",
            "name",
        ]
        indexes = [
            models.Index(fields=["department", "is_active", "name"]),
            models.Index(fields=["section", "is_active", "name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "name"],
                name="org_jobtitle_section_name_uniq",
            )
        ]
        verbose_name = "Job Title"
        verbose_name_plural = "Job Titles"

    def __str__(self):
        if self.section:
            return f"{self.section.name} - {self.name}"
        return self.name

    @property
    def company(self):
        if self.section:
            return self.section.department.company
        return self.department.company

    def clean(self):
        errors = {}

        if not self.section:
            errors["section"] = "Job title must be linked to a section."

        if self.section:
            self.department = self.section.department

        if self.department and self.section and self.section.department_id != self.department_id:
            errors["section"] = "Selected section must belong to the selected department."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.section_id:
            self.department = self.section.department
        self.full_clean()
        return super().save(*args, **kwargs)


def branch_document_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    branch_slug = (instance.branch.name or f"branch-{instance.branch_id}").strip().replace(" ", "-").lower()
    company_slug = (instance.branch.company.name or f"company-{instance.branch.company_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"branches/documents/{company_slug}/{branch_slug}/{unique_name}{extension}"


class BranchDocumentRequirement(TimeStampedModel):
    DOCUMENT_TYPE_CHOICES = [
        ("legal", "Legal Document"),
        ("ad_license", "Ad License"),
        ("store_license", "Store License"),
        ("municipality", "Municipality / Permit"),
        ("lease", "Lease / Contract"),
        ("civil_defense", "Civil Defense / Safety"),
        ("insurance", "Insurance"),
        ("service", "Service Contract"),
        ("other", "Other"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="document_requirements",
    )
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default="other",
    )
    title = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_mandatory = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["branch__company__name", "branch__name", "document_type", "title", "id"]
        indexes = [
            models.Index(fields=["branch", "is_active", "document_type"]),
            models.Index(fields=["is_mandatory", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["branch", "document_type"],
                name="org_branch_doc_req_type_uniq",
            )
        ]
        verbose_name = "Branch Document Requirement"
        verbose_name_plural = "Branch Document Requirements"

    def __str__(self):
        return f"{self.branch.name} - {self.display_title}"

    @property
    def display_title(self):
        return (self.title or self.get_document_type_display()).strip()



class BranchDocument(TimeStampedModel):
    DOCUMENT_TYPE_LEGAL = "legal"
    DOCUMENT_TYPE_AD_LICENSE = "ad_license"
    DOCUMENT_TYPE_STORE_LICENSE = "store_license"
    DOCUMENT_TYPE_MUNICIPALITY = "municipality"
    DOCUMENT_TYPE_LEASE = "lease"
    DOCUMENT_TYPE_CIVIL_DEFENSE = "civil_defense"
    DOCUMENT_TYPE_INSURANCE = "insurance"
    DOCUMENT_TYPE_SERVICE = "service"
    DOCUMENT_TYPE_OTHER = "other"

    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_TYPE_LEGAL, "Legal Document"),
        (DOCUMENT_TYPE_AD_LICENSE, "Ad License"),
        (DOCUMENT_TYPE_STORE_LICENSE, "Store License"),
        (DOCUMENT_TYPE_MUNICIPALITY, "Municipality / Permit"),
        (DOCUMENT_TYPE_LEASE, "Lease / Contract"),
        (DOCUMENT_TYPE_CIVIL_DEFENSE, "Civil Defense / Safety"),
        (DOCUMENT_TYPE_INSURANCE, "Insurance"),
        (DOCUMENT_TYPE_SERVICE, "Service Contract"),
        (DOCUMENT_TYPE_OTHER, "Other"),
    ]

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(max_length=255)
    document_type = models.CharField(
        max_length=30,
        choices=DOCUMENT_TYPE_CHOICES,
        default=DOCUMENT_TYPE_OTHER,
    )
    reference_number = models.CharField(max_length=120, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    is_required = models.BooleanField(default=False)
    file = models.FileField(
        upload_to=branch_document_upload_to,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "jpg",
                    "jpeg",
                    "png",
                    "webp",
                    "txt",
                ]
            )
        ],
    )
    description = models.TextField(blank=True)
    uploaded_by = models.CharField(max_length=150, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "document_type", "-created_at"]),
            models.Index(fields=["expiry_date", "is_required"]),
        ]
        verbose_name = "Branch Document"
        verbose_name_plural = "Branch Documents"

    def __str__(self):
        return self.title or self.filename

    def clean(self):
        errors = {}

        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            errors["expiry_date"] = "Expiry date cannot be earlier than issue date."

        if errors:
            raise ValidationError(errors)

    @property
    def filename(self):
        return Path(self.file.name).name if self.file else ""

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        from django.utils import timezone
        return (self.expiry_date - timezone.localdate()).days

    @property
    def is_expired(self):
        days = self.days_until_expiry
        return days is not None and days < 0

    @property
    def is_expiring_soon(self):
        days = self.days_until_expiry
        return days is not None and 0 <= days <= 30

    @property
    def compliance_status_label(self):
        if not self.expiry_date:
            return "No Expiry Date"
        if self.is_expired:
            return "Expired"
        if self.is_expiring_soon:
            return "Expiring Soon"
        return "Valid"

    @property
    def compliance_badge_class(self):
        if not self.expiry_date:
            return "badge"
        if self.is_expired:
            return "badge-danger"
        if self.is_expiring_soon:
            return "badge-primary"
        return "badge-success"

    def save(self, *args, **kwargs):
        self.title = (self.title or "").strip()
        self.reference_number = (self.reference_number or "").strip()
        self.description = (self.description or "").strip()
        self.full_clean()
        return super().save(*args, **kwargs)
