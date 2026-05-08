"""
Helper pubblico per l'invio di notifiche in-app.

Utilizzo da qualsiasi modulo:

    from core.notifiche import invia_notifica
    invia_notifica(
        legacy_user_id=richiesta.richiedente_legacy_id,
        tipo="dpi_approvata",
        messaggio="La tua richiesta DPI-2026-0001 è stata approvata.",
        url_azione="/dpi/42/",
    )

I tipi disponibili sono definiti in core.models.Notifica.TIPI.
Per tipi non ancora in lista usare "generico".
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def invia_notifica(
    legacy_user_id: int | None,
    tipo: str,
    messaggio: str,
    url_azione: str = "",
) -> None:
    """Crea una Notifica in-app per l'utente indicato.

    Fire-and-forget: gli errori vengono loggati ma non propagati.
    Se legacy_user_id è None o 0 non fa nulla.
    """
    if not legacy_user_id:
        return
    try:
        from core.models import Notifica
        Notifica.objects.create(
            legacy_user_id=int(legacy_user_id),
            tipo=tipo,
            messaggio=messaggio,
            url_azione=url_azione or "",
        )
    except Exception:
        logger.exception(
            "Errore creazione notifica tipo=%s per legacy_user_id=%s",
            tipo,
            legacy_user_id,
        )


def legacy_user_ids_for_email(email: str) -> list[int]:
    """Ritorna gli utenti legacy collegati a un indirizzo email."""
    email_norm = str(email or "").strip().lower()
    if not email_norm:
        return []
    ids: set[int] = set()
    try:
        from core.legacy_models import AnagraficaDipendente, UtenteLegacy

        ids.update(
            int(value)
            for value in UtenteLegacy.objects.filter(email__iexact=email_norm).values_list("id", flat=True)
            if value
        )
        ids.update(
            int(value)
            for value in AnagraficaDipendente.objects.filter(email_notifica__iexact=email_norm)
            .exclude(utente_id__isnull=True)
            .values_list("utente_id", flat=True)
            if value
        )
        ids.update(
            int(value)
            for value in AnagraficaDipendente.objects.filter(email__iexact=email_norm)
            .exclude(utente_id__isnull=True)
            .values_list("utente_id", flat=True)
            if value
        )
    except Exception:
        logger.exception("Errore risoluzione legacy_user_id per email=%s", email_norm)
    return sorted(ids)


def invia_notifica_email(email: str, tipo: str, messaggio: str, url_azione: str = "") -> int:
    """Crea una notifica per tutti gli utenti legacy risolti da email."""
    created = 0
    for legacy_user_id in legacy_user_ids_for_email(email):
        invia_notifica(legacy_user_id, tipo, messaggio, url_azione)
        created += 1
    return created
