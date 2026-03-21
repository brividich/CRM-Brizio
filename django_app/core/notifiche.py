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
