from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from employees.models import Employee, JobTitle, Section
from organization.models import Branch, Company, Department

from .models import Candidate, CandidateAttachment, CandidateInterview, CandidateInterviewFeedback, JobPosting


class JobPostingForm(forms.ModelForm):
    posted_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    closing_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    class Meta:
        model = JobPosting
        fields = [
            "title",
            "department",
            "branch",
            "description",
            "requirements",
            "status",
            "posted_date",
            "closing_date",
        ]


class CandidateForm(forms.ModelForm):
    offer_sent_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    offer_expiry_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))

    class Meta:
        model = Candidate
        fields = [
            "full_name",
            "email",
            "phone",
            "nationality",
            "cv_file",
            "offer_letter_file",
            "offer_sent_date",
            "offer_expiry_date",
            "offer_status",
            "offer_decision_note",
            "recruiter_owner",
            "cover_letter",
            "status",
            "notes",
        ]
        widgets = {
            "cover_letter": forms.Textarea(attrs={"rows": 5}),
            "offer_decision_note": forms.Textarea(attrs={"rows": 3}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user_model = get_user_model()
        self.fields["recruiter_owner"].queryset = user_model.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class CandidateFilterForm(forms.Form):
    search = forms.CharField(required=False)
    status = forms.ChoiceField(required=False, choices=[("", "All Statuses"), *Candidate.STATUS_CHOICES])
    department = forms.ModelChoiceField(required=False, queryset=None)
    branch = forms.ModelChoiceField(required=False, queryset=None)
    job_posting = forms.ModelChoiceField(required=False, queryset=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["job_posting"].queryset = JobPosting.objects.order_by("title")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class CandidateInterviewForm(forms.ModelForm):
    scheduled_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    class Meta:
        model = CandidateInterview
        fields = ["scheduled_at", "interview_type", "interviewer", "location", "score", "recommendation", "note", "outcome"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 3}),
            "outcome": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class CandidateOfferDecisionForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = ["offer_status", "offer_decision_note"]
        widgets = {
            "offer_decision_note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["offer_status"].choices = [
            (Candidate.OFFER_STATUS_ACCEPTED, "Accepted"),
            (Candidate.OFFER_STATUS_DECLINED, "Declined"),
            (Candidate.OFFER_STATUS_PENDING, "Pending Response"),
        ]
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class CandidateInterviewFeedbackForm(forms.ModelForm):
    class Meta:
        model = CandidateInterviewFeedback
        fields = ["score", "recommendation", "strengths", "concerns", "note"]
        widgets = {
            "strengths": forms.Textarea(attrs={"rows": 3}),
            "concerns": forms.Textarea(attrs={"rows": 3}),
            "note": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class CandidateAttachmentForm(forms.ModelForm):
    class Meta:
        model = CandidateAttachment
        fields = ["title", "file", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class CandidateHireForm(forms.Form):
    employee_id = forms.CharField(max_length=50)
    hire_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    company = forms.ModelChoiceField(queryset=None)
    department = forms.ModelChoiceField(queryset=None)
    branch = forms.ModelChoiceField(queryset=None)
    section = forms.ModelChoiceField(required=False, queryset=None)
    job_title = forms.ModelChoiceField(queryset=None)
    salary = forms.DecimalField(required=False, max_digits=10, decimal_places=2)
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, candidate=None, **kwargs):
        self.candidate = candidate
        super().__init__(*args, **kwargs)

        self.fields["company"].queryset = Company.objects.filter(is_active=True).order_by("name")
        self.fields["department"].queryset = Department.objects.filter(is_active=True).order_by("name")
        self.fields["branch"].queryset = Branch.objects.filter(is_active=True).order_by("name")
        self.fields["section"].queryset = Section.objects.filter(is_active=True).order_by("name")
        self.fields["job_title"].queryset = JobTitle.objects.filter(is_active=True).order_by("name")
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

        if candidate:
            self.fields["company"].initial = candidate.job_posting.department.company_id
            self.fields["department"].initial = candidate.job_posting.department_id
            self.fields["branch"].initial = candidate.job_posting.branch_id
            self.fields["hire_date"].initial = timezone.localdate()

    def clean_employee_id(self):
        employee_id = (self.cleaned_data.get("employee_id") or "").strip()
        if Employee.objects.filter(employee_id=employee_id).exists():
            raise forms.ValidationError("This employee ID is already in use.")
        return employee_id

    def clean(self):
        cleaned_data = super().clean()
        department = cleaned_data.get("department")
        branch = cleaned_data.get("branch")
        company = cleaned_data.get("company")
        section = cleaned_data.get("section")
        job_title = cleaned_data.get("job_title")

        if department and company and department.company_id != company.id:
            self.add_error("department", "Department must belong to the selected company.")
        if branch and company and branch.company_id != company.id:
            self.add_error("branch", "Branch must belong to the selected company.")
        if section and department and section.department_id != department.id:
            self.add_error("section", "Section must belong to the selected department.")
        if job_title and department and job_title.department_id != department.id:
            self.add_error("job_title", "Job title must belong to the selected department.")
        if job_title and job_title.section_id and section and job_title.section_id != section.id:
            self.add_error("job_title", "Job title must match the selected section.")
        if job_title and job_title.section_id and not section:
            self.add_error("section", "A section is required for the selected job title.")

        return cleaned_data
