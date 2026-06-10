"""Modello per token monouso di azione anomalie via mail."""
from __future__ import annotations

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _default_token() -> str:
    return secrets.token_urlsafe(32)


class AnomaliaMailActionToken(models.Model):
    """Token sicuro monouso che abilita un'azione su anomalie via link email.

    Il flusso:
    1. Il sistema crea un token per un utente destinatario + lista anomalie + azione.
    2. L'email include il link /gestione-anomalie/mail-action/<token>/.
    3. Il click apre la pagina portale (richiede login); il token viene validato e
       marcato used_at alla conferma.
    """

    class Action(models.TextChoices):
        PRENDI_IN_CARICO = "prendi_in_carico", "Prendi in carico"
        APPROVA = "approva", "Approva"
        RESPINGI = "respingi", "Respingi"
        RICHIEDI_MODIFICA = "richiedi_modifica", "Richiedi modifica"
        CHIUDI = "chiudi", "Chiudi"
        VISUALIZZA = "visualizza", "Visualizza (sola lettura)"

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        default=_default_token,
    )
    # Destinatario: utente Django quando disponibile, oppure dati legacy
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anomalia_mail_action_tokens",
    )
    recipient_legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    recipient_email = models.EmailField(blank=True, default="")
    recipient_display = models.CharField(max_length=200, blank=True, default="")

    # Riferimento OP e anomalie
    op_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    op_nominativo = models.CharField(max_length=255, blank=True, default="")
    # Lista id anomalie legacy (tabella anomalie SQL)
    anomalie_ids = models.JSONField(default=list)
    # Snapshot anomalie al momento della creazione del token
    anomalie_snapshot = models.JSONField(default=list)

    action = models.CharField(
        max_length=32,
        choices=Action.choices,
        db_index=True,
    )
    # Payload opzionale per configurare l'azione (es. avanzamento predefinito)
    payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False, db_index=True)
    is_revoked = models.BooleanField(default=False, db_index=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anomalia_mail_action_tokens_created",
    )
    source_automation = models.CharField(max_length=200, blank=True, default="")

    # Dati tracciati al momento dell'uso
    ip_address_used = models.GenericIPAddressField(null=True, blank=True)
    user_agent_used = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Token azione anomalia via mail"
        verbose_name_plural = "Token azione anomalie via mail"
        indexes = [
            models.Index(fields=["is_used", "is_revoked", "expires_at"], name="anomalia_token_valid_idx"),
        ]

    def __str__(self) -> str:
        return f"AnomaliaMailActionToken<{self.action}:{self.op_id}:{self.token[:8]}…>"

    def is_valid(self) -> bool:
        """True se il token è ancora utilizzabile."""
        return not self.is_used and not self.is_revoked and timezone.now() <= self.expires_at

    def mark_used(self, *, ip_address: str | None = None, user_agent: str = "") -> None:
        self.is_used = True
        self.used_at = timezone.now()
        self.ip_address_used = ip_address
        self.user_agent_used = user_agent
        self.save(update_fields=["is_used", "used_at", "ip_address_used", "user_agent_used"])


class AnomaliaActionLog(models.Model):
    """Log di ogni azione su anomalia tracciata dal sistema mail-action o portale."""

    class Source(models.TextChoices):
        MAIL_ACTION = "mail_action", "Link da mail"
        PORTAL = "portal", "Portale"
        SYSTEM = "system", "Sistema / Automazione"

    # Identificativi dell'anomalia legacy
    anomalia_id = models.IntegerField(db_index=True)
    op_id = models.CharField(max_length=100, blank=True, default="", db_index=True)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    legacy_user_id = models.IntegerField(null=True, blank=True, db_index=True)
    user_display = models.CharField(max_length=200, blank=True, default="")

    action = models.CharField(max_length=32, db_index=True)
    previous_status = models.CharField(max_length=100, blank=True, default="")
    new_status = models.CharField(max_length=100, blank=True, default="")
    note = models.TextField(blank=True, default="")

    source = models.CharField(max_length=20, choices=Source.choices, default=Source.PORTAL, db_index=True)
    token = models.ForeignKey(
        AnomaliaMailActionToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_logs",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Log azione anomalia"
        verbose_name_plural = "Log azioni anomalie"
        indexes = [
            models.Index(fields=["anomalia_id", "created_at"], name="anomalia_log_id_date_idx"),
        ]

    def __str__(self) -> str:
        return f"AnomaliaActionLog<{self.anomalia_id}:{self.action}:{self.source}>"


class AnomaliaPendingNotification(models.Model):
    """Coda di debounce per la mail di conferma aggiornamenti dalla pagina web.

    Quando un'anomalia viene aggiornata in gestione (senza notifica immediata),
    si registra/aggiorna qui l'OP con il timestamp dell'ultima modifica. Un task
    periodico invia la mail di conferma per gli OP fermi da più di una soglia
    (es. 5 minuti) e marca `notified=True`. Il tasto "Salva e notifica" invia
    subito e marca notified, svuotando il pending.
    """

    op_id = models.CharField(max_length=100, unique=True, db_index=True)
    op_nominativo = models.CharField(max_length=255, blank=True, default="")
    last_modified_at = models.DateTimeField(db_index=True)
    last_modified_by = models.CharField(max_length=200, blank=True, default="")
    # Snapshot incrementale delle modifiche da includere nella mail (lista di dict)
    updates_snapshot = models.JSONField(default=list, blank=True)
    notified = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Notifica anomalie in attesa"
        verbose_name_plural = "Notifiche anomalie in attesa"
        indexes = [
            models.Index(fields=["notified", "last_modified_at"], name="anom_pending_notif_idx"),
        ]

    def __str__(self) -> str:
        return f"AnomaliaPendingNotification<{self.op_id}:notified={self.notified}>"
