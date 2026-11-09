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


class TechRefKind(models.TextChoices):
    CAM = "CAM", "Programma CAM"
    CMM = "CMM", "Programma CMM"
    FAI = "FAI", "FAI"


class TappaKickoff(models.TextChoices):
    """Le attività base di ogni kickoff, nell'ordine in cui si preparano."""
    MATERIALI = "MATERIALI", "Arrivo materiali"
    CAM = "CAM", "Programma CAM"
    CMM = "CMM", "Programma CMM"
    MACCHINA = "MACCHINA", "Macchina"
    TERZISTA = "TERZISTA", "Terzista"
    PROCESSI = "PROCESSI", "Processi speciali"
    FAI = "FAI", "FAI"


class ProjectPhase(models.TextChoices):
    BOZZA = "BOZZA", "Bozza"
    VRF = "VRF", "VRF"
    EXEC = "EXEC", "In esecuzione"
    DONE = "DONE", "Completata"


class TaskStatus(models.TextChoices):
    TODO = "TODO", "Da fare"
    IN_PROGRESS = "IN_PROGRESS", "In corso"
    DONE = "DONE", "Completata"
    CANCELED = "CANCELED", "Annullata"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Bassa"
    MEDIUM = "MEDIUM", "Media"
    HIGH = "HIGH", "Alta"


class TaskEventType(models.TextChoices):
    DATE_REQUEST = "DATE_REQUEST", "Richiesta di spostamento"
    STATUS_CHANGE = "STATUS_CHANGE", "Status change"
    ASSIGNMENT_CHANGE = "ASSIGNMENT_CHANGE", "Assignment change"
    EDIT = "EDIT", "Edit"
    COMMENT_ADDED = "COMMENT_ADDED", "Comment added"
    SUBTASK_ADDED = "SUBTASK_ADDED", "Subtask added"
    SUBTASK_STATUS_CHANGE = "SUBTASK_STATUS_CHANGE", "Subtask status change"
    ATTACHMENT_ADDED = "ATTACHMENT_ADDED", "Attachment added"


def user_label(user) -> str:
    """Nome leggibile di un utente (fallback su username)."""
    if user is None:
        return ""
    return user.get_full_name() or user.username


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
    # Team di progetto: righe `ProjectMember` (utente + codice ruolo), lette e
    # scritte con `team_members()` / `set_team()` / `add_team_member()`. Ogni
    # ruolo ammette piu' persone: una commessa puo' avere due capicommessa.
    control_method = models.CharField(max_length=180, blank=True, default="")
    part_number = models.CharField(max_length=120, blank=True, default="")
    revisione = models.CharField(max_length=60, blank=True, default="")
    versione = models.CharField(max_length=60, blank=True, default="")
    vrf_status = models.CharField(
        max_length=20, choices=VRFDocStatus.choices, default=VRFDocStatus.PENDING,
        verbose_name="Stato documento VRF",
    )
    # Valorizzata quando chi gestisce il kickoff decide che il FAI qui non serve.
    # Tappe del percorso che per questo kickoff non servono (es. niente terzista).
    tappe_escluse = models.JSONField(default=list, blank=True, verbose_name="Tappe che non servono")
    fai_non_richiesto_il = models.DateTimeField(null=True, blank=True)
    fai_non_richiesto_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
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

    # Ruoli del team di progetto: (chiave, etichetta, codice ruolo). La chiave e'
    # il vecchio nome del campo M2M, ancora usato da form, template e chiamanti;
    # il dato e' `ProjectMember.role_code`. I codici sono letterali per non
    # anticipare TaskRoleType, definito piu' sotto.
    TEAM_ROLES = (
        ("project_managers", "Project manager", "PM"),
        ("capi_commessa", "Capocommessa", "CC"),
        ("programmers", "Programmatore", "PRG"),
        ("caporeparti", "Caporeparto", "CR"),
    )
    TEAM_ROLE_FIELDS = tuple(field for field, _label, _code in TEAM_ROLES)
    TEAM_CODE_BY_FIELD = {field: code for field, _label, code in TEAM_ROLES}

    @classmethod
    def team_code(cls, role) -> str:
        """Codice ruolo da chiave (``"capi_commessa"``) o da codice (``"CC"``)."""
        return cls.TEAM_CODE_BY_FIELD.get(role, role)

    @classmethod
    def team_prefetch(cls, prefix: str = ""):
        """Prefetch del team (con gli utenti) per elenchi senza N+1."""
        from django.db.models import Prefetch

        return Prefetch(
            f"{prefix}members",
            queryset=ProjectMember.objects.select_related("user").order_by("id"),
        )

    @classmethod
    def team_q(cls, user, roles=None, prefix: str = "") -> models.Q:
        """Filtro «l'utente e' nel team», su tutti i ruoli o solo su ``roles``."""
        lookup = {f"{prefix}members__user": user}
        if roles is not None:
            lookup[f"{prefix}members__role_code__in"] = [cls.team_code(role) for role in roles]
        return models.Q(**lookup)

    def _team_rows(self) -> list:
        prefetched = getattr(self, "_prefetched_objects_cache", {}).get("members")
        if prefetched is not None:
            return list(prefetched)
        rows = self.__dict__.get("_team_rows_cache")
        if rows is None:
            rows = list(self.members.select_related("user").order_by("id")) if self.pk else []
            self.__dict__["_team_rows_cache"] = rows
        return rows

    def _forget_team(self) -> None:
        self.__dict__.pop("_team_rows_cache", None)
        prefetched = getattr(self, "_prefetched_objects_cache", None)
        if prefetched:
            prefetched.pop("members", None)

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        self._forget_team()

    def team_members(self, role):
        """Persone assegnate a un ruolo del team (lista, sfrutta il prefetch)."""
        code = self.team_code(role)
        return [row.user for row in self._team_rows() if row.role_code == code]

    def set_team(self, role, users) -> None:
        """Sostituisce le persone di un ruolo (chi resta non viene riscritto)."""
        code = self.team_code(role)
        wanted = {user.pk: user for user in (users or [])}
        current = set(self.members.filter(role_code=code).values_list("user_id", flat=True))
        self.members.filter(role_code=code).exclude(user_id__in=list(wanted)).delete()
        for pk, user in wanted.items():
            if pk not in current:
                ProjectMember.objects.create(project=self, user=user, role_code=code)
        self._forget_team()

    def add_team_member(self, role, user) -> bool:
        """Aggiunge una persona a un ruolo; False se c'era gia'."""
        _member, created = ProjectMember.objects.get_or_create(
            project=self, user=user, role_code=self.team_code(role)
        )
        if created:
            self._forget_team()
        return created

    def team_display(self, role) -> str:
        return ", ".join(user_label(u) for u in self.team_members(role))

    @property
    def team_blocks(self):
        """Team pronto per i template: un blocco per ruolo, anche se vuoto."""
        return [
            {
                "field": field,
                "label": label,
                "role_type": code,
                "members": self.team_members(field),
                "display": self.team_display(field),
            }
            for field, label, code in self.TEAM_ROLES
        ]

    @property
    def team_display_pm(self) -> str:
        return self.team_display("project_managers")

    @property
    def team_users(self):
        """Tutti i membri del team, senza duplicati, nell'ordine dei ruoli."""
        seen: set[int] = set()
        people = []
        for field in self.TEAM_ROLE_FIELDS:
            for user in self.team_members(field):
                if user.pk not in seen:
                    seen.add(user.pk)
                    people.append(user)
        return people

    @property
    def team_user_ids(self):
        return [user.pk for user in self.team_users]

    def role_types_for_user(self, user_id) -> list[str]:
        """Codici ruolo ricoperti dall'utente in questo kickoff."""
        codes = {row.role_code for row in self._team_rows() if row.user_id == user_id}
        return [code for _field, _label, code in self.TEAM_ROLES if code in codes]

    def default_name(self, kickoff_number=None) -> str:
        """Nome proposto: «Cliente · P/N · KICK-OFF n».

        «KICK-OFF 12» da solo non dice a chi appartiene la commessa: negli
        elenchi e nelle email si riconosceva solo aprendola. Cliente e P/N
        mancanti si saltano, cosi' il nome resta leggibile anche a scheda
        incompleta.
        """
        numero = kickoff_number or self.kickoff_number
        parti = [
            (self.client_name or "").strip(),
            (self.part_number or "").strip(),
        ]
        parti = [parte for parte in parti if parte]
        parti.append(f"KICK-OFF {numero}" if numero else "KICK-OFF")
        return " · ".join(parti)[:180]

    def save(self, *args, **kwargs):
        self.part_number = normalize_part_number(self.part_number)
        self.client_name = normalize_client_name(self.client_name)

        if not self._state.adding:
            if self.kickoff_number and not self.name:
                self.name = f"KICK-OFF {self.kickoff_number}"
            return super().save(*args, **kwargs)

        if self.kickoff_number:
            if not self.name:
                self.name = self.default_name()
            return super().save(*args, **kwargs)

        # Un nome scritto a mano nel form vince sempre sulla proposta; qui si
        # decide una volta sola, perche' a ogni tentativo il numero cambia e la
        # proposta va ricomposta con quello nuovo.
        nome_automatico = not (self.name or "").strip()
        max_attempts = 5
        for attempt in range(max_attempts):
            self.kickoff_number = _next_kickoff_number()
            if nome_automatico:
                self.name = self.default_name()
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                self.kickoff_number = None
                if not self._state.adding or attempt == max_attempts - 1:
                    raise

    def __str__(self) -> str:
        return self.name


