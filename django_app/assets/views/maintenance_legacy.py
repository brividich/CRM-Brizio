"""Pagine del vecchio motore manutenzioni (template, regole, verifiche periodiche, storico).

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from html import escape
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action
from ..registro_permessi import MODULO_VERIFICHE
from ..services.visibilita import filtra_per_asset

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from ..forms import (
    MaintenanceChecklistStepFormSet,
    MaintenanceInterventionTemplateForm,
    MaintenanceRuleAssetOverrideForm,
    PeriodicVerificationForm,
    IT_DEVICE_TYPES,
    NON_IT_ASSET_TYPES,
)
from ..models import _add_months
from ..models import (
    Asset,
    AssetMaintenanceRuleState,
    AssetCalendarEvent,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    PeriodicVerification,
    WorkOrder,
)

from ._helpers import (  # noqa: F401
    PERIODIC_EXECUTION_WINDOW_CHOICES,
    _as_int,
    _asset_calendar_default_user_id,
    _asset_calendar_source_key,
    _asset_calendar_transaction_id,
    _asset_maintenance_rule_list_page_url,
    _build_outlook_event_payload,
    _clean_string,
    _create_asset_calendar_event_record,
    _is_assets_admin,
    _legacy_employee_options,
    _maintenance_schedule_page_url,
    _maintenance_template_list_page_url,
    _normalize_periodic_execution_window,
    _outlook_calendar_graph_ready,
    _parse_execution_cost_input,
    _periodic_execution_rows_for_verification,
    _periodic_execution_window_cutoff,
    _periodic_verification_state,
)
from ._helpers_b import (  # noqa: F401
    _normalize_reports_scope,
    _periodic_verifications_page_url,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _copertura_dato,
    _save_workorder_attachments,
    _validate_workorder_attachment_uploads,
)

def _maintenance_settings_page_url(request: HttpRequest | None = None, *, tab: str = "catalogo") -> str:
    """URL del governo manutenzione, preservando i filtri principali."""
    tab_value = tab if tab in {"catalogo", "piani", "copertura"} else "catalogo"
    params: list[str] = [f"tab={tab_value}"]
    if request is not None:
        category_id = _as_int(request.GET.get("category"), default=0)
        if category_id:
            params.append(f"category={category_id}")
        active_value = _clean_string(request.GET.get("active")).lower()
        if active_value in {"active", "inactive", "all"}:
            params.append(f"active={quote(active_value)}")
        q = _clean_string(request.GET.get("q"))
        if q:
            params.append(f"q={quote(q)}")
    return f"{reverse('assets:maintenance_impostazioni')}?{'&'.join(params)}"


def _asset_maintenance_rule_override_edit_page_url(*, asset_id: int, override_id: int) -> str:
    return reverse(
        "assets:asset_maintenance_rule_override_edit",
        kwargs={"asset_id": int(asset_id), "id": int(override_id)},
    )


def _build_execution_workorder(
    *,
    asset: Asset,
    title: str,
    description: str,
    executed_on: date,
    duration_minutes: int,
    cost_value: "Decimal | None",
    resolution_text: str,
    periodic_verification: PeriodicVerification | None = None,
    maintenance_rule: MaintenanceRule | None = None,
    supplier=None,
) -> WorkOrder:
    executed_at_dt = timezone.make_aware(
        datetime.combine(executed_on, datetime.min.time().replace(hour=12)),
        timezone.get_current_timezone(),
    )
    workorder = WorkOrder.objects.create(
        asset=asset,
        periodic_verification=periodic_verification,
        maintenance_rule=maintenance_rule,
        supplier=supplier,
        kind=WorkOrder.KIND_PREVENTIVE,
        status=WorkOrder.STATUS_OPEN,
        opened_at=executed_at_dt,
        title=title[:255],
        description=description,
    )
    workorder.closed_at = executed_at_dt
    workorder.status = WorkOrder.STATUS_DONE
    if resolution_text:
        workorder.resolution = resolution_text
    workorder.intervention_duration_minutes = max(0, int(duration_minutes or 0))
    if cost_value is not None:
        workorder.cost_eur = cost_value
    workorder.full_clean()
    workorder.save()
    return workorder


def _periodic_verification_redirect_from_request(request: HttpRequest) -> str:
    return _periodic_verifications_page_url(
        asset_id=_as_int(request.POST.get("filter_asset"), default=0),
        edit_id=_as_int(request.POST.get("filter_edit"), default=0),
        scope=_clean_string(request.POST.get("filter_scope") or request.POST.get("scope")),
        window=_clean_string(request.POST.get("filter_window")),
        view=_clean_string(request.POST.get("filter_view")),
        q=_clean_string(request.POST.get("filter_q")),
    )


def _build_periodic_verification_outlook_event_payload(
    *,
    request: HttpRequest,
    asset: Asset,
    verification: PeriodicVerification,
    target_display_name: str,
    transaction_id: str,
) -> dict[str, object]:
    next_date = verification.next_verification_date
    if not isinstance(next_date, date):
        raise RuntimeError("La manutenzione periodica non ha una prossima data calendarizzabile.")
    asset_url = request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id}))
    verification_url = request.build_absolute_uri(_periodic_verifications_page_url(asset_id=asset.id, edit_id=verification.id))
    supplier_label = _clean_string(str(getattr(verification, "supplier", "") or "")) or "Fornitore non impostato"
    body_html = (
        "<p>Promemoria manutenzione periodica generato dal modulo Assets.</p>"
        f"<p><strong>Destinatario:</strong> {escape(target_display_name or 'Utente selezionato')}<br>"
        f"<strong>Asset:</strong> {escape(asset.asset_tag)} - {escape(asset.name)}<br>"
        f"<strong>Manutenzione periodica:</strong> {escape(verification.name)}<br>"
        f"<strong>Prossima data:</strong> {next_date:%d-%m-%Y}<br>"
        f"<strong>Cadenza:</strong> {int(verification.frequency_months or 0)} mesi<br>"
        f"<strong>Fornitore:</strong> {escape(supplier_label)}</p>"
        f"<p><a href=\"{escape(asset_url)}\">Apri scheda asset</a><br>"
        f"<a href=\"{escape(verification_url)}\">Apri manutenzione periodica</a></p>"
    )
    subject = f"Manutenzione periodica {asset.asset_tag} - {verification.name}"[:255]
    return _build_outlook_event_payload(
        subject=subject,
        body_html=body_html,
        location_label=_clean_string(asset.reparto) or "Manutenzione periodica asset",
        due_date=next_date,
        transaction_id=transaction_id,
    )


def _create_asset_periodic_verification_calendar_event(
    *,
    request: HttpRequest,
    asset: Asset,
    verification: PeriodicVerification,
    target_legacy_user_id: int,
    target_details: dict[str, str],
) -> tuple[AssetCalendarEvent, bool]:
    next_date = verification.next_verification_date
    if not isinstance(next_date, date):
        raise RuntimeError("La manutenzione periodica selezionata non ha una prossima data impostata.")
    source_key = _asset_calendar_source_key(
        event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
        asset_id=asset.id,
        source_id=verification.id,
        due_date=next_date,
        target_legacy_user_id=target_legacy_user_id,
    )
    payload = _build_periodic_verification_outlook_event_payload(
        request=request,
        asset=asset,
        verification=verification,
        target_display_name=_clean_string(target_details.get("display_name")),
        transaction_id=_asset_calendar_transaction_id(source_key=source_key),
    )
    return _create_asset_calendar_event_record(
        asset=asset,
        event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
        source_key=source_key,
        due_date=next_date,
        target_legacy_user_id=target_legacy_user_id,
        target_details=target_details,
        payload=payload,
        request_user=request.user,
        periodic_verification=verification,
    )


def _periodic_scope_context(scope: str) -> dict[str, object]:
    if scope == "it":
        return {
            "scope": "it",
            "title": "Manutenzione periodica dispositivi IT",
            "subtitle": "Piani ricorrenti filtrati su PC, server, rete, fonia, TVCC e dispositivi IT.",
            "asset_types": IT_DEVICE_TYPES,
        }
    # Lo scope "production" e' il complemento di quello IT: ogni asset non IT
    # deve poter avere un piano di manutenzione periodica, impianti generici e
    # prodotti chimici inclusi. Stessa semantica dello scadenzario
    # (`exclude(assets__asset_type__in=IT_DEVICE_TYPES)`).
    return {
        "scope": "production",
        "title": "Manutenzione periodica asset produzione",
        "subtitle": "Piani ricorrenti su tutti gli asset non IT: CNC, macchine utensili, carroponti, impianti e altri asset.",
        "asset_types": NON_IT_ASSET_TYPES,
    }


@login_required
def maintenance_template_list(request: HttpRequest) -> HttpResponse:
    """Deprecata: template e regole sono ora un'unica vista in Impostazioni manutenzione.
    Redirige alla tab 'Interventi & Regole' preservando i filtri (categoria/attivo/ricerca)."""
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")
    return redirect(_maintenance_settings_page_url(request, tab="catalogo"), permanent=True)


def _save_template_checklist_formset(formset, template) -> None:
    """Salva il formset degli step checklist e normalizza la numerazione a 10, 20, 30...
    Gli step lasciati senza numero finiscono in coda."""
    from ..models import MaintenanceChecklistStep

    formset.instance = template
    saved = formset.save(commit=False)
    for obj in formset.deleted_objects:
        obj.delete()
    for offset, obj in enumerate(saved):
        if not obj.step_number:
            obj.step_number = 9000 + offset
        obj.save()
    for idx, step in enumerate(
        MaintenanceChecklistStep.objects.filter(intervention_template=template).order_by("step_number", "id"),
        start=1,
    ):
        target = idx * 10
        if step.step_number != target:
            step.step_number = target
            step.save(update_fields=["step_number"])


def _template_next_step_rule_url(template) -> str:
    """URL di creazione regola precompilato con il template appena salvato (CTA continuità)."""
    # Il "template" e' il piano stesso: il passo successivo e' applicarlo a qualcosa.
    return reverse("assets:maintenance_assignment_create", kwargs={"plan_id": template.id})


@login_required
def maintenance_template_create(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")

    selected_category_id = _as_int(request.GET.get("category"), default=0)
    initial = {"asset_category": selected_category_id} if selected_category_id else None

    if request.method == "POST":
        form = MaintenanceInterventionTemplateForm(request.POST)
        checklist_formset = MaintenanceChecklistStepFormSet(request.POST, prefix="checklist")
        if form.is_valid() and checklist_formset.is_valid():
            template = form.save()
            _save_template_checklist_formset(checklist_formset, template)
            log_action(
                request,
                "create_maintenance_template",
                "assets",
                {"template_id": template.id, "code": template.code, "asset_category_id": template.asset_category_id},
            )
            messages.success(
                request,
                "Tipo di attivita creato. Definisci ora il piano che lo applica agli asset.",
            )
            return redirect(_template_next_step_rule_url(template))
    else:
        form = MaintenanceInterventionTemplateForm(initial=initial)
        checklist_formset = MaintenanceChecklistStepFormSet(prefix="checklist")

    return render(
        request,
        "assets/pages/maintenance_template_form.html",
        {
            "page_title": "Nuovo tipo di attivita",
            "form": form,
            "checklist_formset": checklist_formset,
            "is_edit": False,
            "back_url": _maintenance_template_list_page_url(category_id=selected_category_id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_template_list"),
                new_url=reverse("assets:maintenance_template_create"),
                new_label="+ Nuovo tipo",
                search_placeholder="Ricerca rapida per attivita, codice o categoria",
            ),
        },
    )


@login_required
def maintenance_template_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template manutenzione.")
        return redirect("assets:asset_list")
    if id is None:
        return redirect("assets:maintenance_template_list")

    template = get_object_or_404(MaintenanceInterventionTemplate.objects.select_related("asset_category"), pk=id)
    if request.method == "POST":
        form = MaintenanceInterventionTemplateForm(request.POST, instance=template)
        checklist_formset = MaintenanceChecklistStepFormSet(request.POST, instance=template, prefix="checklist")
        if form.is_valid() and checklist_formset.is_valid():
            template = form.save()
            _save_template_checklist_formset(checklist_formset, template)
            log_action(
                request,
                "update_maintenance_template",
                "assets",
                {"template_id": template.id, "code": template.code, "asset_category_id": template.asset_category_id},
            )
            messages.success(request, "Tipo di attivita aggiornato.")
            return redirect(_maintenance_template_list_page_url(category_id=template.asset_category_id or 0))
    else:
        form = MaintenanceInterventionTemplateForm(instance=template)
        checklist_formset = MaintenanceChecklistStepFormSet(instance=template, prefix="checklist")

    return render(
        request,
        "assets/pages/maintenance_template_form.html",
        {
            "page_title": f"Modifica attivita {template.label}",
            "form": form,
            "checklist_formset": checklist_formset,
            "template": template,
            "is_edit": True,
            "rule_create_url": _template_next_step_rule_url(template),
            "back_url": _maintenance_template_list_page_url(category_id=template.asset_category_id or 0),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:maintenance_template_list"),
                new_url=reverse("assets:maintenance_template_create"),
                new_label="+ Nuovo tipo",
                search_placeholder="Ricerca rapida per attivita, codice o categoria",
            ),
        },
    )


@login_required
def maintenance_rule_list(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_plan_list")


@login_required
def maintenance_rule_create(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_plan_create")


@login_required
def maintenance_rule_impact_preview(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_plan_list")


@login_required
def maintenance_rule_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_plan_list")


@login_required
def asset_maintenance_rule_list(request: HttpRequest, asset_id: int) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:asset_maintenance_plans", asset_id=asset_id)


@login_required
def asset_maintenance_rule_override_create(request: HttpRequest, asset_id: int, rule_id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo personalizzare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    base_rule = get_object_or_404(
        MaintenanceRule.objects.select_related("asset_category", "intervention_template"),
        pk=rule_id,
    )
    if not asset.asset_category_id or asset.asset_category_id != base_rule.asset_category_id:
        messages.error(request, "La regola selezionata non appartiene alla categoria dell'asset.")
        return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))

    existing_override = MaintenanceRuleAssetOverride.objects.filter(asset=asset, base_rule=base_rule).first()
    if existing_override is not None:
        messages.info(request, "Esiste gia una personalizzazione per questa regola. Puoi modificarla direttamente.")
        return redirect(_asset_maintenance_rule_override_edit_page_url(asset_id=asset.id, override_id=existing_override.id))

    if request.method == "POST":
        form = MaintenanceRuleAssetOverrideForm(
            request.POST,
            locked_asset=asset,
            locked_base_rule=base_rule,
        )
        if form.is_valid():
            override = form.save()
            log_action(
                request,
                "create_asset_maintenance_override",
                "assets",
                {
                    "override_id": override.id,
                    "asset_id": override.asset_id,
                    "base_rule_id": override.base_rule_id,
                    "is_disabled": override.is_disabled,
                },
            )
            messages.success(request, "Personalizzazione regola salvata.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))
    else:
        form = MaintenanceRuleAssetOverrideForm(
            locked_asset=asset,
            locked_base_rule=base_rule,
        )

    return render(
        request,
        "assets/pages/maintenance_asset_rule_override_form.html",
        {
            "page_title": f"Personalizza regola {base_rule.intervention_template.label}",
            "asset": asset,
            "base_rule": base_rule,
            "form": form,
            "is_edit": False,
            "back_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_maintenance_rule_list_page_url(asset_id=asset.id),
                search_placeholder="Ricerca contestuale disponibile dal dettaglio asset",
            ),
        },
    )


@login_required
def asset_maintenance_rule_override_edit(request: HttpRequest, asset_id: int, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo personalizzare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    override = get_object_or_404(
        MaintenanceRuleAssetOverride.objects.select_related(
            "asset",
            "base_rule",
            "base_rule__asset_category",
            "base_rule__intervention_template",
            "override_intervention_template",
        ),
        pk=id,
        asset_id=asset.id,
    )

    if request.method == "POST":
        form = MaintenanceRuleAssetOverrideForm(
            request.POST,
            instance=override,
            locked_asset=asset,
            locked_base_rule=override.base_rule,
        )
        if form.is_valid():
            override = form.save()
            log_action(
                request,
                "update_asset_maintenance_override",
                "assets",
                {
                    "override_id": override.id,
                    "asset_id": override.asset_id,
                    "base_rule_id": override.base_rule_id,
                    "is_disabled": override.is_disabled,
                },
            )
            messages.success(request, "Personalizzazione regola aggiornata.")
            return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))
    else:
        form = MaintenanceRuleAssetOverrideForm(
            instance=override,
            locked_asset=asset,
            locked_base_rule=override.base_rule,
        )

    return render(
        request,
        "assets/pages/maintenance_asset_rule_override_form.html",
        {
            "page_title": f"Modifica personalizzazione {override.base_rule.intervention_template.label}",
            "asset": asset,
            "base_rule": override.base_rule,
            "override": override,
            "form": form,
            "is_edit": True,
            "back_url": _asset_maintenance_rule_list_page_url(asset_id=asset.id),
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=_asset_maintenance_rule_list_page_url(asset_id=asset.id),
                search_placeholder="Ricerca contestuale disponibile dal dettaglio asset",
            ),
        },
    )


@login_required
def asset_maintenance_rule_override_reset(request: HttpRequest, asset_id: int, id: int) -> HttpResponse:
    asset = get_object_or_404(Asset.objects.only("id"), pk=asset_id)
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo ripristinare le regole manutenzione degli asset.")
        return redirect("assets:asset_view", id=asset.id)

    override = get_object_or_404(
        MaintenanceRuleAssetOverride.objects.select_related("base_rule"),
        pk=id,
        asset_id=asset.id,
    )
    if request.method != "POST":
        messages.error(request, "Usa l'azione di ripristino dalla pagina delle regole asset.")
        return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))

    log_action(
        request,
        "reset_asset_maintenance_override",
        "assets",
        {
            "override_id": override.id,
            "asset_id": override.asset_id,
            "base_rule_id": override.base_rule_id,
        },
    )
    override.delete()
    messages.success(request, "Override rimosso. La regola e tornata ereditata.")
    return redirect(_asset_maintenance_rule_list_page_url(asset_id=asset.id))


@login_required
def maintenance_schedule(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_scadenze")


@login_required
def periodic_verification_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    can_manage_periodic_verifications = _is_assets_admin(request)
    can_manage_outlook_calendar = can_manage_periodic_verifications
    calendar_user_choices: list[tuple[str, str]] = []
    calendar_user_details: dict[str, dict[str, str]] = {}
    if can_manage_outlook_calendar:
        calendar_user_choices, calendar_user_details = _legacy_employee_options()

    selected_asset_id = _as_int(request.POST.get("asset_id") or request.GET.get("asset"), default=0)
    selected_asset = None
    if selected_asset_id:
        selected_asset = Asset.objects.filter(pk=selected_asset_id).only("id", "asset_tag", "name", "reparto", "asset_type").first()

    raw_scope = request.POST.get("scope") or request.GET.get("scope")
    if raw_scope:
        periodic_scope = _normalize_reports_scope(raw_scope)
    elif selected_asset is not None and selected_asset.asset_type in IT_DEVICE_TYPES:
        periodic_scope = "it"
    else:
        periodic_scope = "production"
    periodic_context = _periodic_scope_context(periodic_scope)
    periodic_asset_types = list(periodic_context["asset_types"])
    scope_asset_queryset = Asset.objects.filter(asset_type__in=periodic_asset_types)
    execution_window = _normalize_periodic_execution_window(request.GET.get("window"))
    execution_cutoff = _periodic_execution_window_cutoff(execution_window, today=today)
    periodic_view = _clean_string(request.GET.get("view")).lower()
    if periodic_view not in {"active", "attention", "planned", "archive"}:
        periodic_view = "active"
    periodic_q = _clean_string(request.GET.get("q"))

    if "scope" not in request.GET and request.method == "GET":
        query = request.GET.copy()
        query["scope"] = periodic_scope
        return redirect(f"{reverse('assets:periodic_verifications')}?{query.urlencode()}")

    if selected_asset is not None and selected_asset.asset_type not in periodic_asset_types:
        target_scope = "it" if selected_asset.asset_type in IT_DEVICE_TYPES else "production"
        # Rimbalzare sullo scope da cui si arriva significherebbe redirigere
        # sulla stessa URL all'infinito (ERR_TOO_MANY_REDIRECTS): si redirige
        # solo verso uno scope diverso, altrimenti si resta e si mostra la
        # pagina con il filtro asset attivo.
        if target_scope != periodic_scope:
            query = request.GET.copy()
            query["scope"] = target_scope
            return redirect(f"{reverse('assets:periodic_verifications')}?{query.urlencode()}")

    edit_id = _as_int(request.POST.get("edit_id") or request.GET.get("edit"), default=0)
    edit_verification = None
    if edit_id:
        edit_verification = (
            filtra_per_asset(request, PeriodicVerification.objects.all(), MODULO_VERIFICHE, "assets").select_related("supplier", "created_by")
            .prefetch_related("assets")
            .filter(pk=edit_id)
            .first()
        )

    form = PeriodicVerificationForm(
        instance=edit_verification,
        actor=request.user,
        preselected_asset_id=selected_asset.id if selected_asset else 0,
        asset_queryset=scope_asset_queryset,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        if action == "create_outlook_calendar_event":
            redirect_url = _periodic_verification_redirect_from_request(request)
            if not can_manage_outlook_calendar:
                messages.error(request, "Solo gli admin assets possono creare eventi Outlook su calendari utente.")
                return redirect(redirect_url)
            if selected_asset is None:
                messages.error(
                    request,
                    "Per la manutenzione periodica seleziona prima un asset: l'evento Outlook viene creato sul contesto asset.",
                )
                return redirect(redirect_url)

            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            target_legacy_user_id = _as_int(request.POST.get("target_legacy_user_id"), default=0)
            verification = (
                filtra_per_asset(request, PeriodicVerification.objects.all(), MODULO_VERIFICHE, "assets").select_related("supplier", "created_by")
                .prefetch_related("assets")
                .filter(pk=verification_id)
                .first()
            )
            target_details = calendar_user_details.get(str(target_legacy_user_id))
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(redirect_url)
            if target_details is None:
                messages.error(request, "Seleziona un utente valido per il calendario Outlook.")
                return redirect(redirect_url)
            if not verification.assets.filter(pk=selected_asset.id).exists():
                messages.error(request, "La manutenzione periodica selezionata non e collegata all'asset attualmente filtrato.")
                return redirect(redirect_url)
            if not isinstance(verification.next_verification_date, date):
                messages.error(request, "Questa manutenzione periodica non ha una prossima data calendarizzabile.")
                return redirect(redirect_url)

            try:
                entry, created = _create_asset_periodic_verification_calendar_event(
                    request=request,
                    asset=selected_asset,
                    verification=verification,
                    target_legacy_user_id=target_legacy_user_id,
                    target_details=target_details,
                )
                target_label = entry.target_display_name or entry.target_email or f"utente {entry.target_legacy_user_id}"
                if created:
                    log_action(
                        request,
                        "create_periodic_verification_calendar_event",
                        "assets",
                        {
                            "verification_id": verification.id,
                            "asset_id": selected_asset.id,
                            "due_date": str(verification.next_verification_date),
                            "target_legacy_user_id": entry.target_legacy_user_id,
                            "target_email": entry.target_email,
                            "graph_event_id": entry.graph_event_id,
                        },
                    )
                    messages.success(
                        request,
                        f"Evento Outlook creato per {target_label} sulla scadenza del {entry.due_date:%d-%m-%Y}.",
                    )
                else:
                    messages.info(
                        request,
                        f"Esiste gia un evento Outlook per {target_label} su questa stessa scadenza.",
                    )
            except Exception as exc:
                messages.error(request, f"Creazione evento Outlook fallita: {exc}")
            return redirect(redirect_url)

        if action == "record_periodic_verification_execution":
            redirect_url = _periodic_verification_redirect_from_request(request)
            if not can_manage_periodic_verifications:
                messages.error(request, "Solo admin puo registrare esecuzioni di manutenzione periodica.")
                return redirect(redirect_url)
            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            verification = (
                PeriodicVerification.objects.select_related("supplier")
                .prefetch_related("assets")
                .filter(pk=verification_id)
                .first()
            )
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(redirect_url)
            raw_asset_ids = request.POST.getlist("execution_asset_ids")
            if not raw_asset_ids:
                legacy_single = request.POST.get("execution_asset_id")
                if legacy_single:
                    raw_asset_ids = [legacy_single]
            target_asset_ids: list[int] = []
            for raw_id in raw_asset_ids:
                parsed = _as_int(raw_id, default=0)
                if parsed and parsed not in target_asset_ids:
                    target_asset_ids.append(parsed)
            target_assets = list(
                verification.assets.filter(pk__in=target_asset_ids)
            ) if target_asset_ids else []
            if not target_assets:
                messages.error(request, "Seleziona almeno un asset coinvolto nel piano per registrare l'esecuzione.")
                return redirect(redirect_url)
            executed_on_raw = _clean_string(request.POST.get("execution_date"))
            if executed_on_raw:
                try:
                    executed_on = date.fromisoformat(executed_on_raw)
                except ValueError:
                    messages.error(request, "Data di esecuzione non valida.")
                    return redirect(redirect_url)
            else:
                executed_on = today
            if executed_on > today:
                messages.error(request, "La data di esecuzione non puo essere futura.")
                return redirect(redirect_url)
            duration_minutes = max(0, _as_int(request.POST.get("execution_duration_minutes"), default=0))
            try:
                cost_value = _parse_execution_cost_input(request.POST.get("execution_cost_eur"))
            except ValueError:
                messages.error(request, "Costo non valido: usa un numero non negativo (es. 120.50).")
                return redirect(redirect_url)
            resolution_text = _clean_string(request.POST.get("execution_notes"))
            uploads, upload_errors = _validate_execution_attachment_uploads(request)
            if upload_errors:
                for error in upload_errors:
                    messages.error(request, error)
                return redirect(redirect_url)
            created_workorders: list[WorkOrder] = []
            attachments_total = 0
            try:
                with transaction.atomic():
                    for target_asset in target_assets:
                        workorder = _build_execution_workorder(
                            asset=target_asset,
                            title=f"Esecuzione manutenzione periodica: {verification.name}",
                            description=resolution_text,
                            executed_on=executed_on,
                            duration_minutes=duration_minutes,
                            cost_value=cost_value,
                            resolution_text=resolution_text,
                            periodic_verification=verification,
                            supplier=verification.supplier,
                        )
                        created_workorders.append(workorder)
                        if uploads:
                            attachments_total += len(
                                _save_workorder_attachments(
                                    workorder=workorder,
                                    uploads=uploads,
                                    user=request.user,
                                )
                            )
                    WorkOrder.mark_batch(created_workorders)
                    previous_last = verification.last_verification_date
                    if previous_last is None or executed_on >= previous_last:
                        verification.last_verification_date = executed_on
                        verification.next_verification_date = _add_months(
                            executed_on, verification.frequency_months
                        )
                        verification.save(update_fields=["last_verification_date", "next_verification_date", "updated_at"])
            except ValidationError as exc:
                messages.error(request, f"Esecuzione non registrabile: {exc}")
                return redirect(redirect_url)
            except Exception as exc:
                messages.error(request, f"Errore registrazione esecuzione: {exc}")
                return redirect(redirect_url)
            log_action(
                request,
                "record_periodic_verification_execution",
                "assets",
                {
                    "verification_id": verification.id,
                    "asset_ids": [asset.id for asset in target_assets],
                    "workorder_ids": [wo.id for wo in created_workorders],
                    "executed_on": str(executed_on),
                    "cost_eur": str(cost_value) if cost_value is not None else None,
                    "duration_minutes": duration_minutes,
                    "attachments": attachments_total,
                },
            )
            asset_label = (
                target_assets[0].asset_tag
                if len(target_assets) == 1
                else f"{len(target_assets)} asset"
            )
            attach_suffix = f" ({attachments_total} allegati)" if attachments_total else ""
            messages.success(
                request,
                f"Esecuzione registrata su {asset_label} il {executed_on:%d-%m-%Y}{attach_suffix}.",
            )
            return redirect(redirect_url)

        if action == "convert_periodic_to_rule":
            redirect_url = _periodic_verification_redirect_from_request(request)
            if not can_manage_periodic_verifications:
                messages.error(request, "Solo admin puo inglobare la manutenzione periodica nei piani ordinari.")
                return redirect(redirect_url)
            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            verification = (
                PeriodicVerification.objects.prefetch_related("assets__asset_category")
                .filter(pk=verification_id)
                .first()
            )
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(redirect_url)
            if verification.is_legacy:
                messages.info(request, "Questo piano e gia gestito da una regola di manutenzione.")
                return redirect(redirect_url)
            from ..services.periodic_migration import migrate_periodic_verification_to_rule

            result = migrate_periodic_verification_to_rule(verification)
            if not result.get("ok"):
                messages.error(request, result.get("message") or "Inglobamento non possibile per questo piano.")
                return redirect(redirect_url)
            log_action(
                request,
                "convert_periodic_verification_to_rule",
                "assets",
                {
                    "verification_id": verification.id,
                    "rule_id": result["rule"].id,
                    "template_id": result["template"].id,
                    "created_template": result["created_template"],
                    "created_rule": result["created_rule"],
                    "threshold_days": result["threshold_days"],
                },
            )
            messages.success(
                request,
                f"Piano inglobato in {len(result.get('rules') or [result['rule']])} piano/i ordinari "
                f"({result['threshold_days']} giorni), con asset e storico preservati.",
            )
            return redirect(redirect_url)

        if action in {"create_periodic_verification", "update_periodic_verification", "delete_periodic_verification"} and not can_manage_periodic_verifications:
            messages.error(request, "Solo admin puo gestire la manutenzione periodica.")
            return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0, scope=periodic_scope))

        if action in {"create_periodic_verification", "update_periodic_verification"}:
            instance = edit_verification if action == "update_periodic_verification" else None
            if action == "update_periodic_verification" and instance is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
                return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0, scope=periodic_scope))
            form = PeriodicVerificationForm(
                request.POST,
                instance=instance,
                actor=request.user,
                preselected_asset_id=selected_asset.id if selected_asset else 0,
                asset_queryset=scope_asset_queryset,
            )
            if form.is_valid():
                verification = form.save()
                message = (
                    "Manutenzione periodica aggiornata."
                    if instance is not None
                    else "Manutenzione periodica creata."
                )
                messages.success(request, message)
                return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0, scope=periodic_scope))
        elif action == "delete_periodic_verification":
            verification_id = _as_int(request.POST.get("verification_id"), default=0)
            verification = PeriodicVerification.objects.filter(pk=verification_id).first()
            if verification is None:
                messages.error(request, "Piano di manutenzione periodica non trovato.")
            else:
                verification_name = verification.name
                verification.delete()
                messages.success(request, f'Manutenzione periodica "{verification_name}" eliminata.')
            return redirect(_periodic_verifications_page_url(asset_id=selected_asset.id if selected_asset else 0, scope=periodic_scope))

    verification_rows: list[dict[str, object]] = []
    verification_event_map: dict[int, list[AssetCalendarEvent]] = defaultdict(list)
    if selected_asset is not None:
        linked_ids = list(
            PeriodicVerification.objects.filter(assets__id=selected_asset.id).values_list("id", flat=True).distinct()
        )
        if linked_ids:
            for entry in (
                AssetCalendarEvent.objects.select_related("periodic_verification")
                .filter(
                    event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
                    asset_id=selected_asset.id,
                    periodic_verification_id__in=linked_ids,
                )
                .order_by("target_display_name", "target_email", "created_at", "id")
            ):
                if entry.periodic_verification_id:
                    verification_event_map[entry.periodic_verification_id].append(entry)

    default_calendar_user_id = _asset_calendar_default_user_id(selected_asset, calendar_user_details)
    verification_queryset = (
        filtra_per_asset(request, PeriodicVerification.objects.all(), MODULO_VERIFICHE, "assets").select_related("supplier", "created_by")
        .prefetch_related("assets")
        .filter(assets__asset_type__in=periodic_asset_types)
        .distinct()
        .order_by("-is_active", "next_verification_date", "name", "id")
    )
    if selected_asset is not None:
        verification_queryset = verification_queryset.filter(assets=selected_asset)

    for verification in verification_queryset:
        linked_assets = [asset for asset in verification.assets.all() if asset.asset_type in periodic_asset_types]
        is_selected_asset_linked = bool(selected_asset and any(asset.id == selected_asset.id for asset in linked_assets))
        execution_rows = _periodic_execution_rows_for_verification(
            verification_id=verification.id,
            asset_id=selected_asset.id if selected_asset is not None else 0,
            cutoff_date=execution_cutoff,
        )
        # Idoneità alla conversione in regola (check leggero su asset già prefetchati;
        # la validazione completa avviene nell'azione convert_periodic_to_rule).
        all_assets = list(verification.assets.all())
        all_category_ids = {asset.asset_category_id for asset in all_assets}
        can_convert_to_rule = bool(
            can_manage_periodic_verifications
            and not verification.is_legacy
            and all_assets
            and None not in all_category_ids
            and len(all_category_ids) == 1
        )
        convert_block_reason = ""
        if can_manage_periodic_verifications and not verification.is_legacy and not can_convert_to_rule:
            convert_block_reason = (
                "Nessun asset collegato" if not all_assets
                else "Asset di categorie diverse o senza categoria"
            )
        verification_rows.append(
            {
                "verification": verification,
                "state": _periodic_verification_state(verification, today=today),
                "is_legacy": verification.is_legacy,
                "can_convert_to_rule": can_convert_to_rule,
                "convert_block_reason": convert_block_reason,
                "linked_assets": linked_assets,
                "linked_assets_count": len(linked_assets),
                "is_selected_asset_linked": is_selected_asset_linked,
                "can_create_calendar_event": bool(
                    selected_asset is not None
                    and is_selected_asset_linked
                    and isinstance(verification.next_verification_date, date)
                ),
                "calendar_event_rows": list(verification_event_map.get(verification.id, [])),
                "default_calendar_user_id": default_calendar_user_id,
                "edit_url": _periodic_verifications_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    edit_id=verification.id,
                    scope=periodic_scope,
                    window=execution_window,
                    view=periodic_view,
                    q=periodic_q,
                ),
                "execution_rows": execution_rows,
                "execution_count": len(execution_rows),
                "execution_assets": linked_assets,
            }
        )

    state_priority = {"overdue": 0, "warning": 1, "missing": 2, "ok": 3, "inactive": 4}
    verification_rows.sort(
        key=lambda row: (
            bool(row["is_legacy"]),
            state_priority.get(row["state"]["status"], 9),
            row["verification"].next_verification_date or date.max,
            row["verification"].name.lower(),
        )
    )
    periodic_counts = {
        "active": sum(
            1 for row in verification_rows if row["verification"].is_active and not row["is_legacy"]
        ),
        "attention": sum(
            1
            for row in verification_rows
            if row["verification"].is_active
            and not row["is_legacy"]
            and row["state"]["status"] in {"overdue", "warning", "missing"}
        ),
        "planned": sum(
            1
            for row in verification_rows
            if row["verification"].is_active
            and not row["is_legacy"]
            and row["state"]["status"] == "ok"
        ),
        "archive": sum(
            1 for row in verification_rows if row["is_legacy"] or not row["verification"].is_active
        ),
    }
    verification_total_count = len(verification_rows)
    legacy_verification_count = sum(1 for row in verification_rows if row["is_legacy"])

    def row_matches_view(row) -> bool:
        if periodic_view == "attention":
            return bool(
                row["verification"].is_active
                and not row["is_legacy"]
                and row["state"]["status"] in {"overdue", "warning", "missing"}
            )
        if periodic_view == "planned":
            return bool(
                row["verification"].is_active
                and not row["is_legacy"]
                and row["state"]["status"] == "ok"
            )
        if periodic_view == "archive":
            return bool(row["is_legacy"] or not row["verification"].is_active)
        return bool(row["verification"].is_active and not row["is_legacy"])

    verification_rows = [row for row in verification_rows if row_matches_view(row)]
    if periodic_q:
        search_term = periodic_q.casefold()
        verification_rows = [
            row
            for row in verification_rows
            if search_term
            in " ".join(
                [
                    row["verification"].name,
                    str(row["verification"].supplier or ""),
                    row["verification"].notes or "",
                    *[
                        f"{asset.asset_tag} {asset.name} {asset.reparto}"
                        for asset in row["linked_assets"]
                    ],
                ]
            ).casefold()
        ]

    selected_asset_linked_count = (
        verification_total_count
        if selected_asset is not None
        else 0
    )

    return render(
        request,
        "assets/pages/periodic_verification_list.html",
        {
            "page_title": periodic_context["title"],
            "periodic_scope": periodic_context["scope"],
            "periodic_page_title": periodic_context["title"],
            "periodic_page_subtitle": periodic_context["subtitle"],
            "periodic_base_url": _periodic_verifications_page_url(scope=periodic_scope),
            "form": form,
            "verification_rows": verification_rows,
            "verification_total": verification_total_count,
            "active_verification_count": periodic_counts["active"],
            "due_verification_count": periodic_counts["attention"],
            "legacy_verification_count": legacy_verification_count,
            "periodic_counts": periodic_counts,
            "periodic_view": periodic_view,
            "periodic_q": periodic_q,
            "periodic_view_urls": {
                view_key: _periodic_verifications_page_url(
                    asset_id=selected_asset.id if selected_asset else 0,
                    scope=periodic_scope,
                    view=view_key,
                )
                for view_key in ("active", "attention", "planned", "archive")
            },
            "periodic_current_view_url": _periodic_verifications_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                scope=periodic_scope,
                view=periodic_view,
                q=periodic_q,
            ),
            "periodic_clear_url": _periodic_verifications_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                scope=periodic_scope,
                view=periodic_view,
            ),
            "periodic_create_url": _periodic_verifications_page_url(
                asset_id=selected_asset.id if selected_asset else 0,
                scope=periodic_scope,
                view=periodic_view,
                q=periodic_q,
                create=True,
            ),
            "show_periodic_form": bool(
                can_manage_periodic_verifications
                and (edit_verification is not None or request.GET.get("create") == "1" or form.errors)
            ),
            "selected_asset": selected_asset,
            "selected_asset_linked_count": selected_asset_linked_count,
            "execution_window": execution_window,
            "execution_window_choices": list(PERIODIC_EXECUTION_WINDOW_CHOICES),
            "today_iso": today.isoformat(),
            "can_manage_periodic_verifications": can_manage_periodic_verifications,
            "can_manage_outlook_calendar": can_manage_outlook_calendar,
            "outlook_calendar_ready": _outlook_calendar_graph_ready() if can_manage_outlook_calendar else False,
            "calendar_user_choices": calendar_user_choices,
            "is_edit": edit_verification is not None,
            "edit_verification": edit_verification,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


def _validate_execution_attachment_uploads(request: HttpRequest) -> tuple[list, list[str]]:
    return _validate_workorder_attachment_uploads(request, field_name="execution_files")


@login_required
def maintenance_history(request: HttpRequest) -> HttpResponse:
    """Storico aziendale unico: OdL conclusi, manutenzioni registrate, scadenze
    amministrative svolte e ticket MAN, senza alterarne i flussi."""
    from tickets.models import StatoTicket, Ticket, TipoTicket

    q = _clean_string(request.GET.get("q"))
    source = _clean_string(request.GET.get("source")).lower() or "all"
    if source not in {"all", "workorders", "maintenance", "deadlines", "tickets"}:
        source = "all"

    def parsed_date(name: str) -> date | None:
        raw = _clean_string(request.GET.get(name))
        try:
            return date.fromisoformat(raw) if raw else None
        except ValueError:
            return None

    date_from = parsed_date("date_from")
    date_to = parsed_date("date_to")
    rows: list[dict[str, object]] = []

    if source in {"all", "workorders"}:
        workorders = WorkOrder.objects.filter(
            status__in=[WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED]
        ).select_related(
            "asset", "executed_by", "assigned_to", "supplier", "maintenance_rule__intervention_template"
        )
        if q:
            workorders = workorders.filter(
                Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(resolution__icontains=q)
                | Q(asset__asset_tag__icontains=q)
                | Q(asset__name__icontains=q)
                | Q(maintenance_rule__intervention_template__label__icontains=q)
            )
        if date_from:
            workorders = workorders.filter(closed_at__date__gte=date_from)
        if date_to:
            workorders = workorders.filter(closed_at__date__lte=date_to)
        for workorder in workorders.order_by("-closed_at", "-id")[:500]:
            technician = workorder.executed_by or workorder.assigned_to
            rows.append(
                {
                    "source": "workorder",
                    "source_label": "OdL",
                    "date": workorder.closed_at or workorder.opened_at,
                    "title": workorder.title,
                    "asset": workorder.asset,
                    "type_label": workorder.get_kind_display(),
                    "status_label": workorder.get_status_display(),
                    "technician": technician.get_full_name() or technician.username if technician else "-",
                    "duration_minutes": workorder.intervention_duration_minutes,
                    "cost": workorder.resolved_total_cost_eur,
                    "url": reverse("assets:wo_view", kwargs={"id": workorder.id}),
                }
            )

    if source in {"all", "maintenance"}:
        # Manutenzioni registrate direttamente ("Registra" da Da fare, Calendario,
        # Scadenzario) senza un ordine di lavoro: sono lavoro fatto quanto un OdL
        # chiuso, e prima nello Storico non comparivano.
        from ..models import MaintenanceOccurrence

        registered = MaintenanceOccurrence.objects.filter(
            status=MaintenanceOccurrence.STATUS_DONE, work_order__isnull=True
        ).select_related("asset", "plan", "completed_by")
        if q:
            registered = registered.filter(
                Q(plan__label__icontains=q)
                | Q(completion_notes__icontains=q)
                | Q(asset__asset_tag__icontains=q)
                | Q(asset__name__icontains=q)
            )
        if date_from:
            registered = registered.filter(completed_on__gte=date_from)
        if date_to:
            registered = registered.filter(completed_on__lte=date_to)
        for occ in registered.order_by("-completed_on", "-id")[:500]:
            rows.append(
                {
                    "source": "occurrence",
                    "source_label": "Manutenzione",
                    "date": timezone.make_aware(datetime.combine(occ.completed_on, datetime.min.time()))
                    if occ.completed_on else None,
                    "title": occ.plan.label,
                    "asset": occ.asset,
                    "type_label": "Registrata senza OdL",
                    "status_label": "Eseguita",
                    "technician": (occ.completed_by.get_full_name() or occ.completed_by.username)
                    if occ.completed_by_id else "-",
                    "duration_minutes": 0,
                    "cost": None,
                    "url": reverse("assets:maintenance_plan_detail", kwargs={"plan_id": occ.plan_id}),
                }
            )

    if source in {"all", "deadlines"}:
        # Scadenze amministrative svolte (revisioni, controlli periodici, certificati):
        # registrandole la scadenza si rinnova o si chiude, quindi dall'elenco delle
        # scadenze l'esecuzione sparisce. Qui resta come lavoro fatto.
        from ..models import AssetAdministrativeDeadline, AssetAdministrativeDeadlineCompletion

        completions = AssetAdministrativeDeadlineCompletion.objects.filter(
            deadline__in=filtra_per_asset(
                request, AssetAdministrativeDeadline.objects.all(), MODULO_VERIFICHE
            ).values("id")
        ).select_related("deadline__asset", "completed_by")
        if q:
            completions = completions.filter(
                Q(deadline__title__icontains=q)
                | Q(deadline__reference_code__icontains=q)
                | Q(deadline__issuer__icontains=q)
                | Q(notes__icontains=q)
                | Q(deadline__asset__asset_tag__icontains=q)
                | Q(deadline__asset__name__icontains=q)
            )
        if date_from:
            completions = completions.filter(completed_on__gte=date_from)
        if date_to:
            completions = completions.filter(completed_on__lte=date_to)
        deadlines_url = reverse("assets:asset_administrative_deadline_list")
        for completion in completions.order_by("-completed_on", "-id")[:500]:
            deadline = completion.deadline
            rows.append(
                {
                    "source": "deadline",
                    "source_label": "Scadenza amministrativa",
                    "date": timezone.make_aware(datetime.combine(completion.completed_on, datetime.min.time())),
                    "title": deadline.title,
                    "asset": deadline.asset,
                    "type_label": deadline.get_deadline_type_display(),
                    "status_label": (
                        f"Svolta · prossima {completion.next_due_date:%d/%m/%Y}"
                        if completion.next_due_date else "Svolta"
                    ),
                    "technician": (completion.completed_by.get_full_name() or completion.completed_by.username)
                    if completion.completed_by_id else "-",
                    "duration_minutes": completion.duration_minutes,
                    "cost": completion.cost_eur,
                    "url": f"{deadlines_url}?status=all&q={quote(deadline.asset.asset_tag or deadline.title)}",
                }
            )

    if source in {"all", "tickets"}:
        tickets = Ticket.objects.filter(
            tipo=TipoTicket.MAN,
            include_in_maintenance_register=True,
            stato__in=[StatoTicket.RISOLTO, StatoTicket.CHIUSO, StatoTicket.ANNULLATO],
        ).select_related("asset")
        if q:
            tickets = tickets.filter(
                Q(titolo__icontains=q)
                | Q(descrizione__icontains=q)
                | Q(numero_ticket__icontains=q)
                | Q(asset__asset_tag__icontains=q)
                | Q(asset__name__icontains=q)
            )
        if date_from:
            tickets = tickets.filter(closed_at__date__gte=date_from)
        if date_to:
            tickets = tickets.filter(closed_at__date__lte=date_to)
        for ticket in tickets.order_by("-closed_at", "-id")[:500]:
            rows.append(
                {
                    "source": "ticket",
                    "source_label": "Ticket MAN",
                    "date": ticket.closed_at or ticket.created_at,
                    "title": ticket.titolo,
                    "asset": ticket.asset,
                    "type_label": ticket.label_categoria,
                    "status_label": ticket.label_stato,
                    "technician": ticket.risolto_da_nome or ticket.assegnato_a or "-",
                    "duration_minutes": 0,
                    "cost": None,
                    "url": reverse("tickets:detail", kwargs={"pk": ticket.id}),
                }
            )

    rows.sort(key=lambda row: row["date"] or timezone.now(), reverse=True)
    total_duration = sum(int(row["duration_minutes"] or 0) for row in rows)
    total_cost = sum((row["cost"] or Decimal("0")) for row in rows)

    # Un totale ha senso solo se il dato e' compilato. Durata e costi si compilano a
    # mano in chiusura e quasi nessuno lo fa: presentare "1,5 h" accanto a 661
    # attivita' concluse non e' una statistica, e' un numero che invita a conclusioni
    # sbagliate. Qui si misura su quante righe il dato esiste davvero (>0) e la
    # pagina lo dichiara; sotto una soglia minima il KPI non viene mostrato affatto,
    # perche' un dato coperto all'1% non dice nulla nemmeno con l'avvertenza.
    totale_righe = len(rows)
    righe_con_durata = sum(1 for row in rows if int(row["duration_minutes"] or 0) > 0)
    righe_con_costo = sum(1 for row in rows if (row["cost"] or Decimal("0")) > 0)
    copertura_durata = _copertura_dato(righe_con_durata, totale_righe)
    copertura_costo = _copertura_dato(righe_con_costo, totale_righe)

    return render(
        request,
        "assets/pages/maintenance_history.html",
        {
            **_assets_shell_context(request),
            "page_title": "Storico manutenzione aziendale",
            "history_rows": rows[:500],
            "history_total": len(rows),
            "history_workorder_count": sum(1 for row in rows if row["source"] == "workorder"),
            "history_ticket_count": sum(1 for row in rows if row["source"] == "ticket"),
            "history_occurrence_count": sum(1 for row in rows if row["source"] == "occurrence"),
            "history_deadline_count": sum(1 for row in rows if row["source"] == "deadline"),
            "history_duration_hours": round(total_duration / 60, 1),
            "history_total_cost": total_cost,
            "history_duration_coverage": copertura_durata["label"],
            "history_cost_coverage": copertura_costo["label"],
            "history_duration_rows": righe_con_durata,
            "history_cost_rows": righe_con_costo,
            "history_duration_reliable": copertura_durata["reliable"],
            "history_cost_reliable": copertura_costo["reliable"],
            "q": q,
            "source": source,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@login_required
def maintenance_hub(request: HttpRequest) -> HttpResponse:
    """Vecchio centro operativo, ritirato: contava le scadenze sul vecchio motore a
    regole e sulla tabella delle scadenze amministrative, e dava numeri diversi da
    Panoramica e Scadenzario. L'URL resta per i segnalibri e rimanda alla
    Panoramica; i vecchi deep-link ``?tab=scadenzario`` allo Scadenzario.
    """
    if _clean_string(request.GET.get("tab")) == "scadenzario":
        return redirect(_maintenance_schedule_page_url(reparto=_clean_string(request.GET.get("reparto"))))
    return redirect("assets:maintenance_responsabile")


@login_required
def maintenance_scadenzario(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_scadenze")


def _maintenance_supplier_rows() -> list[dict[str, object]]:
    """Fornitori usati in manutenzione (regole esterne, OdL, contratti, verifiche periodiche),
    con i relativi conteggi. La gestione dei fornitori resta nel modulo dedicato /fornitori/:
    qui è una vista focalizzata con link, non un duplicato."""

    from anagrafica.models import Fornitore

    from ..models import AssistanceContract

    def _counts(qs) -> dict[int, int]:
        # .order_by() azzera l'ordering di default del modello: senza, su SQL Server
        # le colonne dell'ORDER BY ereditato non stanno nel GROUP BY -> errore 8127.
        return {
            row["supplier"]: row["c"]
            for row in qs.filter(supplier__isnull=False)
            .values("supplier")
            .annotate(c=Count("id"))
            .order_by()
        }

    rule_counts = _counts(MaintenanceRule.objects.filter(is_active=True))
    wo_counts = _counts(WorkOrder.objects.all())
    contract_counts = _counts(AssistanceContract.objects.filter(is_active=True))
    verif_counts = _counts(PeriodicVerification.objects.filter(is_active=True))

    # Includi anche i fornitori catalogati come "Manutenzione" anche se non ancora
    # collegati a una regola/OdL: compaiono con conteggi a 0, pronti da assegnare.
    catalog_ids = set(
        Fornitore.objects.filter(
            categoria=Fornitore.CATEGORIA_MANUTENZIONE, is_active=True
        ).values_list("id", flat=True)
    )

    supplier_ids = set(rule_counts) | set(wo_counts) | set(contract_counts) | set(verif_counts) | catalog_ids
    if not supplier_ids:
        return []

    rows: list[dict[str, object]] = []
    for supplier in Fornitore.objects.filter(pk__in=supplier_ids).order_by("ragione_sociale", "id"):
        rows.append(
            {
                "f": supplier,
                "rules": rule_counts.get(supplier.id, 0),
                "workorders": wo_counts.get(supplier.id, 0),
                "contracts": contract_counts.get(supplier.id, 0),
                "verifications": verif_counts.get(supplier.id, 0),
                # La riga apre la scheda di manutenzione; l'anagrafica completa
                # resta nel modulo /fornitori/, raggiunta dal link dedicato.
                "detail_url": reverse("assets:maintenance_supplier_detail", kwargs={"fornitore_id": supplier.id}),
                "anagrafica_url": reverse("fornitori:fornitore_detail", kwargs={"fornitore_id": supplier.id}),
            }
        )
    return rows


@login_required
def maintenance_impostazioni(request: HttpRequest) -> HttpResponse:
    """Il vecchio "Catalogo attivita'" era la stessa lista dei Piani (stesso
    modello, ``MaintenanceInterventionTemplate``) vista da un'altra pagina. Ora la
    lista e' una sola, Piani; checklist e istruzioni si modificano dalla scheda
    del piano. L'URL resta per i segnalibri."""
    if _clean_string(request.GET.get("tab")) == "fornitori":
        return redirect("assets:maintenance_suppliers")
    return redirect("assets:maintenance_plan_list")


