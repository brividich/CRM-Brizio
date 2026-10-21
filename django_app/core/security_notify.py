"""Mail all'utente per gli eventi di sicurezza sul suo account (audit 09/10, Fase 3).

Nuovo autenticatore, 2FA modificato da un amministratore, impersonazione, cambio
password: se non è stato l'utente (o non era previsto) se ne accorge subito.
Best effort: un errore SMTP non blocca mai l'operazione che ha generato l'evento.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Interruttore admin da «Gestione notifiche»: acceso salvo "0" esplicito.
AVVISO_IMPERSONAZIONE_KEY = "sicurezza_avviso_impersonazione"


def avviso_impersonazione_attivo() -> bool:
    from core.models import SiteConfig

    return (SiteConfig.get(AVVISO_IMPERSONAZIONE_KEY, "1") or "1").strip() != "0"


def set_avviso_impersonazione(attivo: bool) -> None:
    from core.models import SiteConfig

    SiteConfig.set(
        AVVISO_IMPERSONAZIONE_KEY,
        "1" if attivo else "0",
        "Mail all'utente quando un amministratore inizia a impersonarlo",
    )


def notify_security_event(user, title: str, message: str) -> bool:
    """Invia la mail di sicurezza a ``user.email``. Ritorna True se spedita."""
    recipient = (getattr(user, "email", "") or "").strip()
    if not recipient:
        return False
    portal_name = getattr(settings, "INSTANCE_NAME", "NOVICROM HUB")
    body = (
        f"{message}\n\n"
        "Se non riconosci questa operazione avvisa subito l'amministratore del portale."
    )
    try:
        from core.email_utils import send_hub_mail

        send_hub_mail(
            f"[{portal_name}] {title}",
            body,
            [recipient],
            title=title,
            email_type="Accesso",
            footer_note="Messaggio automatico di sicurezza.",
            fail_silently=True,
        )
        return True
    except Exception:
        logger.warning("Notifica di sicurezza non inviata (%s) a %s", title, recipient, exc_info=True)
        return False
