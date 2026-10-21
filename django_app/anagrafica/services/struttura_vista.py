"""Dati della pagina «Struttura organizzativa»: albero, processi, ruoli, da completare.

Poche query per tutta la pagina (conteggi aggregati, niente query per riga).
"""
from __future__ import annotations

from collections import Counter, defaultdict

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


def _mansioni():
    return list(
        CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, attiva=True)
        .select_related("area", "reparto", "processo_sgi", "asset", "responsabilita_reparto")
        .prefetch_related("ruoli", "mansioni_rischio", "mansioni_rischio_proposte")
        .order_by("display", "competenza_key")
    )


def _persone_per_ruolo() -> Counter:
    oggi = timezone.localdate()
    return Counter(
        DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
        .values_list("ruolo_id", flat=True)
    )


def _nomi(ids) -> dict[int, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    return {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome")) for r in fetch_anagrafica_rows(ids=ids)}


def albero(mansioni=None) -> list[dict]:
    """Reparto → aree → ruoli → mansioni (solo attivi)."""
    mansioni = mansioni if mansioni is not None else _mansioni()
    per_area: dict[int | None, list] = defaultdict(list)
    per_reparto_senza_area: dict[int, list] = defaultdict(list)
    for m in mansioni:
        if m.responsabilita_reparto_id:
            continue
        if m.area_id:
            per_area[m.area_id].append(m)
        elif m.reparto_id:
            per_reparto_senza_area[m.reparto_id].append(m)
    persone_area = Counter(DipendenteAnagraficaAziendale.objects.exclude(area_aziendale__isnull=True)
                           .values_list("area_aziendale_id", flat=True))
    responsabilita = {m.responsabilita_reparto_id: m for m in mansioni if m.responsabilita_reparto_id}
    reparti = list(Reparto.objects.filter(is_active=True).select_related("ruolo_responsabile")
                   .prefetch_related("aree_aziendali__ruolo_responsabile").order_by("nome"))
    capi = _nomi([r.caporeparto_legacy_id for r in reparti])
    out = []
    for rep in reparti:
        aree = []
        for a in sorted((a for a in rep.aree_aziendali.all() if a.is_active), key=lambda a: a.nome.casefold()):
            ms = per_area.get(a.pk, [])
            per_ruolo: dict[str, list] = defaultdict(list)
            for m in ms:
                for r in (m.ruoli.all() or [None]):
                    per_ruolo[r.etichetta if r else "Senza ruolo"].append(m)
            aree.append({
                "area": a, "persone": persone_area.get(a.pk, 0), "n_mansioni": len(ms),
                "ruoli": sorted(per_ruolo.items(), key=lambda kv: (kv[0] == "Senza ruolo", kv[0].casefold())),
            })
        out.append({
            "reparto": rep, "aree": aree, "caporeparto": capi.get(rep.caporeparto_legacy_id, ""),
            "responsabilita": responsabilita.get(rep.pk),
            "senza_area": per_reparto_senza_area.get(rep.pk, []),
            "n_mansioni": sum(x["n_mansioni"] for x in aree) + len(per_reparto_senza_area.get(rep.pk, [])),
            "persone": sum(x["persone"] for x in aree),
        })
    return out


def processi(mansioni=None) -> list[dict]:
    from sistema_gestione.models import Processo

    mansioni = mansioni if mansioni is not None else _mansioni()
    conta = Counter(m.processo_sgi_id for m in mansioni if m.processo_sgi_id)
    ruoli_per = defaultdict(set)
    for m in mansioni:
        if m.processo_sgi_id:
            for r in m.ruoli.all():
                ruoli_per[m.processo_sgi_id].add(r.etichetta)
    return [{"processo": p, "n_mansioni": conta.get(p.pk, 0), "ruoli": sorted(ruoli_per.get(p.pk, ()), key=str.casefold)}
            for p in Processo.objects.filter(attivo=True).select_related("ruolo_owner").order_by("tipo", "codice")]


def ruoli(mansioni=None) -> list[dict]:
    """Ruoli della struttura: con sigla o classificati diretto/indiretto, più quelli con mansioni."""
    mansioni = mansioni if mansioni is not None else _mansioni()
    conta_m = Counter(r.pk for m in mansioni for r in m.ruoli.all())
    persone = _persone_per_ruolo()
    qs = (RuoloOperativo.objects.filter(is_active=True)
          .filter(Q(sigla__isnull=False) | ~Q(classe="") | Q(pk__in=list(conta_m)))
          .select_related("ambito", "riporta_a").order_by("nome"))
    out = [{"ruolo": r, "persone": persone.get(r.pk, 0), "n_mansioni": conta_m.get(r.pk, 0)} for r in qs]
    out.sort(key=lambda x: (x["ruolo"].classe != RuoloOperativo.CLASSE_INDIRETTO, (x["ruolo"].sigla or "~"),
                            x["ruolo"].nome.casefold()))
    return out


def da_completare(mansioni=None) -> list[dict]:
    """Cosa manca perché la struttura sia completa, voce per voce, con il link dove si risolve."""
    mansioni = mansioni if mansioni is not None else _mansioni()
    lavorative = [m for m in mansioni if not m.responsabilita_reparto_id]
    voci = [
        ("Mansioni senza area", [m for m in lavorative if not m.area_id], "mansione"),
        ("Mansioni senza processo SGI", [m for m in lavorative if not m.processo_sgi_id], "mansione"),
        ("Mansioni senza ruolo", [m for m in lavorative if not m.ruoli.all()], "mansione"),
        ("Mansioni senza mansione di rischio confermata",
         [m for m in lavorative if not m.mansioni_rischio.all()], "mansione"),
        ("Reparti senza caporeparto (persona)",
         list(Reparto.objects.filter(is_active=True, caporeparto_legacy_id__isnull=True).order_by("nome")), "reparto"),
        ("Reparti senza ruolo responsabile",
         list(Reparto.objects.filter(is_active=True, ruolo_responsabile__isnull=True).order_by("nome")), "reparto"),
        ("Aree senza reparto", list(AreaAziendale.objects.filter(is_active=True, reparto__isnull=True)), "area"),
    ]
    persone = _persone_per_ruolo()
    vuoti = [r for r in RuoloOperativo.objects.filter(is_active=True, sigla__isnull=False).order_by("sigla")
             if not persone.get(r.pk)]
    voci.append(("Ruoli della struttura senza nessuno assegnato", vuoti, "ruolo"))
    return [{"titolo": t, "voci": v, "tipo": tipo} for t, v, tipo in voci if v]


def kpi(alb, procs, rls, mans) -> dict:
    return {
        "reparti": len(alb),
        "aree": sum(len(r["aree"]) for r in alb),
        "ruoli": len(rls),
        "mansioni": sum(1 for m in mans if not m.responsabilita_reparto_id),
        "processi": len(procs),
        "rischi_da_confermare": sum(1 for m in mans if m.mansioni_rischio_proposte.all()),
    }
