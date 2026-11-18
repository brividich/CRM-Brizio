"""Pulsante «N da approvare» della barra in alto: tutto ciò che aspetta una decisione dell'utente.

Prima contava solo le assenze e portava sempre alla pagina Assenze. Ora somma le stesse fonti
di «Le mie attività»: assenze della squadra, DPI da approvare, approvazioni dei flussi (quelle
delle assenze sono già nel conteggio assenze), richieste di visita, spostamenti date del KICK-OFF,
modifiche SGI, segnalazioni di modifica e rilevazioni di sicurezza. Con una fonte sola il
pulsante apre quella pagina; con più fonti apre «Le mie attività».
Il conto resta in cache un minuto per persona: la barra lo chiede a ogni pagina.
"""
from __future__ import annotations

import logging

from django.core.cache import cache
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

CACHE_SECONDI = 60


def _url(nome: str, *args) -> str:
    try:
        return reverse(nome, args=args)
    except NoReverseMatch:
        return ""


def _approvazioni_flussi(request) -> int:
    """Richieste «Approva/Rifiuta» dei flussi per l'utente, escluse quelle delle assenze."""
    from django.db.models import Q
    from django.utils import timezone

    from automazioni.approval_security import normalize_actor_email
    from automazioni.models import AutomationApproval

    me = normalize_actor_email(getattr(request.user, "email", "") or getattr(request.user, "username", ""))
    if not me:
        return 0
    qs = (AutomationApproval.objects.filter(status=AutomationApproval.Status.PENDING)
          .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
          .exclude(action__rule__source_code="assenze")
          .only("id", "approver_emails")[:500])
    return sum(1 for a in qs if me in {normalize_actor_email(e) for e in (a.approver_emails or [])})


def _fonti(request, legacy_user) -> list[dict]:
    from dashboard import mie_attivita_fonti as fonti

    out: list[dict] = []

    def aggiungi(etichetta: str, singolare: str, calcolo, url: str) -> None:
        try:
            n = int(calcolo() or 0)
        except Exception:
            logger.warning("Da approvare: fonte «%s» non calcolabile", etichetta, exc_info=True)
            return
        if n:
            out.append({"label": singolare if n == 1 else etichetta, "n": n, "url": url})

    if legacy_user is not None:
        from core.context_processors import _count_car_pending

        aggiungi("assenze", "assenza", lambda: _count_car_pending(int(legacy_user.id), legacy_user=legacy_user),
                 _url("assenze_car_dashboard"))

    def _dpi():
        from dpi.mie_attivita import da_approvare

        return len(da_approvare(request))

    aggiungi("DPI", "DPI", _dpi, _url("dpi:gestione_list") + "?stato=INVIATA")
    aggiungi("approvazioni", "approvazione", lambda: _approvazioni_flussi(request), _url("mie_attivita"))
    aggiungi("visite", "visita", lambda: len(fonti._richieste_visita(request)), _url("reception:annuncia") + "#le-tue-visite")
    aggiungi("spostamenti date", "spostamento date", lambda: len(fonti._spostamenti(request)), _url("tasks:mie_azioni"))
    aggiungi("modifiche SGI", "modifica SGI", lambda: len(fonti._modifiche_sgi(request)),
             _url("procedure_refresh:modifiche") + "?mie=1")
    aggiungi("segnalazioni di modifica", "segnalazione di modifica", lambda: len(fonti._segnalazioni_modifica(request)),
             _url("procedure_refresh:change_request_list"))
    aggiungi("rilevazioni di sicurezza", "rilevazione di sicurezza", lambda: len(fonti._incidenti(request)),
             _url("mie_attivita"))
    return out


def riepilogo(request, legacy_user=None) -> dict:
    """``{"totale", "url", "titolo", "fonti"}`` per il pulsante; totale 0 se non c'è niente."""
    vuoto = {"totale": 0, "url": "", "titolo": "", "fonti": []}
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return vuoto
    chiave = f"nav_da_approvare:{user.pk}:{getattr(legacy_user, 'id', '')}"
    try:
        dati = cache.get(chiave)
    except Exception:
        dati = None
    if dati is None:
        fonti = _fonti(request, legacy_user)
        totale = sum(f["n"] for f in fonti)
        url = fonti[0]["url"] if len(fonti) == 1 else _url("mie_attivita")
        titolo = "Da decidere: " + ", ".join(f"{f['n']} {f['label']}" for f in fonti) if fonti else ""
        dati = {"totale": totale, "url": url or _url("mie_attivita"), "titolo": titolo, "fonti": fonti}
        try:
            cache.set(chiave, dati, CACHE_SECONDI)
        except Exception:
            pass
    return dati

