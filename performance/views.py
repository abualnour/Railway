from datetime import timedelta

from django.contrib import messages
from django.db.models import Avg, Count, IntegerField, Q
from django.db.models.functions import Cast
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from config.access import is_hr, is_operations, is_superuser, role_required
from employees.access import (
    get_user_scope_branch,
    is_admin_compatible,
    is_branch_scoped_supervisor,
    is_hr_user,
    is_operations_manager_user,
)
from employees.models import Employee
from notifications.models import InAppNotification, build_in_app_notification
from notifications.views import persist_in_app_notifications

from .forms import (
    PerformanceAcknowledgementForm,
    PerformanceReviewCommentForm,
    PerformanceReviewForm,
    ReviewCycleForm,
)
from .models import PerformanceReview, PerformanceReviewComment, ReviewCycle


def get_linked_employee(user):
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "employee_profile", None)


def has_linked_employee_profile(user):
    return bool(get_linked_employee(user))


def can_manage_performance_reviews(user, employee=None):
    if not user or not user.is_authenticated:
        return False
    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return True
    if employee and is_branch_scoped_supervisor(user):
        scoped_branch = get_user_scope_branch(user, get_linked_employee(user))
        return bool(scoped_branch and employee.branch_id == scoped_branch.id)
    return False


def can_access_performance_dashboard(user):
    return bool(
        user
        and user.is_authenticated
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or get_linked_employee(user) is not None
        )
    )


def can_acknowledge_performance_review(user, review):
    if not user or not user.is_authenticated or not review:
        return False
    employee_user = getattr(review.employee, "user", None)
    return bool(
        employee_user
        and employee_user.pk == user.pk
        and not review.is_locked
        and review.status == PerformanceReview.STATUS_SUBMITTED
    )


def can_edit_performance_review(user, review):
    return bool(review and not review.is_locked and can_manage_performance_reviews(user, review.employee))


def can_comment_on_performance_review(user, review):
    if not user or not user.is_authenticated or not review:
        return False
    if can_manage_performance_reviews(user, review.employee):
        return True
    linked_employee = get_linked_employee(user)
    employee_user = getattr(review.employee, "user", None)
    return bool(
        (linked_employee and linked_employee.pk == review.reviewer_id)
        or (employee_user and employee_user.pk == user.pk)
    )


def can_force_complete_performance_review(user, review):
    return bool(
        review
        and review.is_locked
        and review.status != PerformanceReview.STATUS_ACKNOWLEDGED
        and (
            is_admin_compatible(user)
            or is_hr_user(user)
            or is_operations_manager_user(user)
            or can_manage_performance_reviews(user, review.employee)
        )
    )


def build_performance_review_queryset():
    return PerformanceReview.objects.select_related(
        "cycle",
        "cycle__company",
        "employee",
        "employee__branch",
        "employee__department",
        "reviewer",
        "reviewer__branch",
        "reviewer__department",
        "created_by",
    ).prefetch_related(
        "comments__author",
    ).annotate(
        overall_rating_value=Cast("overall_rating", IntegerField()),
    ).order_by("-cycle__period_start", "-updated_at", "-id")


def get_accessible_performance_review_queryset(user, queryset=None):
    queryset = queryset or build_performance_review_queryset()
    if not user or not user.is_authenticated:
        return queryset.none()

    if is_admin_compatible(user) or is_hr_user(user) or is_operations_manager_user(user):
        return queryset

    linked_employee = get_linked_employee(user)
    if not linked_employee:
        return queryset.none()

    if is_branch_scoped_supervisor(user):
        scoped_branch = get_user_scope_branch(user, linked_employee)
        if scoped_branch:
            return queryset.filter(Q(employee__branch=scoped_branch) | Q(reviewer=linked_employee))

    return queryset.filter(Q(employee=linked_employee) | Q(reviewer=linked_employee))


def get_performance_notification_recipients(exclude_users=None):
    excluded_user_ids = {
        user.pk
        for user in exclude_users or []
        if user and getattr(user, "pk", None) is not None
    }
    recipients = []
    seen_user_ids = set()
    for user in Employee._meta.get_field("user").remote_field.model.objects.filter(is_active=True).order_by("id"):
        if user.pk in excluded_user_ids or user.pk in seen_user_ids:
            continue
        if can_access_performance_dashboard(user):
            recipients.append(user)
            seen_user_ids.add(user.pk)
    return recipients


