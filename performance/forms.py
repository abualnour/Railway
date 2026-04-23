from django import forms

from employees.models import Employee

from .models import PerformanceReview, PerformanceReviewComment, ReviewCycle


class ReviewCycleForm(forms.ModelForm):
    class Meta:
        model = ReviewCycle
        fields = ["title", "company", "period_start", "period_end", "status"]
        widgets = {
            "period_start": forms.DateInput(attrs={"type": "date"}),
            "period_end": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class PerformanceReviewForm(forms.ModelForm):
    class Meta:
        model = PerformanceReview
        fields = [
            "cycle",
            "reviewer",
            "overall_rating",
            "strengths",
            "areas_for_improvement",
            "goals_next_period",
            "status",
        ]
        widgets = {
            "strengths": forms.Textarea(attrs={"rows": 4}),
            "areas_for_improvement": forms.Textarea(attrs={"rows": 4}),
            "goals_next_period": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)
        if employee:
            self.fields["cycle"].queryset = ReviewCycle.objects.filter(
                company=employee.company,
            ).exclude(status=ReviewCycle.STATUS_CLOSED).order_by("-period_start", "title")
            self.fields["reviewer"].queryset = Employee.objects.filter(company=employee.company, is_active=True).exclude(pk=employee.pk).order_by("full_name", "employee_id")
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class PerformanceAcknowledgementForm(forms.ModelForm):
    class Meta:
        model = PerformanceReview
        fields = ["employee_comments"]
        widgets = {
            "employee_comments": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee_comments"].required = False
        self.fields["employee_comments"].widget.attrs["class"] = "form-control"


class PerformanceReviewCommentForm(forms.ModelForm):
    class Meta:
        model = PerformanceReviewComment
        fields = ["note"]
        widgets = {
            "note": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Add a reviewer or acknowledgement note for the performance history.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["note"].widget.attrs["class"] = "form-control"
