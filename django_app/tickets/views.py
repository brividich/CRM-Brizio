from __future__ import annotations

import json
import os
from io import BytesIO
from datetime import datetime, timezone as dt_timezone
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.timezone import now as tz_now
from django.views.decorators.http import require_POST
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.legacy_utils import get_legacy_user, is_legacy_admin

from .models import (
    CATEGORIE_IT,
    CATEGORIE_MAN,
    PrioritaTicket,
    StatoTicket,
    Ticket,
    TicketAllegato,
    TicketCommento,
    TicketImpostazioni,
    TipoTicket,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legacy_identity(request) -> tuple[str, str, int | None]:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user:
        name  = (legacy_user.nome or "").strip() or request.user.get_full_name() or request.user.get_username()
        email = (legacy_user.email or "").strip().lower() or (request.user.email or "").strip().lower()
        return name, email, getattr(legacy_user, "id", None)
    name  = request.user.get_full_name() or request.user.get_username()
    email = (request.user.email or "").strip().lower()
    return name, email, None


def _can_open_tickets(request, tipo: str) -> bool:
    """Controlla se l'utente può aprire ticket del tipo dato."""
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    cfg = TicketImpostazioni.objects.filter(tipo=tipo).first()
    if not cfg:
        return True  # no config = open to all
    acl = cfg.acl_apertura or []
    if not acl:
        return True  # empty acl = open to all
    username = request.user.get_username().lower()
    email    = (request.user.email or "").lower()
    return any(v.lower() in (username, email) for v in acl)


def _can_manage_tickets(request, tipo: str | None = None) -> bool:
    """Controlla se l'utente è gestore ticket (IT o MAN o entrambi)."""
    if not request.user.is_authenticated:
        return False
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    tipi = [tipo] if tipo else [TipoTicket.IT, TipoTicket.MAN]
    username = request.user.get_username().lower()
    email    = (request.user.email or "").lower()
    for t in tipi:
        cfg = TicketImpostazioni.objects.filter(tipo=t).first()
        if not cfg:
            continue
        acl = cfg.acl_gestione or []
        if any(v.lower() in (username, email) for v in acl):
            return True
    return False


def _tickets_gestione_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _can_manage_tickets(request):
            return render(request, "core/pages/forbidden.html", status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


def _json_err(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": msg}, status=status)


def _get_assets_for_select() -> list[dict]:
    """Carica asset attivi per il datalist nel form."""
    try:
        from assets.models import Asset
        assets = (
            Asset.objects.filter(status__in=["IN_USE", "IN_STOCK"])
            .select_related("asset_category")
            .order_by("name")[:500]
        )
        return [
            {
                "id": asset.id,
                "name": asset.name,
                "asset_tag": asset.asset_tag,
                "asset_type": asset.asset_type,
                "asset_type_label": asset.get_asset_type_display(),
                "asset_category": asset.asset_category.label if asset.asset_category_id else "",
                "manufacturer": asset.manufacturer or "",
                "model": asset.model or "",
                "serial_number": asset.serial_number or "",
                "reparto": asset.reparto or "",
            }
            for asset in assets
        ]
    except Exception:
        return []


def _get_fornitori_for_select() -> list[dict]:
    """Carica fornitori attivi per la delega."""
    try:
        from anagrafica.models import Fornitore
        return list(
            Fornitore.objects.filter(is_active=True)
            .values("id", "ragione_sociale")
            .order_by("ragione_sociale")[:200]
        )
    except Exception:
        return []


def _ticket_form_context(tipo: str = "", error: str = "", form_data=None) -> dict:
    return {
        "error": error,
        "tipo": tipo,
        "categorie_it": CATEGORIE_IT,
        "categorie_man": CATEGORIE_MAN,
        "assets_list": _get_assets_for_select(),
        "priorita_list": PrioritaTicket.choices,
        "tipi": TipoTicket.choices,
        "form_data": form_data,
    }


def _ticket_access_flags(request, ticket: Ticket) -> dict:
    name, email, legacy_id = _legacy_identity(request)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = bool(legacy_user and is_legacy_admin(legacy_user))
    is_gestore = _can_manage_tickets(request, ticket.tipo)
    is_richiedente = (
        (legacy_id and ticket.richiedente_legacy_user_id == legacy_id)
        or ticket.richiedente_nome == name
        or ticket.richiedente_email.lower() == email.lower()
    )
    return {
        "name": name,
        "email": email,
        "legacy_id": legacy_id,
        "is_admin": is_admin,
        "is_gestore": is_gestore,
        "is_richiedente": is_richiedente,
    }


def _draw_ticket_pdf_header(pdf: canvas.Canvas, ticket: Ticket, *, page_width: float, page_height: float) -> float:
    margin_x = 18 * mm
    top_y = page_height - 18 * mm

    pdf.setFillColor(HexColor("#0369a1"))
    pdf.roundRect(margin_x, top_y - 20 * mm, page_width - (2 * margin_x), 18 * mm, 5 * mm, fill=1, stroke=0)
    pdf.setFillColor(HexColor("#ffffff"))
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin_x + 8 * mm, top_y - 8 * mm, "Report Ticket")
    pdf.setFont("Helvetica", 10)
    pdf.drawRightString(page_width - margin_x - 8 * mm, top_y - 8 * mm, ticket.numero_ticket)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(margin_x + 8 * mm, top_y - 14 * mm, "Example Organization - Documento di riferimento")
    return top_y - 28 * mm


def _draw_ticket_pdf_meta(pdf: canvas.Canvas, ticket: Ticket, *, x: float, y: float, width: float) -> float:
    row_height = 8 * mm
    items = [
        ("Tipo", ticket.label_tipo),
        ("Categoria", ticket.label_categoria),
        ("Priorita", ticket.label_priorita),
        ("Stato", ticket.label_stato),
        ("Sicurezza", "Si" if ticket.incide_sicurezza else "No"),
        ("Apertura", ticket.created_at.strftime("%d/%m/%Y %H:%M") if ticket.created_at else "-"),
        ("Chiusura", ticket.closed_at.strftime("%d/%m/%Y %H:%M") if ticket.closed_at else "-"),
        ("Richiedente", ticket.richiedente_nome or "-"),
        ("Assegnato a", ticket.assegnato_a or "-"),
    ]

    current_y = y
    for label, value in items:
        pdf.setFillColor(HexColor("#f8fafc"))
        pdf.setStrokeColor(HexColor("#e2e8f0"))
        pdf.roundRect(x, current_y - row_height, width, row_height - 1.5 * mm, 2 * mm, fill=1, stroke=1)
        pdf.setFillColor(HexColor("#64748b"))
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x + 3 * mm, current_y - 5.4 * mm, label.upper())
        pdf.setFillColor(HexColor("#0f172a"))
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(x + width - 3 * mm, current_y - 5.4 * mm, str(value)[:80])
        current_y -= row_height
    return current_y


def _draw_ticket_pdf_multiline(
    pdf: canvas.Canvas,
    *,
    ticket: Ticket,
    title: str,
    text: str,
    x: float,
    y: float,
    width: float,
) -> float:
    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x, y, title)
    current_y = y - 6 * mm
    pdf.setFont("Helvetica", 9)
    pdf.setFillColor(HexColor("#334155"))
    max_chars = max(40, int(width / 2.4))
    raw_lines = (text or "-").splitlines() or ["-"]
    wrapped_lines: list[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip() or " "
        while len(line) > max_chars:
            split_at = line.rfind(" ", 0, max_chars)
            if split_at < 20:
                split_at = max_chars
            wrapped_lines.append(line[:split_at].rstrip())
            line = line[split_at:].lstrip()
        wrapped_lines.append(line)

    for line in wrapped_lines:
        pdf.drawString(x, current_y, line)
        current_y -= 4.5 * mm
        if current_y < 24 * mm:
            pdf.showPage()
            page_width, page_height = A4
            current_y = _draw_ticket_pdf_header(pdf, ticket, page_width=page_width, page_height=page_height)
    return current_y


def _ticket_pdf_response(ticket: Ticket, *, commenti, allegati, include_internal: bool) -> HttpResponse:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_width, page_height = A4
    pdf.setTitle(f"Report {ticket.numero_ticket}")
    pdf.setAuthor("Portale Applicativo")
    pdf.setSubject(f"Ticket {ticket.numero_ticket}")

    current_y = _draw_ticket_pdf_header(pdf, ticket, page_width=page_width, page_height=page_height)
    margin_x = 18 * mm
    body_width = page_width - (2 * margin_x)

    pdf.setFillColor(HexColor("#0f172a"))
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(margin_x, current_y, ticket.titolo[:90])
    current_y -= 8 * mm

    current_y = _draw_ticket_pdf_meta(pdf, ticket, x=margin_x, y=current_y, width=body_width)
    current_y -= 4 * mm

    asset_label = "-"
    if ticket.asset_id and ticket.asset:
        asset_label = f"{ticket.asset.name} [{ticket.asset.asset_tag}]"
    elif ticket.asset_descrizione_libera:
        asset_label = ticket.asset_descrizione_libera

    current_y = _draw_ticket_pdf_multiline(
        pdf,
        ticket=ticket,
        title="Asset coinvolto",
        text=asset_label,
        x=margin_x,
        y=current_y,
        width=body_width,
    )
    current_y -= 4 * mm

    current_y = _draw_ticket_pdf_multiline(
        pdf,
        ticket=ticket,
        title="Descrizione",
        text=ticket.descrizione,
        x=margin_x,
        y=current_y,
        width=body_width,
    )
    current_y -= 4 * mm

    allegati_text = "\n".join(f"- {a.nome_originale}" for a in allegati) if allegati else "Nessun allegato"
    current_y = _draw_ticket_pdf_multiline(
        pdf,
        ticket=ticket,
        title=f"Allegati ({len(allegati)})",
        text=allegati_text,
        x=margin_x,
        y=current_y,
        width=body_width,
    )
    current_y -= 4 * mm

    comment_lines = []
    for c in commenti:
        prefix = "[Interna] " if include_internal and c.is_interno else ""
        comment_lines.append(
            f"- {c.created_at.strftime('%d/%m/%Y %H:%M')} | {prefix}{c.autore_nome}: {c.testo.replace(chr(10), ' ')}"
        )
    current_y = _draw_ticket_pdf_multiline(
        pdf,
        ticket=ticket,
        title=f"Commenti ({len(commenti)})",
        text="\n".join(comment_lines) if comment_lines else "Nessun commento",
        x=margin_x,
        y=current_y,
        width=body_width,
    )

    pdf.showPage()
    pdf.save()

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{ticket.numero_ticket}.pdf"'
    response.write(buffer.getvalue())
    return response


# ---------------------------------------------------------------------------
# Dashboard utente (miei ticket)
# ---------------------------------------------------------------------------

@login_required
def ticket_dashboard(request):
    name, email, legacy_id = _legacy_identity(request)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin    = bool(legacy_user and is_legacy_admin(legacy_user))
    is_gestore  = _can_manage_tickets(request)

    qs = Ticket.objects.all()
    if not is_admin and not is_gestore:
        # Utente normale: vede solo i propri ticket
        qs = qs.filter(richiedente_legacy_user_id=legacy_id) if legacy_id else qs.filter(richiedente_nome=name)

    # Filtri GET
    tipo_f   = request.GET.get("tipo", "").strip().upper()
    stato_f  = request.GET.get("stato", "").strip().upper()
    prio_f   = request.GET.get("priorita", "").strip().upper()
    cerca_f  = request.GET.get("q", "").strip()

    if tipo_f  in (TipoTicket.IT, TipoTicket.MAN):
        qs = qs.filter(tipo=tipo_f)
    if stato_f in dict(StatoTicket.choices):
        qs = qs.filter(stato=stato_f)
    if prio_f  in dict(PrioritaTicket.choices):
        qs = qs.filter(priorita=prio_f)
    if cerca_f:
        qs = qs.filter(titolo__icontains=cerca_f) | qs.filter(numero_ticket__icontains=cerca_f)

    qs = qs.order_by("-created_at")

    can_open_it  = _can_open_tickets(request, TipoTicket.IT)
    can_open_man = _can_open_tickets(request, TipoTicket.MAN)

    ctx = {
        "tickets":       qs,
        "is_admin":      is_admin,
        "is_gestore":    is_gestore,
        "can_open_it":   can_open_it,
        "can_open_man":  can_open_man,
        "stati":         StatoTicket.choices,
        "priorita_list": PrioritaTicket.choices,
        "tipi":          TipoTicket.choices,
        "filtro_tipo":   tipo_f,
        "filtro_stato":  stato_f,
        "filtro_prio":   prio_f,
        "filtro_cerca":  cerca_f,
        # KPI
        "n_aperte":      Ticket.objects.filter(stato=StatoTicket.APERTA).count(),
        "n_urgenti":     Ticket.objects.filter(priorita=PrioritaTicket.URGENTE, stato__in=[StatoTicket.APERTA, StatoTicket.IN_CARICO]).count(),
        "n_in_carico":   Ticket.objects.filter(stato=StatoTicket.IN_CARICO).count(),
    }
    return render(request, "tickets/pages/dashboard.html", ctx)


# ---------------------------------------------------------------------------
# Creazione ticket
# ---------------------------------------------------------------------------

@login_required
def ticket_nuovo(request):
    tipo = request.GET.get("tipo", "").strip().upper()
    if tipo not in (TipoTicket.IT, TipoTicket.MAN):
        tipo = ""

    if tipo and not _can_open_tickets(request, tipo):
        return render(request, "core/pages/forbidden.html", status=403)

    name, email, legacy_id = _legacy_identity(request)

    if request.method == "POST":
        tipo_post = (request.POST.get("tipo") or "").strip().upper()
        if tipo_post not in (TipoTicket.IT, TipoTicket.MAN):
            return render(
                request,
                "tickets/pages/nuovo.html",
                _ticket_form_context(tipo=tipo_post, error="Tipo ticket non valido.", form_data=request.POST),
            )

        if not _can_open_tickets(request, tipo_post):
            return render(request, "core/pages/forbidden.html", status=403)

        titolo      = (request.POST.get("titolo") or "").strip()[:300]
        descrizione = (request.POST.get("descrizione") or "").strip()
        categoria   = (request.POST.get("categoria") or "").strip()[:30]
        priorita    = (request.POST.get("priorita") or PrioritaTicket.MEDIA).strip()
        sicurezza_raw = (request.POST.get("incide_sicurezza") or "").strip()
        sicurezza   = sicurezza_raw == "1"
        asset_id    = (request.POST.get("asset_id") or "").strip()
        asset_libera= (request.POST.get("asset_descrizione_libera") or "").strip()[:300]

        if sicurezza_raw not in {"0", "1"}:
            return render(
                request,
                "tickets/pages/nuovo.html",
                _ticket_form_context(
                    tipo=tipo_post,
                    error="Indica se il problema incide sulla sicurezza sul lavoro prima di proseguire.",
                    form_data=request.POST,
                ),
            )

        if not titolo or not descrizione or not categoria:
            return render(
                request,
                "tickets/pages/nuovo.html",
                _ticket_form_context(
                    tipo=tipo_post,
                    error="Titolo, descrizione e categoria sono obbligatori.",
                    form_data=request.POST,
                ),
            )

        if priorita not in dict(PrioritaTicket.choices):
            priorita = PrioritaTicket.MEDIA

        asset_obj = None
        if asset_id:
            try:
                from assets.models import Asset
                asset_obj = Asset.objects.filter(pk=int(asset_id)).first()
            except (ValueError, TypeError):
                pass

        ticket = Ticket(
            tipo=tipo_post,
            titolo=titolo,
            descrizione=descrizione,
            categoria=categoria,
            priorita=priorita,
            incide_sicurezza=sicurezza,
            asset=asset_obj,
            asset_descrizione_libera=asset_libera,
            richiedente_nome=name,
            richiedente_email=email,
            richiedente_legacy_user_id=legacy_id,
        )
        ticket.save()

        # Allegati
        for f in request.FILES.getlist("allegati"):
            TicketAllegato.objects.create(
                ticket=ticket,
                file=f,
                nome_originale=f.name[:255],
                tipo_mime=(f.content_type or "")[:100],
                uploaded_by_nome=name,
            )

        # Push SP (fire-and-forget, non blocca)
        try:
            _push_ticket_to_sharepoint(ticket)
        except Exception:
            pass

        return redirect("tickets:detail", pk=ticket.pk)

    return render(request, "tickets/pages/nuovo.html", _ticket_form_context(tipo=tipo))


# ---------------------------------------------------------------------------
# Dettaglio ticket (richiedente)
# ---------------------------------------------------------------------------

@login_required
def ticket_detail(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)
    access = _ticket_access_flags(request, ticket)
    is_admin = access["is_admin"]
    is_gestore = access["is_gestore"]
    is_richiedente = access["is_richiedente"]
    if not (is_richiedente or is_gestore or is_admin):
        return render(request, "core/pages/forbidden.html", status=403)

    commenti = ticket.commenti.all()
    if not (is_gestore or is_admin):
        commenti = commenti.filter(is_interno=False)

    ctx = {
        "ticket":        ticket,
        "commenti":      commenti,
        "allegati":      ticket.allegati.all(),
        "is_gestore":    is_gestore,
        "is_admin":      is_admin,
        "is_richiedente":is_richiedente,
    }
    return render(request, "tickets/pages/detail.html", ctx)


@login_required
def ticket_pdf(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)
    access = _ticket_access_flags(request, ticket)
    if not (access["is_richiedente"] or access["is_gestore"] or access["is_admin"]):
        return render(request, "core/pages/forbidden.html", status=403)

    include_internal = bool(access["is_gestore"] or access["is_admin"])
    commenti = ticket.commenti.all()
    if not include_internal:
        commenti = commenti.filter(is_interno=False)

    return _ticket_pdf_response(
        ticket,
        commenti=list(commenti),
        allegati=list(ticket.allegati.all()),
        include_internal=include_internal,
    )


# ---------------------------------------------------------------------------
# Gestione lista (team)
# ---------------------------------------------------------------------------

@_tickets_gestione_required
def ticket_gestione_list(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin    = bool(legacy_user and is_legacy_admin(legacy_user))

    qs = Ticket.objects.all()

    # Filtri GET
    tipo_f   = request.GET.get("tipo", "").strip().upper()
    stato_f  = request.GET.get("stato", "").strip().upper()
    prio_f   = request.GET.get("priorita", "").strip().upper()
    cerca_f  = request.GET.get("q", "").strip()
    ass_f    = request.GET.get("assegnato", "").strip()

    if tipo_f  in (TipoTicket.IT, TipoTicket.MAN):
        qs = qs.filter(tipo=tipo_f)
    if stato_f in dict(StatoTicket.choices):
        qs = qs.filter(stato=stato_f)
    if prio_f  in dict(PrioritaTicket.choices):
        qs = qs.filter(priorita=prio_f)
    if cerca_f:
        qs = qs.filter(titolo__icontains=cerca_f) | qs.filter(numero_ticket__icontains=cerca_f) | qs.filter(richiedente_nome__icontains=cerca_f)
    if ass_f:
        if ass_f == "__none__":
            qs = qs.filter(assegnato_a="")
        else:
            qs = qs.filter(assegnato_a__icontains=ass_f)

    qs = qs.order_by("-created_at")

    ctx = {
        "tickets":       qs,
        "is_admin":      is_admin,
        "stati":         StatoTicket.choices,
        "priorita_list": PrioritaTicket.choices,
        "tipi":          TipoTicket.choices,
        "filtro_tipo":   tipo_f,
        "filtro_stato":  stato_f,
        "filtro_prio":   prio_f,
        "filtro_cerca":  cerca_f,
        "filtro_ass":    ass_f,
        # KPI
        "n_aperte":    Ticket.objects.filter(stato=StatoTicket.APERTA).count(),
        "n_in_carico": Ticket.objects.filter(stato=StatoTicket.IN_CARICO).count(),
        "n_urgenti":   Ticket.objects.filter(priorita=PrioritaTicket.URGENTE, stato__in=[StatoTicket.APERTA, StatoTicket.IN_CARICO]).count(),
        "n_risolti":   Ticket.objects.filter(stato=StatoTicket.RISOLTO).count(),
    }
    return render(request, "tickets/pages/gestione_list.html", ctx)


# ---------------------------------------------------------------------------
# Gestione dettaglio (team)
# ---------------------------------------------------------------------------

@_tickets_gestione_required
def ticket_gestione_detail(request, pk: int):
    ticket = get_object_or_404(Ticket, pk=pk)
    name, email, legacy_id = _legacy_identity(request)
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin    = bool(legacy_user and is_legacy_admin(legacy_user))

    cfg         = TicketImpostazioni.get_or_create_for(ticket.tipo)
    fornitori   = _get_fornitori_for_select()

    ctx = {
        "ticket":     ticket,
        "commenti":   ticket.commenti.all(),
        "allegati":   ticket.allegati.all(),
        "cfg":        cfg,
        "stati":      StatoTicket.choices,
        "fornitori":  fornitori,
        "is_admin":   is_admin,
        "current_user_name": name,
        "current_user_email": email,
    }
    return render(request, "tickets/pages/gestione_detail.html", ctx)


# ---------------------------------------------------------------------------
# Impostazioni admin
# ---------------------------------------------------------------------------

@login_required
def ticket_impostazioni(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        return render(request, "core/pages/forbidden.html", status=403)

    cfg_it  = TicketImpostazioni.get_or_create_for(TipoTicket.IT)
    cfg_man = TicketImpostazioni.get_or_create_for(TipoTicket.MAN)

    ctx = {
        "cfg_it":  cfg_it,
        "cfg_man": cfg_man,
        "tipi":    TipoTicket.choices,
        "categorie_it":  CATEGORIE_IT,
        "categorie_man": CATEGORIE_MAN,
    }
    return render(request, "tickets/pages/impostazioni.html", ctx)


# ---------------------------------------------------------------------------
# SharePoint push (stub — da configurare con list IDs reali)
# ---------------------------------------------------------------------------

def _push_ticket_to_sharepoint(ticket: Ticket) -> None:
    """Push ticket a SP. Stub — da implementare quando disponibili list IDs."""
    try:
        from core.sharepoint_utils import get_sp_headers, get_sp_site_url
        import requests as req_lib

        cfg = TicketImpostazioni.objects.filter(tipo=ticket.tipo).first()
        if not cfg or not cfg.sharepoint_list_id:
            return

        headers = get_sp_headers()
        site    = get_sp_site_url()
        url     = f"{site}/_api/web/lists('{cfg.sharepoint_list_id}')/items"

        payload = {
            "__metadata": {"type": f"SP.Data.ListItem"},
            "Title":          ticket.titolo,
            "NumeroTicket":   ticket.numero_ticket,
            "Categoria":      ticket.categoria,
            "Priorita":       ticket.priorita,
            "IncideSicurezza": ticket.incide_sicurezza,
            "Stato":          ticket.stato,
            "Richiedente":    ticket.richiedente_nome,
            "Descrizione":    ticket.descrizione,
            "DataApertura":   ticket.created_at.isoformat() if ticket.created_at else "",
        }
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        if resp.ok:
            data = resp.json()
            sp_id = str(data.get("d", {}).get("ID") or data.get("ID") or "")
            if sp_id:
                Ticket.objects.filter(pk=ticket.pk).update(sharepoint_item_id=sp_id)
    except Exception:
        pass


def _update_ticket_sharepoint(ticket: Ticket) -> None:
    """Aggiorna item esistente su SP (stato, assegnazione)."""
    try:
        if not ticket.sharepoint_item_id:
            return
        from core.sharepoint_utils import get_sp_headers, get_sp_site_url
        import requests as req_lib

        cfg = TicketImpostazioni.objects.filter(tipo=ticket.tipo).first()
        if not cfg or not cfg.sharepoint_list_id:
            return

        headers = get_sp_headers()
        headers.update({"X-HTTP-Method": "MERGE", "IF-MATCH": "*"})
        site = get_sp_site_url()
        url  = f"{site}/_api/web/lists('{cfg.sharepoint_list_id}')/items({ticket.sharepoint_item_id})"

        payload = {
            "__metadata": {"type": "SP.Data.ListItem"},
            "Stato":       ticket.stato,
            "AssegnatoA":  ticket.assegnato_a,
            "DataChiusura": ticket.closed_at.isoformat() if ticket.closed_at else None,
        }
        req_lib.patch(url, json=payload, headers=headers, timeout=10)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# API: commento
# ---------------------------------------------------------------------------

@require_POST
@login_required
def api_commento(request):
    try:
        payload    = json.loads(request.body)
        ticket_id  = int(payload.get("ticket_id") or 0)
        testo      = (payload.get("testo") or "").strip()
        is_interno = bool(payload.get("is_interno"))
    except (json.JSONDecodeError, ValueError):
        return _json_err("Dati non validi")

    ticket = get_object_or_404(Ticket, pk=ticket_id)
    name, email, legacy_id = _legacy_identity(request)

    is_gestore = _can_manage_tickets(request, ticket.tipo)
    legacy_user= getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin   = bool(legacy_user and is_legacy_admin(legacy_user))

    # Solo gestori possono scrivere note interne
    if is_interno and not (is_gestore or is_admin):
        return _json_err("Non autorizzato", 403)

    # Verifica che l'utente possa commentare su questo ticket
    is_richiedente = (
        (legacy_id and ticket.richiedente_legacy_user_id == legacy_id)
        or ticket.richiedente_nome == name
        or ticket.richiedente_email.lower() == email.lower()
    )
    if not (is_richiedente or is_gestore or is_admin):
        return _json_err("Non autorizzato", 403)

    if not testo:
        return _json_err("Testo vuoto")

    c = TicketCommento.objects.create(
        ticket=ticket,
        autore_nome=name,
        autore_email=email,
        testo=testo,
        is_interno=is_interno,
    )
    return JsonResponse({
        "ok": True,
        "commento_id": c.pk,
        "autore_nome": c.autore_nome,
        "testo": c.testo,
        "is_interno": c.is_interno,
        "created_at": c.created_at.strftime("%d/%m/%Y %H:%M"),
    })


# ---------------------------------------------------------------------------
# API: allegato upload
# ---------------------------------------------------------------------------

@require_POST
@login_required
def api_allegato(request):
    ticket_id = int(request.POST.get("ticket_id") or 0)
    ticket    = get_object_or_404(Ticket, pk=ticket_id)
    name, email, legacy_id = _legacy_identity(request)

    is_gestore = _can_manage_tickets(request, ticket.tipo)
    legacy_user= getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin   = bool(legacy_user and is_legacy_admin(legacy_user))
    is_richiedente = (
        (legacy_id and ticket.richiedente_legacy_user_id == legacy_id)
        or ticket.richiedente_nome == name
    )
    if not (is_richiedente or is_gestore or is_admin):
        return _json_err("Non autorizzato", 403)

    f = request.FILES.get("file")
    if not f:
        return _json_err("Nessun file")

    allegato = TicketAllegato.objects.create(
        ticket=ticket,
        file=f,
        nome_originale=f.name[:255],
        tipo_mime=(f.content_type or "")[:100],
        uploaded_by_nome=name,
    )
    return JsonResponse({
        "ok": True,
        "allegato_id": allegato.pk,
        "nome": allegato.nome_originale,
        "url":  allegato.file.url,
    })


# ---------------------------------------------------------------------------
# API: aggiorna stato (solo gestori)
# ---------------------------------------------------------------------------

@require_POST
@_tickets_gestione_required
def api_stato(request):
    try:
        payload   = json.loads(request.body)
        ticket_id = int(payload.get("ticket_id") or 0)
        nuovo_stato = (payload.get("stato") or "").strip().upper()
        nota        = (payload.get("nota") or "").strip()
    except (json.JSONDecodeError, ValueError):
        return _json_err("Dati non validi")

    if nuovo_stato not in dict(StatoTicket.choices):
        return _json_err("Stato non valido")

    ticket = get_object_or_404(Ticket, pk=ticket_id)
    vecchio = ticket.stato
    ticket.stato = nuovo_stato

    if nuovo_stato in (StatoTicket.CHIUSO, StatoTicket.ANNULLATO, StatoTicket.RISOLTO):
        if not ticket.closed_at:
            ticket.closed_at = tz_now()
    else:
        ticket.closed_at = None

    ticket.save(update_fields=["stato", "closed_at", "updated_at"])

    name, email, _ = _legacy_identity(request)

    # Commento automatico cambio stato
    label_stato = dict(StatoTicket.choices).get(nuovo_stato, nuovo_stato)
    testo_auto  = f"Stato aggiornato: {dict(StatoTicket.choices).get(vecchio, vecchio)} → {label_stato}"
    if nota:
        testo_auto += f"\n{nota}"
    TicketCommento.objects.create(
        ticket=ticket,
        autore_nome=name,
        autore_email=email,
        testo=testo_auto,
        is_interno=True,
    )

    try:
        _update_ticket_sharepoint(ticket)
    except Exception:
        pass

    return JsonResponse({"ok": True, "stato": nuovo_stato, "label": label_stato})


# ---------------------------------------------------------------------------
# API: assegna tecnico (solo gestori)
# ---------------------------------------------------------------------------

@require_POST
@_tickets_gestione_required
def api_assegna(request):
    try:
        payload       = json.loads(request.body)
        ticket_id     = int(payload.get("ticket_id") or 0)
        assegnato_a   = (payload.get("assegnato_a") or "").strip()[:200]
        assegnato_email = (payload.get("assegnato_email") or "").strip()[:200]
        fornitore_id  = payload.get("fornitore_id")
    except (json.JSONDecodeError, ValueError):
        return _json_err("Dati non validi")

    ticket = get_object_or_404(Ticket, pk=ticket_id)
    ticket.assegnato_a    = assegnato_a
    ticket.assegnato_email= assegnato_email

    if fornitore_id:
        try:
            from anagrafica.models import Fornitore
            ticket.delegato_fornitore = Fornitore.objects.filter(pk=int(fornitore_id)).first()
        except (ValueError, TypeError):
            ticket.delegato_fornitore = None
    else:
        ticket.delegato_fornitore = None

    if ticket.stato == StatoTicket.APERTA and assegnato_a:
        ticket.stato = StatoTicket.IN_CARICO

    ticket.save(update_fields=["assegnato_a", "assegnato_email", "delegato_fornitore", "stato", "updated_at"])

    name, email, _ = _legacy_identity(request)
    desc = assegnato_a or (ticket.delegato_fornitore.ragione_sociale if ticket.delegato_fornitore else "—")
    TicketCommento.objects.create(
        ticket=ticket,
        autore_nome=name,
        autore_email=email,
        testo=f"Ticket assegnato a: {desc}",
        is_interno=True,
    )

    try:
        _update_ticket_sharepoint(ticket)
    except Exception:
        pass

    return JsonResponse({
        "ok": True,
        "assegnato_a": ticket.assegnato_a,
        "stato": ticket.stato,
    })


# ---------------------------------------------------------------------------
# API: salva impostazioni (solo admin)
# ---------------------------------------------------------------------------

@require_POST
@login_required
def api_impostazioni(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        return _json_err("Non autorizzato", 403)

    try:
        payload = json.loads(request.body)
        tipo    = (payload.get("tipo") or "").strip().upper()
    except json.JSONDecodeError:
        return _json_err("JSON non valido")

    if tipo not in (TipoTicket.IT, TipoTicket.MAN):
        return _json_err("Tipo non valido")

    cfg = TicketImpostazioni.get_or_create_for(tipo)
    cfg.sharepoint_list_id = (payload.get("sharepoint_list_id") or "").strip()[:100]

    # team_gestori: lista di {nome, email}
    raw_team = payload.get("team_gestori")
    if isinstance(raw_team, list):
        cfg.team_gestori = [
            {"nome": (m.get("nome") or "").strip(), "email": (m.get("email") or "").strip()}
            for m in raw_team if isinstance(m, dict)
        ]

    # acl_apertura / acl_gestione: lista di stringhe username/email
    for field in ("acl_apertura", "acl_gestione"):
        raw = payload.get(field)
        if isinstance(raw, list):
            setattr(cfg, field, [str(v).strip() for v in raw if str(v).strip()])

    cfg.save()
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# API: ricerca utenti (per autocomplete impostazioni)
# ---------------------------------------------------------------------------

@login_required
def api_cerca_utenti(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        return _json_err("Non autorizzato", 403)

    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    results = []
    try:
        from core.legacy_models import AnagraficaDipendente, UtenteLegacy
        from django.db.models import Q

        # Cerca in anagrafica_dipendenti (nome + cognome) e utenti (email/UPN)
        qs = AnagraficaDipendente.objects.filter(
            Q(nome__icontains=q) | Q(cognome__icontains=q) |
            Q(email__icontains=q) | Q(aliasusername__icontains=q) |
            Q(email_notifica__icontains=q)
        ).select_related("utente").order_by("cognome", "nome")[:20]

        for a in qs:
            nome_completo = f"{(a.nome or '').strip()} {(a.cognome or '').strip()}".strip()
            username      = (a.aliasusername or "").strip()
            email_login   = (a.email or "").strip()          # UPN (login)
            email_notifica= (a.email_notifica or "").strip() # email reale
            results.append({
                "nome":     nome_completo,
                "username": username,
                "email":    email_login,
                "email_notifica": email_notifica,
                "label":    f"{nome_completo}" + (f" — {username}" if username else ""),
            })
    except Exception:
        # Fallback su Django auth users
        from django.contrib.auth import get_user_model
        User = get_user_model()
        qs = User.objects.filter(
            username__icontains=q
        ).order_by("last_name", "first_name")[:20]
        for u in qs:
            nome = f"{u.first_name} {u.last_name}".strip() or u.username
            results.append({
                "nome":     nome,
                "username": u.username,
                "email":    u.email or "",
                "email_notifica": u.email or "",
                "label":    f"{nome} — {u.username}",
            })

    return JsonResponse({"results": results})


# ---------------------------------------------------------------------------
# API: test connessione SharePoint (verifica list ID)
# ---------------------------------------------------------------------------

@require_POST
@login_required
def api_test_sp(request):
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not (legacy_user and is_legacy_admin(legacy_user)):
        return _json_err("Non autorizzato", 403)

    try:
        payload = json.loads(request.body)
        list_id = (payload.get("sharepoint_list_id") or "").strip()
    except json.JSONDecodeError:
        return _json_err("JSON non valido")

    if not list_id:
        return _json_err("List ID vuoto")

    try:
        import configparser, pathlib, os
        from core.graph_utils import acquire_graph_token, is_placeholder_value

        def _cfg(section: str, key: str, *env_keys: str) -> str:
            for ek in env_keys:
                v = os.environ.get(ek, "")
                if v:
                    return v
            try:
                ini = pathlib.Path(__file__).resolve().parents[2] / "config.ini"
                cfg = configparser.ConfigParser()
                cfg.read(str(ini), encoding="utf-8")
                return cfg.get(section, key, fallback="")
            except Exception:
                return ""

        tenant_id     = _cfg("AZIENDA", "tenant_id",     "GRAPH_TENANT_ID",     "AZURE_TENANT_ID")
        client_id     = _cfg("AZIENDA", "client_id",     "GRAPH_CLIENT_ID",     "AZURE_CLIENT_ID")
        client_secret = _cfg("AZIENDA", "client_secret", "GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
        site_id       = _cfg("AZIENDA", "site_id",       "GRAPH_SITE_ID")

        if any(is_placeholder_value(v) or not v for v in [tenant_id, client_id, client_secret, site_id]):
            return _json_err("Configurazione Graph incompleta in config.ini (tenant_id/client_id/client_secret/site_id)")

        import requests as req_lib
        token   = acquire_graph_token(tenant_id, client_id, client_secret)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # GET lista — titolo
        url_list = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}"
        r = req_lib.get(url_list, headers=headers, timeout=10)
        if r.status_code == 404:
            return _json_err("Lista non trovata (404). Verifica il List ID.")
        if r.status_code == 403:
            return _json_err("Permessi insufficienti (403). Verifica che l'app Azure abbia accesso alla lista.")
        if not r.ok:
            return _json_err(f"Errore Graph {r.status_code}: {r.text[:200]}")

        list_title = r.json().get("displayName") or r.json().get("name") or list_id

        # Conta item (prima pagina + @odata.count)
        r2 = req_lib.get(
            f"{url_list}/items?$top=1&$count=true",
            headers={**headers, "ConsistencyLevel": "eventual"},
            timeout=10,
        )
        item_count = r2.json().get("@odata.count", "—") if r2.ok else "—"

        return JsonResponse({"ok": True, "list_title": list_title, "item_count": item_count})

    except Exception as e:
        return _json_err(str(e))
