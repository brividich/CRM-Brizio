from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models import Max
from django.utils import timezone

from tasks.identity import normalize_client_name, normalize_part_number
from tasks.storage import PrivateTasksStorage


def _next_kickoff_number() -> int:
    max_number = Project.objects.aggregate(max_number=Max("kickoff_number")).get("max_number") or 0
    return int(max_number) + 1


class VRFDocStatus(models.TextChoices):
    PENDING      = "PENDING",      "Da caricare"
    UPLOADED     = "UPLOADED",     "Caricato"
    NOT_REQUIRED = "NOT_REQUIRED", "Non richiesto"


class ProjectPhase(models.TextChoices):
    BOZZA = "BOZZA", "Bozza"
    VRF = "VRF", "VRF"
    EXEC = "EXEC", "In esecuzione"
    DONE = "DONE", "Completata"


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
    phase = models.CharField(
        max_length=10, choices=ProjectPhase.choices,
        default=ProjectPhase.BOZZA, db_index=True, verbose_name="Fase",
    )
    # Storage privato (fuori webroot) dalla remediation sicurezza: il VRF contiene
    # dati commerciali (cliente, P/N, matrice rischi) e va servito solo da view protette.
    vrf_file = models.FileField(upload_to="tasks_vrf/%Y/%m/", null=True, blank=True, storage=PrivateTasksStorage())
    vrf_original_name = models.CharField(max_length=255, blank=True, default="")
    vrf_uploaded_at = models.DateTimeField(null=True, blank=True)
    vrf_quote_number = models.CharField(max_length=120, blank=True, default="", verbose_name="Preventivo n°")
    vrf_description = models.CharField(max_length=500, blank=True, default="", verbose_name="Descrizione VRF")
    vrf_esp = models.CharField(max_length=120, blank=True, default="", verbose_name="Esp")
    safety_impact = models.BooleanField(
        default=False,
        verbose_name="Impatto sulla sicurezza",
        help_text="Indica se il progetto ha impatto sulla sicurezza",
        db_index=True,
    )
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
        self.part_number = normalize_part_number(self.part_number)
        self.client_name = normalize_client_name(self.client_name)

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
    progress = models.PositiveSmallIntegerField(
        default=0,
        help_text="Avanzamento manuale dell'attività (0–100).",
    )
    reminder_portal_enabled = models.BooleanField(
        default=True,
        help_text="Se attivo, crea un promemoria nel centro notifiche 'giorni_preavviso' prima della scadenza.",
    )
    category = models.ForeignKey(
        "TaskCategory",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    extra_data = models.JSONField(default=dict, blank=True)

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


class DependencyType(models.TextChoices):
    FS = "FS", "Fine → Inizio (FS)"
    SS = "SS", "Inizio → Inizio (SS)"
    FF = "FF", "Fine → Fine (FF)"
    SF = "SF", "Inizio → Fine (SF)"


class TaskDependency(models.Model):
    """Dipendenza direzionale tra due task: `predecessor` deve rispettare il tipo prima che `successor` possa iniziare/finire."""
    predecessor = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="successors",
    )
    successor = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="predecessors",
    )
    dependency_type = models.CharField(
        max_length=2,
        choices=DependencyType.choices,
        default=DependencyType.FS,
    )
    lag_days = models.SmallIntegerField(
        default=0,
        help_text="Giorni di ritardo/anticipo (positivo = lag, negativo = lead).",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["predecessor", "successor"], name="tasks_taskdependency_unique_pair"),
        ]
        verbose_name = "Dipendenza task"

    def __str__(self) -> str:
        return f"{self.predecessor_id} →{self.dependency_type}→ {self.successor_id}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.predecessor_id and self.successor_id and self.predecessor_id == self.successor_id:
            raise ValidationError("Un task non può dipendere da se stesso.")


