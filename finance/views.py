from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from employees.access import is_admin_compatible, is_finance_manager_user, is_hr_user

from .forms import ExpenseClaimReviewForm
from .models import ExpenseClaim


def can_review_expense_claims(user):
    return bool(
        user
        and user.is_authenticated
        and (is_admin_compatible(user) or is_hr_user(user) or is_finance_manager_user(user))
    )


@login_required
def expense_claim_dashboard(request):
    if not can_review_expense_claims(request.user):
        raise PermissionDenied("You do not have permission to access finance expense claims.")

    status_filter = (request.GET.get("status") or "").strip()
    claims = ExpenseClaim.objects.select_related(
        "employee",
        "employee__branch",
        "employee__department",
        "reviewed_by",
    )
    if status_filter:
        claims = claims.filter(status=status_filter)
    claims = claims.order_by("-submitted_at", "-expense_date", "-id")

    context = {
        "claims": list(claims[:100]),
        "status_choices": ExpenseClaim.STATUS_CHOICES,
        "selected_status": status_filter,
        "claim_total": ExpenseClaim.objects.count(),
        "submitted_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_SUBMITTED).count(),
        "approved_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_APPROVED).count(),
        "paid_total": ExpenseClaim.objects.filter(status=ExpenseClaim.STATUS_PAID).count(),
    }
    return render(request, "finance/expense_claim_dashboard.html", context)


@login_required
def expense_claim_review(request, claim_pk):
    claim = get_object_or_404(
        ExpenseClaim.objects.select_related("employee", "reviewed_by"),
        pk=claim_pk,
    )
    if not can_review_expense_claims(request.user):
        raise PermissionDenied("You do not have permission to review expense claims.")

    if request.method == "POST":
        form = ExpenseClaimReviewForm(request.POST, instance=claim)
        if form.is_valid():
            reviewed_claim = form.save(commit=False)
            reviewed_claim.reviewed_by = request.user
            reviewed_claim.reviewed_at = timezone.now()
            reviewed_claim.save()
            messages.success(request, "Expense claim review saved successfully.")
            return redirect("finance:expense_claim_dashboard")
        messages.error(request, "Please review the expense claim decision and try again.")
    else:
        form = ExpenseClaimReviewForm(instance=claim)

    return render(
        request,
        "finance/expense_claim_review.html",
        {
            "claim": claim,
            "form": form,
        },
    )

# Create your views here.
