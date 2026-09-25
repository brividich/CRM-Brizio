"""Manutenzione > Verifiche periodiche: verifiche sugli impianti.

Modulo separato da ``views.py`` come ``views_maintenance``: dipende da ``views`` e
``views_maintenance`` (helper di shell e gate), mai il contrario.
Dominio in ``services/periodic_checks.py``; vedi docs/ai/VERIFICHE_PERIODICHE.md.
"""
from __future__ import annotations

import mimetypes
from collections import OrderedDict
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action

from .forms_verifiche import (
    PeriodicCheckRegisterForm,
    PeriodicCheckSystemForm,
    PeriodicCheckTypeForm,
    WorkOrderFromResultForm,
)
from .models import (
    Asset,
    PeriodicCheckAttachment,
    PeriodicCheckResult,
    PeriodicCheckSession,
    PeriodicCheckSystem,
    PeriodicCheckType,
)
from .services import periodic_checks as checks
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
            drafts=Count("sessions", filter=Q(sessions__status=PeriodicCheckSession.STATUS_DRAFT)),
            open_ko=Count(
                "sessions__results",
                filter=Q(sessions__results__result=PeriodicCheckResult.RESULT_KO, sessions__results__work_order__isnull=True),
            ),
        )
    )
    last = _last_sessions_by_type([t.id for t in types])
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
    })


@login_required
def periodic_check_type_detail(request: HttpRequest, type_id: int) -> HttpResponse:
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system", "supplier"), pk=type_id)
    sessions = (
        check_type.sessions.select_related("supplier", "created_by")
        .prefetch_related("attachments", Prefetch("results", queryset=PeriodicCheckResult.objects.select_related("work_order")))
        .order_by("-performed_on", "-id")
    )
    state = checks.type_state(check_type)
    return _render(request, "periodic_check_type_detail.html", {
        "page_title": check_type.name,
        "check_type": check_type,
        "items": check_type.items.filter(is_active=True),
        "sessions": sessions,
        "state": state,
        "state_label": checks.STATE_LABELS[state],
    })


@login_required
def periodic_check_register(request: HttpRequest, type_id: int) -> HttpResponse:
    check_type = get_object_or_404(PeriodicCheckType.objects.select_related("system"), pk=type_id)
    back = reverse("assets:periodic_check_type_detail", args=[check_type.id])
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai il permesso di registrare verifiche.", back)
    items = list(check_type.items.filter(is_active=True)) if check_type.method == PeriodicCheckType.METHOD_CHECKLIST else []
    form = PeriodicCheckRegisterForm(request.POST or None, check_type=check_type)
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
    return _render(request, "periodic_check_register.html", {
        "page_title": f"Registra: {check_type.name}",
        "check_type": check_type,
        "form": form,
        "item_rows": item_rows,
        "result_choices": PeriodicCheckResult.RESULT_CHOICES,
    })


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

    results = list(session.results.select_related("work_order", "item"))
    return _render(request, "periodic_check_session_detail.html", {
        "page_title": f"{check_type.name} del {session.performed_on:%d/%m/%Y}",
        "session": session,
        "check_type": check_type,
        "items": [r for r in results if r.kind == PeriodicCheckResult.KIND_ITEM],
        "remarks": [r for r in results if r.kind == PeriodicCheckResult.KIND_REMARK],
        "attachments": session.attachments.all(),
        "default_asset": default_asset,
        "asset_choices": (
            list(Asset.objects.order_by("asset_tag", "name").only("id", "asset_tag", "name"))
            if can_execute_maintenance(request) and any(r.result == PeriodicCheckResult.RESULT_KO and not r.work_order_id for r in results)
            else []
        ),
    })


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
    inline = filename.lower().endswith(".pdf") and request.GET.get("download") != "1"
    return FileResponse(
        storage.open(attachment.file.name, "rb"),
        as_attachment=not inline,
        filename=filename,
        content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
    )
