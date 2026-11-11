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


def q_scadute(oggi):
    """Assegnazioni scadute **adesso**: già marcate OVERDUE oppure ancora da
    leggere con scadenza passata in una campagna pubblicata (stessa regola di
    ``run_assignment_lifecycle``, che le marca solo alle 06:45)."""
    return models.Q(status=AssignmentStatus.OVERDUE) | models.Q(
        status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED],
        campaign__status=CampaignStatus.PUBLISHED,
        due_date__isnull=False,
        due_date__lt=oggi,
    )


def q_in_attesa(oggi):
    """Da leggere e non ancora scadute: il complemento di ``q_scadute`` fra le pendenti."""
    return models.Q(status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]) & ~q_scadute(oggi)


def scaduta_ora(assignment, oggi) -> bool:
    """``q_scadute`` per una riga già caricata."""
    if assignment.status == AssignmentStatus.OVERDUE:
        return True
    return bool(
        assignment.status in (AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED)
        and assignment.due_date
        and assignment.due_date < oggi
        and assignment.campaign.status == CampaignStatus.PUBLISHED
    )


class ReadEventType(models.TextChoices):
    OPENED = "opened", "Aperta"
    CONFIRMED = "confirmed", "Confermata"
    REMINDER_SENT = "reminder_sent", "Reminder inviato"
    REASSIGNED = "reassigned", "Riassegnata"
    EXPORTED = "exported", "Esportata"
    OVERDUE_MARKED = "overdue_marked", "Marcata scaduta"


class SgiSyncAction(models.TextChoices):
    NUOVO_DOC = "nuovo_doc", "Nuovo documento"
    NUOVA_REVISIONE = "nuova_revisione", "Nuova revisione"
    DOC_SPARITO = "doc_sparito", "Documento sparito dalla share"


class SgiSyncLog(models.Model):
    """Riga append-only del log di sincronizzazione SGI.

    Traccia ogni cambiamento rilevato/applicato dalla sync (automatica o manuale):
    nuovo documento, nuova revisione di un documento esistente, documento sparito
    dalla share. È l'evidenza ISO dei cambiamenti al corpus documentale e la fonte
    del badge «nuova revisione» nella lista documenti. Mai cancellata dai flussi.
    """

    run_id = models.CharField(max_length=64, db_index=True, verbose_name="ID esecuzione")
    azione = models.CharField(
        max_length=20, choices=SgiSyncAction.choices, db_index=True, verbose_name="Azione"
    )
    document_code = models.CharField(max_length=50, db_index=True, verbose_name="Codice documento")
    revision_old = models.CharField(max_length=50, blank=True, default="", verbose_name="Revisione precedente")
    revision_new = models.CharField(max_length=50, blank=True, default="", verbose_name="Revisione nuova")
    note = models.CharField(max_length=300, blank=True, default="", verbose_name="Note")
    origine = models.CharField(max_length=10, default="auto", verbose_name="Origine")  # auto | manuale
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Log sincronizzazione SGI"
        verbose_name_plural = "Log sincronizzazioni SGI"

    def __str__(self) -> str:
        return f"[{self.get_azione_display()}] {self.document_code} ({self.created_at:%Y-%m-%d})"


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
    sezione = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Sezione",
        help_text="Sottocartella della share sotto lo scaffale (es. «2_MT»). La scrive la sincronizzazione.",
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


class SgiTestoEstratto(models.Model):
    """Testo estratto e persistito di una revisione SGI (file server), per il RAG.

    Valido finché ``file_hash`` coincide con quello della revisione: se il file
    cambia, il testo viene ri-estratto (``sgi_estrai_testi`` / task a catena). Il
    testo è markdown leggero (heading, tabelle in pipe-table) senza intestazioni e
    piè di pagina ripetuti. Letto dall'assistente solo con
    ``SGI_ESTRAZIONE_PERSISTITA_ENABLED``.
    """

    revision = models.OneToOneField(
        ProcedureRevision,
        on_delete=models.CASCADE,
        related_name="testo_estratto",
        verbose_name="Revisione",
    )
    file_hash = models.CharField(max_length=128, db_index=True, verbose_name="Hash file estratto")
    formato = models.CharField(max_length=10, verbose_name="Formato")
    metodo = models.CharField(max_length=30, verbose_name="Metodo")
    testo = models.TextField(blank=True, default="", verbose_name="Testo")
    n_pagine = models.PositiveIntegerField(null=True, blank=True, verbose_name="Pagine")
    n_caratteri = models.PositiveIntegerField(default=0, verbose_name="Caratteri")
    n_sezioni = models.PositiveIntegerField(default=0, verbose_name="Sezioni §")
    ha_testo_nativo = models.BooleanField(default=True, verbose_name="Testo nativo")
    ocr_usato = models.BooleanField(default=False, verbose_name="OCR usato")
    avvisi = models.TextField(blank=True, default="", verbose_name="Avvisi")
    offset_pagine = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Inizio delle pagine",
        help_text="Posizione nel testo in cui comincia ogni pagina: serve ad aprire il PDF alla pagina trovata dalla ricerca.",
    )
    estratto_il = models.DateTimeField(auto_now=True, verbose_name="Estratto il")

    class Meta:
        verbose_name = "Testo estratto SGI"
        verbose_name_plural = "Testi estratti SGI"

    def __str__(self) -> str:
        return f"{self.revision} [{self.metodo}]"


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


