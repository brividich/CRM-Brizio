"""Helper per il logging di azioni rilevanti nel portale (audit trail)."""
from __future__ import annotations

import logging

from django.conf import settings

from core.impersonation import display_name_for_user

logger = logging.getLogger(__name__)


def log_action(request, azione: str, modulo: str, dettaglio: dict | None = None) -> None:
    """Registra un'azione nell'AuditLog Django.

    Chiamata fire-and-forget: eventuali errori DB sono loggati ma non propagati.
    """
    try:
        from core.models import AuditLog

        impersonator_legacy_user = getattr(request, "impersonator_legacy_user", None)
        impersonator_user = getattr(request, "impersonator_user", None)
        effective_legacy_user = getattr(request, "legacy_user", None)
        actor_legacy_user = impersonator_legacy_user or effective_legacy_user
        actor_display = display_name_for_user(
            django_user=impersonator_user or getattr(request, "user", None),
            legacy_user=actor_legacy_user,
        )
        payload = dict(dettaglio or {})
        if getattr(request, "impersonation_active", False):
            payload.setdefault(
                "_impersonation",
                {
                    "impersonated_legacy_user_id": getattr(getattr(request, "impersonated_legacy_user", None), "id", None),
                    "impersonated_display": display_name_for_user(
                        django_user=getattr(request, "impersonated_user", None) or getattr(request, "user", None),
                        legacy_user=getattr(request, "impersonated_legacy_user", None) or effective_legacy_user,
                    ),
                },
            )
        AuditLog.objects.create(
            legacy_user_id=actor_legacy_user.id if actor_legacy_user else None,
            utente_display=actor_display,
            azione=azione,
            modulo=modulo,
            dettaglio=payload,
            ip_address=_get_client_ip(request),
        )
    except Exception:
        logger.exception("audit log fallito: azione=%s modulo=%s", azione, modulo)


def _get_client_ip(request) -> str | None:
    remote_addr = request.META.get("REMOTE_ADDR")
    trusted_proxies: set[str] = getattr(settings, "TRUSTED_PROXY_IPS", set())
    if remote_addr in trusted_proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return remote_addr
