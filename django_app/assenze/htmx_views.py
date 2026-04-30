"""
Partial views HTMX per il modulo assenze.
Utilizzate per aggiornamenti parziali del calendario senza ricarica intera pagina.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from .views import (
    _assenze_permissions,
    _load_events,
    _template_perm_context,
)


def _parse_mese(mese_str: str) -> date:
    """Converte 'YYYY-MM' in date al primo giorno del mese; fallback al mese corrente."""
    try:
        return datetime.strptime(str(mese_str or "").strip(), "%Y-%m").date().replace(day=1)
    except (ValueError, TypeError):
        return date.today().replace(day=1)


def _month_nav_ctx(d: date) -> dict:
    """Restituisce il contesto di navigazione prev/next per il mese dato."""
    last = monthrange(d.year, d.month)[1]
    prev_m = (d - timedelta(days=1)).replace(day=1)
    next_m = (d + timedelta(days=last)).replace(day=1)
    it_months = [
        "", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
    ]
    label = f"{it_months[d.month].capitalize()} {d.year}"
    return {
        "mese_corrente": d.strftime("%Y-%m"),
        "mese_corrente_label": label,
        "mese_prev": prev_m.strftime("%Y-%m"),
        "mese_next": next_m.strftime("%Y-%m"),
        "initial_date": d.isoformat(),
    }


@login_required
def calendario_month_partial(request):
    """
    HTMX partial — ritorna il fragment HTML del corpo calendario per il mese richiesto.
    Se la richiesta non è HTMX redireziona alla pagina calendario principale.
    """
    if not getattr(request, "htmx", None):
        return redirect("assenze_calendario")

    perms = _assenze_permissions(request)
    if not perms.get("can_view_calendar"):
        return HttpResponseForbidden()

    mese_date = _parse_mese(request.GET.get("mese", ""))
    nav = _month_nav_ctx(mese_date)

    # Carica gli eventi per il mese selezionato
    month_start = datetime(mese_date.year, mese_date.month, 1)
    month_end = datetime(mese_date.year, mese_date.month, monthrange(mese_date.year, mese_date.month)[1], 23, 59, 59)
    eventi_raw = _load_events(start=month_start, end=month_end, limit=500)

    # Adatta i dati per la vista lista
    eventi: list[dict] = []
    for ev in eventi_raw:
        ext = ev.get("extendedProps") or {}
        eventi.append({
            "dipendente": ev.get("title", ""),
            "tipo": ext.get("tipo", ""),
            "consenso": ext.get("consenso", ""),
            "inizio": ev.get("start", ""),
            "fine": ev.get("end", ""),
            "color": ev.get("color", "#94a3b8"),
        })

    eventi.sort(key=lambda e: e["inizio"] or "")

    ctx = {
        **nav,
        "eventi": eventi,
        **_template_perm_context(request),
    }
    return render(request, "assenze/partials/calendario_body.html", ctx)
