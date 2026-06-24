"""Predizioni data-driven per Gestione Carichi Macchina (AI predittiva, Fase 1: durata/ore).

La predizione la fa un modello sui DATI (statistico, spiegabile e validabile), NON l'LLM.
Funzioni pure: ricevono indici precalcolati, nessuna query qui dentro (testabili in isolamento).
Gli indici si costruiscono da DB con `costruisci_indici()`.
"""
from __future__ import annotations

from datetime import date, timedelta
from math import ceil

FONTE_CICLO = "ciclo"      # tempo di ciclo x pezzi (alta confidenza)
FONTE_STORICO = "storico"  # media storica famiglia x macchina (media)
FONTE_FAMIGLIA = "famiglia"  # media storica della famiglia su qualunque macchina (bassa)
FONTE_NESSUNA = "nessuno"


def prevedi_ore(
    *,
    qta: int | None,
    macchina_id: int | None,
    famiglia_id: int | None,
    ciclo_tempi: dict[tuple[int, int], int],
    affinita_ore: dict[tuple[int, int], float],
    famiglia_ore: dict[int, float] | None = None,
) -> tuple[float | None, str, str]:
    """Predice le ore di un lavoro. Ritorna (ore, fonte, confidenza).

    Priorita':
    1) tempo di ciclo (cent/cad) x pezzi, se esiste l'operazione per (famiglia, macchina);
    2) media storica delle ore per (macchina, famiglia);
    3) media storica della famiglia (qualunque macchina);
    altrimenti (None, 'nessuno', 'assente').
    """
    famiglia_ore = famiglia_ore or {}

    if qta and famiglia_id and macchina_id:
        t = ciclo_tempi.get((famiglia_id, macchina_id))
        if t:
            return round(qta * t / 100.0, 1), FONTE_CICLO, "alta"

    if macchina_id and famiglia_id:
        om = affinita_ore.get((macchina_id, famiglia_id))
        if om:
            return round(float(om), 1), FONTE_STORICO, "media"

    if famiglia_id:
        fo = famiglia_ore.get(famiglia_id)
        if fo:
            return round(float(fo), 1), FONTE_FAMIGLIA, "bassa"

    return None, FONTE_NESSUNA, "assente"


def costruisci_indici() -> tuple[dict, dict, dict]:
    """Costruisce gli indici di predizione dal DB: (ciclo_tempi, affinita_ore, famiglia_ore)."""
    from collections import defaultdict

    from .models import MacchinaFamigliaAffinita, Operazione

    ciclo_tempi: dict[tuple[int, int], int] = {}
    for op in (
        Operazione.objects.filter(
            macchina_preferita__isnull=False, tempo_cent_cad__isnull=False,
            ciclo__famiglia__isnull=False,
        ).select_related("ciclo")
    ):
        ciclo_tempi[(op.ciclo.famiglia_id, op.macchina_preferita_id)] = op.tempo_cent_cad

    affinita_ore: dict[tuple[int, int], float] = {}
    fam_acc: dict[int, list] = defaultdict(list)
    for a in MacchinaFamigliaAffinita.objects.filter(ore_medie__isnull=False):
        val = float(a.ore_medie)
        affinita_ore[(a.macchina_id, a.famiglia_id)] = val
        fam_acc[a.famiglia_id].append(val)

    famiglia_ore = {fid: round(sum(v) / len(v), 1) for fid, v in fam_acc.items() if v}
    return ciclo_tempi, affinita_ore, famiglia_ore


# --- Fase 2: macchina piu' probabile per una famiglia/pezzo ----------------
def prevedi_macchina(famiglia_id: int | None, freq_per_famiglia: dict[int, list]) -> list[dict]:
    """Predice su quali macchine finisce, storicamente, un lavoro di una certa famiglia.

    freq_per_famiglia: dict[famiglia_id] -> [(macchina_id, occorrenze), ...].
    Ritorna lista ordinata per occorrenze: [{macchina_id, occorrenze, prob}].
    """
    items = freq_per_famiglia.get(famiglia_id) or []
    tot = sum(o for _m, o in items)
    out = [
        {"macchina_id": m, "occorrenze": o, "prob": round(o / tot, 3) if tot else 0.0}
        for m, o in items
    ]
    out.sort(key=lambda x: (x["occorrenze"], x["macchina_id"]), reverse=True)
    return out


