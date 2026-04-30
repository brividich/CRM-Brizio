from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class AttrezzaturaStato(models.TextChoices):
    DA_CLASSIFICARE = "da_classificare", "Da classificare"
    DA_VERIFICARE = "da_verificare", "Da verificare"
    NON_DISPONIBILE = "non_disponibile", "Non disponibile"
    DA_CREARE = "da_creare", "Da creare"
    IN_CORSO = "in_corso", "In corso"
    IN_ATTESA = "in_attesa", "In attesa"
    FINITA = "finita", "Finita"
    PRONTA_PRODUZIONE = "pronta_produzione", "Pronta produzione"
    ANNULLATA = "annullata", "Annullata"
    ECCEZIONE = "eccezione", "Eccezione"


class DisponibilitaStato(models.TextChoices):
    DA_VERIFICARE = "da_verificare", "Da verificare"
    DISPONIBILE = "disponibile", "Disponibile"
    NON_DISPONIBILE = "non_disponibile", "Non disponibile"
    DA_CREARE = "da_creare", "Da creare"
    DA_MODIFICARE = "da_modificare", "Da modificare"


class AttrezzaturaTaskTipo(models.TextChoices):
    VERIFICA_DISPONIBILITA = "verifica_disponibilita", "Verifica disponibilita"
    CREAZIONE_ATTREZZO = "creazione_attrezzo", "Creazione attrezzo"
    AGGIORNA_AVANZAMENTO = "aggiorna_avanzamento", "Aggiorna avanzamento"
    CONTROLLO_RITARDO = "controllo_ritardo", "Controllo ritardo"
    CONFERMA_PRONTA_PRODUZIONE = "conferma_pronta_produzione", "Conferma pronta produzione"


class AttrezzaturaTaskStato(models.TextChoices):
    APERTA = "aperta", "Aperta"
    IN_LAVORAZIONE = "in_lavorazione", "In lavorazione"
    COMPLETATA = "completata", "Completata"
    ANNULLATA = "annullata", "Annullata"
    BLOCCATA = "bloccata", "Bloccata"


class AttrezzaturaTaskOrigine(models.TextChoices):
    MANUALE = "manuale", "Manuale"
    KICKOFF = "kickoff", "Kickoff"
    IMPORT_EXCEL = "import_excel", "Import Excel"
    REGOLA_AUTOMATICA = "regola_automatica", "Regola automatica"


class AttrezzaturaTaskPriorita(models.TextChoices):
    BASSA = "bassa", "Bassa"
    NORMALE = "normale", "Normale"
    ALTA = "alta", "Alta"
    URGENTE = "urgente", "Urgente"


class ImportBatchStatus(models.TextChoices):
    PREVIEW = "preview", "Preview"
    IMPORTED = "imported", "Imported"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class ImportRowAzione(models.TextChoices):
    CREATED = "created", "Created"
    UPDATED = "updated", "Updated"
    UNCHANGED = "unchanged", "Unchanged"
    SKIPPED = "skipped", "Skipped"
    WARNING = "warning", "Warning"
    ERROR = "error", "Error"


class Attrezzatura(models.Model):
    codice = models.CharField(max_length=80, db_index=True)
    descrizione = models.CharField(max_length=255, blank=True, default="")
    part_number = models.CharField(max_length=120, blank=True, default="", db_index=True)
    numero_pezzi = models.PositiveIntegerField(null=True, blank=True)
    avanzamento_percentuale = models.PositiveSmallIntegerField(null=True, blank=True)
    stato = models.CharField(max_length=40, choices=AttrezzaturaStato.choices, default=AttrezzaturaStato.DA_CLASSIFICARE, db_index=True)
    disponibilita_stato = models.CharField(max_length=40, choices=DisponibilitaStato.choices, default=DisponibilitaStato.DA_VERIFICARE)
    ordine_visuale = models.IntegerField(null=True, blank=True)
    data_consegna_prevista = models.DateField(null=True, blank=True, db_index=True)
    note_consegna = models.TextField(blank=True, default="")
    note_rocco = models.TextField(blank=True, default="")
    origine_import = models.CharField(max_length=120, blank=True, default="")
    pronta_produzione_at = models.DateTimeField(null=True, blank=True)
    pronta_produzione_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzature_pronte_produzione",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzature_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzature_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["codice", "part_number", "id"]
        indexes = [
            models.Index(fields=["codice"]),
            models.Index(fields=["part_number"]),
            models.Index(fields=["stato"]),
            models.Index(fields=["data_consegna_prevista"]),
        ]
        verbose_name = "Attrezzatura"
        verbose_name_plural = "Attrezzature"
        permissions = [
            ("attrezzature_view", "Puo vedere Gestione Attrezzatura"),
            ("attrezzature_add", "Puo creare attrezzature"),
            ("attrezzature_change", "Puo modificare attrezzature"),
            ("attrezzature_import", "Puo importare attrezzature da Excel"),
            ("attrezzature_export", "Puo esportare attrezzature"),
            ("attrezzature_task_view", "Puo vedere task attrezzature"),
            ("attrezzature_task_manage", "Puo gestire task attrezzature"),
            ("attrezzature_link_kickoff", "Puo collegare attrezzature a Kickoff"),
            ("attrezzature_confirm_ready_production", "Puo confermare pronta produzione"),
        ]

    def __str__(self) -> str:
        parts = [self.codice or "Senza codice"]
        if self.part_number:
            parts.append(f"P/N {self.part_number}")
        if self.descrizione:
            parts.append(self.descrizione)
        return " - ".join(parts)

    @property
    def is_finita(self) -> bool:
        return self.stato == AttrezzaturaStato.FINITA

    @property
    def is_pronta_produzione(self) -> bool:
        return self.stato == AttrezzaturaStato.PRONTA_PRODUZIONE

    @property
    def is_in_ritardo(self) -> bool:
        if not self.data_consegna_prevista:
            return False
        if self.stato in {
            AttrezzaturaStato.FINITA,
            AttrezzaturaStato.ANNULLATA,
            AttrezzaturaStato.PRONTA_PRODUZIONE,
        }:
            return False
        return self.data_consegna_prevista < timezone.localdate()

    @property
    def display_part_number(self) -> str:
        return (self.part_number or "").strip() or "-"


