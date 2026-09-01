"""Diritto soggettivo alla formazione (CCNL): monte ore facoltativo per dipendente.

Il CCNL riconosce un monte ore di formazione — non la formazione sicurezza
dovuta per legge, quella è un obbligo distinto — maturato su una finestra
scorrevole di 3 anni: 24 ore. `TrainingCourse.obbligatoria_ccnl` marca i corsi
esclusi dal computo (tipicamente la formazione sicurezza da legge o Accordo
Stato-Regioni); tutti gli altri completamenti vi concorrono.

Una sola scansione dei completamenti della finestra, con corso precaricato:
niente query per dipendente.
"""
from __future__ import annotations

from datetime import date

from dateutil.relativedelta import relativedelta

from core.legacy_anagrafica import fetch_anagrafica_rows

from ..models_formazione import TrainingEmployeeRecord

__all__ = [
    "MONTE_ORE_TARGET", "FINESTRA_ANNI", "finestra_scorrevole",
    "monte_ore_dipendenti", "corsi_dipendente_nel_periodo", "righe_dipendenti",
]

MONTE_ORE_TARGET = 24
FINESTRA_ANNI = 3


def finestra_scorrevole(al: date | None = None) -> tuple[date, date]:
    """Finestra [dal, al] di 3 anni terminante ad `al` (default: oggi)."""
    al = al or date.today()
    dal = al - relativedelta(years=FINESTRA_ANNI)
    return dal, al


def _record_qs(dal: date, al: date):
    return (
        TrainingEmployeeRecord.objects
        .filter(idoneo=True, data_completamento__gte=dal, data_completamento__lte=al)
        .select_related("corso")
        .order_by("-data_completamento")
    )


def monte_ore_dipendenti(al: date | None = None) -> tuple[date, date, dict[int, dict]]:
    """{legacy_anagrafica_id: {ore_facoltative, ore_obbligatorie, n_corsi_facoltativi,
    n_corsi_obbligatori, ultima_data}} sui completamenti idonei della finestra.
    """
    dal, al = finestra_scorrevole(al)
    aggregato: dict[int, dict] = {}
    for rec in _record_qs(dal, al):
        riga = aggregato.setdefault(rec.legacy_anagrafica_id, {
            "ore_facoltative": 0.0, "ore_obbligatorie": 0.0,
            "n_corsi_facoltativi": 0, "n_corsi_obbligatori": 0,
            "ultima_data": None,
        })
        ore = float(rec.ore_frequentate or 0)
        if rec.corso.obbligatoria_ccnl:
            riga["ore_obbligatorie"] += ore
            riga["n_corsi_obbligatori"] += 1
        else:
            riga["ore_facoltative"] += ore
            riga["n_corsi_facoltativi"] += 1
        if riga["ultima_data"] is None or rec.data_completamento > riga["ultima_data"]:
            riga["ultima_data"] = rec.data_completamento
    return dal, al, aggregato


def _cessati_legacy_ids() -> set[int]:
    from ..models import DipendenteAnagraficaAziendale
    return set(
        DipendenteAnagraficaAziendale.objects
        .filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
    )


def righe_dipendenti(
    *, al: date | None = None, filtro_reparto: str = "", filtro_stato: str = "", filtro_q: str = "",
) -> tuple[date, date, list[str], list[dict]]:
    """Una riga per dipendente attivo, con ore facoltative/obbligatorie nella
    finestra e stato verso il monte ore. Usata dalla dashboard e dall'export:
    stessi filtri, stesso risultato.
    """
    from .reparto_canonico import enrich_rows_reparto_canonico

    dal, al, aggregato = monte_ore_dipendenti(al=al)
    cessati = _cessati_legacy_ids()
    reparti_set: set[str] = set()
    righe: list[dict] = []
    rows = enrich_rows_reparto_canonico(fetch_anagrafica_rows(deduplicate=True))
    for r in rows:
        try:
            lid = int(r.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not lid or lid in cessati or not r.get("attivo", True):
            continue
        reparto = (r.get("reparto") or "").strip()
        if reparto:
            reparti_set.add(reparto)
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        nome = f"{(r.get('cognome') or '').strip()} {(r.get('nome') or '').strip()}".strip() or f"#{lid}"
        if filtro_q and filtro_q.lower() not in nome.lower():
            continue

        dati = aggregato.get(lid, {})
        ore_fac = round(dati.get("ore_facoltative", 0.0), 2)
        ore_obb = round(dati.get("ore_obbligatorie", 0.0), 2)
        pct = min(100, round(ore_fac / MONTE_ORE_TARGET * 100)) if ore_fac else 0
        if ore_fac <= 0:
            stato = "DA_INIZIARE"
        elif ore_fac >= MONTE_ORE_TARGET:
            stato = "COMPLETO"
        else:
            stato = "IN_CORSO"
        if filtro_stato and filtro_stato != stato:
            continue

        righe.append({
            "legacy_id": lid,
            "nome": nome,
            "reparto": reparto or "—",
            "mansione": (r.get("mansione") or "").strip() or "—",
            "ore_facoltative": ore_fac,
            "ore_obbligatorie": ore_obb,
            "ore_mancanti": max(0.0, round(MONTE_ORE_TARGET - ore_fac, 2)),
            "pct": pct,
            "n_corsi_facoltativi": dati.get("n_corsi_facoltativi", 0),
            "n_corsi_obbligatori": dati.get("n_corsi_obbligatori", 0),
            "ultima_data": dati.get("ultima_data"),
            "stato": stato,
        })

    righe.sort(key=lambda r: (r["pct"], r["nome"].casefold()))
    return dal, al, sorted(reparti_set), righe


def corsi_dipendente_nel_periodo(legacy_id: int, al: date | None = None) -> dict:
    """Elenco dei completamenti del dipendente nella finestra, divisi facoltativi/obbligatori."""
    dal, al = finestra_scorrevole(al)
    facoltativi: list[TrainingEmployeeRecord] = []
    obbligatori: list[TrainingEmployeeRecord] = []
    for rec in _record_qs(dal, al).filter(legacy_anagrafica_id=legacy_id):
        (obbligatori if rec.corso.obbligatoria_ccnl else facoltativi).append(rec)
    return {"dal": dal, "al": al, "facoltativi": facoltativi, "obbligatori": obbligatori}
