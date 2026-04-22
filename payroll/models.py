from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Company


class PayrollProfile(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_HOLD = "hold"
    STATUS_INACTIVE = "inactive"

    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_HOLD, "On Hold"),
        (STATUS_INACTIVE, "Inactive"),
    ]

    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name="payroll_profile")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_profiles")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    housing_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    transport_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    fixed_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    pifss_employee_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.0800"))
    pifss_employer_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal("0.1150"))
    bank_name = models.CharField(max_length=120, blank=True)
    iban = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["employee__full_name"]
        verbose_name = "Payroll Profile"
        verbose_name_plural = "Payroll Profiles"

    def __str__(self):
        return f"{self.employee.full_name} payroll"

    @property
    def gross_salary(self):
        return (self.base_salary or Decimal("0.00")) + (self.housing_allowance or Decimal("0.00")) + (self.transport_allowance or Decimal("0.00"))

    @property
    def estimated_net_salary(self):
        pifss_employee_deduction = Decimal("0.00")
        if getattr(self.employee, "is_kuwaiti_national", False):
            pifss_employee_deduction = (
                (self.base_salary or Decimal("0.00")) * (self.pifss_employee_rate or Decimal("0.0000"))
            ).quantize(Decimal("0.01"))
        return self.gross_salary - (self.fixed_deduction or Decimal("0.00")) - pifss_employee_deduction


class PayrollObligation(models.Model):
    TYPE_LOAN = "loan"
    TYPE_ADVANCE = "advance"

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_HOLD = "hold"

    TYPE_CHOICES = [
        (TYPE_LOAN, "Loan"),
        (TYPE_ADVANCE, "Advance"),
    ]
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_HOLD, "On Hold"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_obligations")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_obligations")
    title = models.CharField(max_length=150)
    obligation_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    principal_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    installment_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    total_installments = models.PositiveIntegerField(default=1)
    paid_installments = models.PositiveIntegerField(default=0)
    start_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name", "-created_at"]
        verbose_name = "Payroll Obligation"
        verbose_name_plural = "Payroll Obligations"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    @property
    def remaining_installments(self):
        return max(self.total_installments - self.paid_installments, 0)

    @property
    def remaining_balance(self):
        return max(
            (self.principal_amount or Decimal("0.00")) - (Decimal(self.paid_installments) * (self.installment_amount or Decimal("0.00"))),
            Decimal("0.00"),
        )

    @property
    def can_apply_installment(self):
        return self.status == self.STATUS_ACTIVE and self.remaining_installments > 0


class PayrollBonus(models.Model):
    TYPE_PERFORMANCE = "performance"
    TYPE_COMMISSION = "commission"
    TYPE_SEASONAL = "seasonal"
    TYPE_MANUAL = "manual"

    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_HOLD = "hold"

    TYPE_CHOICES = [
        (TYPE_PERFORMANCE, "Performance"),
        (TYPE_COMMISSION, "Commission"),
        (TYPE_SEASONAL, "Seasonal"),
        (TYPE_MANUAL, "Manual"),
    ]
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_HOLD, "On Hold"),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_bonuses")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_bonuses")
    title = models.CharField(max_length=150)
    bonus_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_MANUAL)
    awarded_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    award_date = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name", "-award_date", "-id"]
        verbose_name = "Payroll Bonus"
        verbose_name_plural = "Payroll Bonuses"

    def __str__(self):
        return f"{self.employee.full_name} - {self.title}"

    @property
    def remaining_balance(self):
        return max(
            (self.awarded_amount or Decimal("0.00")) - (self.paid_amount or Decimal("0.00")),
            Decimal("0.00"),
        )

    @property
    def can_apply_balance(self):
        return self.status == self.STATUS_ACTIVE and self.remaining_balance > Decimal("0.00")


