"""Calendario lavorativo del Gantt: delega a ``core.calendario_it``."""
from __future__ import annotations

from datetime import date, timedelta

from core.calendario_it import festivi_nazionali, festivi_tra, is_lavorativo, pasqua

_easter_date = pasqua
_italian_holidays = festivi_nazionali
_build_holidays_set = festivi_tra


def _is_non_working_day(d: date, holidays: set[date]) -> bool:
    return not is_lavorativo(d, holidays)


def _count_working_days(start: date, end: date, holidays: set[date]) -> int:
    return sum(1 for i in range((end - start).days + 1) if not _is_non_working_day(start + timedelta(days=i), holidays))
