"""
dashboard/views_mie_attivita.py
===============================
"Le mie attività" — cockpit operativo personale di NOVICROM HUB.

Pagina focalizzata (distinta dalla home launcher) che aggrega in un solo posto
le cose che l'utente loggato deve gestire/seguire, attraversando i moduli:
anomalie aperte, ticket correlati aperti, approvazioni assenze da evadere,
richieste DPI in corso.

Riusa gli helper già provati in dashboard/views.py (stessa app, no circular import)
per non duplicare la logica di visibilità/ACL. Ogni sezione è difensiva: un errore
in un modulo non rompe l'intera pagina.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from core.legacy_utils import get_legacy_user, is_legacy_admin
from dashboard.views import (
    _board_data_anomalie,
    _board_data_assenze_da_approvare,
    _board_related_tickets_queryset,
)


def _safe_url(name: str, *args) -> str:
    try:
        return reverse(name, args=args) if args else reverse(name)
    except NoReverseMatch:
        return "#"


def _my_anomalie(legacy_user, is_admin: bool) -> list[dict]:
    try:
        raw = _board_data_anomalie(legacy_user, is_admin, {"max_items": 12, "solo_aperte": True})
    except Exception:
        return []
    url = _safe_url("gestione_anomalie_page")
    out = []
    for a in raw:
        out.append({
            "code": f"A-{a.get('id')}",
            "title": a.get("seriale") or a.get("ex_op_nominativo") or "Anomalia",
            "meta": a.get("operatore") or "—",
            "status": a.get("avanzamento") or "Aperta",
            "url": url,
        })
    return out


def _my_tickets(request_user, legacy_user, legacy_user_id) -> list[dict]:
    try:
        from tickets.models import StatoTicket, Ticket  # noqa: F401

        open_states = (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)
        qs = (
            _board_related_tickets_queryset(request_user, legacy_user, legacy_user_id)
            .filter(stato__in=open_states)
            .order_by("-created_at", "-id")[:15]
        )
    except Exception:
        return []
    out = []
    for t in qs:
        try:
            status_label = t.get_stato_display()
        except Exception:
            status_label = getattr(t, "stato", "") or "Aperto"
        out.append({
            "code": t.numero_ticket or f"T-{t.pk}",
            "title": t.titolo or "Ticket",
            "meta": (getattr(t, "asset_descrizione_libera", "") or getattr(t, "categoria", "") or "—"),
            "status": status_label,
            "priority": getattr(t, "priorita", "") or "",
            "url": _safe_url("tickets:detail", t.pk),
        })
    return out


def _my_approvals(legacy_user, is_admin: bool) -> list[dict]:
    try:
        raw = _board_data_assenze_da_approvare(legacy_user, is_admin, {"max_items": 12})
    except Exception:
        return []
    url = _safe_url("assenze_gestione")
    out = []
    for a in raw:
        out.append({
            "title": f"{a.get('tipo', 'Assenza')}",
            "meta": a.get("dipendente", "") or "—",
            "status": a.get("inizio", "") or "",
            "url": url,
        })
    return out


def _my_dpi(legacy_user_id) -> list[dict]:
    if not legacy_user_id:
        return []
    try:
        from dpi.models import RichiestaDPI, StatoRichiesta

        qs = (
            RichiestaDPI.objects.filter(richiedente_legacy_id=legacy_user_id)
            .filter(stato__in=(StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA))
            .order_by("-created_at")[:15]
        )
    except Exception:
        return []
    url = _safe_url("dpi:dashboard")
    out = []
    for r in qs:
        try:
            status_label = r.label_stato
        except Exception:
            status_label = getattr(r, "stato", "")
        out.append({
            "code": r.numero,
            "title": str(getattr(r, "categoria", "") or "Richiesta DPI"),
            "meta": f"Qtà {getattr(r, 'quantita', '') or '—'}",
            "status": status_label,
            "url": url,
        })
    return out


def _my_procedure(request_user) -> list[dict]:
    """Procedure ancora da leggere/confermare assegnate all'utente corrente."""
    if not getattr(request_user, "is_authenticated", False):
        return []
    try:
        from procedure_refresh.models import AssignmentStatus, ProcedureAssignment

        da_leggere = (AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE)
        qs = (
            ProcedureAssignment.objects.filter(user=request_user, status__in=da_leggere)
            .select_related("campaign", "revision")
            .order_by("due_date", "-assigned_at")[:15]
        )
    except Exception:
        return []
    url = _safe_url("procedure_refresh:my_assignments")
    out = []
    for a in qs:
        try:
            status_label = a.get_status_display()
        except Exception:
            status_label = getattr(a, "status", "") or ""
        out.append({
            "title": str(getattr(a.campaign, "name", "") or getattr(a.revision, "file_name", "") or "Procedura"),
            "meta": (a.due_date.strftime("%d-%m-%Y") if a.due_date else "—"),
            "status": status_label,
            "url": url,
        })
    return out


def build_cose_da_gestire(request: HttpRequest) -> dict[str, Any]:
    """Aggrega in un'unica struttura le "cose da gestire" dell'utente corrente,
    attraversando i moduli. Riusato sia dalla pagina dedicata `mie_attivita` sia
    dalla sezione in home. Ogni fonte è difensiva (un errore non rompe il resto).

    Ritorna {"sections": [...], "total": n}. Le scadenze HR personali
    (visite/qualifiche) sono volutamente escluse da questa versione: richiedono il
    mapping utente→anagrafica e toccano dati sanitari (privacy), da inquadrare a parte.
    """
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None

    sections = [
        {
            "key": "approvazioni",
            "label": "Approvazioni assenze",
            "tone": "info",
            "icon": "✅",
            "items": _my_approvals(legacy_user, is_admin),
            "all_url": _safe_url("assenze_gestione"),
            "empty": "Nessuna richiesta in attesa di approvazione.",
        },
        {
            "key": "ticket",
            "label": "Ticket aperti",
            "tone": "warning",
            "icon": "🎫",
            "items": _my_tickets(request.user, legacy_user, legacy_user_id),
            "all_url": _safe_url("tickets:dashboard"),
            "empty": "Nessun ticket aperto correlato.",
        },
        {
            "key": "anomalie",
            "label": "Anomalie aperte",
            "tone": "danger",
            "icon": "⚠",
            "items": _my_anomalie(legacy_user, is_admin),
            "all_url": _safe_url("gestione_anomalie_page"),
            "empty": "Nessuna anomalia aperta a te collegata.",
        },
        {
            "key": "procedure",
            "label": "Procedure da leggere",
            "tone": "info",
            "icon": "📄",
            "items": _my_procedure(request.user),
            "all_url": _safe_url("procedure_refresh:my_assignments"),
            "empty": "Nessuna procedura da leggere.",
        },
        {
            "key": "dpi",
            "label": "Richieste DPI in corso",
            "tone": "info",
            "icon": "🦺",
            "items": _my_dpi(legacy_user_id),
            "all_url": _safe_url("dpi:dashboard"),
            "empty": "Nessuna richiesta DPI in corso.",
        },
    ]
    total = sum(len(s["items"]) for s in sections)
    return {"sections": sections, "total": total}


@login_required
def mie_attivita(request: HttpRequest) -> HttpResponse:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = (
        request.user.first_name
        or getattr(legacy_user, "nome", "")
        or request.user.get_username()
    )

    data = build_cose_da_gestire(request)

    context: dict[str, Any] = {
        "page_title": "Le mie attività",
        "greeting_name": display_name,
        "sections": data["sections"],
        "total_open": data["total"],
    }
    return render(request, "dashboard/pages/mie_attivita.html", context)