def costruisci_indice_macchine() -> dict[int, list]:
    """Indice frequenza: famiglia_id -> [(macchina_id, occorrenze), ...] (da affinita')."""
    from collections import defaultdict

    from .models import MacchinaFamigliaAffinita

    freq: dict[int, list] = defaultdict(list)
    for a in MacchinaFamigliaAffinita.objects.all():
        freq[a.famiglia_id].append((a.macchina_id, a.occorrenze))
    return dict(freq)


# --- Fase 3: rischio ritardo commessa --------------------------------------
def _fine_lavorativa(inizio: date, durata_gg: int) -> date:
    """Data di fine contando `durata_gg` giorni lavorativi a partire da inizio (inclusivo)."""
    giorni: list[date] = []
    d = inizio
    while len(giorni) < max(1, durata_gg):
        if d.weekday() < 5:
            giorni.append(d)
        d += timedelta(days=1)
    return giorni[-1]


def _gg_lavorativi_tra(a: date, b: date) -> int:
    """Giorni lavorativi tra a e b (esclusa a, inclusa b), con segno (negativo se b<a)."""
    if a == b:
        return 0
    lo, hi = (a, b) if a < b else (b, a)
    cnt = 0
    d = lo
    while d < hi:
        d += timedelta(days=1)
        if d.weekday() < 5:
            cnt += 1
    return cnt if a < b else -cnt


def rischio_ritardo(*, data_inizio, ore_previste, ore_giorno, data_consegna) -> dict:
    """Stima se un lavoro finisce entro la consegna.

    Ritorna {valutabile, fine_prevista, in_ritardo, giorni_margine}.
    giorni_margine > 0 = margine (giorni lavorativi prima della consegna); < 0 = ritardo.
    """
    if not (data_inizio and data_consegna and ore_previste):
        return {"valutabile": False}
    ogg = float(ore_giorno) or 8.0
    durata_gg = max(1, ceil(float(ore_previste) / ogg))
    fine = _fine_lavorativa(data_inizio, durata_gg)
    return {
        "valutabile": True,
        "fine_prevista": fine,
        "in_ritardo": fine > data_consegna,
        "giorni_margine": _gg_lavorativi_tra(fine, data_consegna),
    }


# --- Fase 4: previsione carico / colli di bottiglia ------------------------
def carico_settimanale(start: date, n_settimane: int, *, indici=None) -> list[dict]:
    """Carico previsto per le prossime `n_settimane`, per reparto e totale.

    Usa le ore REALI dove ci sono, altrimenti la durata STIMATA (Fase 1), così il carico
    futuro e' realistico. Ritorna [{settimana, totale, per_reparto}] con perc di saturazione;
    un reparto con perc>100 e' un collo di bottiglia.
    """
    from types import SimpleNamespace

    from .models import Macchina, Pianificazione
    from .saturazione import calcola_saturazione

    ciclo_tempi, affinita_ore, famiglia_ore = indici or costruisci_indici()
    macchine = list(Macchina.objects.filter(attivo=True))
    out: list[dict] = []
    for w in range(n_settimane):
        ws = start + timedelta(days=7 * w)
        giorni = [ws + timedelta(days=i) for i in range(7)]
        pians = list(
            Pianificazione.objects.filter(data__range=(giorni[0], giorni[-1]))
            .only("macchina_id", "ore", "qta", "famiglia_id")
        )
        stub = []
        for p in pians:
            ore = float(p.ore) if p.ore else None
            if ore is None:
                ore, _f, _c = prevedi_ore(
                    qta=p.qta, macchina_id=p.macchina_id, famiglia_id=p.famiglia_id,
                    ciclo_tempi=ciclo_tempi, affinita_ore=affinita_ore, famiglia_ore=famiglia_ore,
                )
            stub.append(SimpleNamespace(macchina_id=p.macchina_id, ore=ore or 0))
        sat = calcola_saturazione(macchine, stub, giorni)
        out.append({"settimana": ws, "totale": sat["totale"], "per_reparto": sat["per_reparto"]})
    return out