class GanttBaseline(models.Model):
    """Snapshot delle date Gantt al momento del 'Fissa baseline'.

    `snapshot` è un dict JSON: { "<task_id>": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} }
    """
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="gantt_baseline",
    )
    snapshot = models.JSONField(default=dict)
    fixed_at = models.DateTimeField(auto_now=True)
    fixed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="gantt_baselines_fixed",
    )

    class Meta:
        verbose_name = "Baseline Gantt"

    def __str__(self) -> str:
        return f"Baseline {self.project.name}"

    def get_task_delta_days(self, task: "Task") -> dict[str, int | None]:
        """Restituisce {'start': Δgg, 'end': Δgg} rispetto alla baseline, o None se non presente."""
        entry = self.snapshot.get(str(task.pk))
        if not entry:
            return {"start": None, "end": None}
        from datetime import date as _date
        def _delta(field_val, baseline_str):
            if not field_val or not baseline_str:
                return None
            try:
                b = _date.fromisoformat(baseline_str)
                return (field_val - b).days
            except (ValueError, TypeError):
                return None
        return {
            "start": _delta(task.next_step_due, entry.get("start")),
            "end":   _delta(task.due_date,      entry.get("end")),
        }


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
    file = models.FileField(upload_to="tasks_attachments/%Y/%m/", storage=PrivateTasksStorage())
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


class TaskRolesSource(models.TextChoices):
    ANAGRAFICA = "anagrafica", "Da anagrafica (Reparti)"
    MANUAL     = "manual",     "Manuale"


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
    asset_conflict_check_enabled = models.BooleanField(
        default=True,
        verbose_name="Verifica disponibilita asset",
        help_text="Se attivo, all'assegnazione di un asset mostra OdL, verifiche, ticket e attivita in conflitto nella finestra temporale.",
    )
    asset_conflict_block = models.BooleanField(
        default=False,
        verbose_name="Blocca il salvataggio su conflitto asset",
        help_text="Se attivo, impedisce di salvare l'attivita quando l'asset selezionato ha conflitti rilevanti (OdL aperto, asset in riparazione, sovrapposizione con altra attivita).",
    )
    roles_source = models.CharField(
        max_length=16,
        choices=TaskRolesSource.choices,
        default=TaskRolesSource.ANAGRAFICA,
        verbose_name="Fonte ruoli Caporeparto / Capocommessa",
        help_text=(
            "Anagrafica: i Caporeparto sono derivati automaticamente dai Reparti "
            "e usati come candidati nel campo Capocommessa dei kickoff. "
            "Manuale: le assegnazioni CR e CC vengono gestite dalla tabella sotto."
        ),
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
    CAPOREPARTO     = "CR",   "Caporeparto"


class TaskRoleDefinition(models.Model):
    """Catalogo ruoli operativi configurabile da Impostazioni KICK-OFF."""

    code = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default="")
    is_system = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    order_index = models.PositiveIntegerField(default=0, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "name", "id"]
        verbose_name = "Ruolo operativo task"
        verbose_name_plural = "Ruoli operativi task"

    def __str__(self) -> str:
        return self.name


class TaskAccessLevel(models.TextChoices):
    NONE = "NONE", "Nessun accesso extra"
    READ_ALL = "READ_ALL", "Vede tutto"
    EDIT_ASSIGNED = "EDIT_ASSIGNED", "Modifica solo i task assegnati"
    EDIT_ALL = "EDIT_ALL", "Modifica tutto"


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
    role_type = models.CharField(max_length=32, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "role_type")]
        ordering = ["role_type", "user__last_name", "user__first_name", "user_id"]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.role_type}"


