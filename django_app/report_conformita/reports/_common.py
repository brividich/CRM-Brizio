"""Utilita' condivise dai builder dei report."""
from __future__ import annotations

import logging
from datetime import date, datetime

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

logger = logging.getLogger(__name__)


def link(label: str, route_name: str, query: str = "") -> tuple[str, str] | None:
    """Link verso la pagina sorgente; None se la route non esiste (modulo assente)."""
    try:
        url = reverse(route_name)
    except NoReverseMatch:
        return None
    return (label, f"{url}?{query}" if query else url)


def links(*items: tuple[str, str, str] | tuple[str, str]) -> list[tuple[str, str]]:
    out = []
    for item in items:
        resolved = link(*item)
        if resolved:
            out.append(resolved)
    return out


def _as_date(value):
    """datetime (anche aware, in ora locale) -> date; date resta date."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.date()
    return value


def d(value) -> str:
    """Data in formato italiano, stringa vuota se assente."""
    if not value:
        return ""
    return _as_date(value).strftime("%d/%m/%Y")


def short(text, limit: int = 140) -> str:
    raw = " ".join(str(text or "").split())
    return raw if len(raw) <= limit else raw[: limit - 1].rstrip() + "…"


def pct(part: int, total: int) -> str:
    if not total:
        return "n/d"
    return f"{round(part * 100 / total)}%"


def pct_value(part: int, total: int) -> int | None:
    if not total:
        return None
    return round(part * 100 / total)


def yes_no(value) -> str:
    return "Sì" if value else "No"


def days_between(start, end) -> int | None:
    if not start or not end:
        return None
    return (_as_date(end) - _as_date(start)).days


def scadenza_stato(due: date | None, today: date, *, preavviso: int = 30) -> tuple[str, str]:
    """(etichetta, tono) di una scadenza rispetto a oggi."""
    from ..registry import TONE_DANGER, TONE_OK, TONE_WARN

    if not due:
        return ("Senza data", TONE_WARN)
    delta = (due - today).days
    if delta < 0:
        return (f"Scaduta da {abs(delta)} gg", TONE_DANGER)
    if delta <= preavviso:
        return (f"In scadenza ({delta} gg)", TONE_WARN)
    return ("Valida", TONE_OK)
