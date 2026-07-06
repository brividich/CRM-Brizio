"""Griglia calendario mensile degli incontri kickoff (logica pura)."""
from __future__ import annotations

import calendar as _cal

_MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def _prev_next(year: int, month: int):
    prev = (year - 1, 12) if month == 1 else (year, month - 1)
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{prev[0]:04d}-{prev[1]:02d}", f"{nxt[0]:04d}-{nxt[1]:02d}"


def build_meetings_calendar(meetings, year: int, month: int, today=None) -> dict:
    by_day = {}
    for m in meetings:
        by_day.setdefault(m.data, []).append(m)
    grid = _cal.Calendar(firstweekday=0).monthdatescalendar(year, month)  # Lun–Dom
    weeks = []
    for week in grid:
        days = []
        for d in week:
            days.append({
                "date": d,
                "in_month": d.month == month,
                "is_today": today is not None and d == today,
                "meetings": by_day.get(d, []),
            })
        weeks.append(days)
    prev, nxt = _prev_next(year, month)
    return {
        "weeks": weeks, "year": year, "month": month,
        "month_label": f"{_MONTHS_IT[month]} {year}",
        "prev": prev, "next": nxt, "today": today,
    }
