"""Manutenzione > Verifiche periodiche: verifiche sugli impianti.

Modulo separato da ``views.py`` come ``views_maintenance``: dipende da ``views`` e
``views_maintenance`` (helper di shell e gate), mai il contrario.
Dominio in ``services/periodic_checks.py``; vedi docs/ai/VERIFICHE_PERIODICHE.md.
"""
from __future__ import annotations

import mimetypes
import re
from datetime import date
from collections import OrderedDict
from pathlib import Path

from django.contrib import messages
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

from .forms_verifiche import (
    PeriodicCheckIntakeConfigForm,
    PeriodicCheckRegisterForm,
    PeriodicCheckSystemForm,
    PeriodicCheckTypeForm,
    WorkOrderFromResultForm,
)
from .models import (
    Asset,
    PeriodicCheckAttachment,
    PeriodicCheckIntakeConfig,
    PeriodicCheckIntakeLog,
    PeriodicCheckLayout,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
    WorkOrder,
)
from .services import periodic_checks as checks
from .services import periodic_intake, periodic_stats
from .views import _assets_shell_context, _validate_workorder_attachment_uploads
from .views_maintenance import can_execute_maintenance, can_manage_maintenance_plans

AUDIT_OGGETTO = "assets.periodic_check_session"

_STATE_ORDER = {checks.STATE_OVERDUE: 0, checks.STATE_DUE_SOON: 1, checks.STATE_UNSCHEDULED: 2, checks.STATE_OK: 3}


def _deny(request: HttpRequest, message: str, fallback: str = "assets:periodic_check_list"):
    messages.error(request, message)
    return redirect(fallback)


def _render(request: HttpRequest, template: str, context: dict) -> HttpResponse:
    return render(
        request,
        f"assets/pages/{template}",
        {
            **_assets_shell_context(request),
            "can_register": can_execute_maintenance(request),
            "can_configure": can_manage_maintenance_plans(request),
            **context,
        },
    )


def _days_label(due, today) -> str:
    if due is None:
        return ""
    days = (due - today).days
    if days == 0:
        return "oggi"
    if days < 0:
        return "ieri" if days == -1 else f"{-days} giorni fa"
    return "domani" if days == 1 else f"tra {days} giorni"


def _last_sessions_by_type(type_ids) -> dict[int, PeriodicCheckSession]:
    last: dict[int, PeriodicCheckSession] = {}
    qs = (
        PeriodicCheckSession.objects.filter(check_type_id__in=type_ids, status=PeriodicCheckSession.STATUS_CONFIRMED)
        .order_by("check_type_id", "-performed_on", "-id")
    )
    for session in qs:
        last.setdefault(session.check_type_id, session)
    return last


@login_required
def periodic_check_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    show = (request.GET.get("stato") or "").strip()
    types = list(
        PeriodicCheckType.objects.select_related("system", "supplier")
        .filter(is_active=True, system__is_active=True)
        .annotate(
            drafts=Count("sessions", filter=Q(sessions__status=PeriodicCheckSession.STATUS_DRAFT), distinct=True),
            issued=Count("sessions", filter=Q(sessions__status=PeriodicCheckSession.STATUS_ISSUED), distinct=True),
            has_layout=Count("layouts", filter=Q(layouts__is_active=True), distinct=True),
        )
    )
    last = _last_sessions_by_type([t.id for t in types])
    # Rilievi aperti: solo dell'ultima verifica con esiti, come nella scheda (le precedenti sono superate).
    latest_ids = {}
    for session in (
        PeriodicCheckSession.objects.filter(check_type__in=types, status=PeriodicCheckSession.STATUS_CONFIRMED)
        .exclude(outcome=PeriodicCheckSession.OUTCOME_ARCHIVE).order_by("check_type_id", "-performed_on", "-id")
        .only("id", "check_type_id")
    ):
        latest_ids.setdefault(session.check_type_id, session.id)
    open_by_session = dict(
        PeriodicCheckResult.objects.filter(session_id__in=latest_ids.values(), result=PeriodicCheckResult.RESULT_KO,
                                           work_order__isnull=True)
        .values("session_id").annotate(n=Count("id")).values_list("session_id", "n")
    )
    for check_type in types:
        check_type.open_ko = open_by_session.get(latest_ids.get(check_type.id), 0)
    counts = {state: 0 for state in _STATE_ORDER}
    drafts_total = 0
    rows = []
    for check_type in types:
        state = checks.type_state(check_type, today)
        counts[state] += 1
        drafts_total += check_type.drafts
        rows.append({
            "type": check_type,
            "state": state,
            "state_label": checks.STATE_LABELS[state],
            "days_label": _days_label(check_type.next_due_date, today),
            "last": last.get(check_type.id),
        })
    if show in _STATE_ORDER:
        rows = [row for row in rows if row["state"] == show]
    elif show == "bozze":
        rows = [row for row in rows if row["type"].drafts]
    groups: "OrderedDict[int, dict]" = OrderedDict()
    for row in rows:
        system = row["type"].system
        groups.setdefault(system.id, {"system": system, "rows": []})["rows"].append(row)
    return _render(request, "periodic_check_list.html", {
        "page_title": "Verifiche periodiche",
        "groups": list(groups.values()),
        "counts": counts,
        "drafts_total": drafts_total,
        "show": show,
        "today": today,
        "has_types": bool(types),
        "intake_pending": PeriodicCheckIntakeLog.objects.filter(
            outcome__in=[PeriodicCheckIntakeLog.OUTCOME_UNMATCHED, PeriodicCheckIntakeLog.OUTCOME_ERROR]).count(),
    })