class TaskRoleAccessRule(models.Model):
    """Regola accesso per ruolo operativo kickoff.

    La regola vale all'interno dei kickoff in cui l'utente ricopre il ruolo
    configurato (`project_manager`, `capo_commessa`, `programmer`).
    """

    role_type = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
    )
    access_level = models.CharField(
        max_length=20,
        choices=TaskAccessLevel.choices,
        default=TaskAccessLevel.NONE,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["role_type"]
        verbose_name = "Regola accesso ruolo KICK-OFF"
        verbose_name_plural = "Regole accesso ruoli KICK-OFF"

    def __str__(self) -> str:
        return f"TaskRoleAccessRule<{self.role_type}={self.access_level}>"


class TaskUserAccessRule(models.Model):
    """Override accesso globale modulo KICK-OFF per singolo utente."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="task_access_rule",
    )
    access_level = models.CharField(
        max_length=20,
        choices=TaskAccessLevel.choices,
        default=TaskAccessLevel.READ_ALL,
        db_index=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__last_name", "user__first_name", "user_id"]
        verbose_name = "Override accesso utente KICK-OFF"
        verbose_name_plural = "Override accesso utenti KICK-OFF"

    def __str__(self) -> str:
        return f"TaskUserAccessRule<user={self.user_id}={self.access_level}>"


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


class TaskCategory(models.Model):
    """Tipologia di attivita' configurabile dall'admin.

    Ogni categoria definisce un set di campi extra (TaskCategoryField) che
    l'utente compila quando crea un'attivita' di quella tipologia. I valori
    sono persistiti su Task.extra_data (JSON) e, per i campi FK utente/asset,
    anche in TaskExtraRef per query efficienti.
    """
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    icon = models.CharField(max_length=80, blank=True, default="")
    description = models.CharField(max_length=255, blank=True, default="")
    role_type = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_index=True,
        help_text="Ruolo operativo autorizzato per questo tipo attivita.",
    )
    order_index = models.PositiveIntegerField(default=0, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_machine_work = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Se attivo, le attività di questo tipo sono 'Lavoro macchina': richiedono un campo asset e compaiono nel calendario delle macchine.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "name", "id"]
        verbose_name = "Tipo attivita"
        verbose_name_plural = "Tipi attivita"

    def __str__(self) -> str:
        return self.name


class TaskCategoryFieldType(models.TextChoices):
    TEXT        = "text",        "Testo"
    NUMBER      = "number",      "Numero"
    DATE        = "date",        "Data"
    CHECKBOX    = "checkbox",    "Checkbox"
    SELECT      = "select",      "Menu a tendina"
    MULTISELECT = "multiselect", "Scelta multipla"
    USER        = "user",        "Utente"
    ASSET       = "asset",       "Asset"


class TaskCategoryField(models.Model):
    """Singolo campo extra associato a una TaskCategory.

    - choices_json: solo per select/multiselect, lista di stringhe oppure
      lista di oggetti {value, label}.
    - depends_on_code + depends_on_value: dipendenza dinamica. Il campo e'
      visibile/richiesto solo se il campo 'depends_on_code' (stessa categoria)
      ha il valore indicato. Supporta anche valori multipli separati da '|'.
    """
    category = models.ForeignKey(
        TaskCategory,
        on_delete=models.CASCADE,
        related_name="fields",
    )
    code = models.SlugField(max_length=60)
    label = models.CharField(max_length=180)
    field_type = models.CharField(
        max_length=20,
        choices=TaskCategoryFieldType.choices,
        default=TaskCategoryFieldType.TEXT,
    )
    required = models.BooleanField(default=False)
    order_index = models.PositiveIntegerField(default=0, db_index=True)
    help_text = models.CharField(max_length=255, blank=True, default="")
    placeholder = models.CharField(max_length=120, blank=True, default="")
    choices_json = models.JSONField(default=list, blank=True)
    depends_on_code = models.CharField(max_length=60, blank=True, default="")
    depends_on_value = models.CharField(max_length=255, blank=True, default="")
    asset_type_filter = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Solo per field_type=asset. CSV di codici asset_type (es. 'CNC,WORK_MACHINE'). Vuoto = tutti i tipi.",
    )
    asset_category_filter = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Solo per field_type=asset. CSV di ID AssetCategory. Vuoto = tutte le categorie.",
    )

    class Meta:
        ordering = ["order_index", "id"]
        unique_together = [("category", "code")]
        verbose_name = "Campo tipo attivita"
        verbose_name_plural = "Campi tipo attivita"

    def __str__(self) -> str:
        return f"{self.category_id}.{self.code}"

    def asset_type_filter_list(self) -> list[str]:
        raw = (self.asset_type_filter or "").strip()
        if not raw:
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    def asset_category_filter_ids(self) -> list[int]:
        raw = (self.asset_category_filter or "").strip()
        if not raw:
            return []
        out: list[int] = []
        for p in raw.split(","):
            p = p.strip()
            if not p:
                continue
            try:
                out.append(int(p))
            except (TypeError, ValueError):
                continue
        return out

    def normalized_choices(self) -> list[dict[str, str]]:
        """Normalizza choices_json in lista di {value, label}."""
        out: list[dict[str, str]] = []
        for item in self.choices_json or []:
            if isinstance(item, dict):
                value = str(item.get("value", "")).strip()
                label = str(item.get("label", value)).strip() or value
                if value:
                    out.append({"value": value, "label": label})
            else:
                value = str(item or "").strip()
                if value:
                    out.append({"value": value, "label": value})
        return out


class TaskExtraRef(models.Model):
    """Indice normalizzato dei FK (utente/asset) presenti in Task.extra_data.

    Ogni riga = 1 valore FK compilato nei campi extra di una task. Viene
    rigenerato a ogni save dalla view del form. Consente query tipo
    'quali task fanno riferimento a questo asset?' senza scandire il JSON.
    """
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="extra_refs",
    )
    field_code = models.CharField(max_length=60, db_index=True)
    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="task_extra_refs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="task_extra_refs",
    )

    class Meta:
        indexes = [
            models.Index(fields=["asset", "field_code"]),
            models.Index(fields=["user", "field_code"]),
        ]

    def __str__(self) -> str:
        target = self.asset_id or self.user_id
        return f"TaskExtraRef<task={self.task_id} {self.field_code}={target}>"


class MeetingStatus(models.TextChoices):
    PIANIFICATO = "PIANIFICATO", "Pianificato"
    SVOLTO = "SVOLTO", "Svolto"
    ANNULLATO = "ANNULLATO", "Annullato"


class KickoffMeeting(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="meetings",
        verbose_name="Kickoff",
    )
    numero = models.PositiveIntegerField(verbose_name="Numero incontro")
    titolo = models.CharField(max_length=240, blank=True, default="", verbose_name="Titolo")
    stato = models.CharField(
        max_length=16,
        choices=MeetingStatus.choices,
        default=MeetingStatus.PIANIFICATO,
        db_index=True,
        verbose_name="Stato",
        help_text=(
            "Pianificato: convocazione inviata, incontro non ancora tenuto. "
            "Svolto: verbale registrato. Annullato: incontro non tenuto."
        ),
    )
    svolto_at = models.DateTimeField(null=True, blank=True, verbose_name="Esito registrato il")
    reminder_sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Promemoria pre-incontro inviato il",
        help_text="Marcato dal job periodico che avvisa i partecipanti il giorno prima; evita doppi invii.",
    )
    data = models.DateField(verbose_name="Data")
    ora = models.TimeField(null=True, blank=True, verbose_name="Ora")
    luogo = models.CharField(max_length=200, blank=True, default="", verbose_name="Luogo")

    # Partecipanti: utenti portale (M2M) + email esterne (testo libero)
    partecipanti_utenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="kickoff_meetings_as_partecipante",
        verbose_name="Partecipanti portale",
    )
    partecipanti_email_extra = models.TextField(
        blank=True,
        default="",
        verbose_name="Email aggiuntive",
        help_text="Un indirizzo email per riga (per partecipanti non presenti nel portale).",
    )
    # Campo legacy testo libero — mantenuto per retrocompat
    partecipanti_testo = models.TextField(blank=True, default="", verbose_name="Note partecipanti")

    # Presenze effettive: chi c'era davvero, registrato con l'esito. I convocati
    # (`partecipanti_utenti`) sono l'invito, non la presenza: senza questa
    # distinzione la minuta dichiarava presenti anche gli assenti.
    presenti_utenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="kickoff_meetings_as_presente",
        verbose_name="Presenti (portale)",
    )
    presenti_email_extra = models.TextField(
        blank=True,
        default="",
        verbose_name="Email presenti",
        help_text="Un indirizzo email per riga, fra quelli convocati.",
    )
    presenze_registrate_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Presenze registrate il",
        help_text="Distingue «nessun presente» da «presenze mai registrate» (incontri storici).",
    )

    ordine_del_giorno = models.TextField(blank=True, default="", verbose_name="Ordine del giorno")
    note = models.TextField(blank=True, default="", verbose_name="Note / Verbale")
    problemi_aperti = models.TextField(blank=True, default="", verbose_name="Problemi aperti")
    next_steps = models.TextField(blank=True, default="", verbose_name="Next steps")

    # Approvazione della minuta: dopo la chiusura l'esito non si modifica piu'
    # senza una riapertura esplicita e motivata (tracciata su AuditLog).
    minuta_chiusa_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Minuta approvata il"
    )
    minuta_chiusa_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kickoff_meetings_minuta_chiusa",
        verbose_name="Minuta approvata da",
    )
    minuta_riaperture = models.PositiveSmallIntegerField(
        default=0, verbose_name="Riaperture della minuta"
    )

    # Punti strutturati all'ordine del giorno
    agenda_items = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Punti all'ordine del giorno",
    )

    # Integrazione Outlook Calendar
    sync_outlook = models.BooleanField(
        default=False,
        verbose_name="Crea/aggiorna evento Outlook",
        help_text="Se attivo, invia/aggiorna un evento calendario a tutti i partecipanti con email.",
    )
    outlook_organizer_email = models.CharField(
        max_length=254,
        blank=True,
        default="",
        verbose_name="Email organizzatore (Outlook)",
        help_text="Lascia vuoto per usare l'email dell'utente che salva l'incontro.",
    )
    outlook_event_id = models.CharField(max_length=512, blank=True, default="")
    outlook_event_web_link = models.CharField(max_length=1024, blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kickoff_meetings_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["numero"]
        unique_together = [["project", "numero"]]
        verbose_name = "Incontro kickoff"
        verbose_name_plural = "Incontri kickoff"

    def save(self, *args, **kwargs):
        if not self.pk and not self.numero:
            last = KickoffMeeting.objects.filter(project=self.project).aggregate(m=Max("numero"))["m"]
            self.numero = (last or 0) + 1
        super().save(*args, **kwargs)

    def get_all_attendee_emails(self) -> list[str]:
        """Restituisce la lista deduplicata di email da inviare all'evento Outlook."""
        emails: list[str] = []
        for user in self.partecipanti_utenti.all():
            email = (getattr(user, "email", "") or "").strip()
            if email and email not in emails:
                emails.append(email)
        for line in (self.partecipanti_email_extra or "").splitlines():
            email = line.strip()
            if email and "@" in email and email not in emails:
                emails.append(email)
        return emails

    def get_partecipanti_email_list(self) -> list[str]:
        """Email esterne convocate (una per riga, deduplicate)."""
        emails: list[str] = []
        for line in (self.partecipanti_email_extra or "").splitlines():
            email = line.strip()
            if email and "@" in email and email not in emails:
                emails.append(email)
        return emails

    def get_presenti_email_list(self) -> list[str]:
        """Email esterne registrate come presenti (solo fra i convocati)."""
        convocati = self.get_partecipanti_email_list()
        emails: list[str] = []
        for line in (self.presenti_email_extra or "").splitlines():
            email = line.strip()
            if email and email in convocati and email not in emails:
                emails.append(email)
        return emails

    @property
    def minuta_chiusa(self) -> bool:
        return self.minuta_chiusa_at is not None

    @property
    def presenze_registrate(self) -> bool:
        return self.presenze_registrate_at is not None

    @property
    def assenti_utenti(self) -> list:
        """Convocati del portale che non risultano presenti.

        Vuoto finche' le presenze non sono state registrate: sugli incontri
        storici nessuno e' «assente», il dato semplicemente non esiste.
        """
        if not self.presenze_registrate:
            return []
        presenti_ids = {u.pk for u in self.presenti_utenti.all()}
        return [u for u in self.partecipanti_utenti.all() if u.pk not in presenti_ids]

    @property
    def assenti_email(self) -> list[str]:
        if not self.presenze_registrate:
            return []
        presenti = set(self.get_presenti_email_list())
        return [e for e in self.get_partecipanti_email_list() if e not in presenti]

    @property
    def presenti_count(self) -> int:
        if not self.presenze_registrate:
            return 0
        return self.presenti_utenti.count() + len(self.get_presenti_email_list())

    @property
    def convocati_count(self) -> int:
        return self.partecipanti_utenti.count() + len(self.get_partecipanti_email_list())

    @property
    def is_svolto(self) -> bool:
        return self.stato == MeetingStatus.SVOLTO

    @property
    def label(self) -> str:
        """Etichetta leggibile dell'incontro: il titolo se c'e', altrimenti «Incontro N»."""
        return (self.titolo or "").strip() or f"Incontro {self.numero}"

    def __str__(self) -> str:
        return f"Incontro {self.numero} — {self.project}"


class MeetingAgendaTemplate(models.Model):
    """Modello riutilizzabile di ordine del giorno.

    Ogni incontro ripartiva da zero: i punti ricorrenti (stato avanzamento,
    criticita', prossimi passi) si riscrivevano a mano ogni volta.
    """

    nome = models.CharField(max_length=120, unique=True, verbose_name="Nome modello")
    descrizione = models.CharField(max_length=255, blank=True, default="", verbose_name="Descrizione")
    # [{"titolo": str, "nota": str, "durata_minuti": int|None}]
    items = models.JSONField(default=list, blank=True, verbose_name="Punti")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Attivo")
    order_index = models.PositiveIntegerField(default=0, db_index=True, verbose_name="Ordine")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_agenda_templates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order_index", "nome"]
        verbose_name = "Modello ordine del giorno"
        verbose_name_plural = "Modelli ordine del giorno"

    @property
    def items_text(self) -> str:
        """Punti resi come testo editabile: «Titolo | durata» per riga."""
        lines = []
        for item in self.items or []:
            if not isinstance(item, dict):
                continue
            titolo = str(item.get("titolo", "")).strip()
            if not titolo:
                continue
            durata = item.get("durata_minuti")
            lines.append(f"{titolo} | {durata}" if durata else titolo)
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.nome


class MeetingIssueStatus(models.TextChoices):
    OPEN = "OPEN", "Aperto"
    RESOLVED = "RESOLVED", "Risolto"


class MeetingIssue(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="meeting_issues",
        verbose_name="Kickoff",
    )
    source_meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issues_created",
        verbose_name="Incontro di origine",
    )
    resolution_meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issues_resolved",
        verbose_name="Incontro di risoluzione",
    )
    title = models.CharField(max_length=220, verbose_name="Problema")
    description = models.TextField(blank=True, default="", verbose_name="Dettaglio")
    status = models.CharField(
        max_length=16,
        choices=MeetingIssueStatus.choices,
        default=MeetingIssueStatus.OPEN,
        verbose_name="Stato",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_issues_assigned",
        verbose_name="Responsabile",
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="Scadenza")
    linked_task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_issues",
        verbose_name="Attivita collegata",
    )
    resolution_note = models.TextField(blank=True, default="", verbose_name="Nota risoluzione")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_issues_resolved",
        verbose_name="Risolto da",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_issues_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "created_at", "id"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["source_meeting", "status"]),
            models.Index(fields=["resolution_meeting", "status"]),
        ]
        verbose_name = "Problema incontro"
        verbose_name_plural = "Problemi incontri"

    @property
    def is_resolved(self) -> bool:
        return self.status == MeetingIssueStatus.RESOLVED

    def mark_resolved(self, *, meeting: KickoffMeeting, user=None, note: str = "") -> None:
        self.status = MeetingIssueStatus.RESOLVED
        self.resolution_meeting = meeting
        self.resolved_by = user if getattr(user, "is_authenticated", False) else None
        self.resolved_at = timezone.now()
        if note is not None:
            self.resolution_note = note.strip()

    def reopen(self) -> None:
        self.status = MeetingIssueStatus.OPEN
        self.resolution_meeting = None
        self.resolved_by = None
        self.resolved_at = None
        self.resolution_note = ""

    def __str__(self) -> str:
        return self.title


