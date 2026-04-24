from datetime import date

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from employees.models import get_schedule_week_start
from employees.views import build_branch_weekly_schedule_summary
from organization.models import Branch
from notifications.models import InAppNotification
from notifications.services import build_in_app_notification, persist_in_app_notifications

from .forms import BranchPostForm, BranchPostReplyForm
from .models import BranchPost, BranchPostAcknowledgement, BranchTaskAction
from .services import (
    build_branch_post_cards,
    build_branch_workspace_context,
    can_access_branch_workspace,
    can_acknowledge_branch_post,
    can_change_branch_post_status,
    can_create_branch_post,
    can_manage_branch_post,
    can_manage_branch_workspace,
    can_reply_branch_post,
    create_post_action,
    ensure_branch_access,
    get_user_employee_profile,
)


def get_branch_notification_users(branch, *excluded_users):
    excluded_user_ids = {user.pk for user in excluded_users if user and getattr(user, "pk", None)}
    return list(
        get_user_model().objects.filter(
            is_active=True,
            employee_profile__branch=branch,
            employee_profile__is_active=True,
        )
        .exclude(pk__in=excluded_user_ids)
        .distinct()
        .order_by("email")
    )


def create_operation_notifications(users, *, title, body, action_url, level=InAppNotification.LEVEL_INFO):
    notifications = []
    seen_user_ids = set()
    for user in users:
        if not user or not getattr(user, "is_active", False) or user.pk in seen_user_ids:
            continue
        seen_user_ids.add(user.pk)
        notifications.append(
            build_in_app_notification(
                recipient=user,
                title=title,
                body=body,
                category=InAppNotification.CATEGORY_OPERATIONS,
                level=level,
                action_url=action_url,
            )
        )
    return len(persist_in_app_notifications(notifications))


def notify_branch_post_created(post, actor_user):
    detail_url = reverse("operations:branch_post_detail", kwargs={"post_id": post.id})
    if post.post_type == BranchPost.POST_TYPE_ANNOUNCEMENT:
        create_operation_notifications(
            get_branch_notification_users(post.branch, actor_user),
            title=f"New branch announcement: {post.title}",
            body=f"A new announcement was published for {post.branch.name}.",
            action_url=detail_url,
            level=InAppNotification.LEVEL_INFO,
        )
        return

    if post.assignee_id and getattr(post.assignee, "user_id", None) and post.assignee.user_id != getattr(actor_user, "pk", None):
        create_operation_notifications(
            [post.assignee.user],
            title=f"Branch item assigned: {post.title}",
            body=f"You were assigned a {post.get_post_type_display().lower()} in {post.branch.name}.",
            action_url=detail_url,
            level=InAppNotification.LEVEL_WARNING,
        )


def notify_branch_post_reply(post, reply):
    detail_url = reverse("operations:branch_post_detail", kwargs={"post_id": post.id})
    recipients = []
    if getattr(post.author_user, "is_active", False) and post.author_user_id != reply.author_user_id:
        recipients.append(post.author_user)
    if post.assignee_id and getattr(post.assignee, "user_id", None) and post.assignee.user_id != reply.author_user_id:
        recipients.append(post.assignee.user)
    create_operation_notifications(
        recipients,
        title=f"New reply on branch item: {post.title}",
        body=f"{reply.author_display} added a new reply in {post.branch.name}.",
        action_url=detail_url,
        level=InAppNotification.LEVEL_INFO,
    )


def notify_branch_post_status_change(post, actor_user=None, actor_employee=None):
    detail_url = reverse("operations:branch_post_detail", kwargs={"post_id": post.id})
    recipients = []
    actor_user_id = getattr(actor_user, "pk", None) or getattr(getattr(actor_employee, "user", None), "pk", None)
    if getattr(post.author_user, "is_active", False) and post.author_user_id != actor_user_id:
        recipients.append(post.author_user)
    if post.assignee_id and getattr(post.assignee, "user_id", None) and post.assignee.user_id != actor_user_id:
        recipients.append(post.assignee.user)
    create_operation_notifications(
        recipients,
        title=f"Branch item status updated: {post.title}",
        body=f"The status is now {post.get_status_display()} in {post.branch.name}.",
        action_url=detail_url,
        level=InAppNotification.LEVEL_SUCCESS if post.status in {BranchPost.STATUS_APPROVED, BranchPost.STATUS_CLOSED} else InAppNotification.LEVEL_INFO,
    )


