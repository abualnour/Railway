# core/urls.py
from django.urls import path
from .views import DashboardHomeView

urlpatterns = [
    path("", DashboardHomeView.as_view(), name="dashboard_home"),
]