class MeetingActionStatus(models.TextChoices):
    OPEN = "OPEN", "Da fare"
    DONE = "DONE", "Fatta"


class MeetingActionItem(models.Model):
    """Azione decisa in un incontro: chi fa cosa entro quando.

    Il campo storico `KickoffMeeting.next_steps` e' testo libero: nessun
    responsabile, nessuna scadenza, nessun riporto automatico. Questa entita' e'
    simmetrica a `MeetingIssue` e segue lo stesso ciclo di vita: finche' e'
    aperta rientra nell'agenda degli incontri successivi.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="meeting_actions",
        verbose_name="Kickoff",
    )
    source_meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actions_raised",
        verbose_name="Incontro di origine",
    )
    title = models.CharField(max_length=220, verbose_name="Azione")
    description = models.TextField(blank=True, default="", verbose_name="Dettaglio")
    status = models.CharField(
        max_length=12,
        choices=MeetingActionStatus.choices,
        default=MeetingActionStatus.OPEN,
        db_index=True,
        verbose_name="Stato",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_actions_assigned",
        verbose_name="Responsabile",
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="Scadenza")
    linked_task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_actions",
        verbose_name="Attività collegata",
    )
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_actions_done",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_actions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "due_date", "created_at", "id"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["source_meeting", "status"]),
        ]
        verbose_name = "Azione incontro"
        verbose_name_plural = "Azioni incontri"

    @property
    def is_done(self) -> bool:
        return self.status == MeetingActionStatus.DONE

    @property
    def is_overdue(self) -> bool:
        if self.is_done or not self.due_date:
            return False
        return self.due_date < timezone.localdate()

    def mark_done(self, *, user=None) -> None:
        self.status = MeetingActionStatus.DONE
        self.done_by = user if getattr(user, "is_authenticated", False) else None
        self.done_at = timezone.now()

    def reopen(self) -> None:
        self.status = MeetingActionStatus.OPEN
        self.done_by = None
        self.done_at = None

    def __str__(self) -> str:
        return self.title


class MeetingDecisionImpact(models.TextChoices):
    BASSO = "BASSO", "Basso"
    MEDIO = "MEDIO", "Medio"
    ALTO = "ALTO", "Alto"


class MeetingDecision(models.Model):
    """Decisione presa in un incontro, separata dal verbale libero.

    Nel campo `note` una decisione e' irrecuperabile a mesi di distanza: qui
    resta come record consultabile nel registro di commessa.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="meeting_decisions",
        verbose_name="Kickoff",
    )
    meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.CASCADE,
        related_name="decisions",
        verbose_name="Incontro",
    )
    testo = models.CharField(max_length=400, verbose_name="Decisione")
    dettaglio = models.TextField(blank=True, default="", verbose_name="Motivazione / contesto")
    decisa_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_decisions_taken",
        verbose_name="Decisa da",
    )
    impatto = models.CharField(
        max_length=8,
        choices=MeetingDecisionImpact.choices,
        default=MeetingDecisionImpact.MEDIO,
        db_index=True,
        verbose_name="Impatto",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_decisions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["project", "created_at"])]
        verbose_name = "Decisione incontro"
        verbose_name_plural = "Decisioni incontri"

    def __str__(self) -> str:
        return self.testo


