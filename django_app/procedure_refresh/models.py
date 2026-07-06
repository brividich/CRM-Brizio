from __future__ import annotations

from django.conf import settings
from django.db import models


class DocumentType(models.TextChoices):
    MT = "MT", "MT"
    MTSI = "MTSI", "MTSI"
    ALTRO = "ALTRO", "Altro"


class SourceType(models.TextChoices):
    SHAREPOINT = "sharepoint", "SharePoint"
    FILESERVER = "fileserver", "File server"


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", "Bozza"
    PUBLISHED = "published", "Pubblicata"
    CLOSED = "closed", "Chiusa"
    ARCHIVED = "archived", "Archiviata"


class AssignmentStatus(models.TextChoices):
    ASSIGNED = "assigned", "Assegnata"
    OPENED = "opened", "Aperta"
    READ_CONFIRMED = "read_confirmed", "Presa visione confermata"
    OVERDUE = "overdue", "Scaduta"
    CANCELLED = "cancelled", "Annullata"


class ReadEventType(models.TextChoices):
    OPENED = "opened", "Aperta"
    CONFIRMED = "confirmed", "Confermata"
    REMINDER_SENT = "reminder_sent", "Reminder inviato"
    REASSIGNED = "reassigned", "Riassegnata"
    EXPORTED = "exported", "Esportata"
    OVERDUE_MARKED = "overdue_marked", "Marcata scaduta"


class ProcedureDocument(models.Model):
    code = models.CharField(max_length=50, unique=True, verbose_name="Codice documento")
    title = models.CharField(max_length=300, verbose_name="Titolo")
    category = models.CharField(max_length=100, blank=True, default="", verbose_name="Categoria")
    document_type = models.CharField(
        max_length=10,
        choices=DocumentType.choices,
        default=DocumentType.MT,
        db_index=True,
        verbose_name="Tipo documento",
    )
    owner_department = models.CharField(
        max_length=150, blank=True, default="", verbose_name="Reparto responsabile"
    )
    description = models.TextField(blank=True, default="", verbose_name="Descrizione")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Attivo")
    requires_acknowledgement = models.BooleanField(
        default=True, verbose_name="Richiede presa visione"
    )
    escludi_dal_rag = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Escludi dal RAG AI",
        help_text=(
            "Se attivo, il documento NON viene indicizzato dall'assistente AI (corpus RAG). "
            "Usare per i roster di persone abilitate/licenziate a una macchina (skill matrix / "
            "licensed operators): quel dato deve arrivare solo dal modulo Skill Matrix governato, "
            "non essere dedotto dai documenti (evita allucinazioni HR e bypass dei permessi)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_type", "code"]
        verbose_name = "Documento procedura"
        verbose_name_plural = "Documenti procedura"

    def __str__(self) -> str:
        return f"[{self.document_type}] {self.code} — {self.title}"

    def current_revision(self) -> "ProcedureRevision | None":
        return self.revisions.filter(is_current=True).first()


