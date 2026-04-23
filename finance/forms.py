from django import forms

from .models import ExpenseClaim


class ExpenseClaimForm(forms.ModelForm):
    class Meta:
        model = ExpenseClaim
        fields = [
            "title",
            "category",
            "amount",
            "currency",
            "expense_date",
            "receipt_file",
            "description",
            "status",
        ]
        widgets = {
            "expense_date": forms.DateInput(attrs={"type": "date"}),
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (ExpenseClaim.STATUS_DRAFT, "Save as Draft"),
            (ExpenseClaim.STATUS_SUBMITTED, "Submit for Review"),
        ]
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class ExpenseClaimReviewForm(forms.ModelForm):
    class Meta:
        model = ExpenseClaim
        fields = ["status", "review_note"]
        widgets = {
            "review_note": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (ExpenseClaim.STATUS_APPROVED, "Approve"),
            (ExpenseClaim.STATUS_REJECTED, "Reject"),
            (ExpenseClaim.STATUS_PAID, "Mark as Paid"),
        ]
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()
