from django.urls import path

from .views import (
    employee_payroll_line_payslip,
    employee_payroll_line_payslip_pdf,
    payroll_home,
    payroll_line_payslip,
    payroll_line_payslip_pdf,
    payroll_period_detail,
)

app_name = "payroll"

urlpatterns = [
    path("", payroll_home, name="home"),
    path("periods/<int:pk>/", payroll_period_detail, name="period_detail"),
    path("lines/<int:pk>/payslip/", payroll_line_payslip, name="line_payslip"),
    path("lines/<int:pk>/payslip/pdf/", payroll_line_payslip_pdf, name="line_payslip_pdf"),
    path("self-service/payslips/<int:pk>/", employee_payroll_line_payslip, name="employee_line_payslip"),
    path("self-service/payslips/<int:pk>/pdf/", employee_payroll_line_payslip_pdf, name="employee_line_payslip_pdf"),
]
