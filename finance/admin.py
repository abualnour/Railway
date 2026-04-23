from django.contrib import admin

from .models import ExpenseClaim


@admin.register(ExpenseClaim)
class ExpenseClaimAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "category", "amount", "currency", "expense_date", "status", "submitted_at")
    list_filter = ("status", "category", "currency", "expense_date")
    search_fields = ("employee__full_name", "employee__employee_id", "title", "description")
    readonly_fields = ("submitted_at", "reviewed_at", "created_at", "updated_at")

# Register your models here.
