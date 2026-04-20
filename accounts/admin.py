# accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django import forms

from .models import User


class UserAdminChangeForm(UserChangeForm):
    full_name = forms.CharField(required=False, label="Full name")

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["full_name"].initial = self.instance.get_full_name().strip() or self.instance.first_name or ""

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = (self.cleaned_data.get("full_name") or "").strip()
        user.first_name = full_name
        user.last_name = ""
        if commit:
            user.save()
            self.save_m2m()
        return user


class UserAdminCreationForm(UserCreationForm):
    full_name = forms.CharField(required=False, label="Full name")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email", "full_name", "phone_number", "role", "is_active")

    def save(self, commit=True):
        user = super().save(commit=False)
        full_name = (self.cleaned_data.get("full_name") or "").strip()
        user.first_name = full_name
        user.last_name = ""
        if commit:
            user.save()
            self.save_m2m()
        return user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    model = User
    form = UserAdminChangeForm
    add_form = UserAdminCreationForm
    ordering = ("email",)
    list_display = ("email", "full_name_display", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("email", "first_name", "last_name", "phone_number")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("full_name", "phone_number")}),
        (
            "Business role",
            {
                "fields": (
                    "role",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")} ),
    )


    def save_model(self, request, obj, form, change):
        if getattr(obj, "role", "") in {"hr", "finance_manager", "supervisor", "operations_manager", "employee"} and not getattr(obj, "is_superuser", False):
            obj.is_staff = False
        super().save_model(request, obj, form, change)

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "full_name",
                    "phone_number",
                    "role",
                    "is_active",
                ),
            },
        ),
    )

    @admin.display(description="Full name", ordering="first_name")
    def full_name_display(self, obj):
        return obj.get_full_name().strip() or obj.first_name or "-"
