from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from core.views import BackupCenterView, DashboardHomeView
from .views import system_landing

urlpatterns = [
    path("", system_landing, name="home"),
    path("dashboard/", DashboardHomeView.as_view(), name="dashboard_home"),
    path("system/backup-center/", BackupCenterView.as_view(), name="backup_center"),
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("organization/", include(("organization.urls", "organization"), namespace="organization")),
    path("employees/", include("employees.urls")),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