class ProjectMember(models.Model):
    """Persona del team di un kickoff in un ruolo (PM, CC, PRG, CR).

    Sostituisce i quattro elenchi M2M di `Project` (uno per ruolo): un solo
    posto dove il team vive, filtri di visibilita' su una sola relazione, e un
    ruolo in piu' non richiede un campo nuovo.
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="members", verbose_name="Kickoff"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="kickoff_memberships",
        verbose_name="Persona",
    )
    role_code = models.CharField(max_length=32, db_index=True, verbose_name="Ruolo")

    class Meta:
        ordering = ["project", "role_code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["project", "user", "role_code"], name="tasks_projectmember_uniq"),
        ]
        verbose_name = "Membro del team kickoff"
        verbose_name_plural = "Team kickoff"

    def __str__(self) -> str:
        return f"{self.project_id}:{self.role_code}:{self.user_id}"


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
    gantt_order = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Posizione della riga nel Gantt del kickoff (0 = in fondo, in ordine di creazione).",
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

    def save(self, *args, **kwargs):
        # Una nuova attività del kickoff va in fondo al piano.
        if self._state.adding and self.project_id and not self.gantt_order:
            from .services.gantt_piano import prossimo_ordine

            self.gantt_order = prossimo_ordine(self.project_id)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        # Inizio e fine nello stesso giorno sono ammessi: un'attivita' di una
        # giornata e' un caso normale, non un errore di compilazione.
        if self.next_step_due and self.due_date and self.due_date < self.next_step_due:
            raise ValidationError(
                {"due_date": "La data fine non può precedere la data inizio."}
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

    cc_predefiniti_utenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="kickoff_cc_predefinito",
        verbose_name="CC predefiniti (portale)",
        help_text="Ricevono in copia convocazioni e minute quando l'incontro non indica dei CC propri.",
    )
    cc_predefinite_email = models.TextField(
        blank=True,
        default="",
        verbose_name="CC predefiniti (email)",
        help_text="Un indirizzo per riga, per chi non e' un utente del portale.",
    )
    # Poteri pieni sulla commessa: ruoli di team (codici separati da virgola) + persone scelte.
    poteri_ruoli = models.CharField(
        max_length=60, blank=True, default="CC,PM", verbose_name="Ruoli con pieni poteri",
        help_text="Ruoli del team che modificano tutto sulla commessa, date comprese, senza approvazione.",
    )
    poteri_utenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="Persone con pieni poteri",
    )
    spostamenti_con_approvazione = models.BooleanField(
        default=True, verbose_name="Spostamenti di date con approvazione",
        help_text="Chi non ha pieni poteri chiede lo spostamento: decide il capocommessa.",
    )
    # Chi riceve l'avviso quando cambia un incarico: INCARICATO, CC, PM, CREATORE.
    avvisi_destinatari = models.CharField(
        max_length=60, blank=True, default="INCARICATO,CC", verbose_name="Chi riceve gli avvisi sui cambiamenti",
    )

    fai_mesi_verifica = models.PositiveSmallIntegerField(
        default=18,
        verbose_name="Mesi dall'ultima spedizione per segnalare il FAI",
    )
    fai_mesi_ripetizione = models.PositiveSmallIntegerField(
        default=24,
        verbose_name="Mesi dall'ultima produzione per ripetere il FAI",
    )

    def get_cc_predefiniti(self) -> list[str]:
        """Indirizzi in copia di default (utenti portale + email libere)."""
        emails: list[str] = []
        for user in self.cc_predefiniti_utenti.all():
            email = (getattr(user, "email", "") or "").strip()
            if email and email not in emails:
                emails.append(email)
        for line in (self.cc_predefinite_email or "").splitlines():
            email = line.strip()
            if email and "@" in email and email not in emails:
                emails.append(email)
        return emails

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
    """Scheda MOD.073 VRF compilata online (valutazione rischi e fornitura).

    1:1 col Project. Il payload 'data' segue la shape di vrf_catalog.default_scores()
    (schema 2: P per rischio, azioni correttive, firme). Totale Rischio, fascia e
    coinvolgimento CEO sono cache denormalizzata ricalcolata dal catalogo.
    """

    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="vrf_assessment",
    )
    data = models.JSONField(default=dict, blank=True)
    total_tr = models.FloatField(default=0.0)
    livello = models.CharField(max_length=10, blank=True, default="")
    ceo_required = models.BooleanField(default=False)
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
        self.total_tr = float(result["tr"])
        self.livello = result["level"]["key"]
        self.ceo_required = bool(result["ceo_required"])


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
    configurato (righe `ProjectMember` con quel codice ruolo).
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
    richiede = models.CharField(
        max_length=3,
        choices=TechRefKind.choices,
        blank=True,
        default="",
        verbose_name="Richiede",
        help_text="Cosa deve produrre un'attività di questo tipo.",
    )
    tappa = models.CharField(
        max_length=10,
        choices=TappaKickoff.choices,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Tappa del kickoff",
        help_text="Attività base del percorso del kickoff che questo tipo rappresenta.",
    )
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
    # Convocazione: quando e' partita e con quali dati. La firma confrontata con
    # quella corrente dice se data, luogo, convocati o ordine del giorno sono
    # cambiati dopo l'invio (e la convocazione va reinviata).
    convocazione_inviata_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Convocazione inviata il"
    )
    convocazione_firma = models.CharField(max_length=64, blank=True, default="")
    # Copia leggibile degli stessi dati al momento dell'invio: serve a dire
    # *cosa* e' cambiato, non solo che qualcosa e' cambiato.
    convocazione_dati = models.TextField(blank=True, default="")
    # Ultimo invio della minuta e impronta del contenuto inviato (per «da reinviare»).
    minuta_inviata_at = models.DateTimeField(null=True, blank=True, verbose_name="Minuta inviata il")
    minuta_firma = models.CharField(max_length=64, blank=True, default="")
    annullato_at = models.DateTimeField(null=True, blank=True, verbose_name="Annullato il")
    annullato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="kickoff_meetings_annullati",
        verbose_name="Annullato da",
    )
    annullato_motivo = models.TextField(blank=True, default="", verbose_name="Motivo dell'annullamento")
    data = models.DateField(verbose_name="Data")
    ora = models.TimeField(null=True, blank=True, verbose_name="Ora")
    # Quanto tenere la sala e l'evento Outlook. Vuoto: somma dei punti all'ordine del giorno.
    durata_minuti = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Durata")
    luogo = models.CharField(max_length=200, blank=True, default="", verbose_name="Luogo")
    sala = models.ForeignKey(
        "MeetingRoom", on_delete=models.SET_NULL, null=True, blank=True, related_name="incontri", verbose_name="Sala",
    )
    # Risposta della sala all'invito Outlook: accepted, tentativelyAccepted, declined, none.
    sala_risposta = models.CharField(max_length=24, blank=True, default="", verbose_name="Risposta della sala")
    sala_risposta_at = models.DateTimeField(null=True, blank=True)

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
    # Destinatari in copia conoscenza delle mail dell'incontro (convocazione e
    # minuta): utenti portale (M2M) + email esterne (testo libero). Se restano
    # vuoti vale il CC automatico a PM e capo commessa.
    cc_utenti = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="kickoff_meetings_as_cc",
        verbose_name="In copia (portale)",
    )
    cc_email_extra = models.TextField(
        blank=True,
        default="",
        verbose_name="Email in copia",
        help_text="Un indirizzo email per riga (per destinatari in copia non presenti nel portale).",
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

    # I punti strutturati all'ordine del giorno sono righe `MeetingAgendaItem`
    # (related_name `agenda_rows`), esposte come lista di dict da `agenda_items`.

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

    # --- Ordine del giorno -------------------------------------------------
    # `agenda_items` si comporta come il vecchio campo JSON: si legge, si
    # modifica (anche sul posto) e si salva con `save()`, anche con
    # `update_fields=["agenda_items", ...]`. I dati stanno in `MeetingAgendaItem`.

    @property
    def agenda_items(self) -> list[dict]:
        pending = self.__dict__.get("_agenda_pending")
        if pending is not None:
            return pending
        cache = self.__dict__.get("_agenda_cache")
        if cache is None:
            cache = [row.as_agenda_dict() for row in self.agenda_rows.all()] if self.pk else []
            self._remember_agenda(cache)
        return cache

    @agenda_items.setter
    def agenda_items(self, value) -> None:
        self.__dict__["_agenda_pending"] = value if isinstance(value, list) else []

    def _remember_agenda(self, items: list[dict]) -> None:
        import copy

        self.__dict__["_agenda_cache"] = items
        self.__dict__["_agenda_snapshot"] = copy.deepcopy(items)

    def _sync_agenda_rows(self) -> None:
        pending = self.__dict__.pop("_agenda_pending", None)
        if pending is None:
            cache = self.__dict__.get("_agenda_cache")
            if cache is None or cache == self.__dict__.get("_agenda_snapshot"):
                return
            pending = cache
        rows = MeetingAgendaItem.rows_from_dicts(self, pending)
        with transaction.atomic():
            prima = set(MeetingAgendaItem.objects.filter(meeting=self).values_list("titolo", flat=True))
            MeetingAgendaItem.objects.filter(meeting=self).delete()
            MeetingAgendaItem.objects.bulk_create(rows)
        self._catalogo_odg(rows, prima)
        # La lista del chiamante resta quella viva (come col campo JSON), ma con
        # i valori normalizzati: id univoci, collegamenti validi.
        pending[:] = [row.as_agenda_dict() for row in rows]
        self._remember_agenda(pending)
        prefetched = getattr(self, "_prefetched_objects_cache", None)
        if prefetched:
            prefetched.pop("agenda_rows", None)

    @staticmethod
    def _catalogo_odg(rows, prima) -> None:
        """I punti nuovi scritti a mano entrano nel catalogo (le righe si ricreano a ogni salvataggio)."""
        try:
            from .services.catalogo import chiave, registra_uso

            gia = {chiave(t) for t in prima}
            for row in rows:
                if row.issue_id or row.action_id or str(row.source or "").startswith(("tappa:", "meeting_issue", "meeting_action")):
                    continue
                if chiave(row.titolo) not in gia:
                    registra_uso("ODG", row.titolo, nota=row.nota, durata=row.durata_minuti)
        except Exception:
            pass

    def refresh_from_db(self, *args, **kwargs):
        super().refresh_from_db(*args, **kwargs)
        for key in ("_agenda_pending", "_agenda_cache", "_agenda_snapshot"):
            self.__dict__.pop(key, None)

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = [name for name in update_fields if name != "agenda_items"]
        if not self.pk and not self.numero:
            # Audit S8: due incontri creati insieme non vanno in 500 sul vincolo
            # (project, numero): si ricalcola il numero e si riprova.
            from core.numbering_retry import save_with_next_number

            def assign():
                last = KickoffMeeting.objects.filter(project=self.project).aggregate(m=Max("numero"))["m"]
                self.numero = (last or 0) + 1

            def reset():
                self.numero = None

            result = save_with_next_number(assign, lambda: super(KickoffMeeting, self).save(*args, **kwargs), on_conflict=reset)
        else:
            result = super().save(*args, **kwargs)
        self._sync_agenda_rows()
        return result

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

    def get_all_cc_emails(self) -> list[str]:
        """Email scelte a mano per la copia conoscenza (utenti portale + esterne)."""
        emails: list[str] = []
        for user in self.cc_utenti.all():
            email = (getattr(user, "email", "") or "").strip()
            if email and email not in emails:
                emails.append(email)
        for line in (self.cc_email_extra or "").splitlines():
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

    def dati_convocazione(self) -> dict:
        """Dati che finiscono nella convocazione (base di firma e confronto)."""
        dati = {
            # str(): data e ora possono essere ancora stringhe su un'istanza appena creata.
            "data": str(self.data or ""),
            "ora": str(self.ora or "")[:5],
            "luogo": (self.luogo or "").strip(),
            "convocati": sorted(self.partecipanti_utenti.values_list("pk", flat=True)) if self.pk else [],
            "esterni": sorted(self.get_partecipanti_email_list()),
            "odg": [
                (str(item.get("titolo") or ""), item.get("durata_minuti"))
                for item in (self.agenda_items or [])
                if isinstance(item, dict)
            ],
        }
        # Solo se valorizzate: le convocazioni già inviate prima di sala e durata non risultano cambiate.
        if self.sala_id:
            dati["sala"] = self.sala_id
        if self.durata_minuti:
            dati["durata"] = self.durata_minuti
        return dati

    def firma_convocazione(self) -> str:
        """Impronta dei dati che finiscono nella convocazione."""
        import hashlib
        import json

        raw = json.dumps(self.dati_convocazione(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def firma_minuta(self) -> str:
        """Impronta di quello che finisce nella minuta: se cambia dopo l'invio, va reinviata."""
        import hashlib
        import json

        dati = {
            "note": self.note, "problemi": self.problemi_aperti, "next": self.next_steps,
            "presenti": sorted(self.presenti_utenti.values_list("pk", flat=True)) if self.pk else [],
            "presenti_extra": self.presenti_email_extra,
            "odg": [(i.get("titolo"), i.get("done"), i.get("nota"), i.get("esito")) for i in (self.agenda_items or []) if isinstance(i, dict)],
            "decisioni": list(self.decisions.order_by("pk").values_list("pk", "testo")) if self.pk else [],
            "azioni": [
                (a.pk, a.title, a.status, a.assigned_to_id, str(a.due_date or ""))
                for a in MeetingActionItem.objects.filter(source_meeting=self).order_by("pk")
            ] if self.pk else [],
        }
        raw = json.dumps(dati, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @property
    def minuta_inviata(self) -> bool:
        return self.minuta_inviata_at is not None

    @property
    def minuta_da_reinviare(self) -> bool:
        """Minuta partita, ma verbale, ordine del giorno, decisioni o azioni sono cambiati dopo."""
        return bool(self.minuta_inviata_at and self.minuta_firma and self.minuta_firma != self.firma_minuta())

    def registra_convocazione_inviata(self) -> list[str]:
        """Valorizza firma e copia dei dati inviati; ritorna i campi da salvare."""
        import json

        self.convocazione_firma = self.firma_convocazione()
        self.convocazione_dati = json.dumps(self.dati_convocazione(), ensure_ascii=False)
        return ["convocazione_firma", "convocazione_dati"]

    def modifiche_convocazione(self) -> list[str]:
        """Cosa e' cambiato dall'ultimo invio, una riga leggibile per voce.

        Vuoto se la convocazione non va reinviata o se l'invio e' precedente
        alla copia dei dati (il dettaglio allora resta generico).
        """
        import json

        if not self.convocazione_da_reinviare or not self.convocazione_dati:
            return []
        try:
            prima = json.loads(self.convocazione_dati)
        except (TypeError, ValueError):
            return []
        if not isinstance(prima, dict):
            return []
        ora = self.dati_convocazione()
        righe: list[str] = []

        def _data(valore: str) -> str:
            parti = str(valore or "").split("-")
            return "-".join(reversed(parti)) if len(parti) == 3 else (valore or "—")

        if prima.get("data") != ora["data"]:
            righe.append(f"Data: {_data(prima.get('data'))} → {_data(ora['data'])}")
        if (prima.get("ora") or "") != ora["ora"]:
            righe.append(f"Ora: {prima.get('ora') or '—'} → {ora['ora'] or '—'}")
        if (prima.get("luogo") or "") != ora["luogo"]:
            righe.append(f"Luogo: {prima.get('luogo') or '—'} → {ora['luogo'] or '—'}")

        prima_conv = set(prima.get("convocati") or [])
        ora_conv = set(ora["convocati"])
        if prima_conv != ora_conv:
            from django.contrib.auth import get_user_model

            from tasks.forms import etichetta_utente

            User = get_user_model()
            utenti = {u.pk: u for u in User.objects.filter(pk__in=prima_conv | ora_conv)}

            def _nomi(pks) -> str:
                nomi = [etichetta_utente(utenti[pk]) if pk in utenti else f"utente {pk}" for pk in pks]
                return ", ".join(sorted(nomi))

            if ora_conv - prima_conv:
                righe.append(f"Convocati aggiunti: {_nomi(ora_conv - prima_conv)}")
            if prima_conv - ora_conv:
                righe.append(f"Convocati tolti: {_nomi(prima_conv - ora_conv)}")

        prima_est = set(prima.get("esterni") or [])
        ora_est = set(ora["esterni"])
        if ora_est - prima_est:
            righe.append(f"Esterni aggiunti: {', '.join(sorted(ora_est - prima_est))}")
        if prima_est - ora_est:
            righe.append(f"Esterni tolti: {', '.join(sorted(prima_est - ora_est))}")

        prima_odg = [tuple(item) for item in (prima.get("odg") or []) if isinstance(item, (list, tuple))]
        if prima_odg != ora["odg"]:
            prima_titoli = [t for t, _ in prima_odg]
            ora_titoli = [t for t, _ in ora["odg"]]
            aggiunti = [t for t in ora_titoli if t not in prima_titoli]
            tolti = [t for t in prima_titoli if t not in ora_titoli]
            if aggiunti:
                righe.append(f"Punti dell'ordine del giorno aggiunti: {', '.join(aggiunti)}")
            if tolti:
                righe.append(f"Punti dell'ordine del giorno tolti: {', '.join(tolti)}")
            if not aggiunti and not tolti:
                righe.append("Ordine del giorno: cambiati l'ordine dei punti o le durate")
        return righe

    def durata_prevista_minuti(self) -> int | None:
        """Somma delle durate dei punti all'ordine del giorno, se ce ne sono."""
        totale = 0
        for item in self.agenda_items or []:
            if not isinstance(item, dict):
                continue
            try:
                totale += int(item.get("durata_minuti") or 0)
            except (TypeError, ValueError):
                continue
        return totale or None

    @property
    def convocazione_inviata(self) -> bool:
        return self.convocazione_inviata_at is not None

    @property
    def convocazione_da_reinviare(self) -> bool:
        """Convocazione partita, ma i dati sono cambiati dopo l'invio."""
        if not self.convocazione_inviata or self.stato != MeetingStatus.PIANIFICATO:
            return False
        return bool(self.convocazione_firma) and self.convocazione_firma != self.firma_convocazione()

    @property
    def is_annullato(self) -> bool:
        return self.stato == MeetingStatus.ANNULLATO

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


AGENDA_ITEM_ID_MAX = 255


def _agenda_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _agenda_source(item: dict) -> str:
    """Origine del punto; se manca la si deduce dal collegamento.

    Serve quando il problema o l'azione collegati non esistono piu' e il
    collegamento si azzera: il punto resta riconoscibile come generato.
    """
    source = str(item.get("source") or "").strip()[:40]
    if not source and _agenda_int(item.get("issue_id")):
        return "meeting_issue"
    if not source and _agenda_int(item.get("action_id")):
        return "meeting_action"
    return source


class MeetingAgendaItem(models.Model):
    """Punto all'ordine del giorno di un incontro.

    Prima i punti vivevano in un campo JSON di ``KickoffMeeting``: i
    collegamenti ad attivita', problemi, azioni e responsabile erano interi
    senza vincolo (restavano puntati a record cancellati) e ogni lettura
    trasversale, come i suggerimenti ODG, scandiva il JSON in Python.

    ``KickoffMeeting.agenda_items`` resta l'interfaccia: una lista di dict con
    le stesse chiavi di prima, letta da queste righe e riscritta qui al
    ``save()`` dell'incontro (vedi ``KickoffMeeting._sync_agenda_rows``).
    """

    meeting = models.ForeignKey(
        KickoffMeeting, on_delete=models.CASCADE, related_name="agenda_rows", verbose_name="Incontro"
    )
    ordine = models.PositiveIntegerField(default=0, verbose_name="Ordine")
    item_id = models.CharField(max_length=AGENDA_ITEM_ID_MAX, verbose_name="Id punto")
    titolo = models.CharField(max_length=240, verbose_name="Titolo")
    nota = models.TextField(blank=True, default="", verbose_name="Nota")
    source = models.CharField(max_length=40, blank=True, default="", verbose_name="Origine")
    locked = models.BooleanField(default=False, verbose_name="Bloccato")
    done = models.BooleanField(default=False, verbose_name="Trattato")
    task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Attivita'"
    )
    task_label = models.CharField(max_length=200, blank=True, default="")
    issue = models.ForeignKey(
        MeetingIssue, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Problema"
    )
    action = models.ForeignKey(
        MeetingActionItem, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Azione"
    )
    responsabile = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Responsabile",
    )
    responsabile_label = models.CharField(max_length=150, blank=True, default="")
    durata_minuti = models.PositiveIntegerField(null=True, blank=True, verbose_name="Durata prevista (min)")
    tempo_effettivo_minuti = models.PositiveIntegerField(null=True, blank=True, verbose_name="Tempo effettivo (min)")
    custom_fields = models.JSONField(default=list, blank=True, verbose_name="Campi aggiuntivi")

    class Meta:
        ordering = ["meeting", "ordine", "id"]
        constraints = [
            models.UniqueConstraint(fields=["meeting", "item_id"], name="tasks_agendaitem_meeting_item_uniq"),
        ]
        verbose_name = "Punto ordine del giorno"
        verbose_name_plural = "Punti ordine del giorno"

    def __str__(self) -> str:
        return self.titolo

    def as_agenda_dict(self) -> dict:
        return {
            "id": self.item_id,
            "titolo": self.titolo,
            "nota": self.nota,
            "task_id": self.task_id,
            "task_label": self.task_label,
            "issue_id": self.issue_id,
            "action_id": self.action_id,
            "source": self.source,
            "locked": self.locked,
            "responsabile_id": self.responsabile_id,
            "responsabile_label": self.responsabile_label,
            "durata_minuti": self.durata_minuti,
            "tempo_effettivo_minuti": self.tempo_effettivo_minuti,
            "custom_fields": list(self.custom_fields or []),
            "done": self.done,
        }

    @classmethod
    def rows_from_dicts(cls, meeting, items) -> list["MeetingAgendaItem"]:
        """Righe pronte da salvare a partire dalla lista di dict dell'incontro.

        Id vuoti o ripetuti ricevono un id nuovo (prima due punti con lo stesso
        id ricevevano nota e spunta l'uno dell'altro); i collegamenti a record
        che non esistono piu' si azzerano invece di far fallire il salvataggio.
        """
        from uuid import uuid4

        from django.contrib.auth import get_user_model

        items = [item for item in (items or []) if isinstance(item, dict)]
        wanted = {"task": set(), "issue": set(), "action": set(), "user": set()}
        for item in items:
            for key, bucket in (("task_id", "task"), ("issue_id", "issue"), ("action_id", "action"), ("responsabile_id", "user")):
                value = _agenda_int(item.get(key))
                if value:
                    wanted[bucket].add(value)
        existing = {
            "task": set(Task.objects.filter(pk__in=wanted["task"]).values_list("pk", flat=True)) if wanted["task"] else set(),
            "issue": set(MeetingIssue.objects.filter(pk__in=wanted["issue"]).values_list("pk", flat=True)) if wanted["issue"] else set(),
            "action": set(MeetingActionItem.objects.filter(pk__in=wanted["action"]).values_list("pk", flat=True)) if wanted["action"] else set(),
            "user": set(get_user_model().objects.filter(pk__in=wanted["user"]).values_list("pk", flat=True)) if wanted["user"] else set(),
        }

        def ref(item, key, bucket):
            value = _agenda_int(item.get(key))
            return value if value in existing[bucket] else None

        rows: list[MeetingAgendaItem] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            item_id = str(item.get("id") or "").strip()[:AGENDA_ITEM_ID_MAX]
            if not item_id or item_id in seen:
                item_id = f"item-{index}-{uuid4().hex[:8]}"
            seen.add(item_id)
            custom_fields = item.get("custom_fields")
            rows.append(cls(
                meeting=meeting,
                ordine=index,
                item_id=item_id,
                titolo=str(item.get("titolo") or "").strip()[:240],
                nota=str(item.get("nota") or ""),
                source=_agenda_source(item),
                locked=bool(item.get("locked", False)),
                done=bool(item.get("done", False)),
                task_id=ref(item, "task_id", "task"),
                task_label=str(item.get("task_label") or "").strip()[:200],
                issue_id=ref(item, "issue_id", "issue"),
                action_id=ref(item, "action_id", "action"),
                responsabile_id=ref(item, "responsabile_id", "user"),
                responsabile_label=str(item.get("responsabile_label") or "").strip()[:150],
                durata_minuti=_agenda_int(item.get("durata_minuti")),
                tempo_effettivo_minuti=_agenda_int(item.get("tempo_effettivo_minuti")),
                custom_fields=custom_fields if isinstance(custom_fields, list) else [],
            ))
        return rows


