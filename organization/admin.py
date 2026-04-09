from django.contrib import admin

from .models import Branch, Company, Department, JobTitle, Section


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "legal_name", "is_active", "created_at", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "legal_name", "notes")
    ordering = ("name",)
    fieldsets = (
        ("Basic Information", {
            "fields": ("name", "legal_name", "is_active")
        }),
        ("Additional Information", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "city", "email", "is_active", "created_at")
    list_filter = ("company", "is_active")
    search_fields = ("name", "company__name", "city", "email", "notes")
    ordering = ("company__name", "name")
    autocomplete_fields = ("company",)
    fieldsets = (
        ("Basic Information", {
            "fields": ("company", "name", "is_active")
        }),
        ("Contact / Location", {
            "fields": ("city", "email", "notes"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "manager_name", "is_active", "created_at")
    list_filter = ("company", "is_active")
    search_fields = ("name", "code", "manager_name", "company__name", "notes")
    ordering = ("company__name", "name")
    autocomplete_fields = ("company", "branch")
    fieldsets = (
        ("Primary Relationship", {
            "fields": ("company", "name", "code", "manager_name", "is_active")
        }),
        ("Additional Information", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Legacy Compatibility Only", {
            "fields": ("branch",),
            "classes": ("collapse",),
            "description": "This legacy branch link remains only for compatibility and should not be used in normal workflow.",
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "get_company", "supervisor_name", "is_active")
    list_filter = ("department__company", "department", "is_active")
    search_fields = ("name", "code", "supervisor_name", "department__name", "department__company__name", "notes")
    ordering = ("department__company__name", "department__name", "name")
    autocomplete_fields = ("department",)
    fieldsets = (
        ("Primary Relationship", {
            "fields": ("department", "name", "code", "supervisor_name", "is_active")
        }),
        ("Additional Information", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Company")
    def get_company(self, obj):
        return obj.department.company


@admin.register(JobTitle)
class JobTitleAdmin(admin.ModelAdmin):
    list_display = ("name", "department", "section", "get_company", "is_active")
    list_filter = ("department__company", "department", "section", "is_active")
    search_fields = ("name", "code", "department__name", "department__company__name", "section__name", "notes")
    ordering = ("department__company__name", "department__name", "name")
    autocomplete_fields = ("department", "section")
    fieldsets = (
        ("Primary Relationship", {
            "fields": ("department", "section", "name", "code", "is_active")
        }),
        ("Additional Information", {
            "fields": ("notes",),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Company")
    def get_company(self, obj):
        return obj.department.company