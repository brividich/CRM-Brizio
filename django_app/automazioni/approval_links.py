"""Link di approvazione personali (uno per destinatario).

Il link inviato via email e' la credenziale: identifica la richiesta E il
destinatario, quindi la decisione viene attribuita a ``recipient_email`` senza
login e senza fidarsi di header HTTP. A DB si salva solo l'hash del segreto.

Flusso:
  - ``create_link(approval, email)`` -> segreto in chiaro (solo per l'URL della mail)
  - GET  /approval-actions/r/<segreto>/<approva|rifiuta>/ -> pagina di conferma, nessun effetto
  - POST stessa URL -> ``decide_with_link`` consuma il link e decide
"""
from __future__ import annotations

import hashlib
import secrets

from django.conf import settings
from django.db import transaction
from django.utils import timezone

DECISION_SLUGS = {"approva": "approved", "rifiuta": "rejected"}


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(str(raw_token or "").encode("utf-8")).hexdigest()


def create_link(approval, recipient_email: str) -> str:
    from .models import AutomationApprovalLink

    raw = secrets.token_urlsafe(32)
    AutomationApprovalLink.objects.create(
        approval=approval,
        recipient_email=str(recipient_email or "").strip().lower(),
        token_hash=hash_token(raw),
    )
    return raw


def build_link_urls(raw_token: str) -> tuple[str, str]:
    site_url = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    base = f"{site_url}/approval-actions/r/{raw_token}"
    return f"{base}/approva/", f"{base}/rifiuta/"


def get_link(raw_token: str):
    """Link valido per il segreto, con la richiesta collegata; None se inesistente."""
    from .models import AutomationApprovalLink

    raw = str(raw_token or "").strip()
    if not raw or len(raw) > 128:
        return None
    return (
        AutomationApprovalLink.objects.select_related("approval", "approval__run_log__rule")
        .filter(token_hash=hash_token(raw))
        .first()
    )


def recover_stuck_branches() -> None:
    """Entry point django-q (schedule ``approval_branch_recovery``)."""
    from django.core.management import call_command

    call_command("recover_approval_branches")


def decide_with_link(raw_token: str, decision: str) -> dict:
    """Consuma il link (monouso, atomico) e processa la decisione come il suo destinatario."""
    from .models import AutomationApproval, AutomationApprovalLink
    from .services import process_approval_decision

    if decision not in ("approved", "rejected"):
        return {"ok": False, "code": "invalid_decision", "message": "Azione non valida."}

    link = get_link(raw_token)
    if link is None:
        return {"ok": False, "code": "not_found", "message": "Link non valido."}
    approval = link.approval
    if approval.status != AutomationApproval.Status.PENDING:
        return {"ok": False, "code": "already_decided", "message": "La richiesta e' gia' stata decisa.", "link": link}
    if approval.is_expired():
        return {"ok": False, "code": "expired", "message": "Il link di approvazione e' scaduto.", "link": link}

    with transaction.atomic():
        claimed = AutomationApprovalLink.objects.filter(pk=link.pk, used_at__isnull=True).update(
            used_at=timezone.now(), used_decision=decision
        )
    if not claimed:
        return {"ok": False, "code": "already_used", "message": "Questo link e' gia' stato usato.", "link": link}

    result = process_approval_decision(str(approval.token), decision, decided_by_email=link.recipient_email)
    result = dict(result or {})
    result.setdefault("code", "ok" if result.get("ok") else "failed")
    result["link"] = link
    return result