class MeetingRoom(models.Model):
    nome = models.CharField(max_length=120, unique=True, verbose_name="Nome sala")
    note = models.TextField(blank=True, default="", verbose_name="Note")
    ordine = models.PositiveSmallIntegerField(default=0, verbose_name="Ordine")
    # Casella «sala» di Microsoft 365: con questa l'invito Outlook prenota la sala.
    email = models.EmailField(blank=True, default="", verbose_name="Casella della sala (Microsoft 365)")
    capienza = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Posti")
    attiva = models.BooleanField(default=True, verbose_name="Attiva")

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Sala riunioni"
        verbose_name_plural = "Sale riunioni"

    def __str__(self) -> str:
        return self.nome

class ProgrammaFase(models.TextChoices):
    """Il lavoro vero di un programma CAM/CMM: si scrive, si prova in macchina, si valida."""
    DA_SCRIVERE = "DA_SCRIVERE", "Da scrivere"
    IN_SCRITTURA = "IN_SCRITTURA", "In scrittura"
    DA_PROVARE = "DA_PROVARE", "Da provare in macchina"
    VALIDATO = "VALIDATO", "Validato"


class TechRefStatus(models.TextChoices):
    OPEN = "OPEN", "Da fare"
    DONE = "DONE", "Fatto"


