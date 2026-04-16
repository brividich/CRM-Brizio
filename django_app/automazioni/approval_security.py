"""
automazioni/approval_security.py — Validazione attore per le approvazioni.

Responsabilità unica: verificare che un determinato attore (email) sia
autorizzato a processare un token di approvazione, prima che la business
logic venga eseguita.

Usato da:
  - automazioni/mailbox_graph.py  (canale email → mitt. vs approver_emails)
  - automazioni/views.py          (canale web → identità Entra vs approver_emails)

Contratto:
  validate_approval_actor(token_str, actor_email) -> ApprovalActorValidation
    .allowed    True se la validazione passa
    .error_code stringa machine-readable se fallisce (vedi ErrorCode)
    .error_message messaggio human-readable

Comportamento: fail-closed. Qualsiasi errore tecnico restituisce
  error_code = ErrorCode.TECHNICAL_ERROR invece di concedere l'accesso.
"""
from __future__ import annotations

import logging
import uuid as _uuid_module
from dataclasses import dataclass, field
from email.utils import parseaddr

logger = logging.getLogger(__name__)


# ── Codici di errore machine-readable ────────────────────────────────────────

class ErrorCode:
    NO_IDENTITY     = "no_identity"      # actor_email vuota/mancante
    INVALID_TOKEN   = "invalid_token"    # UUID malformato
    NOT_FOUND       = "not_found"        # token non esiste nel DB
    ALREADY_DECIDED = "already_decided"  # approvazione già processata
    EXPIRED         = "expired"          # approvazione scaduta
    NO_APPROVERS    = "no_approvers"     # approver_emails vuota (config issue)
    UNAUTHORIZED    = "unauthorized"     # actor non nella lista approvatori
    TECHNICAL_ERROR = "technical_error"  # errore DB o di sistema imprevisto


# ── Risultato validazione ─────────────────────────────────────────────────────

@dataclass
class ApprovalActorValidation:
    allowed: bool
    error_code: str = ""
    error_message: str = ""
    # Dati accessori utili per il logging (non richiesti per la decisione)
    approval_id: int | None = None
    approval_status: str = ""

    @classmethod
    def ok(cls, approval_id: int | None = None) -> "ApprovalActorValidation":
        return cls(allowed=True, approval_id=approval_id)

    @classmethod
    def deny(cls, code: str, message: str, approval_id: int | None = None, approval_status: str = "") -> "ApprovalActorValidation":
        return cls(
            allowed=False,
            error_code=code,
            error_message=message,
            approval_id=approval_id,
            approval_status=approval_status,
        )


# ── Helper normalizzazione email ──────────────────────────────────────────────

def normalize_actor_email(value: object) -> str:
    """Normalizza un indirizzo email: strip, lowercase, decodifica RFC 5322."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    _display_name, parsed = parseaddr(raw)
    return str(parsed or raw).strip().lower()


# ── Funzione pubblica principale ──────────────────────────────────────────────

def validate_approval_actor(token_str: str, actor_email: str) -> ApprovalActorValidation:
    """
    Verifica che `actor_email` sia autorizzata a decidere il token di approvazione.

    Controlla (in ordine):
      1. actor_email non vuota                       → NO_IDENTITY
      2. token_str è un UUID valido                  → INVALID_TOKEN
      3. AutomationApproval esiste                   → NOT_FOUND
      4. approval.status == PENDING                  → ALREADY_DECIDED
      5. approval non scaduta                        → EXPIRED
      6. approver_emails non vuota                   → NO_APPROVERS
      7. actor_email in approver_emails              → UNAUTHORIZED

    Ritorna ApprovalActorValidation.ok() se tutte le verifiche passano.
    Fail-closed: errori tecnici restituiscono TECHNICAL_ERROR (denied).
    """
    normalized_actor = normalize_actor_email(actor_email)
    if not normalized_actor:
        return ApprovalActorValidation.deny(
            ErrorCode.NO_IDENTITY,
            "Identità approvatore non disponibile.",
        )

    try:
        token_uuid = _uuid_module.UUID(str(token_str))
    except (ValueError, AttributeError):
        return ApprovalActorValidation.deny(
            ErrorCode.INVALID_TOKEN,
            f"Token non valido: {token_str!r}",
        )

    try:
        from .models import AutomationApproval

        try:
            approval = AutomationApproval.objects.get(token=token_uuid)
        except AutomationApproval.DoesNotExist:
            return ApprovalActorValidation.deny(
                ErrorCode.NOT_FOUND,
                "Richiesta di approvazione non trovata o link non valido.",
            )

        if approval.status != AutomationApproval.Status.PENDING:
            return ApprovalActorValidation.deny(
                ErrorCode.ALREADY_DECIDED,
                f"La richiesta è già in stato '{approval.get_status_display()}'.",
                approval_id=approval.pk,
                approval_status=approval.status,
            )

        if approval.is_expired():
            return ApprovalActorValidation.deny(
                ErrorCode.EXPIRED,
                "Il link di approvazione è scaduto.",
                approval_id=approval.pk,
                approval_status=approval.status,
            )

        approver_emails = approval.approver_emails or []
        normalized_approvers = [
            normalize_actor_email(e) for e in approver_emails
            if normalize_actor_email(e)
        ]
        if not normalized_approvers:
            return ApprovalActorValidation.deny(
                ErrorCode.NO_APPROVERS,
                "Nessun approvatore configurato per questa richiesta.",
                approval_id=approval.pk,
            )

        if normalized_actor not in normalized_approvers:
            return ApprovalActorValidation.deny(
                ErrorCode.UNAUTHORIZED,
                f"L'utente '{normalized_actor}' non è nella lista degli approvatori.",
                approval_id=approval.pk,
            )

        return ApprovalActorValidation.ok(approval_id=approval.pk)

    except Exception as exc:
        logger.warning(
            "validate_approval_actor: errore tecnico token=%s actor=%s: %s",
            token_str,
            normalized_actor,
            exc,
        )
        return ApprovalActorValidation.deny(
            ErrorCode.TECHNICAL_ERROR,
            "Validazione non disponibile per un errore tecnico.",
        )
