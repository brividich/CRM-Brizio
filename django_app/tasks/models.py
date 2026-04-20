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
    reminder_portal_enabled = models.BooleanField(
        default=True,
        help_text="Se attivo, crea un promemoria nel centro notifiche 'giorni_preavviso' prima della scadenza.",
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


class VRFRiskAssessment(models.Model):
    """Valutazione rischi del MOD.073 VRF Rev.10 compilata online.

    1:1 col Project. Il payload 'data' segue la shape di vrf_catalog.default_scores().
    I totali (TR per fase) sono cache denormalizzata: ricalcolati a ogni save()
    dal catalogo per mantenere coerenza con la logica di riferimento.
    """

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="vrf_assessment",
    )
    data = models.JSONField(default=dict, blank=True)
    total_p = models.FloatField(default=0.0)
    total_i = models.FloatField(default=0.0)
    total_c = models.FloatField(default=0.0)
    dig_triggered = models.BooleanField(default=False)
    compiled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vrf_assessments_compiled",
    )
    compiled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Valutazione rischi VRF"
        verbose_name_plural = "Valutazioni rischi VRF"

    def __str__(self) -> str:
        return f"VRF#{self.project_id}"

    def recompute_totals(self) -> None:
        from .vrf_catalog import compute_totals
        result = compute_totals(self.data or {})
        totals = result["totals"]
        self.total_p = float(totals.get("p") or 0.0)
        self.total_i = float(totals.get("i") or 0.0)
        self.total_c = float(totals.get("c") or 0.0)
        self.dig_triggered = bool(result.get("dig_triggered"))


class TaskRoleType(models.TextChoices):
    PROJECT_MANAGER = "PM",   "Project manager"
    CAPO_COMMESSA   = "CC",   "Capocommessa"
    PROGRAMMER      = "PRG",  "Programmatore"


class TaskRoleAssignment(models.Model):
    """Mappatura utenti abilitati a comparire come scelta nei dropdown kickoff/task.

    Serve per filtrare i dropdown di Nuovo kickoff / Nuova attivita':
    - se almeno un utente ha assegnato il role_type X, il dropdown relativo mostra
      solo quegli utenti;
    - se nessun utente ha il role_type X, il dropdown mantiene il comportamento
      originale (tutti gli utenti) per non bloccare l'operativita'.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_role_assignments",
    )
    role_type = models.CharField(max_length=8, choices=TaskRoleType.choices, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role_type")]
        ordering = ["role_type", "user__last_name", "user__first_name", "user_id"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role_type}"


class TaskCalendarEvent(models.Model):
    """Evento Outlook calendar creato per un Task (dedup + tracking).

    Ogni task puo' avere al piu' un evento attivo (dedup su `source_key`).
    Il record mantiene l'identita' Graph per update/delete successivi.
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="calendar_events")
    source_key = models.CharField(max_length=160, unique=True, db_index=True)
    target_email = models.EmailField()
    target_display_name = models.CharField(max_length=200, blank=True, default="")
    due_date = models.DateField()
    subject = models.CharField(max_length=255, blank=True, default="")
    transaction_id = models.CharField(max_length=64, blank=True, default="")
    graph_event_id = models.CharField(max_length=255, blank=True, default="")
    graph_event_web_link = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="task_calendar_events_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"TaskCalendarEvent<task={self.task_id} event={self.graph_event_id}>"


class TaskReminder(models.Model):
    """Promemoria portale schedulato per una task.

    Viene creato al salvataggio della task con `fire_at = due_date - giorni_preavviso`.
    Il management command `send_task_reminders` lo trasforma in `core.Notifica`
    quando `fire_at <= today`.
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="portal_reminders")
    legacy_user_id = models.IntegerField(db_index=True)
    fire_at = models.DateField(db_index=True)
    fired = models.BooleanField(default=False, db_index=True)
    fired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["fire_at", "id"]
        indexes = [models.Index(fields=["fired", "fire_at"])]

    def __str__(self) -> str:
        return f"TaskReminder<task={self.task_id} fire_at={self.fire_at} fired={self.fired}>"