class SgiRiferimento(models.Model):
    """Codice SGI citato nel testo di una revisione (A2, grafo dei riferimenti).

    Deterministico, zero AI: ricostruito per revisione a ogni nuova estrazione del testo
    (``sgi_riferimenti.ricostruisci``). ``a_documento`` vuoto = codice citato che non
    esiste nel catalogo (documento mancante o refuso). Le norme esterne (ISO, EN, ...)
    non sono riferimenti SGI e non entrano qui.
    """

    da_revisione = models.ForeignKey(
        ProcedureRevision,
        on_delete=models.CASCADE,
        related_name="riferimenti_uscenti",
        verbose_name="Revisione che cita",
    )
    codice_citato = models.CharField(max_length=60, db_index=True, verbose_name="Codice citato")
    a_documento = models.ForeignKey(
        ProcedureDocument,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="riferimenti_entranti",
        verbose_name="Documento citato",
    )
    sezione = models.CharField(max_length=160, blank=True, default="", verbose_name="Sezione")
    occorrenze = models.PositiveIntegerField(default=1, verbose_name="Occorrenze")
    risolto = models.BooleanField(default=False, db_index=True, verbose_name="Risolto")
    TIPI_RISOLUZIONE = [
        ("esatto", "Codice esatto"),
        ("normalizzato", "Codice con altra grafia"),
        ("disambiguato", "Codice disambiguato dall'import"),
        ("allegato_base", "Allegato sul documento base"),
        ("senza_cn", "Citazione abbreviata senza CN"),
        ("famiglia", "Famiglia di documenti (X_n)"),
    ]
    tipo_risoluzione = models.CharField(max_length=20, blank=True, default="", choices=TIPI_RISOLUZIONE,
                                        verbose_name="Tipo di risoluzione")

    class Meta:
        verbose_name = "Riferimento SGI"
        verbose_name_plural = "Riferimenti SGI"
        constraints = [
            models.UniqueConstraint(fields=["da_revisione", "codice_citato", "sezione"], name="uq_sgi_rif"),
        ]

    def __str__(self) -> str:
        return f"{self.da_revisione_id} -> {self.codice_citato}"

    def documenti_famiglia(self):
        """Documenti della famiglia citata (``<codice>_n``), per i riferimenti di famiglia."""
        if self.tipo_risoluzione != "famiglia":
            return ProcedureDocument.objects.none()
        from procedure_refresh.sgi_riferimenti import Catalogo

        famiglia = Catalogo().dettaglio(self.codice_citato).famiglia
        return ProcedureDocument.objects.filter(pk__in=[d.pk for d in famiglia]).order_by("code")


class SgiDocumentoProcesso(models.Model):
    """Collegamento proposto documento SGI ↔ processo (``sgi_collega_processi``).

    Nasce da un codice citato nel testo libero del processo (``procedure``,
    ``fonte_documentale``) e resta ``confermato=False`` finché una persona non lo
    conferma. Il testo del processo non viene mai modificato.
    """

    ORIGINE_PROCESSO_TESTO = "processo_testo"
    ORIGINI = [(ORIGINE_PROCESSO_TESTO, "Testo del processo")]

    documento = models.ForeignKey(
        ProcedureDocument,
        on_delete=models.CASCADE,
        related_name="processi_collegati",
        verbose_name="Documento",
    )
    processo = models.ForeignKey(
        "sistema_gestione.Processo",
        on_delete=models.CASCADE,
        related_name="documenti_sgi",
        verbose_name="Processo",
    )
    origine = models.CharField(max_length=20, choices=ORIGINI, default=ORIGINE_PROCESSO_TESTO,
                               verbose_name="Origine")
    codice_citato = models.CharField(max_length=60, blank=True, default="", verbose_name="Codice citato")
    confermato = models.BooleanField(default=False, db_index=True, verbose_name="Confermato")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Creato il")

    class Meta:
        verbose_name = "Documento SGI di processo"
        verbose_name_plural = "Documenti SGI di processo"
        constraints = [
            models.UniqueConstraint(fields=["documento", "processo"], name="uq_sgi_doc_processo"),
        ]

    def __str__(self) -> str:
        return f"{self.processo_id} <-> {self.documento_id}"


