"""Pulsanti «Accetta» e «Rifiuta» nella mail «Richiesta DPI da approvare».

Ogni destinatario riceve la sua mail con due link personali sotto ``/approval-actions/dpi/``
(prefisso gia' esente da login e pubblicato via Entra Application Proxy). Il link e' firmato
(``django.core.signing``): contiene la richiesta e l'indirizzo a cui e' stato mandato, senza
tabelle nuove. Aprirlo NON decide: mostra la richiesta e un pulsante; decide solo il POST.

Vale finche' la richiesta e' «Inviata», per ``GIORNI_VALIDITA`` giorni, e solo se
l'indirizzo e' ancora fra chi approva quella richiesta. Decide chi ha ricevuto la mail:
nello storico resta il suo nome (o l'indirizzo, se non ha un utente nel portale).
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core import signing
from django.urls import reverse

from . import flusso

logger = logging.getLogger(__name__)

SALE = "dpi.approva-da-mail.v1"
GIORNI_VALIDITA = 30
DECISIONI = ("approva", "rifiuta")


def _norm(email: str) -> str:
    return str(email or "").strip().lower()


def crea_token(richiesta, email: str) -> str:
    return signing.dumps({"r": int(richiesta.pk), "e": _norm(email)}, salt=SALE, compress=True)


def link(richiesta, email: str) -> tuple[str, str] | None:
    """(url «approva», url «rifiuta») per ``email``; None senza ``SITE_URL`` (link non costruibile)."""
    base = str(getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if not base or not _norm(email):
        return None
    token = crea_token(richiesta, email)
    return tuple(base + reverse("dpi_pubblico:approva_da_mail", args=[token, d]) for d in DECISIONI)


def leggi(token: str):
    """(richiesta, email) del link; None se la firma non e' valida, e' scaduta o la richiesta non c'e' piu'."""
    from .models import RichiestaDPI

    raw = str(token or "").strip()
    if not raw or len(raw) > 512:
        return None
    try:
        dati = signing.loads(raw, salt=SALE, max_age=GIORNI_VALIDITA * 86400)
        richiesta = RichiestaDPI.objects.select_related(
            "categoria", "tipo_dpi", "modello_dpi", "taglia_dpi"
        ).filter(pk=int(dati["r"])).first()
        email = _norm(dati["e"])
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None
    return (richiesta, email) if richiesta and email else None


def puo_decidere(richiesta, email: str) -> bool:
    """Ancora «Inviata» e l'indirizzo e' tuttora fra chi approva (mai la propria richiesta)."""
    from .models import StatoRichiesta

    email = _norm(email)
    if richiesta.stato != StatoRichiesta.INVIATA or not email:
        return False
    try:
        if richiesta.richiedente_legacy_id and _norm(flusso._email_persona(richiesta.richiedente_legacy_id)) == email:
            return False
        return email in {_norm(e) for e in flusso._destinatari_approvatori(richiesta)}
    except Exception:
        logger.warning("DPI: destinatari dell'approvazione non leggibili (%s)", richiesta.numero, exc_info=True)
        return False


def utente(email: str):
    """Utente attivo del portale con quell'indirizzo (None se non c'e' o non e' univoco)."""
    from django.contrib.auth import get_user_model

    trovati = list(get_user_model().objects.filter(email__iexact=_norm(email), is_active=True)[:2])
    return trovati[0] if len(trovati) == 1 else None


def nome(email: str) -> str:
    u = utente(email)
    return ((u.get_full_name() or u.get_username()) if u else "") or _norm(email)
