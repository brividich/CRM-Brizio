"""Registro degli invii email del modulo anomalie (con reinvio fedele).

Ogni mail prodotta dal modulo (mail-action, conferma aggiornamenti, resoconto
escalation) viene registrata qui *insieme al corpo gia' renderizzato*: il
pulsante «Reinvia» della pagina di configurazione rispedisce esattamente lo
stesso messaggio, senza ricostruirlo da dati che nel frattempo sono cambiati.

Il log e' una traccia di audit: non contiene allegati e non va esposto fuori
dalla pagina di configurazione del modulo.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class AnomalieEmailLog(models.Model):
    """Una riga per ogni tentativo di invio email del modulo anomalie."""

    class Kind(models.TextChoices):
        MAIL_ACTION = "mail_action", "Mail-action (link azione)"
        CONFERMA_AGGIORNAMENTI = "conferma_aggiornamenti", "Conferma aggiornamenti"
        ESCALATION = "escalation_resoconto", "Resoconto escalation"
        RICORRENZA_PN = "ricorrenza_pn", "Difetto ricorrente per P/N"
        DIGEST = "digest_settimanale", "Digest settimanale KPI"
        OP_COMPLETATO = "op_completato", "OP completato"
        ALERT_ADMIN = "alert_admin", "Alert amministratori"
        ALTRO = "altro", "Altro"

    class Status(models.TextChoices):
        SENT = "sent", "Inviata"
        FAILED = "failed", "Fallita"

    kind = models.CharField(
        max_length=32, choices=Kind.choices, default=Kind.ALTRO, db_index=True
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SENT, db_index=True
    )
    subject = models.CharField(max_length=500, blank=True, default="")
    from_email = models.CharField(max_length=254, blank=True, default="")
    to_emails = models.JSONField(default=list, blank=True)
    cc_emails = models.JSONField(default=list, blank=True)
    body_text = models.TextField(blank=True, default="")
    body_html = models.TextField(blank=True, default="")
    # Contesto utile per ritrovare la mail: OP di riferimento e note libere.
    op_id = models.CharField(max_length=255, blank=True, default="", db_index=True)
    context = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="anomalie_email_logs",
    )
    # Reinvio: punta alla riga originale; la riga originale conta i reinvii.
    resend_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resends",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Log email anomalie"
        verbose_name_plural = "Log email anomalie"
        indexes = [
            models.Index(fields=["-created_at"], name="anom_maillog_created_idx"),
        ]

    def __str__(self) -> str:
        return f"AnomalieEmailLog<{self.kind}:{self.status}:{self.subject[:40]}>"

    @property
    def to_display(self) -> str:
        return ", ".join(str(x) for x in (self.to_emails or []) if x)

    @property
    def cc_display(self) -> str:
        return ", ".join(str(x) for x in (self.cc_emails or []) if x)

    @property
    def is_resend(self) -> bool:
        return self.resend_of_id is not None
