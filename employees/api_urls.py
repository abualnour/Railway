from django.urls import path

from .api_views import (
    EmployeeDetailAPIView,
    EmployeeLeaveDetailAPIView,
    EmployeeLeaveListAPIView,
    EmployeeListAPIView,
    PayrollLineDetailAPIView,
    PayrollLineListAPIView,
)

app_name = "employees_api"

urlpatterns = [
    path("", EmployeeListAPIView.as_view(), name="employee_list"),
    path("<int:pk>/", EmployeeDetailAPIView.as_view(), name="employee_detail"),
    path("leaves/", EmployeeLeaveListAPIView.as_view(), name="leave_list"),
    path("leaves/<int:pk>/", EmployeeLeaveDetailAPIView.as_view(), name="leave_detail"),
    path("payroll-lines/", PayrollLineListAPIView.as_view(), name="payroll_line_list"),
    path("payroll-lines/<int:pk>/", PayrollLineDetailAPIView.as_view(), name="payroll_line_detail"),
]