class ProcedureRevision(models.Model):
    document = models.ForeignKey(
        ProcedureDocument,
        on_delete=models.CASCADE,
        related_name="revisions",
        verbose_name="Documento",
    )
    revision_code = models.CharField(max_length=50, verbose_name="Codice revisione")
    revision_date = models.DateField(verbose_name="Data revisione")
    effective_date = models.DateField(verbose_name="Data efficacia")
    source_type = models.CharField(
        max_length=20,
        choices=SourceType.choices,
        default=SourceType.SHAREPOINT,
        verbose_name="Sorgente",
    )
    source_url = models.CharField(
        max_length=2048, blank=True, default="", verbose_name="URL SharePoint"
    )
    source_path = models.CharField(
        max_length=1024, blank=True, default="", verbose_name="Path file server"
    )
    file_name = models.CharField(max_length=300, verbose_name="Nome file")
    file_hash = models.CharField(max_length=128, blank=True, default="", verbose_name="Hash file")
    is_current = models.BooleanField(default=False, db_index=True, verbose_name="Revisione corrente")
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_published_revisions",
        verbose_name="Pubblicato da",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-revision_date"]
        verbose_name = "Revisione procedura"
        verbose_name_plural = "Revisioni procedura"
        constraints = [
            models.UniqueConstraint(
                fields=["document", "revision_code"],
                name="pr_unique_doc_revision_code",
            )
        ]

    def __str__(self) -> str:
        return f"{self.document.code} rev.{self.revision_code}"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        if self.source_type == SourceType.SHAREPOINT and not self.source_url:
            raise ValidationError({"source_url": "URL obbligatorio per sorgente SharePoint."})
        if self.source_type == SourceType.FILESERVER and not self.source_path:
            raise ValidationError({"source_path": "Path obbligatorio per sorgente file server."})

    def save(self, *args, **kwargs) -> None:
        if self.is_current:
            ProcedureRevision.objects.filter(
                document=self.document, is_current=True
            ).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class ProcedureCampaign(models.Model):
    name = models.CharField(max_length=200, verbose_name="Nome campagna")
    description = models.TextField(blank=True, default="", verbose_name="Descrizione")
    status = models.CharField(
        max_length=20,
        choices=CampaignStatus.choices,
        default=CampaignStatus.DRAFT,
        db_index=True,
        verbose_name="Stato",
    )
    start_date = models.DateField(verbose_name="Data inizio")
    due_date = models.DateField(verbose_name="Scadenza")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_created_campaigns",
        verbose_name="Creata da",
    )
    published_at = models.DateTimeField(null=True, blank=True, verbose_name="Pubblicata il")
    closed_at = models.DateTimeField(null=True, blank=True, verbose_name="Chiusa il")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Campagna refresh"
        verbose_name_plural = "Campagne refresh"

    def __str__(self) -> str:
        return self.name


class ProcedureCampaignDocument(models.Model):
    campaign = models.ForeignKey(
        ProcedureCampaign,
        on_delete=models.CASCADE,
        related_name="campaign_documents",
        verbose_name="Campagna",
    )
    revision = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.PROTECT,
        related_name="campaign_documents",
        verbose_name="Revisione",
    )
    is_mandatory = models.BooleanField(default=True, verbose_name="Obbligatoria")
    display_order = models.PositiveIntegerField(default=0, verbose_name="Ordine")

    class Meta:
        ordering = ["display_order", "id"]
        verbose_name = "Documento in campagna"
        verbose_name_plural = "Documenti in campagna"
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "revision"],
                name="pr_unique_campaign_revision",
            )
        ]

    def __str__(self) -> str:
        return f"{self.campaign} / {self.revision}"


class ProcedureAssignment(models.Model):
    campaign = models.ForeignKey(
        ProcedureCampaign,
        on_delete=models.CASCADE,
        related_name="assignments",
        verbose_name="Campagna",
    )
    revision = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.PROTECT,
        related_name="assignments",
        verbose_name="Revisione",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="procedure_assignments",
        verbose_name="Utente",
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_assignments_given",
        verbose_name="Assegnato da",
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name="Assegnato il")
    due_date = models.DateField(null=True, blank=True, verbose_name="Scadenza")
    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ASSIGNED,
        db_index=True,
        verbose_name="Stato",
    )
    first_opened_at = models.DateTimeField(null=True, blank=True, verbose_name="Prima apertura")
    last_opened_at = models.DateTimeField(null=True, blank=True, verbose_name="Ultima apertura")
    read_confirmed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Conferma presa visione"
    )
    read_confirmed_flag = models.BooleanField(default=False, verbose_name="Presa visione confermata")
    user_note = models.TextField(blank=True, default="", verbose_name="Nota utente")
    manager_note = models.TextField(blank=True, default="", verbose_name="Nota manager")
    open_count = models.PositiveIntegerField(default=0, verbose_name="Numero aperture")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    user_agent = models.TextField(blank=True, default="", verbose_name="User agent")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assigned_at"]
        verbose_name = "Assegnazione"
        verbose_name_plural = "Assegnazioni"
        indexes = [
            models.Index(fields=["user", "status"], name="pr_assign_user_status"),
            models.Index(fields=["campaign", "status"], name="pr_assign_campaign_status"),
            models.Index(fields=["revision", "status"], name="pr_assign_revision_status"),
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.revision} [{self.status}]"


