from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.views import View

from employees.access import is_admin_compatible, is_hr_user, is_operations_manager_user

from .forms import AssetAssignmentForm, AssetReturnForm, CompanyAssetForm
from .models import AssetAssignment, CompanyAsset


def can_manage_assets(user):
    return bool(
        user
        and user.is_authenticated
        and (is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user))
    )


class AssetPermissionMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not can_manage_assets(request.user):
            raise PermissionDenied("You do not have permission to manage company assets.")
        return super().dispatch(request, *args, **kwargs)


class CompanyAssetListView(AssetPermissionMixin, ListView):
    model = CompanyAsset
    template_name = "assets/asset_list.html"
    context_object_name = "assets"
    paginate_by = 25

    def get_queryset(self):
        queryset = CompanyAsset.objects.prefetch_related("assignments__employee").order_by("asset_code", "name")
        status = self.request.GET.get("status", "").strip()
        category = self.request.GET.get("category", "").strip()
        query = self.request.GET.get("q", "").strip()
        if status == "available":
            queryset = queryset.filter(is_available=True)
        elif status == "assigned":
            queryset = queryset.filter(is_available=False)
        if category:
            queryset = queryset.filter(category=category)
        if query:
            queryset = queryset.filter(asset_code__icontains=query) | queryset.filter(name__icontains=query) | queryset.filter(serial_number__icontains=query)
        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category_choices"] = CompanyAsset.CATEGORY_CHOICES
        context["selected_status"] = self.request.GET.get("status", "")
        context["selected_category"] = self.request.GET.get("category", "")
        context["search_query"] = self.request.GET.get("q", "")
        context["asset_total"] = CompanyAsset.objects.count()
        context["available_total"] = CompanyAsset.objects.filter(is_available=True).count()
        context["assigned_total"] = CompanyAsset.objects.filter(is_available=False).count()
        return context


class CompanyAssetDetailView(AssetPermissionMixin, DetailView):
    model = CompanyAsset
    template_name = "assets/asset_detail.html"
    context_object_name = "asset"

    def get_queryset(self):
        return CompanyAsset.objects.prefetch_related("assignments__employee", "assignments__assigned_by")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["assignments"] = self.object.assignments.select_related("employee", "assigned_by")
        return context


class CompanyAssetCreateView(AssetPermissionMixin, CreateView):
    model = CompanyAsset
    form_class = CompanyAssetForm
    template_name = "assets/asset_form.html"
    success_url = reverse_lazy("assets:asset_list")

    def form_valid(self, form):
        messages.success(self.request, "Company asset created successfully.")
        return super().form_valid(form)


class CompanyAssetUpdateView(AssetPermissionMixin, UpdateView):
    model = CompanyAsset
    form_class = CompanyAssetForm
    template_name = "assets/asset_form.html"

    def get_success_url(self):
        return reverse("assets:asset_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, "Company asset updated successfully.")
        return super().form_valid(form)


class AssetAssignmentCreateView(AssetPermissionMixin, CreateView):
    model = AssetAssignment
    form_class = AssetAssignmentForm
    template_name = "assets/assignment_form.html"

    def form_valid(self, form):
        assignment = form.save(commit=False)
        assignment.assigned_by = self.request.user
        assignment.full_clean()
        assignment.save()
        assignment.asset.is_available = False
        assignment.asset.save(update_fields=["is_available", "updated_at"])
        messages.success(self.request, "Asset assigned successfully.")
        return redirect("assets:asset_detail", pk=assignment.asset.pk)


class AssetAssignmentReturnView(AssetPermissionMixin, UpdateView):
    model = AssetAssignment
    form_class = AssetReturnForm
    template_name = "assets/assignment_return_form.html"
    context_object_name = "assignment"

    def get_queryset(self):
        return AssetAssignment.objects.select_related("asset", "employee").filter(returned_date__isnull=True)

    def form_valid(self, form):
        assignment = form.save(commit=False)
        assignment.full_clean()
        assignment.save()
        assignment.asset.is_available = True
        assignment.asset.condition = assignment.condition_on_return
        assignment.asset.save(update_fields=["is_available", "condition", "updated_at"])
        messages.success(self.request, "Asset return recorded successfully.")
        return redirect("assets:asset_detail", pk=assignment.asset.pk)

# Create your views here.
