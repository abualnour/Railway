from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from employees.models import Employee
from organization.models import Branch


def branch_post_attachment_upload_to(instance, filename):
    extension = Path(filename).suffix.lower()
    branch_slug = (instance.branch.name or f"branch-{instance.branch_id}").strip().replace(" ", "-").lower()
    unique_name = uuid4().hex
    return f"operations/branch-posts/{branch_slug}/{unique_name}{extension}"


class BranchPost(models.Model):
    POST_TYPE_ANNOUNCEMENT = "announcement"
    POST_TYPE_UPDATE = "update"
    POST_TYPE_TASK = "task"
    POST_TYPE_ISSUE = "issue"

    POST_TYPE_CHOICES = [
        (POST_TYPE_ANNOUNCEMENT, "Announcement"),
        (POST_TYPE_UPDATE, "Update"),
        (POST_TYPE_TASK, "Task"),
        (POST_TYPE_ISSUE, "Issue"),
    ]

    STATUS_OPEN = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CLOSED = "closed"

    STATUS_CHOICES = [
        (STATUS_OPEN, "Open"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_DONE, "Done"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CLOSED, "Closed"),
    ]

    PRIORITY_LOW = "low"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_HIGH = "high"
    PRIORITY_URGENT = "urgent"

    PRIORITY_CHOICES = [
        (PRIORITY_LOW, "Low"),
        (PRIORITY_MEDIUM, "Medium"),
        (PRIORITY_HIGH, "High"),
        (PRIORITY_URGENT, "Urgent"),
    ]

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="posts")
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_posts",
        null=True,
        blank=True,
    )
    author_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="authored_branch_posts",
        null=True,
        blank=True,
    )
    assignee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="assigned_branch_posts",
        null=True,
        blank=True,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    post_type = models.CharField(max_length=20, choices=POST_TYPE_CHOICES, default=POST_TYPE_UPDATE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, blank=True, default="")
    is_pinned = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    attachment = models.FileField(
        upload_to=branch_post_attachment_upload_to,
        blank=True,
        null=True,
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "png",
                    "jpg",
                    "jpeg",
                    "webp",
                    "gif",
                    "bmp",
                    "txt",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                ]
            )
        ],
    )
    due_date = models.DateField(null=True, blank=True)
    requires_acknowledgement = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="approved_branch_posts",
        null=True,
        blank=True,
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_pinned", "-updated_at", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["branch", "status", "-updated_at"]),
            models.Index(fields=["assignee", "status", "due_date"]),
            models.Index(fields=["post_type", "status"]),
        ]
        verbose_name = "Branch Post"
        verbose_name_plural = "Branch Posts"

    def __str__(self):
        return f"{self.branch.name} | {self.title}"

    @property
    def is_task_like(self):
        return self.post_type in {self.POST_TYPE_TASK, self.POST_TYPE_ISSUE}

    @property
    def author_display(self):
        if self.author_employee_id:
            return self.author_employee.full_name
        if self.author_user_id:
            return self.author_user.get_full_name() or self.author_user.email
        return "System"

    def mark_approved(self, user=None):
        self.status = self.STATUS_APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.closed_at = None

    def mark_closed(self):
        self.status = self.STATUS_CLOSED
        self.closed_at = timezone.now()


class BranchPostReply(models.Model):
    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="replies")
    author_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_post_replies",
        null=True,
        blank=True,
    )
    author_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="branch_post_replies",
        null=True,
        blank=True,
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["post", "created_at"])]
        verbose_name = "Branch Post Reply"
        verbose_name_plural = "Branch Post Replies"

    def __str__(self):
        return f"Reply #{self.pk or 'new'} on {self.post_id}"

    @property
    def author_display(self):
        if self.author_employee_id:
            return self.author_employee.full_name
        if self.author_user_id:
            return self.author_user.get_full_name() or self.author_user.email
        return "System"


class BranchTaskAction(models.Model):
    ACTION_CREATED = "created"
    ACTION_STATUS_CHANGED = "status_changed"
    ACTION_ASSIGNED = "assigned"
    ACTION_REPLIED = "replied"
    ACTION_ACKNOWLEDGED = "acknowledged"
    ACTION_APPROVED = "approved"
    ACTION_REJECTED = "rejected"
    ACTION_PINNED = "pinned"
    ACTION_UNPINNED = "unpinned"
    ACTION_CLOSED = "closed"

    ACTION_CHOICES = [
        (ACTION_CREATED, "Created"),
        (ACTION_STATUS_CHANGED, "Status Changed"),
        (ACTION_ASSIGNED, "Assigned"),
        (ACTION_REPLIED, "Replied"),
        (ACTION_ACKNOWLEDGED, "Acknowledged"),
        (ACTION_APPROVED, "Approved"),
        (ACTION_REJECTED, "Rejected"),
        (ACTION_PINNED, "Pinned"),
        (ACTION_UNPINNED, "Unpinned"),
        (ACTION_CLOSED, "Closed"),
    ]

    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="actions")
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="branch_task_actions",
        null=True,
        blank=True,
    )
    actor_employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        related_name="branch_task_actions",
        null=True,
        blank=True,
    )
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20, blank=True, default="")
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["post", "-created_at"]),
            models.Index(fields=["action_type", "-created_at"]),
        ]
        verbose_name = "Branch Task Action"
        verbose_name_plural = "Branch Task Actions"

    def __str__(self):
        return f"{self.post_id} | {self.action_type}"

    @property
    def actor_display(self):
        if self.actor_employee_id:
            return self.actor_employee.full_name
        if self.actor_user_id:
            return self.actor_user.get_full_name() or self.actor_user.email
        return "System"


class BranchPostAcknowledgement(models.Model):
    post = models.ForeignKey(BranchPost, on_delete=models.CASCADE, related_name="acknowledgements")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="branch_post_acknowledgements")
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-acknowledged_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "employee"],
                name="ops_post_ack_post_employee_uniq",
            )
        ]
        verbose_name = "Branch Post Acknowledgement"
        verbose_name_plural = "Branch Post Acknowledgements"

    def __str__(self):
        return f"{self.post_id} | {self.employee.full_name}"
