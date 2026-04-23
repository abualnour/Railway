from django.urls import path

from .views import (
    AssetAssignmentCreateView,
    AssetAssignmentReturnView,
    CompanyAssetCreateView,
    CompanyAssetDetailView,
    CompanyAssetListView,
    CompanyAssetUpdateView,
)

app_name = "assets"

urlpatterns = [
    path("", CompanyAssetListView.as_view(), name="asset_list"),
    path("create/", CompanyAssetCreateView.as_view(), name="asset_create"),
    path("assign/", AssetAssignmentCreateView.as_view(), name="assignment_create"),
    path("<int:pk>/", CompanyAssetDetailView.as_view(), name="asset_detail"),
    path("<int:pk>/edit/", CompanyAssetUpdateView.as_view(), name="asset_update"),
    path("assignments/<int:pk>/return/", AssetAssignmentReturnView.as_view(), name="assignment_return"),
]
