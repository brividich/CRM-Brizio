"""Calendario lavorativo italiano: festivita' nazionali e giorni lavorativi."""
from __future__ import annotations

import logging
from datetime import date, timedelta




logger = logging.getLogger(__name__)


def _easter_date(year: int) -> date:
    """Calcola la domenica di Pasqua (algoritmo gregoriano anonimo)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _italian_holidays(year: int) -> set[date]:
    """Restituisce le festività nazionali italiane fisse + Pasqua/Lunedì dell'Angelo."""
    easter = _easter_date(year)
    return {
        date(year, 1, 1),   # Capodanno
        date(year, 1, 6),   # Epifania
        easter,              # Pasqua
        easter + timedelta(days=1),  # Lunedì dell'Angelo
        date(year, 4, 25),  # Liberazione
        date(year, 5, 1),   # Festa del lavoro
        date(year, 6, 2),   # Repubblica
        date(year, 8, 15),  # Ferragosto
        date(year, 11, 1),  # Ognissanti
        date(year, 12, 8),  # Immacolata Concezione
        date(year, 12, 25), # Natale
        date(year, 12, 26), # Santo Stefano
    }


def _build_holidays_set(start: date, end: date) -> set[date]:
    """Costruisce l'insieme di tutte le festività nell'arco temporale dato."""
    holidays: set[date] = set()
    for year in range(start.year, end.year + 1):
        holidays |= _italian_holidays(year)
    return holidays


def _is_non_working_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() >= 5 or d in holidays


def _count_working_days(start: date, end: date, holidays: set[date]) -> int:
    return sum(1 for i in range((end - start).days + 1) if not _is_non_working_day(start + timedelta(days=i), holidays))
