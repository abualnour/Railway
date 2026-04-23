from rest_framework import generics

from payroll.models import PayrollLine

from .models import Employee, EmployeeLeave
from .serializers import (
    EmployeeDetailSerializer,
    EmployeeLeaveSerializer,
    EmployeeListSerializer,
    PayrollLineSerializer,
)


class EmployeeListAPIView(generics.ListAPIView):
    serializer_class = EmployeeListSerializer

    def get_queryset(self):
        return Employee.objects.select_related(
            "branch",
            "department",
            "job_title",
        ).order_by("employee_id", "full_name")


class EmployeeDetailAPIView(generics.RetrieveAPIView):
    serializer_class = EmployeeDetailSerializer

    def get_queryset(self):
        return Employee.objects.select_related(
            "user",
            "company",
            "department",
            "branch",
            "section",
            "job_title",
        )


class EmployeeLeaveListAPIView(generics.ListAPIView):
    serializer_class = EmployeeLeaveSerializer

    def get_queryset(self):
        return EmployeeLeave.objects.select_related(
            "employee",
            "requested_by",
            "reviewed_by",
            "approved_by",
            "rejected_by",
            "cancelled_by",
        ).order_by("-created_at", "-id")


class EmployeeLeaveDetailAPIView(generics.RetrieveAPIView):
    serializer_class = EmployeeLeaveSerializer

    def get_queryset(self):
        return EmployeeLeave.objects.select_related(
            "employee",
            "requested_by",
            "reviewed_by",
            "approved_by",
            "rejected_by",
            "cancelled_by",
        )


class PayrollLineListAPIView(generics.ListAPIView):
    serializer_class = PayrollLineSerializer

    def get_queryset(self):
        return PayrollLine.objects.select_related(
            "employee",
            "payroll_period",
        ).order_by("-payroll_period__period_start", "employee__full_name", "id")


class PayrollLineDetailAPIView(generics.RetrieveAPIView):
    serializer_class = PayrollLineSerializer

    def get_queryset(self):
        return PayrollLine.objects.select_related(
            "employee",
            "payroll_period",
        )