@login_required
def maintenance_coverage_matrix(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_coverage")


@login_required
def maintenance_suppliers(request: HttpRequest) -> HttpResponse:
    """Pagina dedicata: fornitori (ditte terze) usati in manutenzione, con conteggi e link
    al modulo /fornitori/ (fonte unica di gestione/anagrafica). Raggiungibile dalla nav di
    sezione manutenzione; nessun duplicato di anagrafica."""
    rows = _maintenance_supplier_rows()
    return render(
        request,
        "assets/pages/maintenance_suppliers.html",
        {
            **_assets_shell_context(request),
            "page_title": "Fornitori manutenzione",
            "is_admin": _is_assets_admin(request),
            "supplier_rows": rows,
            "supplier_total": len(rows),
            "url_fornitori_list": reverse("fornitori:fornitori_list"),
            "url_fornitore_new": reverse("fornitori:fornitore_create"),
        },
    )


@login_required
def maintenance_supplier_detail(request: HttpRequest, fornitore_id: int) -> HttpResponse:
    """Scheda di manutenzione di una ditta terza: cosa le e' affidato (contratti,
    piani esterni, verifiche periodiche), quali asset tocca, che interventi ha svolto
    e quanto di quel lavoro e' documentato.

    Non e' un secondo dettaglio fornitore: l'anagrafica (dati fiscali, contatti,
    documenti, valutazioni) resta nel modulo ``/fornitori/`` ed e' raggiunta da un
    link. Qui non si modifica nulla, si guarda il rapporto di lavoro.

    Costi e fermo macchina sono richiesti ma quasi mai compilati in chiusura: invece
    di stampare "0,00 EUR spesi nell'anno" - che sembrerebbe un dato e sarebbe falso -
    la pagina dichiara la copertura reale del campo (vedi ``_copertura_dato``).
    """
    from django.db.models import Q as _Q

    from anagrafica.models import Fornitore


    supplier = get_object_or_404(Fornitore, pk=fornitore_id)
    today = timezone.localdate()
    now = timezone.now()

    contracts = list(
        AssistanceContract.objects.filter(supplier=supplier)
        .select_related("asset", "asset_category", "document")
        .order_by("-is_active", "-start_date", "id")
    )
    rules = list(
        MaintenanceRule.objects.filter(supplier=supplier)
        .select_related("intervention_template", "asset_category")
        .prefetch_related("assets")
        .order_by("-is_active", "asset_category__label", "sort_order", "id")
    )
    verifications = list(
        PeriodicVerification.objects.filter(supplier=supplier)
        .prefetch_related("assets")
        .order_by("-is_active", "next_verification_date", "id")
    )
    workorders = list(
        WorkOrder.objects.filter(supplier=supplier)
        .select_related("asset", "assigned_to")
        .order_by("-opened_at", "-id")
    )

    open_wos = [wo for wo in workorders if wo.status == WorkOrder.STATUS_OPEN]
    closed_wos = [wo for wo in workorders if wo.status == WorkOrder.STATUS_DONE]
    ultimo_anno = today.replace(year=today.year - 1)
    closed_12m = [wo for wo in closed_wos if wo.closed_at and wo.closed_at.date() >= ultimo_anno]

    # Asset toccati dal fornitore: quelli citati direttamente (OdL, contratto su
    # singolo asset, verifiche, piani su asset scelti) piu' quelli che ricadono
    # nelle categorie coperte da un contratto o da un piano di categoria.
    asset_ids: set[int] = {wo.asset_id for wo in workorders if wo.asset_id}
    category_ids: set[int] = set()
    for contract in contracts:
        if not contract.is_active:
            continue
        if contract.asset_id:
            asset_ids.add(contract.asset_id)
        elif contract.asset_category_id:
            category_ids.add(contract.asset_category_id)
    for rule in rules:
        if not rule.is_active:
            continue
        if rule.scope_type == MaintenanceRule.SCOPE_ASSETS:
            asset_ids.update(asset.id for asset in rule.assets.all())
        elif rule.asset_category_id:
            category_ids.add(rule.asset_category_id)
    for verification in verifications:
        if verification.is_active:
            asset_ids.update(asset.id for asset in verification.assets.all())

    covered_assets: list[Asset] = []
    if asset_ids or category_ids:
        covered_assets = list(
            Asset.objects.filter(_Q(pk__in=asset_ids) | _Q(asset_category_id__in=category_ids))
            .select_related("asset_category")
            .order_by("name", "id")
        )

    # Copertura del dato sugli interventi chiusi: i campi hanno default 0, non NULL,
    # quindi si contano con "> 0" (exclude(campo=None) direbbe sempre 100%).
    chiusi = len(closed_wos)
    coperture = [
        {
            "label": "Durata intervento",
            "coverage": _copertura_dato(sum(1 for wo in closed_wos if (wo.intervention_duration_minutes or 0) > 0), chiusi),
        },
        {
            "label": "Fermo macchina",
            "coverage": _copertura_dato(sum(1 for wo in closed_wos if (wo.downtime_minutes or 0) > 0), chiusi),
        },
        {
            "label": "Costo consuntivato",
            "coverage": _copertura_dato(
                sum(1 for wo in closed_wos if (wo.resolved_total_cost_eur or Decimal("0")) > 0), chiusi
            ),
        },
    ]
    costo_totale = sum((wo.resolved_total_cost_eur or Decimal("0")) for wo in closed_12m)
    costo_coverage = _copertura_dato(
        sum(1 for wo in closed_12m if (wo.resolved_total_cost_eur or Decimal("0")) > 0), len(closed_12m)
    )

    contract_rows = [
        {
            "c": contract,
            "is_current": contract.is_current(today),
            "target": contract.target_label,
            "canone": contract.periodic_cost_eur if (contract.periodic_cost_eur or 0) > 0 else None,
        }
        for contract in contracts
    ]
    rule_rows = [
        {
            "r": rule,
            "periodicita": f"ogni {rule.threshold_value} {rule.get_threshold_type_display().lower()}",
            "ambito": rule.asset_category.label
            if rule.scope_type == MaintenanceRule.SCOPE_CATEGORY and rule.asset_category_id
            else f"{len(rule.assets.all())} asset scelti",
        }
        for rule in rules
    ]
    verification_rows = [
        {
            "v": verification,
            "assets": len(verification.assets.all()),
            "scaduta": bool(
                verification.is_active
                and verification.next_verification_date
                and verification.next_verification_date < today
            ),
        }
        for verification in verifications
    ]

    return render(
        request,
        "assets/pages/maintenance_supplier_detail.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Manutenzione - {supplier.ragione_sociale}",
            "is_admin": _is_assets_admin(request),
            "supplier": supplier,
            "contract_rows": contract_rows,
            "rule_rows": rule_rows,
            "verification_rows": verification_rows,
            "contracts_active": sum(1 for contract in contracts if contract.is_active),
            "rules_active": sum(1 for rule in rules if rule.is_active),
            "verifications_active": sum(1 for verification in verifications if verification.is_active),
            "open_workorders": open_wos,
            "open_total": len(open_wos),
            "open_overdue": sum(1 for wo in open_wos if wo.is_overdue),
            "open_unassigned": sum(1 for wo in open_wos if not wo.assigned_to_id),
            "closed_recent": closed_wos[:10],
            "closed_total": chiusi,
            "closed_12m": len(closed_12m),
            "covered_assets": covered_assets[:50],
            "covered_total": len(covered_assets),
            "coperture": coperture,
            "costo_12m": costo_totale,
            "costo_12m_coverage": costo_coverage,
            "now": now,
            "url_suppliers": reverse("assets:maintenance_suppliers"),
            "url_anagrafica": reverse("fornitori:fornitore_detail", kwargs={"fornitore_id": supplier.id}),
            "url_contracts": reverse("assets:assistance_contract_list"),
        },
    )