@login_required
def periodic_check_type_detail(request: HttpRequest, type_id: int) -> HttpResponse:
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system", "supplier"), pk=type_id)
    sessions = (
        check_type.sessions.select_related("supplier", "created_by")
        .prefetch_related("attachments", Prefetch("results", queryset=PeriodicCheckResult.objects.select_related("work_order")))
        .order_by("-performed_on", "-id")
    )
    if request.method == "POST" and request.POST.get("action") == "layout":
        return _upload_layout(request, check_type)
    tab = request.GET.get("tab") or "panoramica"
    if tab not in {key for key, _label in _TYPE_TABS}:
        tab = "panoramica"
    state = checks.type_state(check_type)
    layout = check_type.active_layout
    context = {
        "page_title": check_type.name,
        "check_type": check_type,
        "items": check_type.items.filter(is_active=True),
        "state": state,
        "state_label": checks.STATE_LABELS[state],
        "is_layout": check_type.method == PeriodicCheckType.METHOD_LAYOUT,
        "layout": layout,
        "layout_points": layout.points.count() if layout else 0,
        "tab": tab,
        "guide": _guide(request, check_type, layout),
        "layout_codes": [p.code for p in layout.points.all()] if layout and tab == "impostazioni" else [],
        "tabs": [
            {"key": key, "label": label, "url": f"?tab={key}", "active": key == tab}
            for key, label in _TYPE_TABS
        ],
    }
    if tab == "panoramica":
        stats = periodic_stats.type_stats(check_type)
        context["stats"] = stats
        context["map"] = _map_context(stats)
        context["trend_bars"] = _trend_bars(stats)
    elif tab == "storico":
        context["sessions"] = sessions
    elif tab == "odl":
        context["work_orders"] = (
            WorkOrder.objects.filter(periodic_check_results__session__check_type=check_type)
            .select_related("asset").distinct().order_by("-opened_at", "-id")
        )
    elif tab == "documenti":
        context["documents"] = (
            PeriodicCheckAttachment.objects.filter(session__check_type=check_type)
            .exclude(original_name="lettura-automatica.png")
            .select_related("session").order_by("-session__performed_on", "-id")
        )
    return _render(request, "periodic_check_type_detail.html", context)