# ---------------------------------------------------------------------------
# CN-SGI: libreria delle procedure (scaffali, visibilità, consultazioni)
# ---------------------------------------------------------------------------


class SgiScaffale(models.Model):
    """Uno scaffale della libreria CN-SGI = una cartella di primo livello della share.

    La riga nasce dalla sincronizzazione (o dalla pagina «Scaffali») con nome e colore
    ricavati dal nome della cartella; chi gestisce CN-SGI può cambiarli. Il campo
    ``cartella`` coincide con ``ProcedureDocument.category``.
    """

    cartella = models.CharField(max_length=100, unique=True, verbose_name="Cartella sulla share")
    nome = models.CharField(max_length=120, verbose_name="Nome")
    sigla = models.CharField(max_length=20, blank=True, default="", verbose_name="Sigla sulla copertina")
    norma = models.CharField(max_length=160, blank=True, default="", verbose_name="Norma o riferimento")
    colore = models.CharField(max_length=7, default="#1f4f86", verbose_name="Colore")
    ordine = models.PositiveIntegerField(default=100, verbose_name="Ordine")
    certificazione = models.ForeignKey(
        "sistema_gestione.Certificazione",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scaffali_sgi",
        verbose_name="Certificazione collegata",
    )
    attivo = models.BooleanField(default=True, verbose_name="Mostrato nella libreria")
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ordine", "nome"]
        verbose_name = "Scaffale CN-SGI"
        verbose_name_plural = "Scaffali CN-SGI"

    def __str__(self) -> str:
        return self.nome or self.cartella


class SgiVisibilitaChi(models.TextChoices):
    RUOLI = "ruoli", "Solo i ruoli scelti"
    NESSUNO = "nessuno", "Solo chi gestisce CN-SGI"


class SgiVisibilita(models.Model):
    """Regola «chi vede cosa» dentro CN-SGI.

    Vale per uno scaffale (``sezione`` vuota, nessun documento), per una sezione
    dello scaffale o per un singolo documento. Vince la regola più specifica
    (documento > sezione > scaffale); senza regole il documento è visibile a tutti.
    Chi gestisce CN-SGI, gli amministratori e i ruoli «vede tutto» vedono sempre tutto.
    L'unicità della terna è controllata dal form (niente vincolo DB: con SQL Server
    un vincolo con colonne NULL ammette un solo NULL).
    """

    scaffale = models.CharField(max_length=100, db_index=True, verbose_name="Scaffale (cartella)")
    sezione = models.CharField(max_length=255, blank=True, default="", verbose_name="Sezione")
    documento = models.ForeignKey(
        ProcedureDocument,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="regole_visibilita",
        verbose_name="Documento",
    )
    chi = models.CharField(
        max_length=10, choices=SgiVisibilitaChi.choices, default=SgiVisibilitaChi.RUOLI, verbose_name="Chi vede"
    )
    ruoli = models.ManyToManyField(
        "core.AccessGroup", blank=True, related_name="regole_visibilita_sgi", verbose_name="Ruoli"
    )
    note = models.CharField(max_length=300, blank=True, default="", verbose_name="Note")
    aggiornata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="Aggiornata da",
    )
    aggiornata_il = models.DateTimeField(auto_now=True, verbose_name="Aggiornata il")

    class Meta:
        ordering = ["scaffale", "sezione", "documento_id"]
        verbose_name = "Regola di visibilità CN-SGI"
        verbose_name_plural = "Regole di visibilità CN-SGI"

    @property
    def livello(self) -> str:
        if self.documento_id:
            return "documento"
        if self.sezione:
            return "sezione"
        return "scaffale"

    def __str__(self) -> str:
        return f"{self.livello}: {self.scaffale} / {self.sezione} / {self.documento_id or ''}"


class SgiAperturaGiorno(models.Model):
    """Aperture di un documento dalla libreria, contate per giorno («Più consultati»).

    Solo un contatore: chi ha aperto cosa resta nell'audit (``log_action``).
    """

    documento = models.ForeignKey(
        ProcedureDocument, on_delete=models.CASCADE, related_name="aperture_giorno", verbose_name="Documento"
    )
    giorno = models.DateField(db_index=True, verbose_name="Giorno")
    conteggio = models.PositiveIntegerField(default=0, verbose_name="Aperture")

    class Meta:
        unique_together = [("documento", "giorno")]
        verbose_name = "Aperture giornaliere CN-SGI"
        verbose_name_plural = "Aperture giornaliere CN-SGI"

    def __str__(self) -> str:
        return f"{self.documento_id} {self.giorno}: {self.conteggio}"