def notify_branch_post_acknowledged(post, employee):
    if not getattr(post.author_user, "is_active", False) or post.author_user_id == getattr(employee, "user_id", None):
        return
    create_operation_notifications(
        [post.author_user],
        title=f"Announcement acknowledged: {post.title}",
        body=f"{employee.full_name} acknowledged this announcement.",
        action_url=reverse("operations:branch_post_detail", kwargs={"post_id": post.id}),
        level=InAppNotification.LEVEL_SUCCESS,
    )


def _get_selected_week_start(request):
    week_value = (request.GET.get("week") or request.POST.get("week") or "").strip()
    if week_value:
        try:
            return get_schedule_week_start(date.fromisoformat(week_value))
        except ValueError:
            return get_schedule_week_start(timezone.localdate())
    return get_schedule_week_start(timezone.localdate())


def _get_post_form(branch, user, employee, data=None, files=None):
    return BranchPostForm(
        data=data,
        files=files,
        branch=branch,
        can_manage=can_manage_branch_workspace(user, branch, employee=employee),
    )


@login_required
def branch_workspace_detail(request, branch_id):
    branch = get_object_or_404(Branch.objects.select_related("company"), pk=branch_id)
    employee = get_user_employee_profile(request.user)
    ensure_branch_access(request.user, branch, employee=employee)

    selected_week_start = _get_selected_week_start(request)
    context = build_branch_workspace_context(
        branch,
        request.user,
        employee=employee,
        week_start=selected_week_start,
    )
    context.update(build_branch_weekly_schedule_summary(branch, selected_week_start))
    context["branch"] = branch
    context["branch_post_form"] = _get_post_form(branch, request.user, employee)
    context["branch_workspace_mode"] = "management"
    context["branch_workspace_schedule_url"] = (
        reverse("employees:self_service_weekly_schedule")
        if employee and getattr(employee, "branch_id", None) == branch.id
        else ""
    )
    return render(request, "operations/branch_workspace.html", context)


@login_required
@require_POST
def branch_post_create(request, branch_id):
    branch = get_object_or_404(Branch, pk=branch_id)
    employee = get_user_employee_profile(request.user)
    if not can_create_branch_post(request.user, branch, employee=employee):
        raise PermissionDenied("You do not have permission to post in this branch workspace.")

    form = _get_post_form(branch, request.user, employee, data=request.POST, files=request.FILES)
    if form.is_valid():
        post = form.save(commit=False)
        if not can_manage_branch_workspace(request.user, branch, employee=employee):
            if post.post_type == BranchPost.POST_TYPE_ANNOUNCEMENT:
                post.post_type = BranchPost.POST_TYPE_UPDATE
            if post.priority not in {BranchPost.PRIORITY_LOW, BranchPost.PRIORITY_MEDIUM, ""}:
                post.priority = BranchPost.PRIORITY_MEDIUM
            post.is_pinned = False
            post.requires_acknowledgement = False
        post.branch = branch
        post.author_user = request.user
        post.author_employee = employee
        post.save()
        create_post_action(
            post,
            action_type=BranchTaskAction.ACTION_CREATED,
            user=request.user,
            employee=employee,
            note="Branch post created.",
            to_status=post.status,
        )
        if post.assignee_id:
            create_post_action(
                post,
                action_type=BranchTaskAction.ACTION_ASSIGNED,
                user=request.user,
                employee=employee,
                note=f"Assigned to {post.assignee.full_name}.",
            )
        if post.is_pinned:
            create_post_action(
                post,
                action_type=BranchTaskAction.ACTION_PINNED,
                user=request.user,
                employee=employee,
                note="Post pinned in branch workspace.",
            )
        notify_branch_post_created(post, request.user)
        messages.success(request, "Branch post created successfully.")
    else:
        messages.error(request, "Please correct the branch post form and try again.")

    next_url = request.POST.get("next") or reverse("employees:self_service_branch")
    return redirect(next_url)


@login_required
def branch_post_detail(request, post_id):
    post = get_object_or_404(
        BranchPost.objects.select_related(
            "branch",
            "branch__company",
            "author_user",
            "author_employee",
            "assignee",
            "assignee__job_title",
            "approved_by",
        ).prefetch_related("replies", "actions", "acknowledgements"),
        pk=post_id,
    )
    employee = get_user_employee_profile(request.user)
    if not can_access_branch_workspace(request.user, post.branch, employee=employee):
        raise PermissionDenied("You do not have permission to access this branch post.")

    context = build_branch_workspace_context(post.branch, request.user, employee=employee)
    context["branch"] = post.branch
    context["post"] = post
    context["post_card"] = build_branch_post_cards([post], employee=employee)[0]
    context["reply_form"] = BranchPostReplyForm()
    context["can_reply_branch_post"] = can_reply_branch_post(request.user, post, employee=employee)
    context["can_manage_branch_post"] = can_manage_branch_post(request.user, post, employee=employee)
    context["can_update_assigned_branch_post"] = bool(employee and post.assignee_id == employee.id)
    context["can_acknowledge_branch_post"] = can_acknowledge_branch_post(request.user, post, employee=employee)
    context["has_acknowledged_post"] = bool(
        employee and BranchPostAcknowledgement.objects.filter(post=post, employee=employee).exists()
    )
    return render(request, "operations/branch_post_detail.html", context)