class ProjectTechRef(models.Model):
    """Programma CAM, programma CMM o FAI di una commessa: codice, percorso, responsabile.

    Tutto facoltativo tranne che la riga dica qualcosa: in riunione basta assegnare
    «Programma CAM» a qualcuno, codice e percorso li scrive poi lui. La stessa riga si
    vede in commessa e negli incontri, quindi non va mai inserita due volte.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tech_refs", verbose_name="Kickoff")
    kind = models.CharField(max_length=3, choices=TechRefKind.choices, db_index=True, verbose_name="Tipo")
    code = models.CharField(max_length=120, blank=True, default="", verbose_name="Codice")
    path = models.CharField(max_length=500, blank=True, default="", verbose_name="Cartella o file")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks_tech_refs",
        verbose_name="Responsabile",
    )
    due_date = models.DateField(null=True, blank=True, verbose_name="Entro il")
    # L'attività che deve produrre questo programma: responsabile, data e stato arrivano da lei.
    task = models.OneToOneField(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name="tech_ref", verbose_name="Attività"
    )
    status = models.CharField(
        max_length=4, choices=TechRefStatus.choices, default=TechRefStatus.OPEN, db_index=True, verbose_name="Stato"
    )
    # Solo programmi CAM/CMM: fase del lavoro, revisione, macchina su cui gira, note.
    fase = models.CharField(
        max_length=14, choices=ProgrammaFase.choices, default=ProgrammaFase.DA_SCRIVERE, db_index=True, verbose_name="Fase",
    )
    revisione = models.CharField(max_length=10, blank=True, default="", verbose_name="Revisione")
    macchina = models.ForeignKey(
        "assets.Asset", on_delete=models.SET_NULL, null=True, blank=True, related_name="programmi_kickoff", verbose_name="Macchina",
    )
    note = models.TextField(blank=True, default="", verbose_name="Note")
    source_meeting = models.ForeignKey(
        KickoffMeeting,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tech_refs",
        verbose_name="Incontro di origine",
    )
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "id"]
        verbose_name = "Programma o FAI"
        verbose_name_plural = "Programmi e FAI"

    def __str__(self) -> str:
        return self.label

    @property
    def label(self) -> str:
        return f"{self.get_kind_display()} {self.code}".strip()

    @property
    def is_open(self) -> bool:
        return self.status == TechRefStatus.OPEN

    @property
    def is_overdue(self) -> bool:
        return bool(self.is_open and self.due_date and self.due_date < timezone.localdate())

    @property
    def ha_contenuto(self) -> bool:
        return bool(self.code or self.path or getattr(self, "fai_record", None))

    @property
    def attivita_aperta(self) -> bool:
        return bool(self.task_id and self.task.status not in (TaskStatus.DONE, TaskStatus.CANCELED))

    @property
    def is_web_path(self) -> bool:
        return self.path.lower().startswith(("http://", "https://"))

    @property
    def open_href(self) -> str:
        from .tech_paths import href_percorso

        return href_percorso(self.path)

    def mark_done(self, user=None) -> None:
        self.status = TechRefStatus.DONE
        self.done_by = user
        self.done_at = timezone.now()
        # Per i programmi «fatto» vuol dire validato.
        if self.kind != TechRefKind.FAI:
            self.fase = ProgrammaFase.VALIDATO

    def reopen(self) -> None:
        self.status = TechRefStatus.OPEN
        self.done_by = None
        self.done_at = None
        if self.kind != TechRefKind.FAI and self.fase == ProgrammaFase.VALIDATO:
            self.fase = ProgrammaFase.IN_SCRITTURA if self.code else ProgrammaFase.DA_SCRIVERE

    def save(self, *args, **kwargs):
        # Un programma nato già con il codice non è «da scrivere».
        if self.pk is None and self.kind in (TechRefKind.CAM, TechRefKind.CMM) and self.code:
            if self.fase == ProgrammaFase.DA_SCRIVERE:
                self.fase = ProgrammaFase.VALIDATO if self.status == TechRefStatus.DONE else ProgrammaFase.IN_SCRITTURA
            self.revisione = self.revisione or "A"
        super().save(*args, **kwargs)

    @property
    def is_programma(self) -> bool:
        return self.kind in (TechRefKind.CAM, TechRefKind.CMM)

    @property
    def etichetta_breve(self) -> str:
        """«O1234 rev. B», per leggere il programma in una riga."""
        testo = self.code or "da inserire"
        return f"{testo} rev. {self.revisione}" if self.code and self.revisione else testo


class FaiTipo(models.TextChoices):
    COMPLETO = "COMPLETO", "FAI completo"
    DELTA = "DELTA", "Delta FAI"


class FaiGruppo(models.TextChoices):
    CAUSALE = "CAUSALE", "Perché serve"
    PIANO = "PIANO", "Piano FAI"
    STATO = "STATO", "Stato"
    CHIUSURA = "CHIUSURA", "Chiusura con"
    VERSIONE = "VERSIONE", "Stato versione"
    CROSS = "CROSS", "Cross-correlation"


class FaiFase(models.TextChoices):
    """Cosa significa uno stato per il portale: il nome lo decide chi configura."""

    DA_FARE = "DA_FARE", "Da eseguire: la voce del responsabile resta aperta"
    IN_CORSO = "IN_CORSO", "Eseguito, in attesa di esito"
    POSITIVO = "POSITIVO", "Concluso con esito positivo"
    NON_COMPLETO = "NON_COMPLETO", "Non completo: la voce del responsabile si riapre"
    ANNULLATO = "ANNULLATO", "Annullato: non conta per la scadenza dell'articolo"


class FaiDocumento(models.TextChoices):
    PRESENTE = "S", "Presente"
    DA_VERIFICARE = "V", "Da verificare"
    NON_APPLICABILE = "N", "Non applicabile"


class FaiOpzione(models.Model):
    """Voce configurabile in Impostazioni: perché serve, tipo di piano, stato."""

    gruppo = models.CharField(max_length=10, choices=FaiGruppo.choices, db_index=True)
    # Solo per le voci che il portale riconosce da solo (causali a e f); non si eliminano.
    codice = models.CharField(max_length=20, blank=True, default="", editable=False)
    etichetta = models.CharField(max_length=120, verbose_name="Nome")
    descrizione = models.CharField(max_length=255, blank=True, default="", verbose_name="Descrizione")
    ordine = models.PositiveIntegerField(default=0, db_index=True)
    attiva = models.BooleanField(default=True, db_index=True)
    tipo_proposto = models.CharField(max_length=8, choices=FaiTipo.choices, default=FaiTipo.COMPLETO)
    motivo_se_delta = models.BooleanField(default=False, verbose_name="Motivo se Delta")
    modulo = models.CharField(max_length=60, blank=True, default="")
    stato_op = models.CharField(max_length=20, blank=True, default="")
    numerazione_auto = models.BooleanField(default=False, verbose_name="Numero PFCN automatico")
    fase = models.CharField(max_length=12, choices=FaiFase.choices, default=FaiFase.IN_CORSO)

    class Meta:
        ordering = ["gruppo", "ordine", "id"]
        verbose_name = "Opzione FAI"
        verbose_name_plural = "Opzioni FAI"

    def __str__(self) -> str:
        return self.etichetta


class FaiArticolo(models.Model):
    """Articolo del registro FAI: le date di scadenza sono del P/N, non del singolo FAI."""

    client_name = models.CharField(max_length=180, blank=True, default="", verbose_name="Cliente")
    part_number = models.CharField(max_length=120, verbose_name="P/N")
    ultima_produzione = models.DateField(null=True, blank=True, verbose_name="Fine ultima produzione")
    ultima_spedizione = models.DateField(null=True, blank=True, verbose_name="Ultima spedizione")
    scadenza_cliente = models.DateField(null=True, blank=True, verbose_name="Ripetizione chiesta dal cliente entro")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["client_name", "part_number"]
        verbose_name = "Articolo FAI"
        verbose_name_plural = "Articoli FAI"
        constraints = [
            models.UniqueConstraint(fields=["client_name", "part_number"], name="tasks_fai_articolo_cliente_pn"),
        ]

    def __str__(self) -> str:
        return f"{self.part_number} ({self.client_name})" if self.client_name else self.part_number


class FaiRecord(models.Model):
    """Un FAI di un articolo. Con una commessa ha anche la sua riga in «Programmi e FAI»."""

    articolo = models.ForeignKey(FaiArticolo, on_delete=models.CASCADE, related_name="fai", verbose_name="Articolo")
    project = models.ForeignKey(
        Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="fai_records", verbose_name="Kickoff"
    )
    tech_ref = models.OneToOneField(
        ProjectTechRef, on_delete=models.SET_NULL, null=True, blank=True, related_name="fai_record"
    )
    # Vuoti solo sui FAI storici: il file non li indicava.
    causale = models.ForeignKey(
        FaiOpzione, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Perché serve"
    )
    tipo = models.CharField(max_length=8, choices=FaiTipo.choices, blank=True, default="", verbose_name="Tipo")
    motivo = models.CharField(max_length=1000, blank=True, default="", verbose_name="Motivo del Delta FAI")
    piano = models.ForeignKey(
        FaiOpzione, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Piano FAI"
    )
    piano_numero = models.CharField(max_length=160, blank=True, default="", verbose_name="Numero piano")
    stato = models.ForeignKey(FaiOpzione, on_delete=models.PROTECT, related_name="+", verbose_name="Stato")
    data_invio = models.DateField(null=True, blank=True, verbose_name="Data invio FAI")
    path = models.CharField(max_length=500, blank=True, default="", verbose_name="Cartella o file")
    responsabile = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="tasks_fai", verbose_name="Responsabile",
    )
    # Le colonne del file «Situazione FAI-ISIR», che dal portale si gestisce qui.
    faldone = models.CharField(max_length=40, blank=True, default="", verbose_name="Faldone")
    fai_numero = models.CharField(max_length=40, blank=True, default="", db_index=True, verbose_name="FAI CN n°")
    fai_anno = models.CharField(max_length=20, blank=True, default="", verbose_name="Anno FAI CN")
    cci_numero = models.CharField(max_length=40, blank=True, default="", verbose_name="CCI CN n°")
    cci_anno = models.CharField(max_length=20, blank=True, default="", verbose_name="Anno CCI CN")
    invito = models.CharField(max_length=120, blank=True, default="", verbose_name="N° invito")
    linea = models.CharField(max_length=120, blank=True, default="", verbose_name="Linea")
    pn_assy = models.CharField(max_length=120, blank=True, default="", verbose_name="P/N assy")
    nome_particolare = models.CharField(max_length=255, blank=True, default="", verbose_name="Nome particolare")
    revisione = models.CharField(max_length=60, blank=True, default="", verbose_name="Rev.")
    pn_alternativo = models.CharField(max_length=120, blank=True, default="", verbose_name="P/N alternativo")
    rev_alternativo = models.CharField(max_length=60, blank=True, default="", verbose_name="Rev. P/N alternativo")
    criticita = models.CharField(max_length=120, blank=True, default="", verbose_name="Criticità")
    descrizione_piano = models.CharField(max_length=500, blank=True, default="", verbose_name="Descrizione piano")
    avanzamento = models.CharField(max_length=1000, blank=True, default="", verbose_name="Avanzamento piano")
    op = models.CharField(max_length=120, blank=True, default="", db_index=True, verbose_name="OP")
    oda_item = models.CharField(max_length=120, blank=True, default="", verbose_name="OdA / Item")
    chiusura_con = models.ForeignKey(
        FaiOpzione, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Chiusura con"
    )
    data_chiusura = models.DateField(null=True, blank=True, verbose_name="Data chiusura FAI")
    versione_produzione = models.CharField(max_length=120, blank=True, default="", verbose_name="Versione di produzione")
    stato_versione = models.ForeignKey(
        FaiOpzione, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Stato versione"
    )
    data_versione = models.DateField(null=True, blank=True, verbose_name="Data versione")
    codice_dip = models.CharField(max_length=120, blank=True, default="", verbose_name="Codice DIP")
    data_approvazione_dip = models.DateField(null=True, blank=True, verbose_name="Data approvazione DIP")
    invio_cq = models.CharField(max_length=255, blank=True, default="", verbose_name="Invio CQ")
    cross_correlation = models.ForeignKey(
        FaiOpzione, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="Cross-correlation"
    )
    doc_sdc = models.CharField(max_length=1, choices=FaiDocumento.choices, blank=True, default="", verbose_name="SDC")
    doc_pfc = models.CharField(max_length=1, choices=FaiDocumento.choices, blank=True, default="", verbose_name="PFC")
    doc_sintesi = models.CharField(max_length=1, choices=FaiDocumento.choices, blank=True, default="", verbose_name="Sintesi")
    doc_fai = models.CharField(max_length=1, choices=FaiDocumento.choices, blank=True, default="", verbose_name="FAI")
    # Migrazione dal file: la riga com'era e la chiave per riconoscerla se si importa di nuovo.
    origine_excel = models.JSONField(default=dict, blank=True, editable=False)
    chiave_import = models.CharField(max_length=64, blank=True, default="", db_index=True, editable=False)
    importato_il = models.DateTimeField(null=True, blank=True, editable=False)
    note = models.TextField(blank=True, default="", verbose_name="Note")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "FAI"
        verbose_name_plural = "Registro FAI"

    def __str__(self) -> str:
        return f"{self.get_tipo_display() or 'FAI'} {self.articolo.part_number}".strip()


class SpostamentoStato(models.TextChoices):
    IN_ATTESA = "IN_ATTESA", "In attesa"
    APPROVATA = "APPROVATA", "Approvata"
    RIFIUTATA = "RIFIUTATA", "Rifiutata"
    ANNULLATA = "ANNULLATA", "Annullata"


class TaskSpostamento(models.Model):
    """Richiesta di cambiare le date di un incarico: la decide chi ha pieni poteri sulla commessa."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="spostamenti")
    richiesto_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    inizio_prima = models.DateField(null=True, blank=True)
    fine_prima = models.DateField(null=True, blank=True)
    inizio_nuovo = models.DateField(null=True, blank=True)
    fine_nuovo = models.DateField(null=True, blank=True)
    motivo = models.CharField(max_length=500, blank=True, default="")
    stato = models.CharField(max_length=10, choices=SpostamentoStato.choices, default=SpostamentoStato.IN_ATTESA, db_index=True)
    deciso_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    deciso_at = models.DateTimeField(null=True, blank=True)
    nota_decisione = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Richiesta di spostamento"
        verbose_name_plural = "Richieste di spostamento"

    def __str__(self) -> str:
        return f"Spostamento {self.task_id} ({self.stato})"

    @property
    def in_attesa(self) -> bool:
        return self.stato == SpostamentoStato.IN_ATTESA


