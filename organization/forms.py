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
            "logo",
            "notes",
            "is_active",
        ]


class BranchForm(BaseStyledModelForm):
    class Meta:
        model = Branch
        fields = [
            "company",
            "name",
            "city",
            "email",
            "image",
            "notes",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")


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
