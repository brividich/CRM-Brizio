"""Quali asset vede una persona secondo l'ambito del suo ruolo («Propri», «Propri e del team», «Tutti»).

Con il sistema dei ruoli spento non filtra niente (valgono le regole storiche).
Acceso, un asset è visibile se è assegnato a una persona ammessa (lei o il suo
team) oppure se è una macchina di produzione senza persona assegnata del reparto
di un caporeparto ammesso: è la stessa regola di ``responsabile_asset``, così il
CAR vede le macchine del suo reparto e i beni assegnati a lui.
"""
from __future__ import annotations

import functools
import logging

from django.db.models import Q

from core.permessi import puo_fare, sistema_ruoli_attivo, utenti_visibili
from core.permessi.negato import risposta_negata

from ..models import Asset
from . import responsabile_asset

logger = logging.getLogger(__name__)

MODULO = "assets"
MESSAGGIO_NEGATO = (
    "Questo asset non rientra fra quelli che il tuo ruolo ti consente di vedere: "
    "vedi i beni assegnati a te (o al tuo team) e le macchine dei reparti che guidi."
)


def reparti_guidati(utenti) -> list[str]:
    """Nomi (normalizzati) di aree e reparti il cui capo è fra gli ``utenti.id`` dati."""
    utenti = {int(u) for u in utenti or ()}
    if not utenti:
        return []
    capi = responsabile_asset.capi_per_reparto()
    if not capi:
        return []
    try:
        from core.legacy_models import AnagraficaDipendente

        utente_di = dict(
            AnagraficaDipendente.objects.filter(id__in={pid for pid, _nome in capi.values()})
            .values_list("id", "utente_id")
        )
    except Exception:
        logger.debug("Utenti dei caporeparto non risolti", exc_info=True)
        return []
    return sorted(chiave for chiave, (pid, _nome) in capi.items() if utente_di.get(pid) in utenti)


def filtro(request) -> Q | None:
    """Q degli asset visibili, ``None`` = tutti."""
    if not sistema_ruoli_attivo():
        return None
    ammessi = utenti_visibili(request, MODULO, "vedere")
    if ammessi is None:
        return None
    if not ammessi:
        return Q(pk__in=[])
    q = Q(assigned_legacy_user_id__in=sorted(ammessi))
    reparti = reparti_guidati(ammessi)
    if reparti:
        senza_persona = Q(assigned_legacy_user_id__isnull=True) & (
            Q(assignment_to="") | Q(assignment_to__isnull=True)
            | Q(assignment_to__startswith=responsabile_asset.PREFISSO_REPARTO)
        )
        del_reparto = Q()
        for nome in reparti:
            del_reparto |= Q(reparto__iexact=nome) | (Q(reparto="") & Q(assignment_reparto__iexact=nome))
        q |= Q(asset_type__in=responsabile_asset.TIPI_PRODUZIONE) & senza_persona & del_reparto
    return q


def filtra(request, queryset):
    """Il queryset di asset ristretto a quelli visibili."""
    q = filtro(request)
    return queryset if q is None else queryset.filter(q)


def ids_visibili(request) -> set[int] | None:
    """Id degli asset visibili, ``None`` = tutti (per filtrare righe che puntano a un asset)."""
    q = filtro(request)
    if q is None:
        return None
    return set(Asset.objects.filter(q).values_list("id", flat=True))


def puo_vedere(request, asset) -> bool:
    if asset is None or not sistema_ruoli_attivo():
        return True
    return puo_fare(request, MODULO, "vedere", asset)


def nega(request):
    return risposta_negata(request, MESSAGGIO_NEGATO, pagina="Asset")


def richiede_asset_visibile(kwarg: str):
    """Decoratore: 403 se l'asset nel parametro ``kwarg`` dell'URL non è visibile alla persona."""

    def decora(view):
        @functools.wraps(view)
        def protetta(request, *args, **kwargs):
            asset_id = kwargs.get(kwarg)
            if asset_id and sistema_ruoli_attivo():
                asset = (
                    Asset.objects.filter(pk=asset_id)
                    .only("id", "asset_type", "reparto", "assigned_legacy_user_id",
                          "assignment_to", "assignment_reparto")
                    .first()
                )
                if asset is not None and not puo_vedere(request, asset):
                    return nega(request)
            return view(request, *args, **kwargs)

        protetta.asset_visibile_kwarg = kwarg
        return protetta

    return decora