@login_required
def maintenance_worksheet(request: HttpRequest, asset_id: int, rule_id: int) -> HttpResponse:
    """Scheda intervento stampabile (A4) da portare alla macchina: dati macchina, intervento,
    checklist da spuntare a penna, ultime esecuzioni e campi per la registrazione manuale."""
    from ..models import MaintenanceChecklistStep

    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    base_rule = get_object_or_404(
        MaintenanceRule.objects.select_related("intervention_template", "supplier", "asset_category"),
        pk=rule_id,
    )
    template = base_rule.intervention_template
    checklist_steps = list(
        MaintenanceChecklistStep.objects.filter(intervention_template=template).order_by("step_number", "id")
    )
    last_executions = list(
        WorkOrder.objects.filter(
            asset=asset, maintenance_rule=base_rule, status=WorkOrder.STATUS_DONE
        ).order_by("-closed_at", "-id")[:5]
    )
    state = AssetMaintenanceRuleState.objects.filter(asset=asset, base_rule=base_rule).first()
    return render(
        request,
        "assets/pages/maintenance_worksheet.html",
        {
            "page_title": f"Scheda intervento — {asset.asset_tag}",
            "asset": asset,
            "base_rule": base_rule,
            "template": template,
            "checklist_steps": checklist_steps,
            "last_executions": last_executions,
            "last_execution_date": state.last_execution_date if state else None,
            "today": timezone.localdate(),
        },
    )


@login_required
def maintenance_todo(request: HttpRequest) -> HttpResponse:
    """Ritirata: la superficie del vecchio motore rimanda a quella nuova."""
    return redirect("assets:maintenance_da_fare")
