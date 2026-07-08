"""Task django-q del modulo monitoring."""
from __future__ import annotations

import logging

from monitoring import health

logger = logging.getLogger(__name__)


def run_ai_readiness_alert(**kwargs) -> dict:
    """Entry point schedulato: readiness AI (+ servizi) con alert email su degrado.

    Fail-safe per design (i singoli check catturano le eccezioni); l'invio mail è
    rate-limited e solo-al-cambio-stato dentro ``health.run_ai_readiness_alert``.
    """
    include_services = bool(kwargs.get("include_services", True))
    return health.run_ai_readiness_alert(include_services=include_services)


def run_system_digest(**kwargs) -> dict:
    """Digest giornaliero 'stato portale' via email agli admin del monitoring.

    Heartbeat: per default invia sempre (anche 'tutto ok', conferma che il
    monitoraggio è vivo); con ``MONITORING_DIGEST_ALWAYS=False`` invia solo se c'è
    qualcosa da segnalare. NON è rate-limited come gli alert (è una cadenza fissa).
    Fail-safe: non solleva mai.
    """
    from django.conf import settings

    from monitoring.digest import build_system_digest, render_system_digest

    result: dict = {"sent": False}
    try:
        digest = build_system_digest()
        result["all_green"] = digest["all_green"]
        always = bool(getattr(settings, "MONITORING_DIGEST_ALWAYS", True))
        if not (always or not digest["all_green"]):
            return result
        from core.email_utils import send_hub_mail

        from monitoring.digest import render_system_digest_html
        from monitoring.services import _admin_recipients

        recipients = _admin_recipients()
        if not recipients:
            return result
        subject, body = render_system_digest(digest)
        from_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", "")
            or getattr(settings, "SERVER_EMAIL", "")
            or "monitoring@localhost"
        )
        send_hub_mail(
            subject, body, recipients,
            email_type="Monitoraggio", section_label="Stato sistema",
            badge=("Tutto ok" if digest["all_green"] else "Attenzioni"),
            body_html_fragment=render_system_digest_html(digest),
            from_email=from_email, fail_silently=True,
        )
        result["sent"] = True
    except Exception:
        logger.exception("run_system_digest: errore inatteso")
    return result