def _guide(request: HttpRequest, check_type: PeriodicCheckType, layout) -> dict:
    """«Come funziona questa verifica»: i passi del suo metodo, cosa e' fatto, cosa manca,
    e il pulsante per farlo. Stessa pagina per tutte le verifiche, passi diversi per metodo."""
    base = reverse("assets:periodic_check_type_detail", args=[check_type.id])
    register_url = reverse("assets:periodic_check_register", args=[check_type.id])
    can_register = can_execute_maintenance(request)
    can_configure = can_manage_maintenance_plans(request)
    sessions = check_type.sessions
    issued = sessions.filter(status=PeriodicCheckSession.STATUS_ISSUED).order_by("-id")
    drafts = sessions.filter(status=PeriodicCheckSession.STATUS_DRAFT).order_by("-id")
    latest = sessions.filter(status=PeriodicCheckSession.STATUS_CONFIRMED).exclude(
        outcome=PeriodicCheckSession.OUTCOME_ARCHIVE).order_by("-performed_on", "-id").first()
    open_ko = (latest.results.filter(result=PeriodicCheckResult.RESULT_KO, work_order__isnull=True).count()
               if latest else 0)
    steps: list[dict] = []

    def step(title, detail, state, action=None):
        steps.append({"n": len(steps) + 1, "title": title, "detail": detail, "state": state, "action": action})

    method = check_type.method
    if method == PeriodicCheckType.METHOD_LAYOUT:
        if layout:
            step("Planimetria", f"Versione {layout.version}: {layout.points.count()} punti riconosciuti.", "done",
                 {"label": "Controlla i punti", "url": f"{base}?tab=impostazioni#punti"})
        else:
            step("Carica la planimetria", "Il PDF vettoriale con i punti numerati: il portale li riconosce da solo.",
                 "todo", {"label": "Carica la planimetria", "url": f"{base}?tab=impostazioni#planimetria"} if can_configure else None)
        step("Stampa il foglio per il tecnico",
             "Il portale crea la verifica e un foglio con il QR: il tecnico segna sulla planimetria "
             f"(evidenziatore = {check_type.category_list[0].lower()}"
             + (f", cerchio a penna = {check_type.category_list[1].lower()}" if len(check_type.category_list) > 1 else "") + ").",
             "ready" if layout else "blocked",
             {"label": "Stampa foglio", "post": reverse("assets:periodic_check_sheet_issue", args=[check_type.id])}
             if layout and can_register else None)
        first_issued = issued.first()
        step("Carica la scansione",
             f"{issued.count()} fogl{'io' if issued.count() == 1 else 'i'} stampat{'o' if issued.count() == 1 else 'i'} in attesa: "
             "apri la verifica e carica il foglio scansionato, il QR la riconosce." if first_issued
             else ("Quando il foglio torna compilato basta scansionarlo nella cartella dello scanner: il portale lo "
                   "riconosce dal QR." if PeriodicCheckIntakeConfig.load().attiva
                   else "Quando il foglio torna compilato, si carica nella verifica creata con la stampa "
                        "(o dalla Cartella scansioni)."),
             "todo" if first_issued else "waiting",
             {"label": "Apri il foglio in attesa", "url": reverse("assets:periodic_check_session_detail", args=[first_issued.id])}
             if first_issued else None)
        first_draft = drafts.first()
        step("Conferma i punti",
             "Il portale propone i punti segnati: correggi, scarta o aggiungi e conferma. La scadenza si ricalcola."
             if not first_draft else f"{drafts.count()} verific{'a' if drafts.count() == 1 else 'he'} da confermare.",
             "todo" if first_draft else "waiting",
             {"label": "Conferma", "url": reverse("assets:periodic_check_session_detail", args=[first_draft.id])}
             if first_draft else None)
    elif method == PeriodicCheckType.METHOD_CHECKLIST:
        count = check_type.items.filter(is_active=True).count()
        if count:
            step("Voci da controllare", f"{count} voci: ognuna si segna OK, non OK o non applicabile.", "done",
                 {"label": "Vedi le voci", "url": f"{base}?tab=impostazioni"})
        else:
            step("Definisci le voci", "Scrivi le voci della checklist, una per riga.", "todo",
                 {"label": "Aggiungi le voci", "url": reverse("assets:periodic_check_type_edit", args=[check_type.id])}
                 if can_configure else None)
        step("Registra la verifica", "Data, tecnico, esito per voce, rapportino firmato allegato.", "ready" if count else "blocked",
             {"label": "Registra", "url": register_url} if can_register and count else None)
    else:
        detail = "Data, esito, rilievi o prescrizioni (uno per riga) e il verbale allegato."
        if method == PeriodicCheckType.METHOD_MEASURES:
            detail += " La lettura automatica delle misure (batterie, tempi di intervento) arrivera' in seguito."
        step("Registra la verifica", detail, "ready", {"label": "Registra", "url": register_url} if can_register else None)
    if latest:
        step("Rilievi → ordini di lavoro",
             f"{open_ko} rilievi dell'ultima verifica ({latest.performed_on:%d/%m/%Y}) senza ordine di lavoro." if open_ko
             else "Nessun rilievo aperto nell'ultima verifica.",
             "todo" if open_ko else "done",
             {"label": "Crea gli OdL", "url": reverse("assets:periodic_check_session_detail", args=[latest.id])} if open_ko else None)
    else:
        step("Rilievi → ordini di lavoro", "Ogni rilievo non conforme diventa un ordine di lavoro dalla pagina della verifica.", "waiting")
    next_step = next((s for s in steps if s["state"] in ("todo", "ready") and s["action"]), None)
    if next_step:
        next_step["is_next"] = True
    return {"steps": steps, "method": check_type.get_method_display()}


_TYPE_TABS = (
    ("panoramica", "Panoramica"),
    ("storico", "Storico verifiche"),
    ("odl", "Ordini di lavoro"),
    ("documenti", "Documenti"),
    ("impostazioni", "Impostazioni"),
)


def _layout_page_size(layout) -> tuple[float, float]:
    key = f"assets:pc-layout-size:{layout.id}"
    size = cache.get(key)
    if size is None:
        import fitz

        with layout.source_pdf.open("rb") as handle, fitz.open(stream=handle.read(), filetype="pdf") as doc:
            rect = doc[layout.page_index].rect
        size = (rect.width, rect.height)
        cache.set(key, size, 60 * 60 * 24 * 30)
    return size


def _map_context(stats) -> dict | None:
    """Punti posizionati in percentuale sull'immagine della planimetria."""
    if stats.layout is None or not stats.points:
        return None
    width, height = _layout_page_size(stats.layout)
    return {
        "image_url": reverse("assets:periodic_check_layout_image", args=[stats.layout.id]),
        "ratio": round(height / width * 100, 3),
        "points": [
            {"p": p, "left": round(p.x / width * 100, 3), "top": round(p.y / height * 100, 3)}
            for p in stats.points
        ],
    }


