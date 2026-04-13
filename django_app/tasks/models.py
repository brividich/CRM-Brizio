from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.utils import timezone


def _next_kickoff_number() -> int:
    max_number = Project.objects.aggregate(max_number=Max("kickoff_number")).get("max_number") or 0
    return int(max_number) + 1


class VRFDocStatus(models.TextChoices):
    PENDING      = "PENDING",      "Da caricare"
    UPLOADED     = "UPLOADED",     "Caricato"
    NOT_REQUIRED = "NOT_REQUIRED", "Non richiesto"


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
    kickoff_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        editable=False,
    )
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
    revisione = models.CharField(max_length=60, blank=True, default="")
    versione = models.CharField(max_length=60, blank=True, default="")
    vrf_status = models.CharField(
        max_length=20, choices=VRFDocStatus.choices, default=VRFDocStatus.PENDING,
        verbose_name="Stato documento VRF",
    )
    vrf_file = models.FileField(upload_to="tasks_vrf/%Y/%m/", null=True, blank=True)
    vrf_original_name = models.CharField(max_length=255, blank=True, default="")
    vrf_uploaded_at = models.DateTimeField(null=True, blank=True)
    vrf_quote_number = models.CharField(max_length=120, blank=True, default="", verbose_name="Preventivo n°")
    vrf_description = models.CharField(max_length=500, blank=True, default="", verbose_name="Descrizione VRF")
    vrf_esp = models.CharField(max_length=120, blank=True, default="", verbose_name="Esp")
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

    def save(self, *args, **kwargs):
        if not self._state.adding:
            if self.kickoff_number and not self.name:
                self.name = f"KICK-OFF {self.kickoff_number}"
            return super().save(*args, **kwargs)

        if self.kickoff_number:
            if not self.name:
                self.name = f"KICK-OFF {self.kickoff_number}"
            return super().save(*args, **kwargs)

        max_attempts = 5
        for attempt in range(max_attempts):
            self.kickoff_number = _next_kickoff_number()
            self.name = f"KICK-OFF {self.kickoff_number}"
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.kickoff_number = None
                if not self._state.adding or attempt == max_attempts - 1:
                    raise

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


class TaskImpostazioni(models.Model):
    """Singleton: impostazioni globali del modulo Task."""

    responsabile_email = models.EmailField(
        blank=True, default="",
        verbose_name="Email notifiche",
        help_text="Indirizzo email per notifiche di sistema (scadenze, assegnazioni).",
    )
    notifiche_scadenza_attive = models.BooleanField(
        default=False,
        verbose_name="Notifiche scadenza attive",
        help_text="Invia email di promemoria X giorni prima della scadenza di un task.",
    )
    giorni_preavviso = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Giorni preavviso scadenza",
    )
    note_generali = models.TextField(blank=True, default="", verbose_name="Note generali")
    vrf_reminder_days = models.PositiveSmallIntegerField(
        default=7,
        verbose_name="Giorni avviso VRF",
        help_text="Mostra un avviso giallo dopo N giorni dalla creazione del progetto senza documento VRF caricato.",
    )
    vrf_blocking_days = models.PositiveSmallIntegerField(
        default=30,
        verbose_name="Giorni blocco VRF",
        help_text="Blocca la creazione/modifica di VRF su quel progetto dopo N giorni senza documento VRF.",
    )

    class Meta:
        verbose_name = "Impostazioni KICK-OFF"
        verbose_name_plural = "Impostazioni KICK-OFF"
        constraints = [
            models.CheckConstraint(check=models.Q(pk=1), name="taskimpostazioni_singleton"),
        ]

    def __str__(self) -> str:
        return "Impostazioni KICK-OFF"

    @classmethod
    def get_singleton(cls) -> "TaskImpostazioni":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
