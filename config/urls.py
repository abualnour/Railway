from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

from accounts.views import NourAxisLoginView, session_expire, session_ping
from core.views import BackupCenterView, DashboardHomeView
from .views import system_landing

urlpatterns = [
    path("", system_landing, name="home"),
    path("dashboard/", DashboardHomeView.as_view(), name="dashboard_home"),
    path("system/backup-center/", BackupCenterView.as_view(), name="backup_center"),
    path("admin/", admin.site.urls),
    path("accounts/login/", NourAxisLoginView.as_view(), name="login"),
    path("accounts/session/ping/", session_ping, name="session_ping"),
    path("accounts/session/expire/", session_expire, name="session_expire"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("organization/", include(("organization.urls", "organization"), namespace="organization")),
    path("employees/", include("employees.urls")),
    path("operations/", include(("operations.urls", "operations"), namespace="operations")),
    path("hr/", include(("hr.urls", "hr"), namespace="hr")),
    path("payroll/", include(("payroll.urls", "payroll"), namespace="payroll")),
    path("notifications/", include(("notifications.urls", "notifications"), namespace="notifications")),
    path("work-calendar/", include(("workcalendar.urls", "workcalendar"), namespace="workcalendar")),
    path("recruitment/", include(("recruitment.urls", "recruitment"), namespace="recruitment")),
    path("performance/", include(("performance.urls", "performance"), namespace="performance")),
    path("assets/", include(("assets.urls", "assets"), namespace="assets")),
    path("finance/", include(("finance.urls", "finance"), namespace="finance")),
    path("api/v1/employees/", include(("employees.api_urls", "employees_api"), namespace="employees_api")),
]

urlpatterns += [
    re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT}),
]
