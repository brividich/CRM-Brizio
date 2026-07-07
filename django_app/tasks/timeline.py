"""Roadmap portfolio: geometria della timeline cross-commessa (logica pura)."""
from __future__ import annotations

import calendar as _cal
from datetime import date

_MONTHS_ABBR = ["", "Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_end(d: date) -> date:
    return date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])


def _next_month(y: int, m: int):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def build_portfolio_timeline(items, today: date) -> dict:
    dated = [dict(it) for it in items if it.get("start") and it.get("end")]
    for it in dated:
        if it["end"] < it["start"]:
            it["end"] = it["start"]
    if not dated:
        return {"months": [], "rows": [], "today_pct": None, "empty": True,
                "window_start": None, "window_end": None}

    window_start = _month_start(min([it["start"] for it in dated] + [today]))
    window_end = _month_end(max([it["end"] for it in dated] + [today]))
    total_days = (window_end - window_start).days + 1

    def pct(d: date) -> float:
        return (d - window_start).days / total_days * 100

    months = []
    y, m = window_start.year, window_start.month
    while (y, m) <= (window_end.year, window_end.month):
        ms = date(y, m, 1)
        me = _month_end(ms)
        months.append({
            "label": f"{_MONTHS_ABBR[m]} {str(y)[2:]}",
            "left_pct": round(pct(ms), 4),
            "width_pct": round(((me - ms).days + 1) / total_days * 100, 4),
        })
        y, m = _next_month(y, m)

    rows = []
    for it in dated:
        width = max(((it["end"] - it["start"]).days + 1) / total_days * 100, 1.2)
        rows.append({
            "project": it["project"], "readiness": it.get("readiness"),
            "start": it["start"], "end": it["end"],
            "left_pct": round(pct(it["start"]), 4), "width_pct": round(width, 4),
        })

    today_pct = round(pct(today), 4) if window_start <= today <= window_end else None
    return {"months": months, "rows": rows, "today_pct": today_pct, "empty": False,
            "window_start": window_start, "window_end": window_end}
