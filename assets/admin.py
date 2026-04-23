from django.contrib import admin

from .models import AssetAssignment, CompanyAsset


@admin.register(CompanyAsset)
class CompanyAssetAdmin(admin.ModelAdmin):
    list_display = ("asset_code", "name", "category", "condition", "is_available", "current_assignee")
    list_filter = ("category", "condition", "is_available")
    search_fields = ("asset_code", "name", "serial_number")


@admin.register(AssetAssignment)
class AssetAssignmentAdmin(admin.ModelAdmin):
    list_display = ("asset", "employee", "assigned_date", "returned_date", "assigned_by")
    list_filter = ("assigned_date", "returned_date", "condition_on_assign", "condition_on_return")
    search_fields = ("asset__asset_code", "asset__name", "employee__full_name", "employee__employee_id")

# Register your models here.
