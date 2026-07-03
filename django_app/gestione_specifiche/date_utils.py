"""Date lavorative per l'auto-approvazione "umanizzata" del MOD.133.

`festivi_it` calcola i festivi nazionali italiani (fissi + Pasquetta) senza dipendenze
esterne; `next_business_datetime` restituisce il primo giorno lavorativo dopo una data,
con un'ora casuale in orario ufficio. Nessun festivo locale/patronale.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.utils import timezone

# Festivi nazionali a data fissa (giorno, mese).
_FISSI = [(1, 1), (6, 1), (25, 4), (1, 5), (2, 6), (15, 8), (1, 11), (8, 12), (25, 12), (26, 12)]


def _pasqua(anno: int) -> date:
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
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1
    return date(anno, mese, giorno)


def festivi_it(anno: int) -> set[date]:
    """Festivi nazionali italiani dell'anno: fissi + Pasquetta (lunedì dopo Pasqua)."""
    giorni = {date(anno, mese, giorno) for giorno, mese in _FISSI}
    giorni.add(_pasqua(anno) + timedelta(days=1))  # Pasquetta
    return giorni


def _e_lavorativo(d: date) -> bool:
    return d.weekday() < 5 and d not in festivi_it(d.year)


def next_business_datetime(base: datetime) -> datetime:
    """Primo giorno lavorativo dopo `base`, con ora casuale in [9:00, 17:00).

    Salta sabato, domenica e festivi nazionali (Pasquetta inclusa). Ritorna un
    `datetime` *aware* nella timezone corrente.
    """
    giorno = base.date() + timedelta(days=1)
    while not _e_lavorativo(giorno):
        giorno += timedelta(days=1)
    ora = time(hour=random.randint(9, 16), minute=random.randint(0, 59), second=random.randint(0, 59))
    return timezone.make_aware(datetime.combine(giorno, ora))
