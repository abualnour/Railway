from django import forms
from django.core.exceptions import ValidationError

from .models import Branch, BranchDocument, BranchDocumentRequirement, Company, Department, JobTitle, Section


class BaseStyledModelForm(forms.ModelForm):
    """
    Shared styling for all organization forms.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        textarea_fields = {"notes", "description"}

        for name, field in self.fields.items():
            if name in textarea_fields:
                field.widget.attrs.update(
                    {
                        "class": "form-control",
                        "rows": 4,
                    }
                )
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({"class": "form-check-input"})
            elif isinstance(field.widget, forms.ClearableFileInput):
                field.widget.attrs.update({"class": "form-control"})
            else:
                field.widget.attrs.update({"class": "form-control"})


class CompanyForm(BaseStyledModelForm):
    class Meta:
        model = Company
        fields = [
            "name",
            "legal_name",
            "email",
            "phone",
            "address",
            "logo",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].help_text = "Main company name used across lists, navigation, and employee assignment."
        self.fields["legal_name"].help_text = "Official legal or registered company name shown on the company record."
        self.fields["email"].help_text = "Primary business contact email for this company."
        self.fields["phone"].help_text = "Main company phone number for internal reference."
        self.fields["address"].help_text = "Business address shown on the company detail page."
        self.fields["logo"].help_text = "Optional logo used on the company detail record."
        self.fields["notes"].help_text = "Internal notes for admins, HR, or operations."


class BranchForm(BaseStyledModelForm):
    class Meta:
        model = Branch
        fields = [
            "company",
            "name",
            "city",
            "email",
            "attendance_latitude",
            "attendance_longitude",
            "attendance_radius_meters",
            "image",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["company"].help_text = "Company that owns this branch."
        self.fields["city"].help_text = "Branch city or operating location."
        self.fields["email"].help_text = "Branch contact email shown in branch records."
        self.fields["attendance_latitude"].help_text = (
            "Fixed branch attendance latitude used for live employee attendance validation."
        )
        self.fields["attendance_longitude"].help_text = (
            "Fixed branch attendance longitude used for live employee attendance validation."
        )
        self.fields["attendance_radius_meters"].help_text = (
            "Allowed distance in meters from the fixed branch attendance point."
        )
        self.fields["attendance_latitude"].widget.attrs.setdefault("placeholder", "Example: 29.375900")
        self.fields["attendance_longitude"].widget.attrs.setdefault("placeholder", "Example: 47.977400")
        self.fields["attendance_radius_meters"].widget.attrs.setdefault("placeholder", "Example: 120")
        self.fields["image"].help_text = "Optional branch image shown on the branch detail page."
        self.fields["notes"].help_text = "Internal branch notes for operations or HR."


class DepartmentForm(BaseStyledModelForm):
    class Meta:
        model = Department
        fields = [
            "company",
            "name",
            "code",
            "manager_name",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["company"].help_text = "Company this department belongs to."
        self.fields["code"].help_text = "Optional short code used in lists and detail pages."
        self.fields["manager_name"].help_text = "Department manager or lead name for quick reference."
        self.fields["notes"].help_text = "Internal notes for this department."

    def clean(self):
        cleaned_data = super().clean()
        company = cleaned_data.get("company")
        branch = getattr(self.instance, "branch", None)

        # Compatibility-safe validation only.
        # Department.branch is legacy and not exposed in the normal form,
        # but if an existing instance still has it, keep company alignment valid.
        if company and branch and branch.company_id != company.id:
            raise ValidationError(
                {"company": "This department has a legacy branch linked from another company."}
            )

        return cleaned_data


class SectionForm(BaseStyledModelForm):
    class Meta:
        model = Section
        fields = [
            "department",
            "name",
            "code",
            "supervisor_name",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = (
            Department.objects.filter(is_active=True)
            .select_related("company")
            .order_by("company__name", "name")
        )
        self.fields["department"].help_text = "Department this section belongs to."
        self.fields["code"].help_text = "Optional short code used for quick identification."
        self.fields["supervisor_name"].help_text = "Section supervisor or team lead name."
        self.fields["notes"].help_text = "Internal notes for this section."


class JobTitleForm(BaseStyledModelForm):
    class Meta:
        model = JobTitle
        fields = [
            "section",
            "name",
            "code",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["section"].queryset = (
            Section.objects.filter(is_active=True, department__is_active=True)
            .select_related("department", "department__company")
            .order_by("department__company__name", "department__name", "name")
        )
        self.fields["section"].required = True
        self.fields["section"].empty_label = "Select section"
        self.fields["section"].help_text = (
            "Select the section for this role. The department is assigned automatically from that section."
        )
        self.fields["code"].help_text = "Optional role code used in lists and record details."
        self.fields["notes"].help_text = "Internal notes for this job title."

    def clean(self):
        cleaned_data = super().clean()
        section = cleaned_data.get("section")

        if not section:
            raise ValidationError({"section": "Please select a section for this job title."})

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.department = self.cleaned_data["section"].department

        if commit:
            instance.save()

        return instance


class BranchDocumentRequirementForm(BaseStyledModelForm):
    class Meta:
        model = BranchDocumentRequirement
        fields = [
            "document_type",
            "title",
            "notes",
            "is_mandatory",
            "is_active",
        ]



class BranchDocumentForm(BaseStyledModelForm):
    class Meta:
        model = BranchDocument
        fields = [
            "title",
            "document_type",
            "reference_number",
            "issue_date",
            "expiry_date",
            "is_required",
            "file",
            "description",
        ]
