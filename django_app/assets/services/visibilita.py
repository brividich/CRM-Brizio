"""Quali asset vede una persona secondo l'ambito del suo ruolo («Propri», «Propri e del team», «Tutti»).

Con il sistema dei ruoli spento non filtra niente (valgono le regole storiche).
Acceso, un asset è visibile se è assegnato a una persona ammessa (lei o il suo
team) oppure se è un asset non IT senza persona assegnata installato nel reparto
di un caporeparto ammesso: è la stessa regola di ``responsabile_asset``, così il
CAR vede le macchine del suo reparto e i beni assegnati a lui.

L'ambito si legge dal modulo della matrice che governa la pagina: Inventario
(``assets``), Manutenzione, Ordini di lavoro, Verifiche e scadenze (vedi
``assets/registro_permessi.py``). I record di manutenzione, gli OdL e le verifiche
seguono il loro asset: :func:`filtra_per_asset`.
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
MESSAGGI_NEGATO = {
    "assets_manutenzione": (
        "Questa manutenzione riguarda un asset che il tuo ruolo non ti consente di vedere: "
        "vedi le manutenzioni dei beni assegnati a te (o al tuo team) e dei reparti che guidi."
    ),
    "assets_odl": (
        "Questo ordine di lavoro riguarda un asset che il tuo ruolo non ti consente di vedere: "
        "vedi gli ordini dei beni assegnati a te (o al tuo team), dei reparti che guidi e quelli assegnati a te."
    ),
    "assets_verifiche": (
        "Questa verifica o scadenza riguarda un asset che il tuo ruolo non ti consente di vedere: "
        "vedi quelle dei beni assegnati a te (o al tuo team) e dei reparti che guidi."
    ),
}
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


def filtro(request, modulo: str = MODULO) -> Q | None:
    """Q degli asset visibili secondo l'ambito «vedere» di ``modulo``, ``None`` = tutti."""
    if not sistema_ruoli_attivo():
        return None
    ammessi = utenti_visibili(request, modulo, "vedere")
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
        q |= Q(asset_type__in=sorted(responsabile_asset.TIPI_REPARTO)) & senza_persona & del_reparto
    return q


def filtra(request, queryset, modulo: str = MODULO):
    """Il queryset di asset ristretto a quelli visibili."""
    q = filtro(request, modulo)
    return queryset if q is None else queryset.filter(q)


def filtra_per_asset(request, queryset, modulo: str, campo: str = "asset", *, anche=None):
    """Righe che puntano a un asset (``campo``) ristrette a quelle di asset visibili.

    ``anche``: Q in più sempre visibile (es. gli OdL assegnati alla persona).
    Su una relazione molti-a-molti si filtra per ``pk`` (niente ``distinct()``,
    che su SQL Server non convive con ordinamenti e annotazioni).
    """
    q = filtro(request, modulo)
    if q is None:
        return queryset
    condizione = Q(**{f"{campo}__in": Asset.objects.filter(q).values("id")})
    if anche is not None:
        condizione |= anche
    return queryset.filter(pk__in=queryset.model.objects.filter(condizione).values("pk"))


def odl_della_persona(request) -> Q:
    """Gli ordini di lavoro assegnati alla persona o eseguiti da lei: li vede sempre."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return Q(pk__in=[])
    return Q(assigned_to=user) | Q(executed_by=user)


def filtra_odl(request, queryset, campo: str = "asset"):
    """Ordini di lavoro visibili: del suo ambito sugli asset, più quelli assegnati alla persona."""
    from ..registro_permessi import MODULO_ODL

    return filtra_per_asset(request, queryset, MODULO_ODL, campo, anche=odl_della_persona(request))


def filtra_piani(request, queryset):
    """Piani di manutenzione che toccano almeno un asset visibile.

    Un piano su più reparti (es. «tutti i compressori») resta visibile a chi ha
    almeno una delle sue macchine; le scadenze dentro si filtrano asset per asset.
    """
    from ..registro_permessi import MODULO_MANUTENZIONE

    q = filtro(request, MODULO_MANUTENZIONE)
    if q is None:
        return queryset
    visibili = Asset.objects.filter(q)
    ids = visibili.values("id")
    condizione = (
        Q(occurrences__asset__in=ids)
        | Q(assignments__asset__in=ids)
        | Q(assignments__asset_group__assets__in=ids)
        | Q(assignments__asset_category__in=visibili.filter(asset_category__isnull=False).values("asset_category_id"))
    )
    return queryset.filter(pk__in=queryset.model.objects.filter(condizione).values("pk"))


def ids_visibili(request, modulo: str = MODULO) -> set[int] | None:
    """Id degli asset visibili, ``None`` = tutti (per filtrare righe che puntano a un asset)."""
    q = filtro(request, modulo)
    if q is None:
        return None
    return set(Asset.objects.filter(q).values_list("id", flat=True))


def ambito_ristretto(request, modulo: str = MODULO) -> bool:
    """La persona vede solo una parte degli asset (ambito «Propri» o «del team»)."""
    return filtro(request, modulo) is not None


def puo_vedere(request, asset, modulo: str = MODULO) -> bool:
    if asset is None or not sistema_ruoli_attivo():
        return True
    return puo_fare(request, modulo, "vedere", asset)


def nega(request, modulo: str = MODULO):
    return risposta_negata(request, MESSAGGI_NEGATO.get(modulo, MESSAGGIO_NEGATO), pagina="Asset")


def richiede_asset_visibile(kwarg: str, modulo: str = MODULO):
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
                if asset is not None and not puo_vedere(request, asset, modulo):
                    return nega(request, modulo)
            return view(request, *args, **kwargs)

        protetta.asset_visibile_kwarg = kwarg
        return protetta

    return decora


def richiede_record_visibile(kwarg: str, modulo: str, filtra_righe):
    """Decoratore: 403 se il record con id nel parametro ``kwarg`` non è visibile alla persona.

    ``filtra_righe(request, queryset)`` restringe il queryset del record a quelli
    visibili (``filtra_per_asset``, ``filtra_odl``, ``filtra_piani``...). Un id che
    non esiste passa: la vista risponde 404 come sempre.
    """
    modello, filtra_qs = filtra_righe

    def decora(view):
        @functools.wraps(view)
        def protetta(request, *args, **kwargs):
            pk = kwargs.get(kwarg)
            if pk and sistema_ruoli_attivo():
                righe = modello.objects.filter(pk=pk)
                if righe.exists() and not filtra_qs(request, righe).exists():
                    return nega(request, modulo)
            return view(request, *args, **kwargs)

        protetta.record_visibile_kwarg = kwarg
        return protetta

    return decora
