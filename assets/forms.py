from django import forms

from .models import AssetAssignment, CompanyAsset


class CompanyAssetForm(forms.ModelForm):
    class Meta:
        model = CompanyAsset
        fields = [
            "asset_code",
            "name",
            "category",
            "serial_number",
            "purchase_date",
            "condition",
            "notes",
            "is_available",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class AssetAssignmentForm(forms.ModelForm):
    class Meta:
        model = AssetAssignment
        fields = [
            "asset",
            "employee",
            "assigned_date",
            "condition_on_assign",
            "notes",
        ]
        widgets = {
            "assigned_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["asset"].queryset = CompanyAsset.objects.filter(is_available=True).order_by("asset_code", "name")
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()


class AssetReturnForm(forms.ModelForm):
    class Meta:
        model = AssetAssignment
        fields = ["returned_date", "condition_on_return", "notes"]
        widgets = {
            "returned_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["condition_on_return"].required = True
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} form-control".strip()
