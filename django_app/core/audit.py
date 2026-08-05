"""Helper per il logging di azioni rilevanti nel portale (audit trail)."""
from __future__ import annotations

import logging

from django.conf import settings

from core.impersonation import display_name_for_user

logger = logging.getLogger(__name__)


def _riferimento_oggetto(oggetto, oggetto_tipo: str, oggetto_id: str) -> tuple[str, str]:
    """Normalizza il riferimento al record: da istanza, o esplicito.

    Passare l'istanza (``oggetto=ticket``) evita di scrivere a mano l'etichetta e
    di sbagliarla; i due parametri espliciti restano per le tabelle **legacy**,
    che non hanno un modello Django da cui dedurla.
    """
    if oggetto is not None:
        meta = getattr(oggetto, "_meta", None)
        etichetta = getattr(meta, "label_lower", "") if meta is not None else ""
        return (etichetta or oggetto_tipo)[:100], str(getattr(oggetto, "pk", "") or oggetto_id)[:64]
    return (oggetto_tipo or "")[:100], str(oggetto_id or "")[:64]


def log_action(
    request,
    azione: str,
    modulo: str,
    dettaglio: dict | str | None = None,
    *,
    oggetto=None,
    oggetto_tipo: str = "",
    oggetto_id: str = "",
) -> None:
    """Registra un'azione nell'AuditLog Django.

    Chiamata fire-and-forget: eventuali errori DB sono loggati ma non propagati.

    ``dettaglio`` è tollerante al tipo: un ``dict`` viene usato così com'è, una
    ``str`` viene incapsulata in ``{"dettaglio": ...}``, ``None``/vuoto dà ``{}``.
    Molte call-site storiche passano una stringa: senza questo wrap ``dict("...")``
    solleverebbe ``ValueError`` e l'audit andava perso silenziosamente.

    ``oggetto`` (o la coppia ``oggetto_tipo``/``oggetto_id`` per il legacy) aggancia
    la voce al record toccato, ed è ciò che rende possibile lo storico mostrato
    sulla scheda — vedi :func:`storico_oggetto`. È **opzionale**: le chiamate
    storiche che non lo passano continuano a funzionare identiche, semplicemente
    restano fuori dagli storici per record.
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
        if isinstance(dettaglio, str):
            payload = {"dettaglio": dettaglio} if dettaglio else {}
        elif dettaglio:
            payload = dict(dettaglio)
        else:
            payload = {}
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
        tipo, identificativo = _riferimento_oggetto(oggetto, oggetto_tipo, oggetto_id)
        AuditLog.objects.create(
            legacy_user_id=actor_legacy_user.id if actor_legacy_user else None,
            utente_display=actor_display,
            azione=azione,
            modulo=modulo,
            dettaglio=payload,
            ip_address=_get_client_ip(request),
            oggetto_tipo=tipo,
            oggetto_id=identificativo,
        )
    except Exception:
        logger.exception("audit log fallito: azione=%s modulo=%s", azione, modulo)


def storico_oggetto(oggetto=None, *, oggetto_tipo: str = "", oggetto_id: str = "", limit: int = 50):
    """Le voci di audit di un singolo record, dalla più recente.

    Restituisce sempre un queryset (vuoto se il riferimento non è determinabile),
    così il chiamante non deve difendersi dal ``None``.
    """
    from core.models import AuditLog

    tipo, identificativo = _riferimento_oggetto(oggetto, oggetto_tipo, oggetto_id)
    if not tipo or not identificativo:
        return AuditLog.objects.none()
    return AuditLog.objects.filter(
        oggetto_tipo=tipo, oggetto_id=identificativo
    ).order_by("-created_at")[:limit]


def _get_client_ip(request) -> str | None:
    remote_addr = request.META.get("REMOTE_ADDR")
    trusted_proxies: set[str] = getattr(settings, "TRUSTED_PROXY_IPS", set())
    if remote_addr in trusted_proxies:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return remote_addr