@login_required
@require_POST
def branch_post_reply_create(request, post_id):
    post = get_object_or_404(BranchPost.objects.select_related("branch"), pk=post_id)
    employee = get_user_employee_profile(request.user)
    if not can_reply_branch_post(request.user, post, employee=employee):
        raise PermissionDenied("You do not have permission to reply in this branch post.")

    form = BranchPostReplyForm(request.POST)
    if form.is_valid():
        reply = form.save(commit=False)
        reply.post = post
        reply.author_user = request.user
        reply.author_employee = employee
        reply.save()
        create_post_action(
            post,
            action_type=BranchTaskAction.ACTION_REPLIED,
            user=request.user,
            employee=employee,
            note="Reply added to branch post.",
        )
        notify_branch_post_reply(post, reply)
        messages.success(request, "Reply added successfully.")
    else:
        messages.error(request, "Reply text is required.")

    return redirect("operations:branch_post_detail", post_id=post.id)


@login_required
@require_POST
def branch_post_status_update(request, post_id):
    post = get_object_or_404(BranchPost.objects.select_related("branch", "assignee"), pk=post_id)
    employee = get_user_employee_profile(request.user)
    target_status = (request.POST.get("target_status") or "").strip()
    if not can_change_branch_post_status(request.user, post, target_status, employee=employee):
        raise PermissionDenied("You do not have permission to change this branch workflow status.")

    valid_statuses = {choice[0] for choice in BranchPost.STATUS_CHOICES}
    if target_status not in valid_statuses:
        messages.error(request, "Invalid branch workflow status.")
        return redirect("operations:branch_post_detail", post_id=post.id)

    previous_status = post.status
    post.status = target_status
    action_type = BranchTaskAction.ACTION_STATUS_CHANGED
    note = f"Status updated to {post.get_status_display()}."

    if target_status == BranchPost.STATUS_APPROVED:
        post.mark_approved(user=request.user)
        action_type = BranchTaskAction.ACTION_APPROVED
        note = "Task approved."
    elif target_status == BranchPost.STATUS_REJECTED:
        post.approved_at = None
        post.approved_by = None
        post.closed_at = None
        action_type = BranchTaskAction.ACTION_REJECTED
        note = "Task rejected."
    elif target_status == BranchPost.STATUS_CLOSED:
        post.mark_closed()
        action_type = BranchTaskAction.ACTION_CLOSED
        note = "Post closed."
    else:
        post.approved_at = None
        post.approved_by = None
        post.closed_at = None

    post.save(update_fields=["status", "approved_at", "approved_by", "closed_at", "updated_at"])
    create_post_action(
        post,
        action_type=action_type,
        user=request.user,
        employee=employee,
        from_status=previous_status,
        to_status=target_status,
        note=note,
    )
    notify_branch_post_status_change(post, actor_user=request.user, actor_employee=employee)
    messages.success(request, "Branch workflow status updated.")
    return redirect("operations:branch_post_detail", post_id=post.id)


@login_required
@require_POST
def branch_post_acknowledge(request, post_id):
    post = get_object_or_404(BranchPost.objects.select_related("branch"), pk=post_id)
    employee = get_user_employee_profile(request.user)
    if not can_acknowledge_branch_post(request.user, post, employee=employee):
        raise PermissionDenied("You do not have permission to acknowledge this branch post.")

    acknowledgement, created = BranchPostAcknowledgement.objects.get_or_create(post=post, employee=employee)
    if created:
        create_post_action(
            post,
            action_type=BranchTaskAction.ACTION_ACKNOWLEDGED,
            user=request.user,
            employee=employee,
            note="Announcement acknowledged.",
        )
        notify_branch_post_acknowledged(post, employee)
        messages.success(request, "Announcement acknowledged.")
    else:
        messages.info(request, "This announcement was already acknowledged.")

    return redirect("operations:branch_post_detail", post_id=post.id)
