from __future__ import annotations

from django.conf import settings
from django.db import models

PRIVACY_STATUS_CHOICES = [
    ("pending", "Da revisionare"),
    ("approved", "Approvato"),
    ("restricted", "Uso limitato"),
    ("blocked", "Bloccato"),
]


class AiToolPrivacyReview(models.Model):
    """Revisione privacy per ogni tool runtime AI. Un record per tool_key."""

    tool_key = models.CharField(max_length=80, unique=True, db_index=True)
    tool_label = models.CharField(max_length=120, blank=True)
    privacy_status = models.CharField(
        max_length=20,
        choices=PRIVACY_STATUS_CHOICES,
        default="pending",
        db_index=True,
    )
    allowed_fields = models.TextField(
        blank=True,
        help_text="Campi consentiti nel contesto AI, separati da virgola.",
    )
    blocked_fields = models.TextField(
        blank=True,
        help_text="Campi vietati, separati da virgola.",
    )
    retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Giorni di retention per audit AI di questo tool (vuoto = policy globale).",
    )
    notes = models.TextField(
        blank=True,
        help_text="Note interne sulla revisione. Non trasmesse al modello.",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_privacy_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tool_key"]
        verbose_name = "revisione privacy tool AI"
        verbose_name_plural = "revisioni privacy tool AI"

    def __str__(self) -> str:
        return f"{self.tool_key} [{self.privacy_status}]"

    def allowed_fields_list(self) -> list[str]:
        return [f.strip() for f in self.allowed_fields.split(",") if f.strip()]

    def blocked_fields_list(self) -> list[str]:
        return [f.strip() for f in self.blocked_fields.split(",") if f.strip()]


class AiChatFeedback(models.Model):
    """Feedback thumbs up/down sulle risposte dell'assistente AI."""

    RATING_CHOICES = [
        ("up", "Positivo"),
        ("down", "Negativo"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_chat_feedbacks",
    )
    prompt = models.TextField(
        help_text="Il messaggio utente originale, max 500 char.",
    )
    response = models.TextField(
        help_text="La risposta AI originale, max 2000 char.",
    )
    rating = models.CharField(
        max_length=4,
        choices=RATING_CHOICES,
        db_index=True,
    )
    correction = models.TextField(
        blank=True,
        help_text="La risposta corretta proposta dall'utente.",
    )
    source_label = models.CharField(max_length=120, default="Feedback chat")
    is_reviewed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="L'amministratore ha visionato questo feedback.",
    )
    knowledge_entry = models.ForeignKey(
        "AiKnowledgeEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedback_entries",
        help_text="Voce FAQ generata automaticamente da questo feedback (se rating=down con correzione).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "feedback chat AI"
        verbose_name_plural = "feedback chat AI"

    def __str__(self) -> str:
        return f"[{self.rating}] {(self.prompt or '')[:60]}"


class AiProposta(models.Model):
    """Una proposta dei copiloti AI e cosa ne ha fatto la persona: e' cosi' che l'AI «impara».

    Il modello non viene riaddestrato: alla proposta successiva il copilota legge qui come sono
    state trattate le sue proposte precedenti (accettate, corrette, scartate) e lo mette nel
    contesto. Si salvano solo valori strutturati e brevi (etichette, codici, esiti), mai testi
    personali o documenti.
    """

    IN_ATTESA = "in_attesa"
    ACCETTATA = "accettata"
    MODIFICATA = "modificata"
    SCARTATA = "scartata"
    SUPERATA = "superata"
    ESITI = [
        (IN_ATTESA, "In attesa"),
        (ACCETTATA, "Accettata"),
        (MODIFICATA, "Corretta"),
        (SCARTATA, "Scartata"),
        (SUPERATA, "Superata da una nuova proposta"),
    ]

    modulo = models.CharField(max_length=40, db_index=True)
    azione = models.CharField(max_length=60, db_index=True)
    oggetto_ref = models.CharField(max_length=80, db_index=True)
    proposta = models.JSONField(default=dict, blank=True)
    decisione = models.JSONField(default=dict, blank=True)
    campi_corretti = models.JSONField(default=list, blank=True)
    esito = models.CharField(max_length=12, choices=ESITI, default=IN_ATTESA, db_index=True)
    utente = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_proposte",
    )
    deciso_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ai_proposte_decise",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    deciso_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["modulo", "azione", "esito"])]
        verbose_name = "proposta AI"
        verbose_name_plural = "proposte AI"

    def __str__(self) -> str:
        return f"{self.modulo}.{self.azione} {self.oggetto_ref} [{self.esito}]"


class AiKnowledgeEntry(models.Model):
    question = models.CharField(max_length=500)
    answer = models.TextField()
    source_label = models.CharField(max_length=120, blank=True, default="FAQ Portale")
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_knowledge_entries_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_knowledge_entries_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        verbose_name = "conoscenza AI"
        verbose_name_plural = "conoscenze AI"

    def __str__(self) -> str:
        return self.question[:80]