def _trend_bars(stats) -> dict | None:
    """Barre impilate dell'andamento, gia' in coordinate SVG (viewBox 100 x 60)."""
    if not stats.trend:
        return None
    n = len(stats.trend)
    plot_h, top = 46.0, 4.0
    slot_w = 100.0 / n
    bar_w = min(7.0, slot_w * 0.56)
    peak = max(stats.trend_max, 1)
    bars = []
    for index, row in enumerate(stats.trend):
        x = index * slot_w + (slot_w - bar_w) / 2
        y = top + plot_h
        segments = []
        for seg in row["segments"]:
            if not seg["value"]:
                continue
            h = seg["value"] / peak * plot_h
            y -= h
            segments.append({"x": round(x, 3), "y": round(y, 3), "w": round(bar_w, 3), "h": round(max(h - 0.6, 0.4), 3),
                             "slot": seg["slot"], "key": seg["key"], "value": seg["value"]})
        bars.append({
            "session": row["session"], "total": row["total"], "segments": segments,
            "label_x": round(x + bar_w / 2, 3), "hit_x": round(index * slot_w, 3), "hit_w": round(slot_w, 3),
        })
    return {"bars": bars, "peak": peak, "base_y": top + plot_h, "top": top}


@login_required
def periodic_check_layout_image(request: HttpRequest, layout_id: int):
    """Planimetria come immagine per la mappa della scheda (in cache: non cambia mai)."""
    layout = get_object_or_404(PeriodicCheckLayout, pk=layout_id)
    key = f"assets:pc-layout-png:{layout.id}"
    png = cache.get(key)
    if png is None:
        import fitz

        with layout.source_pdf.open("rb") as handle, fitz.open(stream=handle.read(), filetype="pdf") as doc:
            png = doc[layout.page_index].get_pixmap(dpi=110, alpha=False).tobytes("png")
        cache.set(key, png, 60 * 60 * 24 * 30)
    response = HttpResponse(png, content_type="image/png")
    response["Cache-Control"] = "private, max-age=86400"
    return response


def _parse_areas(text: str) -> list[list[float]]:
    areas = []
    for line in (text or "").splitlines():
        parts = [p for p in line.replace(";", ",").split(",") if p.strip()]
        if len(parts) == 4:
            areas.append([float(p) for p in parts])
    return areas


def _upload_layout(request: HttpRequest, check_type: PeriodicCheckType) -> HttpResponse:
    back = reverse("assets:periodic_check_type_detail", args=[check_type.id])
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Solo chi configura la manutenzione puo' caricare la planimetria.", back)
    upload = request.FILES.get("layout_pdf")
    if upload is None or not (upload.name or "").lower().endswith(".pdf"):
        messages.error(request, "Carica la planimetria in PDF (vettoriale, quella da cui si stampa).")
        return redirect(back)
    try:
        areas = _parse_areas(request.POST.get("exclude_areas", ""))
    except ValueError:
        messages.error(request, "Zone da coprire: una per riga, quattro numeri separati da virgola.")
        return redirect(back)
    try:
        layout = checks.create_layout(check_type, upload.read(), name=upload.name, exclude_areas=areas, user=request.user)
    except checks.LayoutError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    log_action(request, "periodic_check_layout_upload", "assets",
               {"check_type_id": check_type.id, "layout_id": layout.id, "version": layout.version,
                "points": layout.points.count()},
               oggetto_tipo="assets.periodic_check_type", oggetto_id=check_type.id)
    messages.success(request, f"Planimetria v{layout.version} caricata: {layout.points.count()} punti riconosciuti.")
    return redirect(back)