class AttrezzaturaPartNumber(models.Model):
    attrezzatura = models.ForeignKey(Attrezzatura, on_delete=models.CASCADE, related_name="part_numbers")
    part_number = models.CharField(max_length=120, db_index=True)
    is_principale = models.BooleanField(default=True)
    fonte = models.CharField(max_length=80, blank=True, default="")
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("attrezzatura", "part_number")]
        ordering = ["-is_principale", "part_number", "id"]

    def __str__(self) -> str:
        return f"{self.part_number} -> {self.attrezzatura_id}"


class AttrezzaturaAvanzamento(models.Model):
    attrezzatura = models.ForeignKey(Attrezzatura, on_delete=models.CASCADE, related_name="avanzamenti")
    stato_precedente = models.CharField(max_length=40, blank=True, default="")
    stato_nuovo = models.CharField(max_length=40, blank=True, default="")
    avanzamento_precedente = models.PositiveSmallIntegerField(null=True, blank=True)
    avanzamento_nuovo = models.PositiveSmallIntegerField(null=True, blank=True)
    nota = models.TextField(blank=True, default="")
    origine = models.CharField(max_length=80, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return f"Avanzamento<{self.attrezzatura_id}:{self.stato_precedente}->{self.stato_nuovo}>"


class AttrezzaturaTask(models.Model):
    attrezzatura = models.ForeignKey(
        Attrezzatura,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
    )
    part_number = models.CharField(max_length=120, blank=True, default="", db_index=True)
    codice_attrezzo = models.CharField(max_length=80, blank=True, default="")
    tipo = models.CharField(max_length=50, choices=AttrezzaturaTaskTipo.choices)
    titolo = models.CharField(max_length=255)
    descrizione = models.TextField(blank=True, default="")
    stato = models.CharField(max_length=40, choices=AttrezzaturaTaskStato.choices, default=AttrezzaturaTaskStato.APERTA)
    priorita = models.CharField(max_length=30, choices=AttrezzaturaTaskPriorita.choices, default=AttrezzaturaTaskPriorita.NORMALE)
    assegnato_a = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzatura_tasks_assigned",
    )
    scadenza = models.DateField(null=True, blank=True)
    origine = models.CharField(max_length=40, choices=AttrezzaturaTaskOrigine.choices, default=AttrezzaturaTaskOrigine.MANUALE)
    external_kickoff_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    external_kickoff_activity_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzatura_tasks_completed",
    )
    blocked_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attrezzatura_tasks_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scadenza", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["tipo", "stato"]),
            models.Index(fields=["part_number", "stato"]),
            models.Index(fields=["external_kickoff_activity_id"]),
        ]

    def __str__(self) -> str:
        return self.titolo

    @property
    def is_open(self) -> bool:
        return self.stato in {AttrezzaturaTaskStato.APERTA, AttrezzaturaTaskStato.IN_LAVORAZIONE, AttrezzaturaTaskStato.BLOCCATA}

    @property
    def is_completed(self) -> bool:
        return self.stato == AttrezzaturaTaskStato.COMPLETATA

    @property
    def is_overdue(self) -> bool:
        return bool(self.scadenza and self.is_open and self.scadenza < timezone.localdate())


class AttrezzaturaNota(models.Model):
    attrezzatura = models.ForeignKey(Attrezzatura, on_delete=models.CASCADE, related_name="note")
    task = models.ForeignKey(AttrezzaturaTask, null=True, blank=True, on_delete=models.SET_NULL, related_name="note")
    testo = models.TextField()
    origine = models.CharField(max_length=80, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self) -> str:
        return self.testo[:80]


class AttrezzaturaImportBatch(models.Model):
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    total_rows = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=40, choices=ImportBatchStatus.choices, default=ImportBatchStatus.PREVIEW)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self) -> str:
        return f"{self.file_name} ({self.status})"


class AttrezzaturaImportRow(models.Model):
    batch = models.ForeignKey(AttrezzaturaImportBatch, on_delete=models.CASCADE, related_name="rows")
    excel_sheet = models.CharField(max_length=120, blank=True, default="")
    excel_row_number = models.PositiveIntegerField()
    payload_originale_json = models.JSONField(default=dict)
    row_hash = models.CharField(max_length=64, db_index=True)
    codice_letto = models.CharField(max_length=80, blank=True, default="")
    part_number_letto = models.CharField(max_length=120, blank=True, default="")
    azione = models.CharField(max_length=40, choices=ImportRowAzione.choices)
    warnings = models.JSONField(default=list, blank=True)
    errors = models.JSONField(default=list, blank=True)
    attrezzatura = models.ForeignKey(
        Attrezzatura,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_rows",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["batch_id", "excel_row_number", "id"]

    def __str__(self) -> str:
        return f"Row {self.excel_row_number}: {self.azione}"
