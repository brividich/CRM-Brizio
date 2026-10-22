"""Schede laterali della pagina «Struttura organizzativa»: ruolo, mansione, reparto.

Ogni scheda raccoglie in un posto solo quello che oggi è sparso fra catalogo dei
ruoli, Mansionario, Aree e reparti, Ruoli e permessi: chi, cosa, dove, con quali
accessi. Sola lettura; le modifiche passano dai servizi esistenti.
"""
from __future__ import annotations

from collections import Counter

from django.db.models import Q
from django.utils import timezone

from ..models import (
    AreaAziendale,
    CompetenzaSkm,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Reparto,
    RuoloOperativo,
)
from .mansionario_struttura import TIPI_MANSIONE
from .struttura_vista import _nomi

MAX_ELENCO = 60


def _attivi_ruolo():
    oggi = timezone.localdate()
    return DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))


def _persone(ids) -> list[dict]:
    nomi = _nomi(list(ids))
    return sorted(({"id": i, "nome": nomi.get(i) or f"#{i}"} for i in nomi), key=lambda p: p["nome"].casefold())


def _righe(testo: str) -> list[str]:
    return [r.strip() for r in (testo or "").splitlines() if r.strip()]


def scheda_ruolo(ruolo: RuoloOperativo) -> dict:
    from sistema_gestione.models import Processo

    assegnazioni = list(_attivi_ruolo().filter(ruolo=ruolo).values_list("legacy_anagrafica_id", flat=True))
    mansioni = list(CompetenzaSkm.objects.filter(ruoli=ruolo, tipo__in=TIPI_MANSIONE, attiva=True)
                    .select_related("area", "reparto").order_by("display"))
    return {
        "ruolo": ruolo,
        "nomi_precedenti": _righe(ruolo.nomi_precedenti),
        "persone": _persone(set(assegnazioni)),
        "mansioni": mansioni,
        "processi": list(Processo.objects.filter(ruolo_owner=ruolo, attivo=True).order_by("codice")),
        "reparti": list(Reparto.objects.filter(ruolo_responsabile=ruolo, is_active=True).order_by("nome")),
        "aree": list(AreaAziendale.objects.filter(ruolo_responsabile=ruolo, is_active=True)
                     .select_related("reparto").order_by("nome")),
        "sotto": list(RuoloOperativo.objects.filter(riporta_a=ruolo, is_active=True).order_by("nome")),
        # Accessi al portale che il ruolo concede a chi lo ricopre (ruoli del portale collegati).
        "accessi": list(ruolo.profili_permessi.order_by("label")),
    }


def scheda_mansione(mansione: CompetenzaSkm) -> dict:
    from . import mansionario_struttura as ms

    persone = ms.persone(mansione)
    return {
        "mansione": mansione,
        "ruoli": list(mansione.ruoli.order_by("nome")),
        "rischi": list(mansione.mansioni_rischio.order_by("nome")),
        "rischi_proposti": list(mansione.mansioni_rischio_proposte.order_by("nome")),
        "nomi_precedenti": ms.nomi_precedenti(mansione),
        "derivate": list(CompetenzaSkm.objects.filter(deriva_da=mansione).order_by("display")),
        "persone": persone,
        "operativi": sum(1 for p in persone if p["operativa"] and not p["sospesa"]),
    }


def scheda_reparto(reparto: Reparto) -> dict:
    from assets.models import Asset

    aree = [a for a in reparto.aree_aziendali.select_related("ruolo_responsabile").order_by("nome") if a.is_active]
    persone_area = Counter(DipendenteAnagraficaAziendale.objects.filter(area_aziendale__in=aree)
                           .values_list("area_aziendale_id", flat=True))
    capi = _nomi([reparto.caporeparto_legacy_id] + [a.responsabile_legacy_id for a in aree])
    macchine = Asset.objects.filter(reparto__iexact=reparto.nome).order_by("name")
    return {
        "reparto": reparto,
        "caporeparto": capi.get(reparto.caporeparto_legacy_id, ""),
        "aree": [{"area": a, "persone": persone_area.get(a.pk, 0),
                  "responsabile": capi.get(a.responsabile_legacy_id, "")} for a in aree],
        "persone": sum(persone_area.values()),
        "n_mansioni": CompetenzaSkm.objects.filter(Q(reparto=reparto) | Q(area__reparto=reparto),
                                                   tipo__in=TIPI_MANSIONE, attiva=True).count(),
        "macchine": list(macchine[:MAX_ELENCO]),
        "n_macchine": macchine.count(),
        "responsabili": _persone(reparto.responsabili.values_list("id", flat=True)),
    }
