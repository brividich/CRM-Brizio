"""Viste del modulo Automazioni — Approvazioni: pagine di decisione (web e proxy Entra), template, canali Teams, log mailbox.

Spacchettamento di ``automazioni/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import json

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from admin_portale.decorators import legacy_admin_or_acl_required
from core.public_headers import risposta_pubblica, risposta_pubblica_con_form

from ..forms import (
    ApprovalEmailTemplateForm,
    AutomationDeliveryEndpointForm,
    TeamsWebhookPresetForm,
)
from ..models import (
    ApprovalEmailTemplate,
    APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE,
    AutomationDeliveryEndpoint,
    AutomationDeliveryEndpointType,
    TeamsWebhookPreset,
    list_approval_email_templates,
)
from ..services import (
    process_approval_decision,
)


import logging as _logging

from . import _helpers  # noqa: E402


def _build_teams_delivery_context(
    *,
    preset_form=None,
    preset_form_mode: str = "",
    edit_preset: TeamsWebhookPreset | None = None,
    flow_form=None,
    flow_form_mode: str = "",
    edit_flow_endpoint: AutomationDeliveryEndpoint | None = None,
) -> dict[str, object]:
    flow_endpoints, flow_endpoints_warning = _helpers._get_teams_flow_endpoints_context(active_only=None)
    return {
        **_helpers._base_context(),
        "presets": list(TeamsWebhookPreset.objects.order_by("name")),
        "flow_endpoints": flow_endpoints,
        "flow_endpoints_warning": flow_endpoints_warning,
        "preset_form": preset_form,
        "preset_form_mode": preset_form_mode,
        "edit_preset": edit_preset,
        "flow_form": flow_form,
        "flow_form_mode": flow_form_mode,
        "edit_flow_endpoint": edit_flow_endpoint,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Approval Decision Views
#
# Due modi di decidere, entrambi con identita' certa dell'approvatore:
#   1. link personale  /approval-actions/r/<segreto>/<approva|rifiuta>/
#      Il segreto e' stato inviato a UN destinatario: chi lo apre decide come lui,
#      senza login (approval_links.py). E' il link delle email.
#   2. link della richiesta  /automazioni/approvazione/<uuid>/<approva|rifiuta>/
#      e  /approval-actions/approve|reject/<uuid>/  (link inviati prima dei link
#      personali, canale Teams condiviso). L'uuid identifica la richiesta ma NON
#      chi decide: serve il login, e l'utente deve essere fra gli approvatori.
# Nessun header HTTP di identita' viene letto: il client li puo' falsificare.
# GET mostra sempre una conferma senza effetti (i link scanner delle mail aprono
# i link in GET); la decisione avviene solo in POST.
# ─────────────────────────────────────────────────────────────────────────────


_proxy_logger = _logging.getLogger(__name__)

_DECISION_SLUGS = {"approva": "approved", "rifiuta": "rejected", "approve": "approved", "reject": "rejected"}


def _session_approver_email(request) -> str:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return ""
    return str(getattr(user, "email", "") or getattr(user, "username", "") or "").strip()


def _login_redirect(request):
    from urllib.parse import urlencode

    from django.urls import reverse

    return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")


def _render_decision(request, context: dict, status: int = 200):
    return render(request, "automazioni/pages/approval_decision.html", context, status=status)


def _contesto_calendario(request, approval, decision: str) -> dict:
    """Spunta «Metti nel mio calendario Outlook» sulla conferma di un'assenza da approvare.

    ``?calendario=1`` (pulsante «Approva e metti in calendario» della mail) la trova già messa.
    """
    from ..calendario_outlook import approvazione_di_assenza, opzione_calendario

    offerta = decision == "approved" and approvazione_di_assenza(approval) and opzione_calendario(
        "assenze", approval.resume_payload
    )
    return {
        "calendario_opzione": offerta,
        "calendario_spuntato": request.GET.get("calendario") == "1",
        "calendario_richiesto": request.GET.get("calendario") == "1" and request.GET.get("done") == "1",
    }


def _dopo_decisione(request, approval, decision: str, email: str) -> str:
    """Registra la richiesta di calendario dopo «Approva»; ritorna il suffisso del redirect."""
    from ..calendario_outlook import richiedi_da_approvazione

    if decision != "approved" or request.POST.get("calendario") != "1":
        return "?done=1"
    richiedi_da_approvazione(approval, email)
    return "?done=1&calendario=1"


@risposta_pubblica
@csrf_exempt  # il segreto nell'URL fa da protezione CSRF: un sito terzo non lo conosce
@require_http_methods(["GET", "POST"])
def approval_link_page(request, token: str, decision: str):
    """Link personale delle email: GET conferma, POST decide come il destinatario del link."""
    from ..approval_links import decide_with_link, get_link
    from ..models import AutomationApproval

    normalized = _DECISION_SLUGS.get(decision)
    link = get_link(token)
    if normalized is None or link is None:
        return _render_decision(request, {"error": "Link di approvazione non valido."}, status=404)

    approval = link.approval
    base_context = {
        "approval": approval,
        "decision": normalized,
        "token": "",
        "link_mode": True,
        "decider_email": link.recipient_email,
        **_contesto_calendario(request, approval, normalized),
    }

    if request.method == "GET":
        if request.GET.get("done") == "1" and approval.status != AutomationApproval.Status.PENDING:
            return _render_decision(request, {**base_context, "just_done": True})
        if link.used_at is not None or approval.status != AutomationApproval.Status.PENDING:
            return _render_decision(request, {**base_context, "already_decided": True})
        return _render_decision(request, {**base_context, "is_expired": approval.is_expired()})

    result = decide_with_link(token, normalized)
    _helpers.log_action(
        request,
        "approval_link_decision" if result.get("ok") else "approval_link_denied",
        "automazioni",
        {
            "approval_id": approval.pk,
            "link_id": link.pk,
            "decision": normalized,
            "actor": link.recipient_email,
            "ok": bool(result.get("ok")),
            "code": result.get("code"),
            "message": result.get("message"),
        },
    )
    if result.get("ok"):
        # Fa fede la casella a cui è arrivato il link, non chi lo apre.
        return redirect(request.path + _dopo_decisione(request, approval, normalized, link.recipient_email))
    approval.refresh_from_db()
    return _render_decision(request, {
        **base_context,
        "result": {k: v for k, v in result.items() if k != "link"},
        "already_decided": result.get("code") in {"already_decided", "already_used"},
    })


def _decide_as_session_user(request, token: str, normalized: str, *, via: str):
    """Decisione sul link della richiesta: solo utente loggato e fra gli approvatori."""
    from ..approval_security import validate_approval_actor

    decided_by = _session_approver_email(request)
    validation = validate_approval_actor(str(token), decided_by)
    if not validation.allowed:
        _helpers.log_action(request, "approval_proxy_denied", "automazioni", {
            "approval_id": validation.approval_id,
            "decision": normalized,
            "actor": decided_by or "(vuoto)",
            "error_code": validation.error_code,
            "via": via,
        })
        return None, validation

    result = process_approval_decision(str(token), normalized, decided_by_email=decided_by)
    _helpers.log_action(request, "approval_proxy_decision", "automazioni", {
        "approval_id": result.get("approval_id"),
        "decision": normalized,
        "actor": decided_by,
        "ok": result.get("ok"),
        "message": result.get("message"),
        "via": via,
    })
    return result, validation


@risposta_pubblica_con_form
@require_http_methods(["GET", "POST"])
def approval_decision_page(request, token: str, decision: str):
    """Link della richiesta (uuid): GET conferma, POST decide solo con login da approvatore."""
    from ..models import AutomationApproval

    normalized = _DECISION_SLUGS.get(decision)
    if normalized is None:
        return _render_decision(request, {"error": "Azione non valida.", "token": token}, status=400)

    if not request.user.is_authenticated:
        return _login_redirect(request)

    try:
        approval = AutomationApproval.objects.select_related("run_log__rule").get(token=token)
    except AutomationApproval.DoesNotExist:
        return _render_decision(
            request, {"error": "Richiesta di approvazione non trovata o link non valido.", "token": token}, status=404
        )

    base_context = {
        "approval": approval,
        "decision": normalized,
        "decision_label": "Approvare" if normalized == "approved" else "Rifiutare",
        "decision_verb": "approva" if normalized == "approved" else "rifiuta",
        "token": token,
        "decider_email": _session_approver_email(request),
        **_contesto_calendario(request, approval, normalized),
    }

    if request.method == "GET":
        already = approval.status != AutomationApproval.Status.PENDING
        just_done = already and request.GET.get("done") == "1"
        return _render_decision(request, {
            **base_context,
            "is_expired": approval.is_expired(),
            "already_decided": already and not just_done,
            "just_done": just_done,
        })

    result, validation = _decide_as_session_user(request, token, normalized, via="portal_link")
    if result is None:
        return _render_decision(request, {
            **base_context,
            "result": {"ok": False, "message": validation.error_message},
            "already_decided": validation.error_code == "already_decided",
        }, status=403)
    if result.get("ok"):
        return redirect(request.path + _dopo_decisione(request, approval, normalized, _session_approver_email(request)))
    return _render_decision(request, {
        **base_context,
        "result": result,
        "already_decided": "già" in str(result.get("message") or ""),
    })


@risposta_pubblica
@require_GET
def approval_status_page(request, token: str):
    """Stato di una richiesta: solo utenti loggati fra gli approvatori (o admin)."""
    from ..models import AutomationApproval

    if not request.user.is_authenticated:
        return _login_redirect(request)
    try:
        approval = AutomationApproval.objects.get(token=token)
    except AutomationApproval.DoesNotExist:
        return _render_decision(request, {"error": "Richiesta non trovata.", "token": token}, status=404)

    from core.legacy_utils import get_legacy_user, is_legacy_admin
    from ..approval_security import normalize_actor_email

    approvers = {normalize_actor_email(e) for e in (approval.approver_emails or [])}
    me = normalize_actor_email(_session_approver_email(request))
    if not (request.user.is_superuser or is_legacy_admin(get_legacy_user(request.user)) or (me and me in approvers)):
        return _render_decision(request, {"error": "Non sei fra gli approvatori di questa richiesta.", "token": token}, status=403)
    return _render_decision(request, {"approval": approval, "token": token, "status_only": True})


@risposta_pubblica_con_form
@require_http_methods(["GET", "POST"])
def approval_proxy_approve(request, token):
    """Compat: vecchio link /approval-actions/approve/<uuid>/ — richiede login da approvatore."""
    return _handle_approval_proxy(request, token, "approved")


@risposta_pubblica_con_form
@require_http_methods(["GET", "POST"])
def approval_proxy_reject(request, token):
    """Compat: vecchio link /approval-actions/reject/<uuid>/ — richiede login da approvatore."""
    return _handle_approval_proxy(request, token, "rejected")


def _handle_approval_proxy(request, token, decision: str):
    from ..approval_security import ErrorCode, validate_approval_actor

    token_str = str(token)
    if not request.user.is_authenticated:
        return _login_redirect(request)

    decided_by = _session_approver_email(request)
    if request.method == "GET":
        validation = validate_approval_actor(token_str, decided_by)
        if validation.allowed:
            return render(request, "automazioni/pages/approval_proxy_result.html", {
                "requires_confirmation": True,
                "decision": decision,
                "token": token_str,
                "decided_by": decided_by,
                "approval_id": validation.approval_id,
            })
        result, validation = None, validation
    else:
        result, validation = _decide_as_session_user(request, token_str, decision, via="entra_proxy")

    if result is None:
        return render(request, "automazioni/pages/approval_proxy_result.html", {
            "denied": True,
            "error_code": validation.error_code,
            "error_message": validation.error_message,
            "decision": decision,
            "token": token_str,
            "decided_by": decided_by,
            "is_no_identity":     validation.error_code == ErrorCode.NO_IDENTITY,
            "is_not_found":       validation.error_code == ErrorCode.NOT_FOUND,
            "is_already_decided": validation.error_code == ErrorCode.ALREADY_DECIDED,
            "is_expired":         validation.error_code == ErrorCode.EXPIRED,
            "is_unauthorized":    validation.error_code == ErrorCode.UNAUTHORIZED,
            "is_no_approvers":    validation.error_code == ErrorCode.NO_APPROVERS,
        })

    if not result.get("ok"):
        _proxy_logger.warning(
            "approval_proxy: process_approval_decision ko approval=%s decision=%s reason=%s",
            result.get("approval_id"), decision, result.get("message"),
        )
    return render(request, "automazioni/pages/approval_proxy_result.html", {
        "result": result,
        "decision": decision,
        "token": token_str,
        "decided_by": decided_by,
    })


@legacy_admin_or_acl_required("automazioni", "teams_presets_page")
def teams_presets_page(request):
    return render(request, "automazioni/pages/teams_presets.html", _build_teams_delivery_context())


@legacy_admin_or_acl_required("automazioni", "approval_mailbox_log_page")
def approval_mailbox_log_page(request):
    """Diagnostica: ultimi messaggi letti dalla mailbox approvazioni."""
    from ..models import ApprovalMailboxMessage

    page_size = 40
    try:
        qs = ApprovalMailboxMessage.objects.select_related("linked_approval").order_by(
            "-received_at", "-created_at"
        )[:page_size]
        log_entries = list(qs)
        table_missing = False
    except Exception:
        log_entries = []
        table_missing = True

    return render(
        request,
        "automazioni/pages/approval_mailbox_log.html",
        {
            **_helpers._base_context(),
            "log_entries": log_entries,
            "table_missing": table_missing,
            "graph_status": None,  # lazy — caricato nella template se necessario
        },
    )


@legacy_admin_or_acl_required("automazioni", "teams_preset_create")
def teams_preset_create(request):
    if request.method == "POST":
        form = TeamsWebhookPresetForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Canale Teams creato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = TeamsWebhookPresetForm()
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(preset_form=form, preset_form_mode="create"),
    )


@legacy_admin_or_acl_required("automazioni", "teams_preset_edit")
def teams_preset_edit(request, pk: int):
    preset = get_object_or_404(TeamsWebhookPreset, pk=pk)
    if request.method == "POST":
        form = TeamsWebhookPresetForm(request.POST, instance=preset)
        if form.is_valid():
            form.save()
            messages.success(request, f"Canale '{preset.name}' aggiornato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = TeamsWebhookPresetForm(instance=preset)
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(
            preset_form=form,
            preset_form_mode="edit",
            edit_preset=preset,
        ),
    )


@legacy_admin_or_acl_required("automazioni", "teams_preset_delete")
@require_POST
def teams_preset_delete(request, pk: int):
    preset = get_object_or_404(TeamsWebhookPreset, pk=pk)
    name = preset.name
    preset.delete()
    messages.success(request, f"Canale '{name}' eliminato.")
    return redirect("admin_portale:automazioni_teams_presets")


@legacy_admin_or_acl_required("automazioni", "teams_flow_endpoint_create")
def teams_flow_endpoint_create(request):
    _flow_endpoints, flow_endpoints_warning = _helpers._get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    if request.method == "POST":
        form = AutomationDeliveryEndpointForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Endpoint Teams Flow creato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = AutomationDeliveryEndpointForm()
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(flow_form=form, flow_form_mode="create"),
    )


@legacy_admin_or_acl_required("automazioni", "teams_flow_endpoint_edit")
def teams_flow_endpoint_edit(request, pk: int):
    _flow_endpoints, flow_endpoints_warning = _helpers._get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    endpoint = get_object_or_404(
        AutomationDeliveryEndpoint,
        pk=pk,
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
    )
    if request.method == "POST":
        form = AutomationDeliveryEndpointForm(request.POST, instance=endpoint)
        if form.is_valid():
            form.save()
            messages.success(request, f"Endpoint '{endpoint.name}' aggiornato.")
            return redirect("admin_portale:automazioni_teams_presets")
    else:
        form = AutomationDeliveryEndpointForm(instance=endpoint)
    return render(
        request,
        "automazioni/pages/teams_presets.html",
        _build_teams_delivery_context(
            flow_form=form,
            flow_form_mode="edit",
            edit_flow_endpoint=endpoint,
        ),
    )


@legacy_admin_or_acl_required("automazioni", "teams_flow_endpoint_delete")
@require_POST
def teams_flow_endpoint_delete(request, pk: int):
    _flow_endpoints, flow_endpoints_warning = _helpers._get_teams_flow_endpoints_context(active_only=None)
    if flow_endpoints_warning:
        messages.warning(request, flow_endpoints_warning)
        return redirect("admin_portale:automazioni_teams_presets")
    endpoint = get_object_or_404(
        AutomationDeliveryEndpoint,
        pk=pk,
        endpoint_type=AutomationDeliveryEndpointType.TEAMS_FLOW_WEBHOOK,
    )
    name = endpoint.name
    endpoint.delete()
    messages.success(request, f"Endpoint '{name}' eliminato.")
    return redirect("admin_portale:automazioni_teams_presets")


# ═══════════════════════════════════════════════════════════════════════════════
# Template Email Approvazioni — CRUD + Preview + Clone
# ═══════════════════════════════════════════════════════════════════════════════

def _get_approval_templates_context() -> dict:
    """Contesto comune: lista template + warning schema drift."""
    templates, unavailable = list_approval_email_templates(enabled_only=False)
    return {
        "approval_templates": templates,
        "approval_templates_unavailable": APPROVAL_EMAIL_TEMPLATE_UNAVAILABLE_MESSAGE if unavailable else "",
    }


@legacy_admin_or_acl_required("automazioni", "approval_templates_list_page")
def approval_templates_list_page(request):
    ctx = _get_approval_templates_context()
    return render(request, "automazioni/pages/approval_template_list.html", ctx)


@legacy_admin_or_acl_required("automazioni", "approval_template_create_page")
def approval_template_create_page(request):
    from ..approval_email_templates import get_default_approval_mailbox

    if request.method == "POST":
        form = ApprovalEmailTemplateForm(request.POST)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.created_by = request.user
            tpl.updated_by = request.user
            tpl.save()
            messages.success(request, f"Template '{tpl.name}' creato.")
            return redirect("admin_portale:automazioni_approval_template_edit", pk=tpl.pk)
    else:
        form = ApprovalEmailTemplateForm(
            initial={"mailto_mailbox": get_default_approval_mailbox()}
        )

    _placeholders = ["id", "dipendente_nome", "tipo_assenza", "data_inizio", "data_fine", "note", "reparto", "capo_email", "approval_token", "approval_id", "approve_url", "reject_url"]
    return render(request, "automazioni/pages/approval_template_form.html", {
        "form": form,
        "is_create": True,
        "page_title": "Crea template email approvazione",
        "available_placeholders": _placeholders,
    })


@legacy_admin_or_acl_required("automazioni", "approval_template_edit_page")
def approval_template_edit_page(request, pk: int):
    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    if request.method == "POST":
        form = ApprovalEmailTemplateForm(request.POST, instance=tpl)
        if form.is_valid():
            tpl = form.save(commit=False)
            tpl.updated_by = request.user
            tpl.save()
            messages.success(request, f"Template '{tpl.name}' aggiornato.")
            return redirect("admin_portale:automazioni_approval_template_edit", pk=tpl.pk)
    else:
        form = ApprovalEmailTemplateForm(instance=tpl)

    _placeholders = ["id", "dipendente_nome", "tipo_assenza", "data_inizio", "data_fine", "note", "reparto", "capo_email", "approval_token", "approval_id", "approve_url", "reject_url"]
    return render(request, "automazioni/pages/approval_template_form.html", {
        "form": form,
        "template": tpl,
        "is_create": False,
        "page_title": f"Modifica — {tpl.name}",
        "available_placeholders": _placeholders,
    })


@legacy_admin_or_acl_required("automazioni", "approval_template_delete_page")
@require_POST
def approval_template_delete_page(request, pk: int):
    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    name = tpl.name
    tpl.delete()
    messages.success(request, f"Template '{name}' eliminato.")
    return redirect("admin_portale:automazioni_approval_templates")


@legacy_admin_or_acl_required("automazioni", "approval_template_clone_page")
@require_POST
def approval_template_clone_page(request, pk: int):
    """Clona un template esistente con nuovo code/name."""
    import uuid as _uuid
    source = get_object_or_404(ApprovalEmailTemplate, pk=pk)
    new_code_base = f"{source.code}-copia"
    suffix = str(_uuid.uuid4())[:6]
    new_code = f"{new_code_base}-{suffix}"

    clone = ApprovalEmailTemplate(
        code=new_code,
        name=f"{source.name} (copia)",
        description=source.description,
        is_enabled=False,
        delivery_mode=source.delivery_mode,
        subject_template=source.subject_template,
        title_template=source.title_template,
        intro_template=source.intro_template,
        body_template=source.body_template,
        include_facts=source.include_facts,
        facts_lines=source.facts_lines,
        approval_label=source.approval_label,
        rejection_label=source.rejection_label,
        include_mailto_actions=source.include_mailto_actions,
        mailto_mailbox=source.mailto_mailbox,
        approval_mailto_subject_template=source.approval_mailto_subject_template,
        approval_mailto_body_template=source.approval_mailto_body_template,
        rejection_mailto_subject_template=source.rejection_mailto_subject_template,
        rejection_mailto_body_template=source.rejection_mailto_body_template,
        created_by=request.user,
        updated_by=request.user,
    )
    clone.save()
    messages.success(request, f"Template clonato come '{clone.name}' (disabilitato, codice: {clone.code}).")
    return redirect("admin_portale:automazioni_approval_template_edit", pk=clone.pk)


@legacy_admin_or_acl_required("automazioni", "approval_template_preview_page")
def approval_template_preview_page(request, pk: int):
    """
    Preview HTML del template con dati mock o payload custom via GET params.
    Supporta ?raw=1 per restituire solo il corpo HTML (iframe-friendly).
    """
    from ..approval_email_templates import (
        DEMO_PAYLOAD,
        find_unresolved_placeholders,
        render_approval_email_preview,
    )

    tpl = get_object_or_404(ApprovalEmailTemplate, pk=pk)

    # Payload personalizzato opzionale via query string (JSON encoded)
    custom_payload_raw = request.GET.get("payload", "")
    custom_payload: dict = {}
    payload_error = ""
    if custom_payload_raw:
        try:
            parsed = json.loads(custom_payload_raw)
            if isinstance(parsed, dict):
                custom_payload = parsed
            else:
                payload_error = "Il payload deve essere un oggetto JSON."
        except Exception:
            payload_error = "JSON non valido nel parametro 'payload'."

    rendered = render_approval_email_preview(tpl, custom_payload or None)
    unresolved = find_unresolved_placeholders(rendered["html_body"] + rendered["subject"])

    if request.GET.get("raw") == "1":
        return HttpResponse(rendered["html_body"], content_type="text/html; charset=utf-8")

    return render(request, "automazioni/pages/approval_template_preview.html", {
        "template": tpl,
        "rendered": rendered,
        "unresolved": unresolved,
        "demo_payload": DEMO_PAYLOAD,
        "custom_payload_raw": custom_payload_raw,
        "payload_error": payload_error,
    })
