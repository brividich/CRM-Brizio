"""Notifiche in-app dello scadenzario: chi riceve o perde una scadenza lo viene a sapere."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def avvisa_utente(user, tipo: str, testo: str, url: str = "") -> None:
    """Non blocca mai l'azione: senza account collegato non c'è nessuno da avvisare."""
    if user is None:
        return
    try:
        from core.legacy_utils import get_legacy_user
        from core.notifiche import invia_notifica

        legacy = get_legacy_user(user)
        if legacy:
            invia_notifica(int(legacy.id), tipo, testo, url)
    except Exception:
        logger.exception("scadenzario: notifica non inviata")
