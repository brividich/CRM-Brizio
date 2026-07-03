"""Calcolo della saturazione (carico/capacita') per macchina e per reparto.

Funzioni pure (niente DB qui): ricevono le macchine, le pianificazioni e i giorni
della finestra. La capacita' considera i giorni lavorativi (lun-ven) e i TURNI
abilitati della macchina: 1° turno sempre, +2° turno di giorno, +notturno
(ore/giorno x giorni-lavorativi x n_turni). I flag stanno su Macchina; qui si
leggono in modo difensivo (getattr) perche' la funzione accetta anche stub di test.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date


def working_days(giorni: list[date]) -> int:
    return sum(1 for g in giorni if g.weekday() < 5)


def calcola_saturazione(macchine, pians, giorni: list[date]) -> dict:
    wd = working_days(giorni) or 1

    carico_per_macchina: dict[int, float] = defaultdict(float)
    for p in pians:
        carico_per_macchina[p.macchina_id] += float(p.ore or 0)

    per_macchina: dict[int, dict] = {}
    per_reparto: dict[str, dict] = defaultdict(lambda: {"carico": 0.0, "capacita": 0.0})
    tot = {"carico": 0.0, "capacita": 0.0}

    for m in macchine:
        # n_turni = 1° (sempre) + 2° turno giorno + notturno, secondo i flag macchina.
        turni = 1 + (1 if getattr(m, "ha_secondo_turno", False) else 0) \
                  + (1 if getattr(m, "ha_turno_notte", False) else 0)
        capacita = float(m.ore_giorno_disponibili) * wd * turni
        carico = carico_per_macchina.get(m.id, 0.0)
        perc = round(100 * carico / capacita, 1) if capacita else 0.0
        per_macchina[m.id] = {
            "carico": round(carico, 1), "capacita": round(capacita, 1), "perc": perc,
        }
        per_reparto[m.categoria]["carico"] += carico
        per_reparto[m.categoria]["capacita"] += capacita
        tot["carico"] += carico
        tot["capacita"] += capacita

    reparti = {}
    for cat, v in per_reparto.items():
        reparti[cat] = {
            "carico": round(v["carico"], 1),
            "capacita": round(v["capacita"], 1),
            "perc": round(100 * v["carico"] / v["capacita"], 1) if v["capacita"] else 0.0,
        }

    return {
        "per_macchina": per_macchina,
        "per_reparto": reparti,
        "totale": {
            "carico": round(tot["carico"], 1),
            "capacita": round(tot["capacita"], 1),
            "perc": round(100 * tot["carico"] / tot["capacita"], 1) if tot["capacita"] else 0.0,
        },
    }