class ProgrammaStorico(models.Model):
    """Ogni passaggio di un programma: fase, revisione, codice. Non si cancella."""

    ref = models.ForeignKey(ProjectTechRef, on_delete=models.CASCADE, related_name="storico")
    fase = models.CharField(max_length=14, choices=ProgrammaFase.choices)
    revisione = models.CharField(max_length=10, blank=True, default="")
    code = models.CharField(max_length=120, blank=True, default="")
    nota = models.CharField(max_length=500, blank=True, default="")
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Passaggio del programma"
        verbose_name_plural = "Storico dei programmi"

    def __str__(self) -> str:
        return f"{self.ref_id} {self.fase} {self.revisione}"


class CatalogoTipo(models.TextChoices):
    ODG = "ODG", "Punto all'ordine del giorno"
    AZIONE = "AZIONE", "Azione"
    ATTIVITA = "ATTIVITA", "Attività"
    PROBLEMA = "PROBLEMA", "Problema"


class CatalogoVoce(models.Model):
    """Voce ricorrente: si riempie da sola con quello che si scrive e torna come suggerimento."""

    tipo = models.CharField(max_length=10, choices=CatalogoTipo.choices, db_index=True)
    testo = models.CharField(max_length=220)
    chiave = models.CharField(max_length=220, db_index=True)
    nota = models.CharField(max_length=500, blank=True, default="", verbose_name="Nota predefinita")
    durata_minuti = models.PositiveSmallIntegerField(null=True, blank=True)
    usi = models.PositiveIntegerField(default=0)
    ultimo_uso = models.DateTimeField(null=True, blank=True)
    attiva = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["tipo", "-usi", "testo"]
        constraints = [models.UniqueConstraint(fields=["tipo", "chiave"], name="tasks_catalogo_tipo_chiave")]
        verbose_name = "Voce del catalogo"
        verbose_name_plural = "Catalogo voci ricorrenti"

    def __str__(self) -> str:
        return f"{self.get_tipo_display()}: {self.testo}"
