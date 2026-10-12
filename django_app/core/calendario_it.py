"""Calendario lavorativo italiano: Pasqua e festivita' nazionali.

Unica implementazione condivisa (prima duplicata in ``tasks`` e
``gestione_specifiche``). Solo festivi nazionali: nessun patrono o festivo locale.
"""
from __future__ import annotations

from datetime import date, timedelta

# Festivi nazionali a data fissa (mese, giorno).
_FESTIVI_FISSI = (
    (1, 1),    # Capodanno
    (1, 6),    # Epifania
    (4, 25),   # Liberazione
    (5, 1),    # Festa del lavoro
    (6, 2),    # Repubblica
    (8, 15),   # Ferragosto
    (11, 1),   # Ognissanti
    (12, 8),   # Immacolata Concezione
    (12, 25),  # Natale
    (12, 26),  # Santo Stefano
)


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (computus di Gauss/Meeus, calendario gregoriano)."""
    a = anno % 19
    b = anno // 100
    c = anno % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - nome dell'algoritmo
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1
    return date(anno, mese, giorno)


def festivi_nazionali(anno: int) -> set[date]:
    """Festivi nazionali dell'anno: fissi + Pasqua + Lunedi' dell'Angelo."""
    domenica_pasqua = pasqua(anno)
    giorni = {date(anno, mese, giorno) for mese, giorno in _FESTIVI_FISSI}
    giorni.add(domenica_pasqua)
    giorni.add(domenica_pasqua + timedelta(days=1))
    return giorni


def festivi_tra(inizio: date, fine: date) -> set[date]:
    """Festivi nazionali di tutti gli anni toccati dall'intervallo."""
    giorni: set[date] = set()
    for anno in range(inizio.year, fine.year + 1):
        giorni |= festivi_nazionali(anno)
    return giorni


def is_lavorativo(giorno: date, festivi: set[date] | None = None) -> bool:
    """Lunedi'-venerdi' e non festivo nazionale."""
    if festivi is None:
        festivi = festivi_nazionali(giorno.year)
    return giorno.weekday() < 5 and giorno not in festivi