class PayrollPeriod(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_REVIEW = "review"
    STATUS_APPROVED = "approved"
    STATUS_PAID = "paid"

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_REVIEW, "In Review"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_PAID, "Paid"),
    ]

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payroll_periods")
    title = models.CharField(max_length=150)
    period_start = models.DateField()
    period_end = models.DateField()
    pay_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    notes = models.TextField(blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_start", "-id"]
        verbose_name = "Payroll Period"
        verbose_name_plural = "Payroll Periods"

    def __str__(self):
        return self.title

    @property
    def can_move_to_review(self):
        return self.status == self.STATUS_DRAFT

    @property
    def can_approve(self):
        return self.status == self.STATUS_REVIEW

    @property
    def can_mark_paid(self):
        return self.status == self.STATUS_APPROVED

    @property
    def can_reopen(self):
        return self.status in {self.STATUS_REVIEW, self.STATUS_APPROVED, self.STATUS_PAID}


class PayrollLine(models.Model):
    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="payroll_lines")
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    overtime_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    pifss_employee_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    pifss_employer_contribution = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notes = models.CharField(max_length=255, blank=True)
    snapshot_payload = models.JSONField(null=True, blank=True)
    snapshot_taken_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee__full_name"]
        unique_together = [("payroll_period", "employee")]
        verbose_name = "Payroll Line"
        verbose_name_plural = "Payroll Lines"

    def __str__(self):
        return f"{self.employee.full_name} - {self.payroll_period.title}"

    @property
    def gross_total(self):
        return (
            (self.base_salary or Decimal("0.00"))
            + (self.allowances or Decimal("0.00"))
            + (self.overtime_amount or Decimal("0.00"))
            + self.adjustment_allowances_total
        )

    @property
    def adjustment_allowances_total(self):
        adjustments_manager = getattr(self, "adjustments", None)
        if adjustments_manager is None:
            return Decimal("0.00")
        total = Decimal("0.00")
        for adjustment in adjustments_manager.all():
            if adjustment.adjustment_type == PayrollAdjustment.TYPE_ALLOWANCE:
                total += adjustment.amount or Decimal("0.00")
        return total

    @property
    def adjustment_deductions_total(self):
        adjustments_manager = getattr(self, "adjustments", None)
        if adjustments_manager is None:
            return Decimal("0.00")
        total = Decimal("0.00")
        for adjustment in adjustments_manager.all():
            if adjustment.adjustment_type == PayrollAdjustment.TYPE_DEDUCTION:
                total += adjustment.amount or Decimal("0.00")
        return total

    @property
    def total_deductions_value(self):
        return (
            (self.deductions or Decimal("0.00"))
            + (self.pifss_employee_deduction or Decimal("0.00"))
            + self.adjustment_deductions_total
        )

    def calculate_net_pay(self):
        return self.gross_total - self.total_deductions_value

    @property
    def has_snapshot(self):
        return bool(self.snapshot_payload and self.snapshot_taken_at)


class PayrollAdjustment(models.Model):
    TYPE_ALLOWANCE = "allowance"
    TYPE_DEDUCTION = "deduction"

    TYPE_CHOICES = [
        (TYPE_ALLOWANCE, "Allowance"),
        (TYPE_DEDUCTION, "Deduction"),
    ]

    payroll_line = models.ForeignKey(PayrollLine, on_delete=models.CASCADE, related_name="adjustments")
    payroll_obligation = models.ForeignKey("PayrollObligation", on_delete=models.SET_NULL, related_name="generated_adjustments", null=True, blank=True)
    payroll_bonus = models.ForeignKey("PayrollBonus", on_delete=models.SET_NULL, related_name="generated_adjustments", null=True, blank=True)
    title = models.CharField(max_length=120)
    adjustment_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["adjustment_type", "title", "id"]
        verbose_name = "Payroll Adjustment"
        verbose_name_plural = "Payroll Adjustments"

    def __str__(self):
        return f"{self.title} - {self.payroll_line.employee.full_name}"


def current_payroll_month_label():
    return timezone.localdate().strftime("%B %Y")