class ProcedureReadEvent(models.Model):
    assignment = models.ForeignKey(
        ProcedureAssignment,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name="Assegnazione",
    )
    event_type = models.CharField(
        max_length=20,
        choices=ReadEventType.choices,
        db_index=True,
        verbose_name="Tipo evento",
    )
    event_at = models.DateTimeField(auto_now_add=True, verbose_name="Timestamp")
    event_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_read_events",
        verbose_name="Eseguito da",
    )
    notes = models.TextField(blank=True, default="", verbose_name="Note")
    meta_json = models.TextField(blank=True, default="", verbose_name="Metadati JSON")

    class Meta:
        ordering = ["-event_at"]
        verbose_name = "Evento lettura"
        verbose_name_plural = "Eventi lettura"

    def __str__(self) -> str:
        return f"{self.event_type} @ {self.event_at}"


class ChangeRequestStatus(models.TextChoices):
    APERTA = "aperta", "Aperta"
    IN_CARICO = "in_carico", "Presa in carico"
    RECEPITA = "recepita", "Recepita"
    RESPINTA = "respinta", "Respinta"


class ProcedureChangeRequest(models.Model):
    """Segnalazione di modifica a un documento proposta da chi ne fa la presa
    visione. Evidenza del ciclo di miglioramento (ISO 9001/EN 9100): non si
    cancella mai, si tracciano solo i cambi di stato fino alla chiusura
    (recepita in una revisione / respinta con motivazione)."""

    document = models.ForeignKey(
        ProcedureDocument,
        on_delete=models.PROTECT,
        related_name="change_requests",
        verbose_name="Documento",
    )
    revision = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="change_requests",
        verbose_name="Revisione letta",
    )
    assignment = models.ForeignKey(
        ProcedureAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="change_requests",
        verbose_name="Assegnazione di origine",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_change_requests_created",
        verbose_name="Proponente",
    )
    testo = models.TextField(verbose_name="Proposta di modifica")
    status = models.CharField(
        max_length=20,
        choices=ChangeRequestStatus.choices,
        default=ChangeRequestStatus.APERTA,
        db_index=True,
        verbose_name="Stato",
    )
    risposta_gestore = models.TextField(blank=True, default="", verbose_name="Risposta del gestore")
    gestita_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_change_requests_gestite",
        verbose_name="Gestita da",
    )
    gestita_il = models.DateTimeField(null=True, blank=True, verbose_name="Gestita il")
    recepita_in_revisione = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Recepita nella revisione",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Segnalazione di modifica"
        verbose_name_plural = "Segnalazioni di modifica"
        indexes = [
            models.Index(fields=["document", "status"], name="pr_cr_document_status"),
        ]

    def __str__(self) -> str:
        return f"CR#{self.pk} {self.document.code} [{self.status}]"

    @property
    def is_open(self) -> bool:
        return self.status in {ChangeRequestStatus.APERTA, ChangeRequestStatus.IN_CARICO}


class ProcedureQuiz(models.Model):
    revision = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.CASCADE,
        related_name="quizzes",
        verbose_name="Revisione",
    )
    title = models.CharField(max_length=200, default="Quiz post-lettura", verbose_name="Titolo")
    questions = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Domande",
        help_text="Lista di domande a risposta multipla con opzioni e indice risposta corretta.",
    )
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Attivo")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pr_quizzes_created",
        verbose_name="Creato da",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_active", "-updated_at", "-id"]
        verbose_name = "Quiz procedura"
        verbose_name_plural = "Quiz procedure"

    def __str__(self) -> str:
        return f"{self.revision} - {self.title}"

    @property
    def question_count(self) -> int:
        return len(self.questions or [])


class ProcedureQuizAttempt(models.Model):
    quiz = models.ForeignKey(
        ProcedureQuiz,
        on_delete=models.CASCADE,
        related_name="attempts",
        verbose_name="Quiz",
    )
    assignment = models.ForeignKey(
        ProcedureAssignment,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
        verbose_name="Assegnazione",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="procedure_quiz_attempts",
        verbose_name="Utente",
    )
    answers = models.JSONField(default=list, blank=True, verbose_name="Risposte")
    score = models.PositiveIntegerField(default=0, verbose_name="Punteggio")
    total_questions = models.PositiveIntegerField(default=0, verbose_name="Totale domande")
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name="Inviato il")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP")
    user_agent = models.TextField(blank=True, default="", verbose_name="User agent")

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "Tentativo quiz procedura"
        verbose_name_plural = "Tentativi quiz procedure"
        constraints = [
            models.UniqueConstraint(
                fields=["quiz", "assignment", "user"],
                name="pr_unique_quiz_attempt_assignment_user",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.quiz} ({self.score}/{self.total_questions})"
