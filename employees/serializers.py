from rest_framework import serializers

from payroll.models import PayrollLine

from .models import Employee, EmployeeLeave


class EmployeeListSerializer(serializers.ModelSerializer):
    branch = serializers.CharField(source="branch.name", read_only=True)
    department = serializers.CharField(source="department.name", read_only=True)
    job_title = serializers.CharField(source="job_title.name", read_only=True)
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_id",
            "full_name",
            "branch",
            "department",
            "job_title",
            "employment_status",
            "photo_url",
        ]

    def get_photo_url(self, obj):
        if not obj.photo:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.photo.url)
        return obj.photo.url


class EmployeeDetailSerializer(serializers.ModelSerializer):
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = "__all__"

    def get_photo_url(self, obj):
        if not obj.photo:
            return ""
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.photo.url)
        return obj.photo.url


class EmployeeLeaveSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_id_code = serializers.CharField(source="employee.employee_id", read_only=True)
    leave_type_display = serializers.CharField(source="get_leave_type_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    current_stage_display = serializers.CharField(source="get_current_stage_display", read_only=True)

    class Meta:
        model = EmployeeLeave
        fields = [
            "id",
            "employee",
            "employee_name",
            "employee_id_code",
            "leave_type",
            "leave_type_display",
            "start_date",
            "end_date",
            "total_days",
            "reason",
            "approval_note",
            "status",
            "status_display",
            "current_stage",
            "current_stage_display",
            "requested_by",
            "reviewed_by",
            "approved_by",
            "rejected_by",
            "cancelled_by",
            "created_at",
            "updated_at",
        ]


class PayrollLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.full_name", read_only=True)
    employee_id_code = serializers.CharField(source="employee.employee_id", read_only=True)
    payroll_period_title = serializers.CharField(source="payroll_period.title", read_only=True)
    gross_total = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    total_deductions_value = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = PayrollLine
        fields = [
            "id",
            "payroll_period",
            "payroll_period_title",
            "employee",
            "employee_name",
            "employee_id_code",
            "base_salary",
            "allowances",
            "deductions",
            "overtime_amount",
            "pifss_employee_deduction",
            "pifss_employer_contribution",
            "gross_total",
            "total_deductions_value",
            "net_pay",
            "notes",
            "snapshot_payload",
            "snapshot_taken_at",
            "created_at",
            "updated_at",
        ]