def _pdf_response(pdf: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


@login_required
def periodic_check_sheet_preview(request: HttpRequest, type_id: int):
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system"), pk=type_id)
    layout = check_type.active_layout
    if layout is None:
        return HttpResponse("Planimetria non caricata.", status=404)
    pdf, _geo = checks.build_sheet_for(layout)
    return _pdf_response(pdf, f"anteprima-foglio-{check_type.id}.pdf")


@login_required
def periodic_check_sheet_issue(request: HttpRequest, type_id: int):
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system"), pk=type_id)
    back = reverse("assets:periodic_check_type_detail", args=[check_type.id])
    if request.method != "POST":
        return redirect(back)
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai il permesso di stampare fogli di verifica.", back)
    try:
        session = checks.issue_sheet(check_type, user=request.user)
    except checks.LayoutError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    log_action(request, "periodic_check_sheet_issue", "assets",
               {"session_id": session.id, "check_type_id": check_type.id, "token": session.sheet_token},
               oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
    messages.success(request, f"Foglio {session.sheet_token} pronto: stampalo e dallo al tecnico. "
                              "Quando torna, carica qui la scansione.")
    return redirect(f"{reverse('assets:periodic_check_session_detail', args=[session.id])}?stampa=1")


@login_required
def periodic_check_sheet_pdf(request: HttpRequest, session_id: int):
    session = get_object_or_404(PeriodicCheckSession.objects.select_related("check_type__system", "layout"), pk=session_id)
    if not session.sheet_token or session.layout is None:
        return HttpResponse("Questa verifica non ha un foglio stampabile.", status=404)
    pdf, _geo = checks.build_sheet_for(session.layout, token=session.sheet_token)
    log_action(request, "periodic_check_sheet_pdf", "assets", {"session_id": session.id},
               oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
    return _pdf_response(pdf, f"foglio-verifica-{session.sheet_token}.pdf")


@login_required
def periodic_check_register(request: HttpRequest, type_id: int) -> HttpResponse:
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system"), pk=type_id)
    back = reverse("assets:periodic_check_type_detail", args=[check_type.id])
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai il permesso di registrare verifiche.", back)
    items = list(check_type.items.filter(is_active=True)) if check_type.method == PeriodicCheckType.METHOD_CHECKLIST else []
    form = PeriodicCheckRegisterForm(request.POST or None, check_type=check_type)
    layout = check_type.active_layout if check_type.method == PeriodicCheckType.METHOD_LAYOUT else None
    point_rows = [
        {"index": index, "category": category, "value": request.POST.get(f"codes_{index}", "")}
        for index, category in enumerate(check_type.category_list)
    ] if layout else []
    item_rows = []
    for item in items:
        item_rows.append({
            "item": item,
            "result": request.POST.get(f"item_{item.id}", PeriodicCheckResult.RESULT_OK) if request.method == "POST" else PeriodicCheckResult.RESULT_OK,
            "note": request.POST.get(f"item_note_{item.id}", "") if request.method == "POST" else "",
        })
    if request.method == "POST" and form.is_valid():
        uploads, upload_errors = _validate_workorder_attachment_uploads(request, field_name="files")
        if upload_errors:
            for error in upload_errors:
                form.add_error(None, error)
        else:
            valid_results = {code for code, _label in PeriodicCheckResult.RESULT_CHOICES}
            results = [
                checks.ResultInput(
                    label=row["item"].label,
                    item=row["item"],
                    result=row["result"] if row["result"] in valid_results else PeriodicCheckResult.RESULT_OK,
                    note=(row["note"] or "").strip(),
                )
                for row in item_rows
            ]
            results += [
                checks.ResultInput(label=text, kind=PeriodicCheckResult.KIND_REMARK, result=PeriodicCheckResult.RESULT_KO)
                for text in form.remarks
            ]
            point_results, unknown = _point_results(layout, point_rows)
            if unknown:
                form.add_error(None, "Punti che non esistono sulla planimetria: " + ", ".join(unknown))
                return _register_page(request, check_type, form, item_rows, point_rows)
            results += point_results
            supplier = form.cleaned_data.get("supplier")
            session = checks.register_session(
                checks.SessionInput(
                    check_type=check_type,
                    performed_on=form.cleaned_data["performed_on"],
                    outcome=form.cleaned_data["outcome"],
                    technician=form.cleaned_data.get("technician") or "",
                    supplier_id=supplier.id if supplier else None,
                    notes=form.cleaned_data.get("notes") or "",
                    next_due_date=form.cleaned_data.get("next_due_date"),
                    results=results,
                ),
                user=request.user,
                files=uploads,
            )
            log_action(
                request,
                "periodic_check_register",
                "assets",
                {
                    "session_id": session.id,
                    "check_type_id": check_type.id,
                    "performed_on": str(session.performed_on),
                    "outcome": session.outcome,
                    "results_ko": sum(1 for r in results if r.result == PeriodicCheckResult.RESULT_KO),
                    "attachments": len(uploads),
                },
                oggetto_tipo=AUDIT_OGGETTO,
                oggetto_id=session.id,
            )
            check_type.refresh_from_db()
            due = f" Prossima scadenza: {check_type.next_due_date:%d/%m/%Y}." if check_type.next_due_date else ""
            messages.success(request, f"Verifica del {session.performed_on:%d/%m/%Y} registrata.{due}")
            return redirect("assets:periodic_check_session_detail", session_id=session.id)
    return _register_page(request, check_type, form, item_rows, point_rows)


def _register_page(request, check_type, form, item_rows, point_rows):
    return _render(request, "periodic_check_register.html", {
        "page_title": f"Registra: {check_type.name}",
        "check_type": check_type,
        "form": form,
        "item_rows": item_rows,
        "point_rows": point_rows,
        "result_choices": PeriodicCheckResult.RESULT_CHOICES,
    })


def _split_codes(text: str) -> list[str]:
    return [c.strip().upper() for c in re.split(r"[\s,;]+", text or "") if c.strip()]


def _point_results(layout, point_rows) -> tuple[list, list[str]]:
    if layout is None:
        return [], []
    by_code = {p.code.upper(): p for p in layout.points.all()}
    results, unknown, seen = [], [], set()
    for row in point_rows:
        for code in _split_codes(row["value"]):
            point = by_code.get(code)
            if point is None:
                unknown.append(code)
                continue
            if code in seen:
                continue
            seen.add(code)
            results.append(checks.ResultInput(
                label=f"Punto {point.code}", kind=PeriodicCheckResult.KIND_POINT, result=PeriodicCheckResult.RESULT_KO,
                point=point, category=row["category"],
            ))
    return results, unknown


@login_required
def periodic_check_session_detail(request: HttpRequest, session_id: int) -> HttpResponse:
    session = get_object_or_404(
        PeriodicCheckSession.objects.select_related("check_type__system__asset", "supplier", "created_by", "confirmed_by"),
        pk=session_id,
    )
    check_type = session.check_type
    default_asset = check_type.system.asset
    if request.method == "POST":
        if not can_execute_maintenance(request):
            return _deny(request, "Non hai il permesso di modificare le verifiche.",
                         reverse("assets:periodic_check_session_detail", args=[session.id]))
        action = request.POST.get("action")
        if action == "confirm" and not session.is_confirmed:
            checks.confirm_session(session, user=request.user)
            log_action(request, "periodic_check_confirm", "assets", {"session_id": session.id},
                       oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
            messages.success(request, "Verifica confermata.")
        elif action == "work_order":
            result = get_object_or_404(PeriodicCheckResult, pk=request.POST.get("result_id"), session=session)
            wo_form = WorkOrderFromResultForm(request.POST)
            if result.work_order_id:
                messages.info(request, f"Esiste gia' l'ordine di lavoro #{result.work_order_id}.")
            elif wo_form.is_valid():
                work_order = checks.create_work_order(
                    result, asset=wo_form.cleaned_data["asset"], user=request.user, title=wo_form.cleaned_data["title"]
                )
                log_action(request, "periodic_check_work_order", "assets",
                           {"session_id": session.id, "result_id": result.id, "work_order_id": work_order.id},
                           oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
                messages.success(request, f"Ordine di lavoro #{work_order.id} aperto.")
            else:
                messages.error(request, "Scegli l'asset e il titolo dell'ordine di lavoro.")
        elif action == "scan":
            return _scan_upload(request, session)
        elif action == "confirm_points" and not session.is_confirmed:
            return _confirm_points(request, session)
        elif action == "attach":
            uploads, errors = _validate_workorder_attachment_uploads(request, field_name="files")
            for error in errors:
                messages.error(request, error)
            for upload in uploads:
                checks.add_attachment(session, upload, user=request.user)
            if uploads:
                log_action(request, "periodic_check_attach", "assets",
                           {"session_id": session.id, "attachments": len(uploads)},
                           oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
                messages.success(request, f"{len(uploads)} allegati aggiunti.")
        return redirect("assets:periodic_check_session_detail", session_id=session.id)

    results = list(session.results.select_related("work_order", "item", "point"))
    attachments = list(session.attachments.all())
    overlay = next((a for a in reversed(attachments) if a.original_name == "lettura-automatica.png"), None)
    return _render(request, "periodic_check_session_detail.html", {
        "points": sorted((r for r in results if r.kind == PeriodicCheckResult.KIND_POINT),
                         key=lambda r: checks._code_key(r.point.code if r.point else r.label)),
        "categories": check_type.category_list,
        "overlay": overlay,
        "reading": session.reading or {},
        "print_now": request.GET.get("stampa") == "1" and session.status == PeriodicCheckSession.STATUS_ISSUED,
        "show_results": bool(results) and (session.is_confirmed or session.layout_id is None),
        "today": timezone.localdate(),
        "page_title": f"{check_type.name} del {session.performed_on:%d/%m/%Y}",
        "session": session,
        "check_type": check_type,
        "items": [r for r in results if r.kind == PeriodicCheckResult.KIND_ITEM],
        "remarks": [r for r in results if r.kind == PeriodicCheckResult.KIND_REMARK],
        "attachments": [a for a in attachments if a is not overlay],
        "default_asset": default_asset,
        "asset_choices": (
            list(Asset.objects.order_by("asset_tag", "name").only("id", "asset_tag", "name"))
            if can_execute_maintenance(request) and any(r.result == PeriodicCheckResult.RESULT_KO and not r.work_order_id for r in results)
            else []
        ),
    })


def _scan_upload(request: HttpRequest, session: PeriodicCheckSession) -> HttpResponse:
    back = reverse("assets:periodic_check_session_detail", args=[session.id])
    uploads, errors = _validate_workorder_attachment_uploads(request, field_name="scan")
    for error in errors:
        messages.error(request, error)
    if not uploads:
        if not errors:
            messages.error(request, "Scegli il file della scansione.")
        return redirect(back)
    upload = uploads[0]
    data = upload.read()
    from core.qr import leggi_codici

    found = [checks.session_for_token(code) for code in leggi_codici(data, upload.name or "")]
    found = [f for f in found if f is not None]
    if found and all(f.id != session.id for f in found):
        other = found[0]
        messages.error(request, f"Questa scansione e' del foglio {other.sheet_token} ({other.check_type.name}), "
                                "non di questa verifica: caricala dalla sua pagina.")
        return redirect(back)
    try:
        reading = checks.read_scan_into(session, data, name=upload.name or "scansione.pdf", user=request.user)
    except checks.LayoutError as exc:
        messages.error(request, str(exc))
        return redirect(back)
    log_action(request, "periodic_check_scan_read", "assets",
               {"session_id": session.id, "ok": reading.get("ok"), "proposti": list(reading.get("proposti", {})),
                "qr_verificato": bool(found)},
               oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
    if reading.get("ok"):
        count = len(reading.get("proposti", {}))
        messages.success(request, f"Scansione letta: {count} punti segnati. Controlla e conferma." if count
                         else "Scansione letta: nessun punto segnato. Controlla e conferma.")
    else:
        messages.warning(request, "Non sono riuscito ad allineare la scansione alla planimetria: "
                                  "inserisci i punti a mano qui sotto.")
    return redirect(back)


def _confirm_points(request: HttpRequest, session: PeriodicCheckSession) -> HttpResponse:
    back = reverse("assets:periodic_check_session_detail", args=[session.id])
    categories = session.check_type.category_list
    try:
        performed_on = date.fromisoformat(request.POST.get("performed_on", ""))
    except ValueError:
        messages.error(request, "Indica la data della verifica (quella scritta sul foglio).")
        return redirect(back)
    if performed_on > timezone.localdate():
        messages.error(request, "La data della verifica non puo' essere futura.")
        return redirect(back)
    decisions = {}
    for result in session.results.filter(kind=PeriodicCheckResult.KIND_POINT):
        value = request.POST.get(f"point_{result.id}")
        if value is not None:
            decisions[result.id] = value if value in categories else ""
    added, unknown = {}, []
    codes = {p.code.upper(): p.code for p in session.layout.points.all()} if session.layout else {}
    for index, category in enumerate(categories):
        for code in _split_codes(request.POST.get(f"add_{index}", "")):
            if code in codes:
                added[codes[code]] = category
            else:
                unknown.append(code)
    if unknown:
        messages.error(request, "Punti che non esistono sulla planimetria: " + ", ".join(unknown))
        return redirect(back)
    checks.confirm_layout_session(session, performed_on=performed_on, technician=request.POST.get("technician", ""),
                                  decisions=decisions, added=added, user=request.user)
    log_action(request, "periodic_check_confirm", "assets",
               {"session_id": session.id, "punti": session.results.filter(kind=PeriodicCheckResult.KIND_POINT).count()},
               oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
    session.check_type.refresh_from_db()
    due = session.check_type.next_due_date
    messages.success(request, "Verifica confermata." + (f" Prossima scadenza: {due:%d/%m/%Y}." if due else ""))
    return redirect(back)


@login_required
def periodic_check_type_form(request: HttpRequest, type_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Solo chi configura la manutenzione puo' modificare le verifiche.")
    check_type = get_object_or_404(PeriodicCheckType, pk=type_id) if type_id else None
    form = PeriodicCheckTypeForm(request.POST or None, instance=check_type)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        form.save_items(saved)
        log_action(request, "periodic_check_type_save", "assets",
                   {"check_type_id": saved.id, "created": check_type is None, "name": saved.name},
                   oggetto_tipo="assets.periodic_check_type", oggetto_id=saved.id)
        messages.success(request, f"Verifica «{saved.name}» salvata.")
        return redirect("assets:periodic_check_type_detail", type_id=saved.id)
    return _render(request, "periodic_check_type_form.html", {
        "page_title": "Modifica verifica" if check_type else "Nuova verifica periodica",
        "form": form,
        "check_type": check_type,
        "no_systems": not PeriodicCheckSystem.objects.filter(is_active=True).exists(),
    })


@login_required
def periodic_check_systems(request: HttpRequest) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Solo chi configura la manutenzione puo' gestire gli impianti.")
    edit_id = request.GET.get("modifica") or request.POST.get("system_id")
    instance = get_object_or_404(PeriodicCheckSystem, pk=edit_id) if edit_id else None
    form = PeriodicCheckSystemForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        log_action(request, "periodic_check_system_save", "assets",
                   {"system_id": saved.id, "created": instance is None, "name": saved.name},
                   oggetto_tipo="assets.periodic_check_system", oggetto_id=saved.id)
        messages.success(request, f"Impianto «{saved.name}» salvato.")
        return redirect("assets:periodic_check_systems")
    systems = PeriodicCheckSystem.objects.select_related("asset").annotate(types_count=Count("check_types"))
    return _render(request, "periodic_check_systems.html", {
        "page_title": "Impianti",
        "form": form,
        "editing": instance,
        "systems": systems,
    })


@login_required
def periodic_check_attachment_download(request: HttpRequest, attachment_id: int):
    attachment = get_object_or_404(PeriodicCheckAttachment.objects.select_related("session"), pk=attachment_id)
    payload = {"attachment_id": attachment.id, "session_id": attachment.session_id}
    if not can_execute_maintenance(request):
        log_action(request, "download_periodic_check_attachment", "assets", {**payload, "esito": "denied"},
                   oggetto_tipo=AUDIT_OGGETTO, oggetto_id=attachment.session_id)
        return render(request, "core/pages/forbidden.html", status=403)
    storage = attachment.file.storage
    if not attachment.file or not attachment.file.name or not storage.exists(attachment.file.name):
        log_action(request, "download_periodic_check_attachment", "assets", {**payload, "esito": "not_found"},
                   oggetto_tipo=AUDIT_OGGETTO, oggetto_id=attachment.session_id)
        return HttpResponse("Allegato non trovato.", status=404)
    filename = attachment.original_name or Path(attachment.file.name).name
    log_action(request, "download_periodic_check_attachment", "assets",
               {**payload, "filename": filename, "esito": "success"},
               oggetto_tipo=AUDIT_OGGETTO, oggetto_id=attachment.session_id)
    inline = filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) and request.GET.get("download") != "1"
    return FileResponse(
        storage.open(attachment.file.name, "rb"),
        as_attachment=not inline,
        filename=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )


# ---------------------------------------------------------------------------
# Cartella scansioni (acquisizione dei fogli dallo scanner)
# ---------------------------------------------------------------------------

@login_required
def periodic_check_intake(request: HttpRequest) -> HttpResponse:
    config = PeriodicCheckIntakeConfig.load()
    can_register = can_execute_maintenance(request)
    can_configure = can_manage_maintenance_plans(request)
    back = reverse("assets:periodic_check_intake")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "config":
            if not can_configure:
                return _deny(request, "Solo chi configura la manutenzione puo' cambiare la cartella.", back)
            form = PeriodicCheckIntakeConfigForm(request.POST, instance=config)
            if form.is_valid():
                form.save()
                log_action(request, "periodic_check_intake_config", "assets",
                           {"attiva": config.attiva, "cartella": config.cartella})
                messages.success(request, "Impostazioni della cartella salvate.")
                return redirect(back)
        elif not can_register:
            return _deny(request, "Non hai il permesso di acquisire scansioni.", back)
        elif action == "run":
            result = periodic_intake.process_folder(config, force=True)
            log_action(request, "periodic_check_intake_run", "assets", {"riepilogo": result["riepilogo"]})
            messages.info(request, f"Cartella letta: {result['riepilogo']}")
            return redirect(back)
        elif action == "upload":
            uploads, errors = _validate_workorder_attachment_uploads(request, field_name="scan")
            for error in errors:
                messages.error(request, error)
            logs = []
            for upload in uploads:
                logs += periodic_intake.process_file(upload.read(), upload.name or "scansione.pdf",
                                                     source="CARICAMENTO", user=request.user)
            if logs:
                read = sum(1 for log in logs if log.outcome == PeriodicCheckIntakeLog.OUTCOME_READ)
                log_action(request, "periodic_check_intake_upload", "assets", {"fogli": len(logs), "letti": read})
                messages.info(request, f"{len(logs)} fogli: {read} associati alla loro verifica, "
                                       f"{len(logs) - read} da smistare qui sotto.")
            return redirect(back)
        elif action in {"assign", "discard"}:
            log = get_object_or_404(PeriodicCheckIntakeLog, pk=request.POST.get("log_id"))
            if action == "discard":
                periodic_intake.discard(log, user=request.user)
                messages.info(request, f"Scansione «{log.file_name}» scartata.")
            else:
                session = get_object_or_404(PeriodicCheckSession, pk=request.POST.get("session_id"))
                try:
                    periodic_intake.assign(log, session, user=request.user)
                except checks.LayoutError as exc:
                    messages.error(request, str(exc))
                    return redirect(back)
                messages.success(request, f"Scansione associata a «{session.check_type.name}»: controlla e conferma i punti.")
                log_action(request, "periodic_check_intake_assign", "assets",
                           {"log_id": log.id, "session_id": session.id}, oggetto_tipo=AUDIT_OGGETTO, oggetto_id=session.id)
                return redirect("assets:periodic_check_session_detail", session_id=session.id)
            return redirect(back)
        form = PeriodicCheckIntakeConfigForm(request.POST, instance=config)
    else:
        form = PeriodicCheckIntakeConfigForm(instance=config)

    pending = PeriodicCheckIntakeLog.objects.filter(
        outcome__in=[PeriodicCheckIntakeLog.OUTCOME_UNMATCHED, PeriodicCheckIntakeLog.OUTCOME_ERROR]
    ).select_related("session__check_type")
    open_sessions = (
        PeriodicCheckSession.objects.filter(
            status__in=[PeriodicCheckSession.STATUS_ISSUED, PeriodicCheckSession.STATUS_DRAFT], layout__isnull=False)
        .select_related("check_type").order_by("check_type__name", "-id")
    )
    return _render(request, "periodic_check_intake.html", {
        "page_title": "Cartella scansioni",
        "config": config,
        "form": form,
        "pending": pending,
        "open_sessions": open_sessions,
        "logs": PeriodicCheckIntakeLog.objects.select_related("session__check_type")[:50],
        "can_register": can_register,
        "can_configure": can_configure,
    })


@login_required
def periodic_check_intake_scan(request: HttpRequest, log_id: int):
    log = get_object_or_404(PeriodicCheckIntakeLog, pk=log_id)
    if not can_execute_maintenance(request):
        return render(request, "core/pages/forbidden.html", status=403)
    if not log.scan or not log.scan.storage.exists(log.scan.name):
        return HttpResponse("Scansione non disponibile.", status=404)
    log_action(request, "download_periodic_check_intake_scan", "assets", {"log_id": log.id})
    name = log.file_name or "scansione.pdf"
    return FileResponse(log.scan.open("rb"), as_attachment=False, filename=name,
                        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream")
