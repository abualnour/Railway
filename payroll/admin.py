from django.contrib import admin

from .models import PayrollAdjustment, PayrollBonus, PayrollLine, PayrollObligation, PayrollPeriod, PayrollProfile


@admin.register(PayrollProfile)
class PayrollProfileAdmin(admin.ModelAdmin):
    list_display = ("employee", "company", "base_salary", "status", "updated_at")
    list_filter = ("status", "company")
    search_fields = ("employee__full_name", "employee__employee_id", "company__name")


class PayrollLineInline(admin.TabularInline):
    model = PayrollLine
    extra = 0


class PayrollAdjustmentInline(admin.TabularInline):
    model = PayrollAdjustment
    extra = 0


@admin.register(PayrollPeriod)
class PayrollPeriodAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "period_start", "period_end", "pay_date", "status")
    list_filter = ("status", "company")
    search_fields = ("title", "company__name")
    inlines = [PayrollLineInline]


@admin.register(PayrollLine)
class PayrollLineAdmin(admin.ModelAdmin):
    list_display = ("employee", "payroll_period", "base_salary", "allowances", "deductions", "net_pay")
    list_filter = ("payroll_period__company", "payroll_period__status")
    search_fields = ("employee__full_name", "employee__employee_id", "payroll_period__title")
    inlines = [PayrollAdjustmentInline]


@admin.register(PayrollAdjustment)
class PayrollAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("title", "payroll_line", "adjustment_type", "amount", "updated_at")
    list_filter = ("adjustment_type", "payroll_line__payroll_period__company")
    search_fields = ("title", "payroll_line__employee__full_name", "payroll_line__payroll_period__title")


@admin.register(PayrollObligation)
class PayrollObligationAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "obligation_type", "installment_amount", "remaining_installments", "status")
    list_filter = ("obligation_type", "status", "company")
    search_fields = ("employee__full_name", "employee__employee_id", "title", "company__name")


@admin.register(PayrollBonus)
class PayrollBonusAdmin(admin.ModelAdmin):
    list_display = ("employee", "title", "bonus_type", "awarded_amount", "paid_amount", "remaining_balance", "status")
    list_filter = ("bonus_type", "status", "company")
    search_fields = ("employee__full_name", "employee__employee_id", "title", "company__name")
