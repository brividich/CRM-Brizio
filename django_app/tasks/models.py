from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TaskStatus(models.TextChoices):
    TODO = "TODO", "To do"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    DONE = "DONE", "Done"
    CANCELED = "CANCELED", "Canceled"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class TaskEventType(models.TextChoices):
    STATUS_CHANGE = "STATUS_CHANGE", "Status change"
    ASSIGNMENT_CHANGE = "ASSIGNMENT_CHANGE", "Assignment change"
    EDIT = "EDIT", "Edit"
    COMMENT_ADDED = "COMMENT_ADDED", "Comment added"
    SUBTASK_ADDED = "SUBTASK_ADDED", "Subtask added"
    SUBTASK_STATUS_CHANGE = "SUBTASK_STATUS_CHANGE", "Subtask status change"
    ATTACHMENT_ADDED = "ATTACHMENT_ADDED", "Attachment added"


class Project(models.Model):
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True, default="")
    client_name = models.CharField(max_length=180, blank=True, default="")
    project_manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_as_manager",
    )
    capo_commessa = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_as_capo_commessa",
    )
    programmer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_as_programmer",
    )
    control_method = models.CharField(max_length=180, blank=True, default="")
    part_number = models.CharField(max_length=120, blank=True, default="")
    similar_project = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="similar_projects",
    )
    similar_work_note = models.CharField(max_length=220, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="projects_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self) -> str:
        return self.name


class Task(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    tags = models.CharField(max_length=250, blank=True, default="")
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.TODO, db_index=True)
    priority = models.CharField(max_length=20, choices=TaskPriority.choices, default=TaskPriority.MEDIUM, db_index=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    next_step_text = models.CharField(max_length=300, blank=True, default="")
    next_step_due = models.DateField(null=True, blank=True, db_index=True)
    project = models.ForeignKey(
        Project,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tasks_created",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="tasks_assigned",
        null=True,
        blank=True,
    )
    subscribers = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="tasks_subscribed",
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            models.F("next_step_due").asc(nulls_last=True),
            models.F("due_date").asc(nulls_last=True),
            "-updated_at",
        ]

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if self.next_step_due and self.due_date and self.due_date <= self.next_step_due:
            raise ValidationError(
                {"due_date": "La data fine deve essere successiva alla data inizio (next step)."}
            )

    @property
    def is_overdue(self) -> bool:
        if not self.due_date:
            return False
        if self.status in {TaskStatus.DONE, TaskStatus.CANCELED}:
            return False
        return self.due_date < timezone.localdate()


class SubTask(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="subtasks")
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.TODO, db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="subtasks_assigned",
        null=True,
        blank=True,
    )
    due_date = models.DateField(null=True, blank=True, db_index=True)
    order_index = models.PositiveIntegerField(default=0, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "id"]

    def __str__(self) -> str:
        return self.title


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="task_comments")
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_comments_targeted",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Comment<{self.task_id}:{self.author_id}>"


class TaskEvent(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_events",
    )
    type = models.CharField(max_length=40, choices=TaskEventType.choices, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"TaskEvent<{self.task_id}:{self.type}>"


class ProjectComment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="project_comments")
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_comments_targeted",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"ProjectComment<{self.project_id}:{self.author_id}>"


class TaskAttachment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="attachments",
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task_attachments_uploaded",
    )
    file = models.FileField(upload_to="tasks_attachments/%Y/%m/")
    original_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        if self.task_id:
            return f"TaskAttachment<task={self.task_id}>"
        return f"TaskAttachment<project={self.project_id}>"

    def clean(self):
        super().clean()
        has_task = bool(self.task_id)
        has_project = bool(self.project_id)
        if not has_task and not has_project:
            raise ValidationError("Allegato non valido: devi associarlo a task o progetto.")
        if has_task and has_project:
            raise ValidationError("Allegato non valido: scegli task o progetto, non entrambi.")