class MeetingProposalStatus(models.TextChoices):
    PENDING = "PENDING", "In attesa"
    ACCEPTED = "ACCEPTED", "Accettata"
    REJECTED = "REJECTED", "Rifiutata"


class MeetingAgendaProposal(models.Model):
    """Punto proposto da un convocato, che il gestore accetta o rifiuta.

    L'ordine del giorno lo scriveva solo chi gestisce la commessa: chi era
    convocato non aveva modo di far mettere un punto all'ordine del giorno se
    non chiedendolo fuori dal portale.
    """

    meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.CASCADE,
        related_name="agenda_proposals",
        verbose_name="Incontro",
    )
    proposed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_agenda_proposals",
        verbose_name="Proposto da",
    )
    titolo = models.CharField(max_length=200, verbose_name="Punto proposto")
    nota = models.TextField(blank=True, default="", verbose_name="Nota")
    stato = models.CharField(
        max_length=10,
        choices=MeetingProposalStatus.choices,
        default=MeetingProposalStatus.PENDING,
        db_index=True,
        verbose_name="Stato",
    )
    nota_decisione = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Nota della decisione"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meeting_agenda_proposals_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["stato", "created_at", "id"]
        indexes = [models.Index(fields=["meeting", "stato"])]
        verbose_name = "Proposta ordine del giorno"
        verbose_name_plural = "Proposte ordine del giorno"

    @property
    def is_pending(self) -> bool:
        return self.stato == MeetingProposalStatus.PENDING

    def __str__(self) -> str:
        return self.titolo


class MeetingRoom(models.Model):
    nome = models.CharField(max_length=120, unique=True, verbose_name="Nome sala")
    note = models.TextField(blank=True, default="", verbose_name="Note")
    ordine = models.PositiveSmallIntegerField(default=0, verbose_name="Ordine")

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Sala riunioni"
        verbose_name_plural = "Sale riunioni"

    def __str__(self) -> str:
        return self.nome