def trigger_performance_review_alerts(reference_date=None):
    reference_date = reference_date or timezone.localdate()
    alert_cutoff = reference_date + timedelta(days=7)
    notifications = []

    due_reviews = PerformanceReview.objects.select_related(
        "cycle",
        "employee",
        "reviewer",
        "reviewer__user",
    ).filter(
        status=PerformanceReview.STATUS_DRAFT,
        cycle__status=ReviewCycle.STATUS_ACTIVE,
        cycle__period_end__lte=alert_cutoff,
    ).order_by("cycle__period_end", "employee__full_name", "id")

    for review in due_reviews:
        reviewer_user = getattr(review.reviewer, "user", None)
        if not reviewer_user or not reviewer_user.is_active:
            continue
        action_url = f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance"
        title = f"Performance review due for {review.employee.full_name}"
        body = (
            f"{review.employee.full_name} has a {review.cycle.title} review still in draft status. "
            f"Cycle end date: {review.cycle.period_end.strftime('%B %d, %Y')}."
        )
        already_exists = InAppNotification.objects.filter(
            recipient=reviewer_user,
            category=InAppNotification.CATEGORY_HR,
            title=title,
            action_url=action_url,
            created_at__date=reference_date,
        ).exists()
        if already_exists:
            continue
        notification = build_in_app_notification(
            recipient=reviewer_user,
            title=title,
            body=body,
            category=InAppNotification.CATEGORY_HR,
            action_url=action_url,
            level=InAppNotification.LEVEL_WARNING,
        )
        if notification is not None:
            notifications.append(notification)

    pending_ack_reviews = PerformanceReview.objects.select_related(
        "cycle",
        "employee",
        "employee__user",
        "reviewer",
    ).filter(
        status=PerformanceReview.STATUS_SUBMITTED,
        submitted_at__date__lte=reference_date - timedelta(days=2),
    ).order_by("submitted_at", "employee__full_name", "id")

    for review in pending_ack_reviews:
        employee_user = getattr(review.employee, "user", None)
        if not employee_user or not employee_user.is_active:
            continue
        action_url = f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance"
        title = f"Performance review awaiting acknowledgement"
        body = (
            f"Your {review.cycle.title} performance review from {review.reviewer.full_name} "
            f"is ready for acknowledgement."
        )
        already_exists = InAppNotification.objects.filter(
            recipient=employee_user,
            category=InAppNotification.CATEGORY_HR,
            title=title,
            action_url=action_url,
            created_at__date=reference_date,
        ).exists()
        if already_exists:
            continue
        notification = build_in_app_notification(
            recipient=employee_user,
            title=title,
            body=body,
            category=InAppNotification.CATEGORY_HR,
            action_url=action_url,
            level=InAppNotification.LEVEL_INFO,
        )
        if notification is not None:
            notifications.append(notification)

    return persist_in_app_notifications(notifications)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to access the performance workspace.",
)
def performance_dashboard(request):
    linked_employee = get_linked_employee(request.user)
    manager_scope = is_admin_compatible(request.user) or is_hr_user(request.user) or is_operations_manager_user(request.user)

    cycle_queryset = ReviewCycle.objects.select_related("company").annotate(
        review_total=Count("performance_reviews"),
        submitted_total=Count("performance_reviews", filter=Q(performance_reviews__status=PerformanceReview.STATUS_SUBMITTED)),
        acknowledged_total=Count("performance_reviews", filter=Q(performance_reviews__status=PerformanceReview.STATUS_ACKNOWLEDGED)),
    ).order_by("-period_start", "-id")
    review_queryset = build_performance_review_queryset()

    assigned_reviews = []
    if linked_employee:
        assigned_reviews = list(
            review_queryset.filter(reviewer=linked_employee).order_by("cycle__period_end", "employee__full_name")
        )

    if not manager_scope and linked_employee:
        cycle_queryset = cycle_queryset.filter(company=linked_employee.company)
        review_queryset = review_queryset.filter(Q(employee=linked_employee) | Q(reviewer=linked_employee))

    review_status_totals = {
        "draft": review_queryset.filter(status=PerformanceReview.STATUS_DRAFT).count(),
        "submitted": review_queryset.filter(status=PerformanceReview.STATUS_SUBMITTED).count(),
        "acknowledged": review_queryset.filter(status=PerformanceReview.STATUS_ACKNOWLEDGED).count(),
    }
    rating_summary = review_queryset.aggregate(average_rating=Avg("overall_rating_value"))
    department_rating_summary = list(
        review_queryset.values("employee__department__name")
        .annotate(
            average_rating=Avg("overall_rating_value"),
            review_total=Count("id"),
            outstanding_total=Count("id", filter=Q(overall_rating=PerformanceReview.RATING_OUTSTANDING)),
        )
        .order_by("-review_total", "employee__department__name")[:6]
    )
    for row in department_rating_summary:
        row["label"] = row.pop("employee__department__name") or "Unassigned Department"

    branch_rating_summary = list(
        review_queryset.values("employee__branch__name")
        .annotate(
            average_rating=Avg("overall_rating_value"),
            review_total=Count("id"),
            needs_support_total=Count(
                "id",
                filter=Q(
                    overall_rating__in=[
                        PerformanceReview.RATING_UNSATISFACTORY,
                        PerformanceReview.RATING_NEEDS_IMPROVEMENT,
                    ]
                ),
            ),
        )
        .order_by("-review_total", "employee__branch__name")[:6]
    )
    for row in branch_rating_summary:
        row["label"] = row.pop("employee__branch__name") or "Unassigned Branch"

    calibration_summary = {
        "unsatisfactory": review_queryset.filter(overall_rating=PerformanceReview.RATING_UNSATISFACTORY).count(),
        "needs_improvement": review_queryset.filter(overall_rating=PerformanceReview.RATING_NEEDS_IMPROVEMENT).count(),
        "meets_expectations": review_queryset.filter(overall_rating=PerformanceReview.RATING_MEETS_EXPECTATIONS).count(),
        "exceeds_expectations": review_queryset.filter(overall_rating=PerformanceReview.RATING_EXCEEDS_EXPECTATIONS).count(),
        "outstanding": review_queryset.filter(overall_rating=PerformanceReview.RATING_OUTSTANDING).count(),
    }
    max_calibration_total = max(calibration_summary.values()) if calibration_summary else 0
    calibration_bands = [
        {
            "label": "Unsatisfactory",
            "count": calibration_summary["unsatisfactory"],
            "width": int((calibration_summary["unsatisfactory"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "danger",
        },
        {
            "label": "Needs Improvement",
            "count": calibration_summary["needs_improvement"],
            "width": int((calibration_summary["needs_improvement"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "warning",
        },
        {
            "label": "Meets Expectations",
            "count": calibration_summary["meets_expectations"],
            "width": int((calibration_summary["meets_expectations"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "primary",
        },
        {
            "label": "Exceeds Expectations",
            "count": calibration_summary["exceeds_expectations"],
            "width": int((calibration_summary["exceeds_expectations"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "success",
        },
        {
            "label": "Outstanding",
            "count": calibration_summary["outstanding"],
            "width": int((calibration_summary["outstanding"] / max_calibration_total) * 100) if max_calibration_total else 0,
            "tone": "success",
        },
    ]
    overdue_reviews = list(
        review_queryset.filter(
            status=PerformanceReview.STATUS_DRAFT,
            cycle__status=ReviewCycle.STATUS_ACTIVE,
            cycle__period_end__lt=timezone.localdate(),
        ).select_related("cycle", "employee", "reviewer")[:8]
    )
    pending_ack_reviews = list(
        review_queryset.filter(status=PerformanceReview.STATUS_SUBMITTED).select_related("cycle", "employee", "reviewer")[:8]
    )
    reviewer_queue = list(
        review_queryset.filter(
            reviewer=linked_employee,
            status__in=[PerformanceReview.STATUS_DRAFT, PerformanceReview.STATUS_SUBMITTED],
        ).order_by("cycle__period_end", "employee__full_name", "id")[:12]
    ) if linked_employee else []

    context = {
        "cycle_form": ReviewCycleForm(),
        "cycles": list(cycle_queryset[:10]),
        "review_total": review_queryset.count(),
        "cycle_total": cycle_queryset.count(),
        "active_cycle_total": cycle_queryset.filter(status=ReviewCycle.STATUS_ACTIVE).count(),
        "closed_cycle_total": cycle_queryset.filter(status=ReviewCycle.STATUS_CLOSED).count(),
        "draft_review_total": review_status_totals["draft"],
        "submitted_review_total": review_status_totals["submitted"],
        "acknowledged_review_total": review_status_totals["acknowledged"],
        "average_rating": rating_summary["average_rating"],
        "assigned_reviews": assigned_reviews[:8],
        "reviewer_queue": reviewer_queue,
        "overdue_reviews": overdue_reviews,
        "pending_ack_reviews": pending_ack_reviews,
        "department_rating_summary": department_rating_summary,
        "branch_rating_summary": branch_rating_summary,
        "calibration_bands": calibration_bands,
        "can_manage_cycles": manager_scope,
    }
    return render(request, "performance/dashboard.html", context)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to create review cycles.",
    redirect_to="performance:dashboard",
)
def review_cycle_create(request):
    if request.method == "POST":
        form = ReviewCycleForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Review cycle created successfully.")
            return redirect("performance:dashboard")
    else:
        form = ReviewCycleForm()

    return render(
        request,
        "performance/cycle_form.html",
        {
            "form": form,
            "page_title": "Create Review Cycle",
            "submit_label": "Create Cycle",
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to update review cycles.",
    redirect_to="performance:dashboard",
)
def review_cycle_update(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle, pk=cycle_pk)
    if request.method == "POST":
        form = ReviewCycleForm(request.POST, instance=cycle)
        if form.is_valid():
            form.save()
            messages.success(request, "Review cycle updated successfully.")
            return redirect("performance:dashboard")
    else:
        form = ReviewCycleForm(instance=cycle)

    return render(
        request,
        "performance/cycle_form.html",
        {
            "form": form,
            "page_title": "Update Review Cycle",
            "submit_label": "Save Cycle",
            "cycle": cycle,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to clone review cycles.",
    redirect_to="performance:dashboard",
)
@require_POST
def review_cycle_clone(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle.objects.select_related("company"), pk=cycle_pk)
    if request.method != "POST":
        return redirect("performance:dashboard")
    cloned_cycle = cycle.clone_as_draft()
    messages.success(request, f"{cycle.title} was cloned into a new draft cycle.")
    return redirect("performance:review_cycle_update", cycle_pk=cloned_cycle.pk)


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    message="You do not have permission to close review cycles.",
    redirect_to="performance:dashboard",
)
@require_POST
def review_cycle_close(request, cycle_pk):
    cycle = get_object_or_404(ReviewCycle, pk=cycle_pk)
    if request.method != "POST":
        return redirect("performance:dashboard")
    if cycle.status == ReviewCycle.STATUS_CLOSED:
        messages.info(request, "This review cycle is already closed and locked.")
        return redirect("performance:dashboard")
    cycle.status = ReviewCycle.STATUS_CLOSED
    cycle.save(update_fields=["status", "updated_at"])
    messages.success(request, f"{cycle.title} is now closed and locked for standard review updates.")
    return redirect("performance:dashboard")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to create performance reviews.",
)
def performance_review_create(request, employee_pk):
    employee = get_object_or_404(
        Employee.objects.select_related("company", "branch", "user"),
        pk=employee_pk,
    )
    if not can_manage_performance_reviews(request.user, employee):
        messages.error(request, "You do not have permission to create performance reviews for this employee.")
        return redirect("employees:employee_detail", pk=employee.pk)

    if request.method == "POST":
        form = PerformanceReviewForm(request.POST, employee=employee)
        if form.is_valid():
            review = form.save(commit=False)
            review.employee = employee
            review.created_by = request.user
            review.save()
            if review.status == PerformanceReview.STATUS_SUBMITTED and not review.submitted_at:
                review.submit()
            messages.success(request, "Performance review saved successfully.")
            return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': employee.pk})}?tab=performance")
    else:
        form = PerformanceReviewForm(employee=employee)

    return render(
        request,
        "performance/review_form.html",
        {
            "employee": employee,
            "form": form,
            "page_title": "Create Performance Review",
            "submit_label": "Save Review",
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to update performance reviews.",
)
def performance_review_update(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "cycle", "reviewer"),
        pk=review_pk,
    )
    if not can_edit_performance_review(request.user, review):
        if review.is_locked:
            messages.error(request, "This performance review belongs to a closed cycle and is locked for standard edits.")
        else:
            messages.error(request, "You do not have permission to update this performance review.")
        return redirect("employees:employee_detail", pk=review.employee.pk)

    if request.method == "POST":
        form = PerformanceReviewForm(request.POST, instance=review, employee=review.employee)
        if form.is_valid():
            updated_review = form.save()
            if updated_review.status == PerformanceReview.STATUS_SUBMITTED and not updated_review.submitted_at:
                updated_review.submit()
            messages.success(request, "Performance review updated successfully.")
            return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")
    else:
        form = PerformanceReviewForm(instance=review, employee=review.employee)

    return render(
        request,
        "performance/review_form.html",
        {
            "employee": review.employee,
            "form": form,
            "page_title": "Update Performance Review",
            "submit_label": "Save Review",
            "review": review,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to acknowledge performance reviews.",
)
@require_POST
def performance_review_acknowledge(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "employee__user", "cycle", "reviewer"),
        pk=review_pk,
    )
    if not can_acknowledge_performance_review(request.user, review):
        if review.is_locked:
            messages.error(request, "This review belongs to a closed cycle and can only be completed by management.")
        else:
            messages.error(request, "You do not have permission to acknowledge this performance review.")
        return redirect("employees:employee_detail", pk=review.employee.pk)

    if request.method == "POST":
        form = PerformanceAcknowledgementForm(request.POST, instance=review)
        if form.is_valid():
            review.acknowledge(employee_comments=form.cleaned_data.get("employee_comments", ""))
            messages.success(request, "Performance review acknowledged successfully.")
        else:
            messages.error(request, "Please review your acknowledgement comment.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to comment on performance reviews.",
)
@require_POST
def performance_review_comment_create(request, review_pk):
    review = get_object_or_404(
        build_performance_review_queryset(),
        pk=review_pk,
    )
    if request.method != "POST":
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")
    if not can_comment_on_performance_review(request.user, review):
        messages.error(request, "You do not have permission to add a note to this performance review.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")

    form = PerformanceReviewCommentForm(request.POST)
    if form.is_valid():
        PerformanceReviewComment.objects.create(
            review=review,
            author=request.user,
            note=form.cleaned_data["note"],
        )
        messages.success(request, "Performance review note added successfully.")
    else:
        messages.error(request, "Please enter a note before saving.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to force-complete performance reviews.",
)
@require_POST
def performance_review_force_complete(request, review_pk):
    review = get_object_or_404(
        PerformanceReview.objects.select_related("employee", "cycle", "reviewer"),
        pk=review_pk,
    )
    if request.method != "POST":
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")
    if not can_force_complete_performance_review(request.user, review):
        messages.error(request, "You do not have permission to force-complete this review.")
        return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")

    if not review.submitted_at:
        review.submitted_at = timezone.now()
    review.status = PerformanceReview.STATUS_ACKNOWLEDGED
    review.acknowledged_at = timezone.now()
    review.save(update_fields=["status", "submitted_at", "acknowledged_at", "updated_at"])
    PerformanceReviewComment.objects.create(
        review=review,
        author=request.user,
        note="Review force-completed after the cycle was closed and locked.",
    )
    messages.success(request, "Performance review force-completed successfully.")
    return redirect(f"{reverse('employees:employee_detail', kwargs={'pk': review.employee.pk})}?tab=performance")


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to access the reviewer queue.",
)
def performance_reviewer_queue(request):
    linked_employee = get_linked_employee(request.user)
    queue_reviews = []
    if linked_employee:
        queue_reviews = list(
            build_performance_review_queryset().filter(
                reviewer=linked_employee,
                status__in=[PerformanceReview.STATUS_DRAFT, PerformanceReview.STATUS_SUBMITTED],
            ).order_by("cycle__period_end", "employee__full_name", "id")
        )

    return render(
        request,
        "performance/reviewer_queue.html",
        {
            "queue_reviews": queue_reviews,
            "linked_employee": linked_employee,
        },
    )


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to export performance reviews.",
)
def performance_reviews_export(request):
    review_queryset = get_accessible_performance_review_queryset(request.user)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="performance-reviews.csv"'
    response.write(
        "Cycle,Company,Employee ID,Employee,Department,Branch,Reviewer,Rating,Status,Submitted At,Acknowledged At\n"
    )
    for review in review_queryset:
        response.write(
            (
                f"\"{review.cycle.title}\","
                f"\"{review.cycle.company.name}\","
                f"\"{review.employee.employee_id}\","
                f"\"{review.employee.full_name}\","
                f"\"{getattr(review.employee.department, 'name', '')}\","
                f"\"{getattr(review.employee.branch, 'name', '')}\","
                f"\"{review.reviewer.full_name}\","
                f"\"{review.get_overall_rating_display()}\","
                f"\"{review.get_status_display()}\","
                f"\"{review.submitted_at or ''}\","
                f"\"{review.acknowledged_at or ''}\"\n"
            )
        )
    return response


@role_required(
    is_admin_compatible,
    is_hr,
    is_operations,
    is_superuser,
    has_linked_employee_profile,
    message="You do not have permission to view this performance review export.",
)
def performance_review_print(request, review_pk):
    review = get_object_or_404(
        get_accessible_performance_review_queryset(request.user),
        pk=review_pk,
    )
    return render(
        request,
        "performance/review_print.html",
        {
            "review": review,
        },
    )
