"""Interventi (OdL): elenco, campagne, creazione, scheda, checklist, chiusura.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, When
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.utils.dateparse import parse_date
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.audit import log_action
from ..registro_permessi import MODULO_ODL
from ..services.visibilita import filtra as filtra_visibili
from ..services.visibilita import filtra_odl

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from ..forms import (
    WorkOrderCloseForm,
    WorkOrderForm,
)
from ..models import (
    Asset,
    AssetCategory,
    AssistanceContract,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    PeriodicVerification,
    WorkOrder,
    WorkOrderChecklist,
    WorkOrderLog,
)
from ..maintenance import (
    build_workorder_prefill_payload,
    copy_template_checklist_to_workorder,
    distribute_campaign_due_dates,
    get_applicable_assistance_contracts,
    normalize_workorder_source,
)
from ..notifications import notify_workorder_assigned, notify_workorder_reassigned, notify_workorder_taken_over

from ._helpers import (  # noqa: F401
    ASSET_DOCUMENT_MAX_BYTES,
    _as_int,
    _asset_maintenance_rule_list_page_url,
    _assistance_contracts_page_url,
    _clean_string,
    _is_assets_admin,
)
from ._helpers_c import (  # noqa: F401
    _apply_workorder_list_filters,
    _apply_workorder_operational_view,
    _assets_shell_context,
    _resolve_workorder_operational_view,
    _save_workorder_attachments,
    _validate_workorder_attachment_uploads,
    _workorder_attachment_accept_attr,
    _workorder_list_page_url,
)

def _workorder_status_payload(status: str) -> dict[str, str]:
    if status == WorkOrder.STATUS_DONE:
        return {"label": "Chiuso", "badge_class": "ok"}
    if status == WorkOrder.STATUS_CANCELED:
        return {"label": "Annullato", "badge_class": "muted"}
    return {"label": "Aperto", "badge_class": "info"}


def _workorder_kind_payload(kind: str) -> dict[str, str]:
    mapping = {
        WorkOrder.KIND_PREVENTIVE: "ok",
        WorkOrder.KIND_CORRECTIVE: "warn",
        WorkOrder.KIND_SAFETY: "danger",
        WorkOrder.KIND_CALIBRATION: "info",
        WorkOrder.KIND_OTHER: "muted",
    }
    return {
        "label": dict(WorkOrder.KIND_CHOICES).get(kind, kind),
        "badge_class": mapping.get(kind, "muted"),
    }


def _coverage_status_payload(*, is_covered: bool, contract: AssistanceContract | None = None) -> dict[str, str]:
    if is_covered or contract is not None:
        label = "Coperto da contratto"
        if contract is not None:
            label = "Contratto collegato"
        return {"label": label, "badge_class": "info"}
    return {"label": "Copertura non disponibile", "badge_class": "muted"}


def _rule_sibling_assets(rule: MaintenanceRule, exclude_asset_id: int) -> list[Asset]:
    """Altri asset coperti dalla stessa regola di manutenzione (esclude l'asset corrente)."""
    if rule.scope_type == MaintenanceRule.SCOPE_ASSETS:
        qs = rule.assets.all()
    else:
        qs = Asset.objects.filter(asset_category_id=rule.asset_category_id, status=Asset.STATUS_IN_USE)
    return list(qs.exclude(pk=exclude_asset_id).order_by("asset_tag"))


def _verification_sibling_assets(verification: PeriodicVerification, exclude_asset_id: int) -> list[Asset]:
    """Altri asset coperti dallo stesso piano di verifica periodica (esclude l'asset corrente)."""
    return list(verification.assets.exclude(pk=exclude_asset_id).order_by("asset_tag"))


def _clone_workorder_for_sibling_asset(source: WorkOrder, sibling_asset: Asset) -> WorkOrder:
    """Duplica i dati pianificatori di un OdL appena creato su un altro asset con la
    stessa manutenzione (suggerimento "altri asset dello stesso tipo" in creazione
    singola). Non copia allegati/checklist gia' spuntate: solo l'impostazione."""
    sibling = WorkOrder(
        asset=sibling_asset,
        periodic_verification=source.periodic_verification,
        maintenance_rule=source.maintenance_rule,
        supplier=source.supplier,
        assistance_contract=source.assistance_contract,
        covered_by_contract=source.covered_by_contract,
        kind=source.kind,
        priority=source.priority,
        due_at=source.due_at,
        status=WorkOrder.STATUS_OPEN,
        origin=source.origin,
        title=source.title,
        description=source.description,
        opened_at=source.opened_at,
    )
    sibling.full_clean()
    sibling.save()
    return sibling


def _create_sibling_workorders_from_request(*, request: HttpRequest, source: WorkOrder) -> list[WorkOrder]:
    """Crea gli OdL "collegati" scelti nel suggerimento "altri asset con la stessa
    manutenzione" del form di creazione singola. Ricalcola lato server l'elenco
    consentito (stessa regola/piano di ``source``) per non fidarsi degli id postati
    dal client, poi lega tutto con display_number tramite WorkOrder.mark_batch."""
    raw_ids = request.POST.getlist("extra_asset_ids")
    if not raw_ids:
        return []
    requested_ids = {_as_int(raw_id, default=0) for raw_id in raw_ids} - {0}
    if not requested_ids:
        return []
    if source.maintenance_rule_id:
        allowed_assets = _rule_sibling_assets(source.maintenance_rule, source.asset_id)
    elif source.periodic_verification_id:
        allowed_assets = _verification_sibling_assets(source.periodic_verification, source.asset_id)
    else:
        allowed_assets = []
    allowed_by_id = {sibling_asset.id: sibling_asset for sibling_asset in allowed_assets}
    created: list[WorkOrder] = []
    for sibling_asset in (allowed_by_id[asset_id] for asset_id in requested_ids if asset_id in allowed_by_id):
        sibling = _clone_workorder_for_sibling_asset(source, sibling_asset)
        _prepopulate_workorder_checklist_from_template(sibling)
        WorkOrderLog.objects.create(
            work_order=sibling,
            note=f"Intervento creato insieme a #{source.asset.asset_tag} (stessa manutenzione).",
            author=request.user if request.user.is_authenticated else None,
        )
        created.append(sibling)
    if created:
        WorkOrder.mark_batch([source, *created])
    return created


def _prepopulate_workorder_checklist_from_template(workorder: WorkOrder) -> int:
    """Copia gli step del template intervento nel WorkOrder alla creazione.
    Delega all'helper condiviso in maintenance.py (stesso comportamento usato dalla
    generazione periodica automatica). Ritorna il numero di step creati."""
    return copy_template_checklist_to_workorder(workorder)


def _add_form_validation_errors(form, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field_name, field_errors in exc.message_dict.items():
            target_field = field_name if field_name in form.fields else None
            for error in field_errors:
                form.add_error(target_field, error)
        return
    for error in list(getattr(exc, "messages", []) or [str(exc)]):
        form.add_error(None, error)


def _workorder_priority_order_case() -> Case:
    return Case(
        When(priority=WorkOrder.PRIORITY_URGENT, then=0),
        When(priority=WorkOrder.PRIORITY_NORMAL, then=1),
        When(priority=WorkOrder.PRIORITY_LOW, then=2),
        default=1,
        output_field=IntegerField(),
    )


def _workorder_list_filter_remove_url(get_params, filter_key: str) -> str:
    query = get_params.copy()
    for key in (filter_key, "page", "create", "export"):
        if key in query:
            query.pop(key)
    query_string = query.urlencode()
    base_url = reverse("assets:wo_list")
    return f"{base_url}?{query_string}" if query_string else base_url


def _workorder_list_filter_chips(
    request: HttpRequest,
    *,
    status: str,
    kind: str,
    origin: str,
    coverage: str,
    reparto: str,
    category_id: int,
    assigned_id: int,
    open_age_days: int,
    priority: str = "",
    q: str,
    operational_view: str,
    category_options,
    user_options,
    asset_filter=None,
) -> list[dict[str, str]]:
    status_labels = dict(WorkOrder.STATUS_CHOICES)
    kind_labels = dict(WorkOrder.KIND_CHOICES)
    origin_labels = dict(WorkOrder.ORIGIN_CHOICES)
    priority_labels = dict(WorkOrder.PRIORITY_CHOICES)
    coverage_labels = {
        "covered": "Con contratto",
        "uncovered": "Senza contratto",
    }
    category_by_id = {category.id: category for category in category_options}
    user_by_id = {user.id: user for user in user_options}
    chips: list[dict[str, str]] = []

    def add(filter_key: str, label: str, value: str) -> None:
        value = _clean_string(value)
        if not value:
            return
        remove_url = _workorder_list_filter_remove_url(request.GET, filter_key)
        if "view" not in request.GET:
            parsed_remove_url = urlsplit(remove_url)
            remove_query = parse_qs(parsed_remove_url.query)
            remove_query["view"] = [operational_view]
            remove_url = urlunsplit(
                (
                    parsed_remove_url.scheme,
                    parsed_remove_url.netloc,
                    parsed_remove_url.path,
                    urlencode(remove_query, doseq=True),
                    parsed_remove_url.fragment,
                )
            )
        chips.append(
            {
                "label": label,
                "value": value,
                "remove_url": remove_url,
            }
        )

    if q:
        add("q", "Ricerca", q)
    if status:
        add("status", "Stato", status_labels.get(status, status))
    if kind:
        add("kind", "Tipo", kind_labels.get(kind, kind))
    if priority:
        add("priority", "Priorità", priority_labels.get(priority, priority))
    if origin:
        add("origin", "Origine", origin_labels.get(origin, origin))
    if coverage in coverage_labels:
        add("coverage", "Copertura", coverage_labels[coverage])
    if reparto:
        add("reparto", "Reparto", reparto)
    if category_id:
        category = category_by_id.get(category_id)
        add("category", "Categoria", category.label if category else f"ID {category_id}")
    if assigned_id:
        user = user_by_id.get(assigned_id)
        user_label = (user.get_full_name() or user.username) if user else f"ID {assigned_id}"
        add("assigned", "Responsabile", user_label)
    if open_age_days:
        add("open_age", "Aperti da", f"{open_age_days} giorni")
    if asset_filter is not None:
        add("asset", "Asset", asset_filter.asset_tag or asset_filter.name)
    return chips


@login_required
def workorder_list(request: HttpRequest) -> HttpResponse:
    status = _clean_string(request.GET.get("status"))
    kind = _clean_string(request.GET.get("kind"))
    origin = _clean_string(request.GET.get("origin"))
    coverage = _clean_string(request.GET.get("coverage")) or "all"
    reparto = _clean_string(request.GET.get("reparto"))
    category_id = _as_int(request.GET.get("category"), default=0)
    assigned_id = _as_int(request.GET.get("assigned"), default=0)
    open_age_days = _as_int(request.GET.get("open_age"), default=0)
    asset_id = _as_int(request.GET.get("asset"), default=0)
    priority = _clean_string(request.GET.get("priority"))
    q = _clean_string(request.GET.get("q"))
    operational_view = _resolve_workorder_operational_view(request.GET)
    display = _clean_string(request.GET.get("display")).lower()
    display = display if display in ("list", "board") else "list"
    asset_filter = Asset.objects.filter(pk=asset_id).first() if asset_id else None

    workorders = _apply_workorder_operational_view(
        _apply_workorder_list_filters(request.GET),
        operational_view=operational_view,
        user=request.user,
    )
    # Ambito della matrice ruoli (modulo Ordini di lavoro): con «Propri / del team»
    # restano gli OdL degli asset visibili e quelli assegnati alla persona.
    workorders = filtra_odl(request, workorders)
    if operational_view in ("open", "mine", "unassigned"):
        # Coda di lavoro: urgente prima, poi il più vecchio aperto — non l'ultimo creato.
        workorders = workorders.order_by(_workorder_priority_order_case(), "opened_at", "id")
    else:
        workorders = workorders.order_by("-opened_at", "-id")
    count_source = filtra_odl(request, WorkOrder.objects.all())
    operational_counts = {
        "open": count_source.filter(status=WorkOrder.STATUS_OPEN).count(),
        "mine": count_source.filter(status=WorkOrder.STATUS_OPEN, assigned_to=request.user).count(),
        "unassigned": count_source.filter(status=WorkOrder.STATUS_OPEN, assigned_to__isnull=True).count(),
        "closed": count_source.filter(status__in=[WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED]).count(),
    }
    reparto_options = list(
        Asset.objects.exclude(reparto="")
        .order_by("reparto")
        .values_list("reparto", flat=True)
        .distinct()
    )
    category_options = list(AssetCategory.objects.order_by("sort_order", "label", "id"))
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_options = list(User.objects.filter(is_active=True).order_by("first_name", "last_name", "username"))
    active_filter_chips = _workorder_list_filter_chips(
        request,
        status=status,
        kind=kind,
        origin=origin,
        coverage=coverage,
        reparto=reparto,
        category_id=category_id,
        assigned_id=assigned_id,
        open_age_days=open_age_days,
        priority=priority,
        q=q,
        operational_view=operational_view,
        category_options=category_options,
        user_options=user_options,
        asset_filter=asset_filter,
    )

    # "Raggruppa per": l'ordine resta quello della coda, i gruppi si leggono come
    # intestazioni dentro la stessa tabella (le azioni di riga non cambiano).
    group_by = _clean_string(request.GET.get("by"))
    workorder_group_modes = [
        ("", "Nessuno"), ("asset", "Asset"), ("assegnatario", "Assegnatario"), ("stato", "Stato"),
        ("gruppo", "Gruppo OdL"), ("giorno", "Giorno"),
    ]
    if group_by not in {key for key, _ in workorder_group_modes}:
        group_by = ""
    if group_by and display != "board":
        grouped = list(workorders.select_related("asset", "assigned_to")[:500])
        for wo in grouped:
            if group_by == "asset":
                wo.group_label = f"{wo.asset.asset_tag} — {wo.asset.name}" if wo.asset_id else "Senza asset"
            elif group_by == "assegnatario":
                wo.group_label = (
                    wo.assigned_to.get_full_name() or wo.assigned_to.get_username()
                ) if wo.assigned_to_id else "Di nessuno"
            elif group_by == "stato":
                wo.group_label = wo.operational_state_label if wo.status == WorkOrder.STATUS_OPEN else wo.get_status_display()
            elif group_by == "gruppo":
                batch = wo.reference_batch or ""
                wo.group_label = (
                    f"Gruppo {batch[len(WorkOrder.BATCH_REFERENCE_PREFIX):]}"
                    if batch.startswith(WorkOrder.BATCH_REFERENCE_PREFIX) else "OdL singoli"
                )
            else:
                day = timezone.localtime(wo.due_at).date() if wo.due_at else None
                wo.group_label = f"Entro {day:%d/%m/%Y}" if day else "Senza scadenza"
                wo.group_sort = day.isoformat() if day else "9999"
        grouped.sort(key=lambda wo: getattr(wo, "group_sort", wo.group_label))
        workorders = grouped
    group_query = request.GET.copy()
    workorder_group_links = []
    for key, label in workorder_group_modes:
        group_query["by"] = key
        workorder_group_links.append({"label": label, "url": f"?{group_query.urlencode()}", "active": key == group_by})

    board_columns = []
    if display == "board":
        # Kanban degli stati operativi (unassigned/assigned/in_progress/waiting), diversa dalla
        # vecchia board per scadenza del centro operativo ritirato: qui la colonna e' lo stato
        # reale dell'OdL, non quanto e' vecchio.
        board_by_state = {key: [] for key in WorkOrder.OPSTATE_LABELS}
        for wo in workorders.filter(status=WorkOrder.STATUS_OPEN).select_related("asset", "assigned_to"):
            state = wo.operational_state
            if state in board_by_state:
                board_by_state[state].append(wo)
        board_columns = [
            {"key": key, "label": label, "workorders": board_by_state[key]}
            for key, label in WorkOrder.OPSTATE_LABELS.items()
        ]

    from ..views_maintenance import can_execute_maintenance, can_plan_maintenance, _workorder_bulk_form

    can_bulk_workorders = operational_view != "closed" and can_execute_maintenance(request)
    return render(
        request,
        "assets/pages/workorder_list.html",
        {
            "page_title": "Interventi",
            "workorders": workorders,
            # Selezione multipla (casella o Ctrl+clic): chiudi / assegna piu' OdL insieme.
            "can_bulk_workorders": can_bulk_workorders,
            "can_plan": can_plan_maintenance(request) if can_bulk_workorders else False,
            "workorder_bulk_form": _workorder_bulk_form() if can_bulk_workorders else None,
            "workorder_group_by": group_by,
            "workorder_group_links": workorder_group_links,
            "workorder_display": display,
            "board_columns": board_columns,
            "workorder_display_toggle_url": _workorder_list_page_url(
                view=operational_view, display="list" if display == "board" else "board"
            ),
            "status_filter": status,
            "kind_filter": kind,
            "origin_filter": origin,
            "coverage_filter": coverage,
            "reparto_filter": reparto,
            "priority_filter": priority,
            "priority_choices": WorkOrder.PRIORITY_CHOICES,
            "selected_category_id": category_id,
            "assigned_filter": assigned_id,
            "open_age_filter": open_age_days,
            "asset_filter": asset_filter,
            "q_filter": q,
            "workorder_view": operational_view,
            "workorder_view_url": _workorder_list_page_url(view=operational_view),
            "operational_counts": operational_counts,
            "workorder_view_urls": {
                view_key: _workorder_list_page_url(view=view_key)
                for view_key in ("open", "mine", "unassigned", "closed", "all")
            },
            "advanced_filters_open": bool(
                kind
                or origin
                or coverage != "all"
                or reparto
                or category_id
                or assigned_id
                or open_age_days
                or priority
                or status
            ),
            "status_choices": WorkOrder.STATUS_CHOICES,
            "kind_choices": WorkOrder.KIND_CHOICES,
            "origin_choices": WorkOrder.ORIGIN_CHOICES,
            "reparto_options": reparto_options,
            "category_options": category_options,
            "user_options": user_options,
            "active_filter_chips": active_filter_chips,
            "workorder_create_asset_options": filtra_visibili(
                request, Asset.objects.all(), MODULO_ODL
            ).exclude(status=Asset.STATUS_RETIRED).order_by(
                "asset_tag",
                "name",
                "id",
            ),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def workorder_campaign_create(request: HttpRequest) -> HttpResponse:
    """Crea più OdL in un colpo solo per un gruppo di asset simili (es. verifica annuale su
    12 presse), stesso template, scadenze distribuite su una finestra invece che tutte sulla
    stessa data. `reference_batch` raggruppa il lotto (stesso campo già usato da
    `generate_workorders_for_rule`); `origin` resta `ORIGIN_MANUAL` — una campagna è una
    creazione manuale multipla, non un nuovo tipo di origine da tracciare a parte."""
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin può creare campagne di manutenzione.")
        return redirect("assets:wo_list")

    from django.contrib.auth import get_user_model

    User = get_user_model()

    templates = list(
        MaintenanceInterventionTemplate.objects.filter(is_active=True)
        .select_related("asset_category")
        .order_by("sort_order", "label")
    )
    assets_qs = (
        Asset.objects.filter(status=Asset.STATUS_IN_USE)
        .select_related("asset_category")
        .order_by("asset_category__sort_order", "reparto", "name", "id")
    )
    campaign_asset_groups: dict[str, list[Asset]] = {}
    for asset in assets_qs:
        group_label = asset.asset_category.label if asset.asset_category_id else "Senza categoria"
        campaign_asset_groups.setdefault(group_label, []).append(asset)

    user_options = list(User.objects.filter(is_active=True).order_by("first_name", "last_name", "username"))

    if request.method == "POST":
        template_id = _as_int(request.POST.get("intervention_template"), default=0)
        asset_ids = [_as_int(v) for v in request.POST.getlist("assets") if _as_int(v)]
        selected_assets = list(assets_qs.filter(id__in=asset_ids)) if asset_ids else []
        template = MaintenanceInterventionTemplate.objects.filter(pk=template_id).first() if template_id else None
        window_days = _as_int(request.POST.get("window_days"), default=10) or 10
        window_days = max(1, min(window_days, 60))
        priority = _clean_string(request.POST.get("priority")) or WorkOrder.PRIORITY_NORMAL
        if priority not in dict(WorkOrder.PRIORITY_CHOICES):
            priority = WorkOrder.PRIORITY_NORMAL
        assigned_id = _as_int(request.POST.get("assigned_to"), default=0)
        assigned_user = User.objects.filter(pk=assigned_id, is_active=True).first() if assigned_id else None
        start_date_raw = _clean_string(request.POST.get("start_date"))
        start_date = (parse_date(start_date_raw) if start_date_raw else None) or timezone.localdate()

        if not template:
            messages.error(request, "Seleziona un tipo di attività.")
        elif not selected_assets:
            messages.error(request, "Seleziona almeno un asset.")
        else:
            due_dates = distribute_campaign_due_dates(
                count=len(selected_assets),
                window_days=window_days,
                start_date=start_date,
                assigned_to=assigned_user,
            )
            reference_batch = f"CAMPAIGN_{template.id}_{timezone.now():%Y%m%d_%H%M%S}"
            created: list[WorkOrder] = []
            with transaction.atomic():
                for asset, due_date in zip(selected_assets, due_dates):
                    workorder = WorkOrder(
                        asset=asset,
                        kind=template.workorder_kind,
                        status=WorkOrder.STATUS_OPEN,
                        origin=WorkOrder.ORIGIN_MANUAL,
                        title=f"{template.label} — {asset.asset_tag or asset.name}",
                        description=template.description or "",
                        priority=priority,
                        due_at=timezone.make_aware(datetime.combine(due_date, time(9, 0))),
                        assigned_to=assigned_user,
                        reference_batch=reference_batch,
                        opened_at=timezone.now(),
                    )
                    workorder.full_clean()
                    workorder.save()
                    copy_template_checklist_to_workorder(workorder, template_id=template.id)
                    WorkOrderLog.objects.create(
                        work_order=workorder,
                        note=f"Creato in campagna (lotto {reference_batch}).",
                        author=request.user,
                    )
                    created.append(workorder)
            log_action(
                request,
                "create_workorder_campaign",
                "assets",
                {
                    "reference_batch": reference_batch,
                    "template_id": template.id,
                    "count": len(created),
                    "window_days": window_days,
                },
            )
            messages.success(request, f"Creati {len(created)} interventi (lotto {reference_batch}).")
            return redirect(_workorder_list_page_url(view="open"))

    return render(
        request,
        "assets/pages/workorder_campaign_create.html",
        {
            "page_title": "Nuova campagna di manutenzione",
            "templates": templates,
            "campaign_asset_groups": [
                {"label": label, "assets": assets} for label, assets in campaign_asset_groups.items()
            ],
            "priority_choices": WorkOrder.PRIORITY_CHOICES,
            "user_options": user_options,
            "back_url": reverse("assets:wo_list"),
            **_assets_shell_context(request),
        },
    )


@login_required
def il_mio_turno(request: HttpRequest) -> HttpResponse:
    """«Il mio turno» non e' piu' una pagina: e' la scheda «Il mio lavoro» di «Da fare».

    Una home in meno: «Da fare» con ?mio=1 mostra gia' le manutenzioni e gli
    interventi propri e di nessuno. L'URL resta per link e preferiti salvati
    (redirect temporaneo, query string conservata).
    """
    query = request.GET.copy()
    query["mio"] = "1"
    return redirect(f"{reverse('assets:maintenance_da_fare')}?{query.urlencode()}")


@login_required
def workorder_create(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        selected_asset_id = _as_int(request.GET.get("asset") or request.POST.get("asset"), default=0)
        if selected_asset_id:
            query = request.GET.copy()
            query.pop("asset", None)
            query.setdefault("source", "workorder_list")
            target_url = reverse("assets:wo_create", kwargs={"id": selected_asset_id})
            query_string = query.urlencode()
            return redirect(f"{target_url}?{query_string}" if query_string else target_url)
        # Un OdL richiede sempre un asset: un ingresso globale deve aprire il
        # selettore canonico, non arrestarsi sulla lista interventi.
        return redirect(_workorder_list_page_url(create=1))
    asset = get_object_or_404(Asset, pk=id)
    source = normalize_workorder_source(request.GET.get("source"))
    back_to_list = source == "workorder_list"
    workorder_back_url = reverse("assets:wo_list") if back_to_list else reverse("assets:asset_view", kwargs={"id": id})
    workorder_back_label = "Torna agli interventi" if back_to_list else "Torna al dettaglio asset"
    prefill_payload = build_workorder_prefill_payload(
        asset=asset,
        base_rule_id=_as_int(request.GET.get("rule"), default=0),
        source=source,
    )
    selected_periodic_verification = None
    periodic_verification_id = _as_int(request.GET.get("periodic"), default=0)
    if periodic_verification_id:
        selected_periodic_verification = get_object_or_404(
            PeriodicVerification.objects.select_related("supplier").filter(
                is_active=True,
                assets=asset,
            ),
            pk=periodic_verification_id,
        )
        prefill_payload["periodic_verification"] = selected_periodic_verification
        prefill_payload["title"] = (selected_periodic_verification.name or "Manutenzione periodica").strip()
        prefill_payload["description"] = (selected_periodic_verification.notes or "").strip()
        prefill_payload["kind"] = WorkOrder.KIND_PREVENTIVE
        prefill_payload["supplier"] = selected_periodic_verification.supplier
        suggested_contract = prefill_payload.get("contract")
        if (
            suggested_contract is not None
            and selected_periodic_verification.supplier_id
            and suggested_contract.supplier_id != selected_periodic_verification.supplier_id
        ):
            prefill_payload["contract"] = None
            prefill_payload["covered_by_contract"] = False
    selected_rule_id = getattr(prefill_payload.get("maintenance_rule"), "id", 0)
    form_kwargs = {
        "asset": asset,
        "prefill_payload": prefill_payload,
    }
    if request.method == "POST":
        form = WorkOrderForm(request.POST, **form_kwargs)
        uploads, upload_errors = _validate_workorder_attachment_uploads(request)
        form_is_valid = form.is_valid()
        for error in upload_errors:
            form.add_error(None, error)
        if form_is_valid and not upload_errors:
            workorder = form.save(commit=False)
            workorder.asset = asset
            workorder.status = WorkOrder.STATUS_OPEN
            workorder.origin = (
                WorkOrder.ORIGIN_PERIODIC
                if workorder.periodic_verification_id or workorder.maintenance_rule_id
                else WorkOrder.ORIGIN_MANUAL
            )
            if not workorder.opened_at:
                workorder.opened_at = timezone.now()
            try:
                workorder.full_clean()
            except ValidationError as exc:
                _add_form_validation_errors(form, exc)
            else:
                with transaction.atomic():
                    workorder.save()
                    _prepopulate_workorder_checklist_from_template(workorder)
                    created_attachments = _save_workorder_attachments(
                        workorder=workorder,
                        uploads=uploads,
                        user=request.user,
                    )
                    log_note = "Intervento creato."
                    if created_attachments:
                        log_note = f"{log_note} Allegati caricati: {len(created_attachments)}."
                    WorkOrderLog.objects.create(
                        work_order=workorder,
                        note=log_note,
                        author=request.user if request.user.is_authenticated else None,
                    )
                    sibling_workorders = _create_sibling_workorders_from_request(
                        request=request,
                        source=workorder,
                    )
                notify_workorder_assigned(
                    workorder,
                    actor=request.user if request.user.is_authenticated else None,
                )
                for sibling in sibling_workorders:
                    notify_workorder_assigned(
                        sibling,
                        actor=request.user if request.user.is_authenticated else None,
                    )
                if sibling_workorders:
                    messages.success(
                        request,
                        f"Intervento creato insieme a {len(sibling_workorders)} interventi collegati "
                        f"({workorder.display_number} - {', '.join(sibling.display_number for sibling in sibling_workorders)}).",
                    )
                else:
                    messages.success(request, "Intervento creato.")
                if request.POST.get("submit_action") == "close":
                    return redirect("assets:wo_close", id=workorder.id)
                return redirect("assets:wo_view", id=workorder.id)
    else:
        initial = {"status": WorkOrder.STATUS_OPEN}
        kind_param = request.GET.get("kind", "").strip().upper()
        if kind_param in {c[0] for c in WorkOrder.KIND_CHOICES}:
            initial["kind"] = kind_param
        form = WorkOrderForm(initial=initial, **form_kwargs)
    periodic_verification_supplier_map = {
        str(verification.id): {
            "supplier_id": str(verification.supplier_id or ""),
            "supplier_label": str(verification.supplier) if verification.supplier_id else "",
        }
        for verification in form.fields["periodic_verification"].queryset
    }
    maintenance_rule_suggestion_map = form.build_rule_suggestion_map()
    contract_suggestion_map = form.build_contract_suggestion_map()
    sibling_asset_map: dict[str, list[dict[str, object]]] = {}
    for rule in form.fields["maintenance_rule"].queryset:
        siblings = _rule_sibling_assets(rule, asset.id)
        if siblings:
            sibling_asset_map[f"rule-{rule.id}"] = [
                {"id": sibling.id, "label": f"{sibling.asset_tag} - {sibling.name}"} for sibling in siblings
            ]
    for verification in form.fields["periodic_verification"].queryset:
        siblings = _verification_sibling_assets(verification, asset.id)
        if siblings:
            sibling_asset_map[f"verification-{verification.id}"] = [
                {"id": sibling.id, "label": f"{sibling.asset_tag} - {sibling.name}"} for sibling in siblings
            ]
    initial_rule = None
    rule_value = form["maintenance_rule"].value()
    if rule_value:
        initial_rule = form.fields["maintenance_rule"].queryset.filter(pk=_as_int(rule_value, default=0)).first()
    initial_contract = None
    contract_value = form["assistance_contract"].value()
    if contract_value:
        initial_contract = form.fields["assistance_contract"].queryset.filter(pk=_as_int(contract_value, default=0)).first()
    return render(
        request,
        "assets/pages/workorder_form.html",
        {
            "page_title": f"Nuovo intervento - {asset.asset_tag}",
            "asset": asset,
            "form": form,
            "workorder_back_url": workorder_back_url,
            "workorder_back_label": workorder_back_label,
            "selected_rule_id": selected_rule_id,
            "initial_rule": initial_rule,
            "initial_contract": initial_contract,
            "workorder_prefill": prefill_payload,
            "available_contract_count": form.fields["assistance_contract"].queryset.count(),
            "attachment_accept": _workorder_attachment_accept_attr(),
            "attachment_max_mb": int(ASSET_DOCUMENT_MAX_BYTES / (1024 * 1024)),
            "periodic_verification_supplier_map_json": json.dumps(periodic_verification_supplier_map),
            "maintenance_rule_suggestion_map_json": json.dumps(maintenance_rule_suggestion_map),
            "contract_suggestion_map_json": json.dumps(contract_suggestion_map),
            "sibling_asset_map_json": json.dumps(sibling_asset_map),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
            # Il form e' un flusso transazionale: evita tab e azioni globali
            # duplicate mentre l'utente sta compilando l'intervento.
            "assets_section_nav": None,
        },
    )


def _workorder_occurrences_context(request: HttpRequest, workorder: WorkOrder) -> dict[str, object]:
    """Contesto del pannello "manutenzioni raccolte" del nuovo dominio.

    Vive qui e non in ``views_maintenance`` perche' e' il dettaglio OdL storico a
    doverlo mostrare; la dipendenza fra i due moduli resta a senso unico.
    """
    from ..forms_maintenance import ExecutionDayForm, OccurrenceBulkCompletionForm
    from ..models import MaintenanceOccurrence
    from ..services import maintenance_domain as maintenance_dom
    from ..views_maintenance import can_execute_maintenance, can_plan_maintenance

    occurrences = list(
        MaintenanceOccurrence.objects.filter(work_order=workorder)
        .select_related("plan", "asset", "assignment", "execution_day")
        .prefetch_related("attachments")
        .order_by("execution_day__execution_date", "due_date", "asset__asset_tag")
    )
    if not occurrences:
        return {"wo_occurrence_rows": [], "wo_occurrence_progress": None}

    today = timezone.localdate()
    rows = []
    for occurrence in occurrences:
        payload = maintenance_dom.occurrence_state_payload(occurrence, today=today)
        rows.append({"occurrence": occurrence, **payload})

    by_day: dict[object, list[dict[str, object]]] = {}
    for row in rows:
        by_day.setdefault(row["occurrence"].execution_day, []).append(row)
    day_groups = sorted(
        ({"day": day, "rows": items} for day, items in by_day.items()),
        key=lambda group: (group["day"] is None, getattr(group["day"], "execution_date", date.max)),
    )

    return {
        "wo_occurrence_rows": rows,
        "wo_occurrence_day_groups": day_groups,
        "wo_occurrence_progress": maintenance_dom.workorder_progress(workorder),
        "wo_execution_day_form": ExecutionDayForm(),
        "wo_bulk_completion_form": OccurrenceBulkCompletionForm(),
        "wo_can_plan_maintenance": can_plan_maintenance(request),
        "wo_can_execute_maintenance": can_execute_maintenance(request),
    }



@login_required
def workorder_detail(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:wo_list")
    workorder = get_object_or_404(
        WorkOrder.objects.select_related(
            "asset",
            "periodic_verification",
            "supplier",
            "maintenance_rule",
            "maintenance_rule__intervention_template",
            "assistance_contract",
            "assistance_contract__supplier",
        ),
        pk=id,
    )

    if request.method == "POST":
        action = _clean_string(request.POST.get("action"))
        author = request.user if request.user.is_authenticated else None

        if action == "set_waiting":
            reason = _clean_string(request.POST.get("wait_reason"))
            note = _clean_string(request.POST.get("wait_note"))
            reason_choices = dict(WorkOrder.WAIT_REASON_CHOICES)
            if workorder.status != WorkOrder.STATUS_OPEN:
                messages.error(request, "Solo un intervento aperto puo essere messo in attesa.")
            elif reason not in reason_choices:
                messages.error(request, "Seleziona un motivo di attesa valido.")
            else:
                workorder.set_waiting(reason=reason, note=note)
                log_text = f"Intervento messo in attesa · motivo: {reason_choices[reason]}"
                if note:
                    log_text = f"{log_text} · {note}"
                WorkOrderLog.objects.create(work_order=workorder, note=log_text, author=author)
                messages.success(request, "Intervento messo in attesa.")
            return redirect("assets:wo_view", id=workorder.id)

        if action == "start":
            if workorder.status != WorkOrder.STATUS_OPEN:
                messages.error(request, "Solo un intervento aperto puo essere iniziato.")
            else:
                was_waiting = workorder.is_waiting
                already_started = bool(workorder.started_at)
                claimed = workorder.start(user=request.user)
                actor_label = request.user.get_full_name() or request.user.username
                if not already_started:
                    log_text = "Intervento iniziato."
                    if was_waiting:
                        log_text = "Intervento ripreso e iniziato."
                    if claimed:
                        log_text = f"{log_text} Intestato a {actor_label}, che lo ha avviato."
                    WorkOrderLog.objects.create(work_order=workorder, note=log_text, author=author)
                    messages.success(request, "Intervento iniziato.")
                elif was_waiting:
                    WorkOrderLog.objects.create(
                        work_order=workorder, note="Intervento ripreso dall'attesa.", author=author
                    )
                    messages.success(request, "Intervento ripreso.")
            return redirect("assets:wo_view", id=workorder.id)

        if action == "set_priority":
            priority_choices = dict(WorkOrder.PRIORITY_CHOICES)
            new_priority = _clean_string(request.POST.get("priority"))
            if new_priority not in priority_choices:
                messages.error(request, "Seleziona una priorità valida.")
            elif new_priority != workorder.priority:
                previous_label = workorder.get_priority_display()
                workorder.priority = new_priority
                workorder.save(update_fields=["priority"])
                WorkOrderLog.objects.create(
                    work_order=workorder,
                    note=f"Priorità aggiornata: {previous_label} → {priority_choices[new_priority]}",
                    author=author,
                )
                messages.success(request, "Priorità aggiornata.")
            return redirect("assets:wo_view", id=workorder.id)

        if action == "resume_from_waiting":
            if workorder.is_waiting:
                workorder.resume_from_waiting()
                WorkOrderLog.objects.create(
                    work_order=workorder, note="Intervento ripreso dall'attesa.", author=author
                )
                messages.success(request, "Intervento ripreso.")
            return redirect("assets:wo_view", id=workorder.id)

        if action == "reassign":
            from django.contrib.auth import get_user_model

            User = get_user_model()
            if workorder.status != WorkOrder.STATUS_OPEN:
                messages.error(request, "Solo un intervento aperto puo essere riassegnato.")
                return redirect("assets:wo_view", id=workorder.id)
            new_assignee_id = _clean_string(request.POST.get("new_assignee"))
            reason = _clean_string(request.POST.get("reassign_reason"))
            new_assignee = None
            if new_assignee_id:
                new_assignee = User.objects.filter(pk=new_assignee_id, is_active=True).first()
                if new_assignee is None:
                    messages.error(request, "Seleziona un manutentore valido.")
                    return redirect("assets:wo_view", id=workorder.id)
            previous_assignee = workorder.assigned_to
            if new_assignee_id == "" and previous_assignee is None:
                messages.info(request, "Nessuna modifica: assegnatario invariato.")
                return redirect("assets:wo_view", id=workorder.id)
            if new_assignee is not None and previous_assignee is not None and new_assignee.pk == previous_assignee.pk:
                messages.info(request, "Nessuna modifica: assegnatario invariato.")
                return redirect("assets:wo_view", id=workorder.id)
            workorder.assigned_to = new_assignee
            workorder.save(update_fields=["assigned_to"])
            previous_label = (
                previous_assignee.get_full_name() or previous_assignee.username if previous_assignee else "nessuno"
            )
            new_label = new_assignee.get_full_name() or new_assignee.username if new_assignee else "nessuno"
            actor_label = author.get_full_name() or author.username if author else "—"
            log_text = f"Riassegnato da {previous_label} a {new_label} · da {actor_label}"
            if reason:
                log_text = f"{log_text} · motivo: {reason}"
            WorkOrderLog.objects.create(work_order=workorder, note=log_text, author=author)
            notify_workorder_assigned(workorder, actor=request.user)
            notify_workorder_reassigned(workorder, previous_assignee=previous_assignee, actor=request.user)
            messages.success(request, "Intervento riassegnato.")
            return redirect("assets:wo_view", id=workorder.id)

        log_note = _clean_string(request.POST.get("log_note"))
        if log_note:
            WorkOrderLog.objects.create(
                work_order=workorder,
                note=log_note,
                author=author,
            )
            messages.success(request, "Nota aggiunta.")
            return redirect("assets:wo_view", id=workorder.id)

    from django.contrib.auth import get_user_model

    User = get_user_model()
    assignable_users = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    logs = workorder.logs.select_related("author").all()
    attachments = workorder.attachments.all()
    checklist_items = list(
        workorder.checklist_items.select_related("done_by", "skipped_by").prefetch_related("photos").order_by("step_number", "id")
    )
    checklist_done_count = sum(1 for it in checklist_items if it.is_complete or it.is_skipped)
    execution_days = list(workorder.execution_days.order_by("execution_date"))
    duration_hours, duration_remainder = divmod(max(0, int(workorder.intervention_duration_minutes or 0)), 60)
    downtime_hours, downtime_remainder = divmod(max(0, int(workorder.downtime_minutes or 0)), 60)
    return render(
        request,
        "assets/pages/workorder_detail.html",
        {
            "page_title": f"Intervento #{workorder.display_number}",
            "workorder": workorder,
            "batch_rows": _workorder_batch_rows(workorder),
            **_workorder_suggestions(request, workorder),
            "logs": logs,
            "attachments": attachments,
            "checklist_items": checklist_items,
            "checklist_done_count": checklist_done_count,
            "checklist_total": len(checklist_items),
            "execution_days": execution_days,
            # Pannello del nuovo dominio: le manutenzioni raccolte in questo OdL.
            # Un OdL massivo va letto per asset, non come un blocco unico.
            **_workorder_occurrences_context(request, workorder),
            **_checklist_followup_context(request, workorder, checklist_items),
            "duration_hours": duration_hours,
            "duration_remainder": duration_remainder,
            "downtime_hours": downtime_hours,
            "downtime_remainder": downtime_remainder,
            "is_open": workorder.status == WorkOrder.STATUS_OPEN,
            "workorder_asset_url": reverse("assets:asset_view", kwargs={"id": workorder.asset_id}),
            "workorder_rule_url": (
                _asset_maintenance_rule_list_page_url(
                    asset_id=workorder.asset_id,
                    focus_rule_id=workorder.maintenance_rule_id or 0,
                )
                if workorder.maintenance_rule_id
                else ""
            ),
            "workorder_contract_url": (
                _assistance_contracts_page_url(
                    asset_id=workorder.asset_id,
                    edit_id=workorder.assistance_contract_id or 0,
                )
                if workorder.assistance_contract_id
                else _assistance_contracts_page_url(asset_id=workorder.asset_id)
            ),
            "workorder_contract_label": "Apri contratto" if workorder.assistance_contract_id else "Apri contratti",
            "workorder_status": _workorder_status_payload(workorder.status),
            "workorder_kind": _workorder_kind_payload(workorder.kind),
            "workorder_coverage": _coverage_status_payload(
                is_covered=bool(workorder.covered_by_contract),
                contract=workorder.assistance_contract,
            ),
            "wait_reason_choices": WorkOrder.WAIT_REASON_CHOICES,
            "priority_choices": WorkOrder.PRIORITY_CHOICES,
            "operational_state": workorder.operational_state,
            "operational_state_label": workorder.operational_state_label,
            "is_overdue": workorder.is_overdue,
            "assignable_users": assignable_users,
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
            # Il dettaglio di un OdL è un'azione operativa su un intervento specifico: la
            # subnav di sezione ("+Nuovo intervento" ecc.) non è contestuale a questa pagina
            # e spingeva fuori dal flusso, stesso motivo per cui è già soppressa in
            # workorder_create.
            "assets_section_nav": None,
        },
    )


def _workorder_batch_rows(workorder: WorkOrder) -> list[dict[str, object]]:
    """Gli OdL nati insieme a questo (gruppo X-1, X-2...), per navigarli dalla scheda."""
    if not (workorder.reference_batch or "").startswith(WorkOrder.BATCH_REFERENCE_PREFIX):
        return []
    siblings = list(
        WorkOrder.objects.filter(reference_batch=workorder.reference_batch)
        .select_related("asset", "assigned_to")
        .order_by("id")
    )
    if len(siblings) < 2:
        return []
    leader = siblings[0].id
    return [
        {
            "wo": wo,
            "number": f"{leader}-{position}",
            "is_current": wo.id == workorder.id,
            "url": reverse("assets:wo_view", kwargs={"id": wo.id}),
        }
        for position, wo in enumerate(siblings, start=1)
    ]


def _workorder_suggestions(request: HttpRequest, workorder: WorkOrder) -> dict[str, object]:
    """Cose utili da aggiungere all'intervento, proposte dal sistema.

    Solo proposte: nulla viene modificato finche' qualcuno non preme il pulsante.
    """
    from ..models import MaintenanceOccurrence

    suggestions: list[dict[str, object]] = []
    if workorder.status != WorkOrder.STATUS_OPEN:
        return {"suggestions": suggestions, "suggested_occurrences": []}
    asset_ids = set(workorder.occurrences.values_list("asset_id", flat=True)) or {workorder.asset_id}
    today = timezone.localdate()

    # 1. Altre manutenzioni dello stesso asset, non ancora in un OdL, entro 30 giorni:
    #    farle nella stessa uscita risparmia un viaggio alla macchina.
    suggested_occurrences = list(
        MaintenanceOccurrence.objects.filter(
            asset_id__in=asset_ids,
            status=MaintenanceOccurrence.STATUS_OPEN,
            work_order__isnull=True,
            due_date__lte=today + timedelta(days=30),
        )
        .select_related("plan", "asset")
        .order_by("due_date")[:10]
    )
    # 2. Altri OdL aperti sulla stessa macchina.
    other_open = list(
        WorkOrder.objects.filter(asset_id__in=asset_ids, status=WorkOrder.STATUS_OPEN)
        .exclude(pk=workorder.pk)
        .exclude(reference_batch__gt="", reference_batch=workorder.reference_batch)
        .order_by("opened_at")[:5]
    )
    for other in other_open:
        suggestions.append({
            "tone": "info",
            "text": f"Sullo stesso asset c'e' gia' l'intervento #{other.display_number} «{other.title}» aperto: valuta di farli insieme.",
            "url": reverse("assets:wo_view", kwargs={"id": other.id}),
            "cta": "Apri",
        })
    # 3. Contratto di assistenza attivo ma nessuna ditta indicata.
    if not workorder.supplier_id and workorder.asset_id:
        for contract in get_applicable_assistance_contracts(workorder.asset, today=today)[:1]:
            suggestions.append({
                "tone": "info",
                "text": f"L'asset e' coperto dal contratto «{contract.title}» con {contract.supplier}: se interviene la ditta, indicala in chiusura.",
                "url": reverse("assets:assistance_contract_list"),
                "cta": "Contratti",
            })
    # 4. Nessuno se ne occupa.
    if not workorder.assigned_to_id and not workorder.supplier_id:
        suggestions.append({
            "tone": "warn",
            "text": "Nessun manutentore e nessuna ditta: assegna l'intervento perche' qualcuno lo prenda in carico.",
            "url": "#wo-riassegna",
            "cta": "Riassegna",
        })
    return {"suggestions": suggestions, "suggested_occurrences": suggested_occurrences}


def _checklist_followup_context(request: HttpRequest, workorder: WorkOrder, items) -> dict[str, object]:
    """Da quale step si puo' aprire un follow-up, e su quale asset.

    Uno step fuori range o saltato con motivazione e' il momento in cui l'anomalia
    si vede: se il pulsante non e' li', il follow-up si apre dopo, a memoria, o non
    si apre affatto. Il follow-up del nuovo dominio nasce pero' da un'occorrenza,
    quindi serve sapere *su quale macchina*: su un OdL massivo la checklist e' una
    sola ma gli asset sono molti, e sceglierne uno d'ufficio sarebbe un'invenzione.
    """
    from ..models import MaintenanceOccurrence
    from ..views_maintenance import can_execute_maintenance

    if not can_execute_maintenance(request):
        return {"checklist_followup_occurrences": [], "checklist_followups_by_item": {}}

    occurrences = list(
        MaintenanceOccurrence.objects.filter(work_order=workorder)
        .select_related("asset", "plan")
        .order_by("asset__asset_tag")
    )
    existing = {
        follow_up.follow_up_checklist_item_id: follow_up
        for follow_up in WorkOrder.objects.filter(
            follow_up_checklist_item__in=[item.id for item in items]
        ).only("id", "title", "status", "follow_up_checklist_item")
    }
    for item in items:
        # Attributo sul singolo step: il template non deve fare lookup in un dict.
        item.existing_follow_up = existing.get(item.id)
    return {
        "checklist_followup_occurrences": occurrences,
        "checklist_followups_by_item": existing,
    }


def _render_checklist_fragment(request: HttpRequest, workorder: WorkOrder) -> HttpResponse:
    items = list(
        workorder.checklist_items.select_related("done_by", "skipped_by").prefetch_related("photos").order_by("step_number", "id")
    )
    done_count = sum(1 for it in items if it.is_complete or it.is_skipped)
    return render(
        request,
        "assets/components/workorder_checklist.html",
        {
            "workorder": workorder,
            "checklist_items": items,
            "checklist_done_count": done_count,
            "checklist_total": len(items),
            "is_open": workorder.status == WorkOrder.STATUS_OPEN,
            **_checklist_followup_context(request, workorder, items),
        },
    )


@login_required
def workorder_checklist_add(request: HttpRequest, id: int) -> HttpResponse:
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    description = _clean_string(request.POST.get("description"))
    if not description:
        return _render_checklist_fragment(request, workorder)
    max_step = (
        WorkOrderChecklist.objects.filter(work_order=workorder)
        .order_by("-step_number")
        .values_list("step_number", flat=True)
        .first()
    ) or 0
    WorkOrderChecklist.objects.create(
        work_order=workorder,
        step_number=max_step + 1,
        description=description,
    )
    return _render_checklist_fragment(request, workorder)


@login_required
def workorder_checklist_toggle(request: HttpRequest, id: int, item_id: int) -> HttpResponse:
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    item = get_object_or_404(WorkOrderChecklist, pk=item_id, work_order=workorder)
    item.toggle(request.user)
    return _render_checklist_fragment(request, workorder)


@login_required
def workorder_checklist_delete(request: HttpRequest, id: int, item_id: int) -> HttpResponse:
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    WorkOrderChecklist.objects.filter(pk=item_id, work_order=workorder).delete()
    return _render_checklist_fragment(request, workorder)


@login_required
def workorder_checklist_set_value(request: HttpRequest, id: int, item_id: int) -> HttpResponse:
    """Valorizza uno step Misura o Testo (gli step Sì/No usano il toggle, le Foto l'upload)."""
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    item = get_object_or_404(WorkOrderChecklist, pk=item_id, work_order=workorder)
    if item.step_type == WorkOrderChecklist.TYPE_MEASURE:
        raw_value = _clean_string(request.POST.get("value_numeric"))
        try:
            value_numeric = Decimal(raw_value.replace(",", ".")) if raw_value else None
        except (InvalidOperation, ValueError):
            value_numeric = None
        item.set_value(value_numeric=value_numeric, user=request.user)
    elif item.step_type == WorkOrderChecklist.TYPE_TEXT:
        item.set_value(value_text=request.POST.get("value_text", ""), user=request.user)
    return _render_checklist_fragment(request, workorder)


@login_required
def workorder_checklist_photo(request: HttpRequest, id: int, item_id: int) -> HttpResponse:
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    item = get_object_or_404(WorkOrderChecklist, pk=item_id, work_order=workorder, step_type=WorkOrderChecklist.TYPE_PHOTO)
    uploads, upload_errors = _validate_workorder_attachment_uploads(request, field_name="photo")
    if uploads:
        _save_workorder_attachments(workorder=workorder, uploads=uploads[:1], user=request.user, checklist_item=item)
    elif upload_errors:
        messages.error(request, upload_errors[0])
    return redirect(f"{reverse('assets:wo_view', args=[workorder.id])}#wod-checklist-section")


@login_required
def workorder_checklist_skip(request: HttpRequest, id: int, item_id: int) -> HttpResponse:
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return HttpResponseForbidden("OdL non aperto.")
    if request.method != "POST":
        return HttpResponseForbidden("Metodo non consentito.")
    item = get_object_or_404(WorkOrderChecklist, pk=item_id, work_order=workorder)
    if item.is_skipped:
        item.unskip()
    else:
        reason = _clean_string(request.POST.get("skip_reason"))
        if reason:
            item.skip(reason=reason, user=request.user)
    return _render_checklist_fragment(request, workorder)


@login_required
def workorder_claim(request: HttpRequest, id: int) -> HttpResponse:
    """Assegna l'intervento aperto all'utente corrente ("prendi in carico").

    Azione leggera richiamabile dal Centro Manutenzione senza aprire il dettaglio.
    Non modifica lo stato dell'OdL: imposta solo ``assigned_to`` e logga la presa
    in carico. Ritorna al referer (hub) o al dettaglio.
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    workorder = get_object_or_404(WorkOrder, pk=id)
    raw_next = request.POST.get("next") or ""
    if raw_next and url_has_allowed_host_and_scheme(
        raw_next, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_url = raw_next
    else:
        next_url = reverse("assets:wo_view", args=[workorder.id])
    if request.method != "POST":
        return redirect(next_url)
    if workorder.status != WorkOrder.STATUS_OPEN:
        messages.error(request, "L'intervento non è aperto: impossibile prenderlo in carico.")
        return redirect(next_url)
    if workorder.assigned_to_id == request.user.id:
        messages.info(request, f"Intervento #{workorder.id} già assegnato a te.")
        return redirect(next_url)

    previous_assignee = workorder.assigned_to
    workorder.assigned_to = request.user
    workorder.save(update_fields=["assigned_to"])
    actor = request.user.get_full_name() or request.user.username
    WorkOrderLog.objects.create(
        work_order=workorder,
        note=f"Preso in carico da {actor}.",
        author=request.user if request.user.is_authenticated else None,
    )
    notify_workorder_taken_over(workorder, previous_assignee=previous_assignee, actor=request.user)
    messages.success(request, f"Intervento #{workorder.id} preso in carico.")
    return redirect(next_url)


@login_required
def workorder_set_state(request: HttpRequest, id: int) -> JsonResponse:
    """Endpoint della board Kanban OdL (drag&drop): sposta un intervento aperto tra gli stati
    operativi derivati (assegna/avvia/metti in attesa). Risposta sempre JSON, mai redirect —
    e' l'unico consumatore, via fetch(), stesso pattern di tasks/_board.html."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Metodo non consentito."}, status=405)
    workorder = get_object_or_404(WorkOrder, pk=id)
    if workorder.status != WorkOrder.STATUS_OPEN:
        return JsonResponse({"ok": False, "error": "Intervento non aperto."}, status=409)

    target_state = _clean_string(request.POST.get("state"))
    actor = request.user.get_full_name() or request.user.username

    if target_state == WorkOrder.OPSTATE_ASSIGNED:
        previous_assignee = workorder.assigned_to
        workorder.assign(request.user)
        WorkOrderLog.objects.create(
            work_order=workorder,
            note=f"Preso in carico da {actor} (board).",
            author=request.user,
        )
        notify_workorder_taken_over(workorder, previous_assignee=previous_assignee, actor=request.user)
    elif target_state == WorkOrder.OPSTATE_IN_PROGRESS:
        claimed = workorder.start(user=request.user)
        note = f"Intervento avviato da {actor} (board)."
        if claimed:
            note = f"{note} Intestato a {actor}, che lo ha avviato."
        WorkOrderLog.objects.create(
            work_order=workorder,
            note=note,
            author=request.user,
        )
    elif target_state == WorkOrder.OPSTATE_WAITING:
        workorder.set_waiting(reason=WorkOrder.WAIT_REASON_ALTRO, note="")
        WorkOrderLog.objects.create(
            work_order=workorder,
            note=f"Messo in attesa da {actor} (board). Motivo da precisare in scheda.",
            author=request.user,
        )
    else:
        return JsonResponse({"ok": False, "error": "Stato non valido."}, status=400)

    return JsonResponse({"ok": True, "operational_state": workorder.operational_state})


@login_required
def workorder_close(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:wo_list")
    workorder = get_object_or_404(
        WorkOrder.objects.select_related(
            "asset", "maintenance_rule", "assistance_contract", "assistance_contract__supplier", "ticket"
        ),
        pk=id,
    )

    # Segnalazione collegata ancora aperta: la si puo' risolvere insieme all'OdL,
    # ma solo chi puo' gestire quel ticket (stessa regola delle API ticket).
    from tickets.services.accesso import identita_utente, utente_puo_gestire_ticket

    from ..services.workorder_close import ticket_resolvable

    linked_ticket = workorder.ticket if ticket_resolvable(workorder) else None
    can_manage_ticket = bool(linked_ticket is not None and utente_puo_gestire_ticket(request, linked_ticket))
    ticket_identity = identita_utente(request) if can_manage_ticket else ("", "")
    form_ticket_kwargs = {"resolvable_ticket": linked_ticket if can_manage_ticket else None}

    # Manutenzioni raccolte e non ancora registrate: la chiusura non le tocca (ogni
    # asset avanza sul suo piano quando *quella* manutenzione e' dichiarata eseguita),
    # quindi restano dovute. Prima l'avviso arrivava a cose fatte, su una pagina gia'
    # cambiata: si leggeva di sfuggita. Ora ferma la chiusura e la fa confermare.
    from ..views_maintenance import can_plan_maintenance

    pending_occurrences: list = []
    pending_confirmation = False
    pending_reason_required = False
    pending_reason_value = ""
    can_force_close = can_plan_maintenance(request)

    if request.method == "POST":
        form = WorkOrderCloseForm(request.POST, asset=workorder.asset, workorder=workorder, **form_ticket_kwargs)
        uploads, upload_errors = _validate_workorder_attachment_uploads(request, field_name="close_attachments")
        form_is_valid = form.is_valid()
        for error in upload_errors:
            form.add_error(None, error)
        pending_reason_value = _clean_string(request.POST.get("open_occurrences_reason"))
        if form_is_valid and form.cleaned_data["status"] in (WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED):
            from ..models import MaintenanceOccurrence

            pending_occurrences = list(
                MaintenanceOccurrence.objects.filter(
                    work_order=workorder, status=MaintenanceOccurrence.STATUS_OPEN
                ).select_related("plan", "asset")
            )
            if pending_occurrences:
                confirmed = request.POST.get("confirm_open_occurrences") == "1"
                # Chi pianifica sa che cosa lascia dovuto: gli basta un click. Chi
                # esegue lo dichiara, e la motivazione finisce nel log di chiusura.
                pending_reason_required = not can_force_close
                if not confirmed or (pending_reason_required and not pending_reason_value):
                    pending_confirmation = True
                    form_is_valid = False
                    if confirmed and pending_reason_required and not pending_reason_value:
                        form.add_error(
                            None,
                            "Spiega perche' chiudi l'intervento lasciando manutenzioni non registrate.",
                        )
        if form_is_valid and not upload_errors:
            from ..services.workorder_close import (
                CloseData,
                RequestIdentity,
                WorkOrderAlreadyClosed,
                WorkOrderCloseError,
                close_workorder,
            )

            cleaned = form.cleaned_data
            ticket_name, ticket_email = ticket_identity
            close_data = CloseData(
                status=cleaned["status"],
                esito=cleaned.get("esito") or "",
                closed_at=cleaned.get("closed_at"),
                resolution=cleaned.get("resolution") or "",
                intervention_duration=cleaned.get("intervention_duration_minutes"),
                downtime=cleaned.get("downtime_minutes"),
                labor_cost=cleaned.get("labor_cost_eur"),
                materials_cost=cleaned.get("materials_cost_eur"),
                cost=cleaned.get("cost_eur"),
                covered_by_contract=cleaned.get("covered_by_contract"),
                assistance_contract=cleaned.get("assistance_contract"),
                resolved_supplier=cleaned.get("resolved_supplier"),
                failure_cause=cleaned.get("failure_cause") or "",
                execution_days=tuple(cleaned.get("execution_days_list") or ()),
                follow_up_date=cleaned.get("follow_up_date"),
                log_note=_clean_string(cleaned.get("log_note")),
                assigned_to=cleaned.get("assigned_to"),
                executed_by=cleaned.get("executed_by"),
                claim_on_close=bool(cleaned.get("claim_on_close")),
                pending_occurrences_count=len(pending_occurrences),
                pending_reason=pending_reason_value if pending_occurrences else "",
                uploads=tuple(uploads),
                resolve_ticket=bool(cleaned.get("resolve_ticket")),
                failure_problem=cleaned.get("failure_problem"),
                failure_cause_code=cleaned.get("failure_cause_code"),
                failure_remedy=cleaned.get("failure_remedy"),
            )
            try:
                result = close_workorder(
                    workorder.pk,
                    data=close_data,
                    user=request.user,
                    request_identity=RequestIdentity(
                        name=ticket_name, email=ticket_email, can_manage_ticket=can_manage_ticket
                    ),
                )
            except WorkOrderAlreadyClosed as exc:
                # Doppio invio del form: la prima chiusura e' gia' passata.
                messages.info(request, str(exc))
                return redirect("assets:wo_view", id=workorder.id)
            except WorkOrderCloseError as exc:
                form.add_error(None, str(exc))
            except ValidationError as exc:
                _add_form_validation_errors(form, exc)
            else:
                for text in result.messages:
                    messages.success(request, text)
                for text in result.warnings:
                    messages.warning(request, text)
                return redirect("assets:wo_view", id=workorder.id)
    else:
        # Fermo: se l'OdL non lo dice ma la segnalazione si', si parte da quello
        # dichiarato sul ticket (ore -> minuti). Resta modificabile.
        initial_downtime = workorder.downtime_minutes
        ticket_hours = getattr(workorder.ticket, "ore_fermo_macchina", None) if workorder.ticket_id else None
        if not initial_downtime and ticket_hours:
            initial_downtime = int(round(Decimal(ticket_hours) * 60))
        form = WorkOrderCloseForm(
            initial={
                "status": WorkOrder.STATUS_DONE,
                # Il caso normale: chi chiude ha risolto. Gli altri esiti sono un click.
                "esito": WorkOrder.OUTCOME_RESOLVED,
                "intervention_duration_minutes": workorder.intervention_duration_minutes,
                "downtime_minutes": initial_downtime,
                "labor_cost_eur": workorder.labor_cost_eur,
                "materials_cost_eur": workorder.materials_cost_eur,
                "cost_eur": workorder.cost_eur,
                "assistance_contract": workorder.assistance_contract_id,
                "covered_by_contract": workorder.covered_by_contract,
                "assigned_to": workorder.assigned_to_id,
                # Chi chiude l'intervento è quasi sempre chi l'ha eseguito: precompilare
                # evita al manutentore di doversi ricercare in un elenco ad ogni chiusura.
                "executed_by": workorder.executed_by_id or (
                    request.user.id if request.user.is_authenticated else None
                ),
                "failure_cause": workorder.failure_cause,
                "failure_problem": workorder.failure_problem_id,
                "failure_cause_code": workorder.failure_cause_code_id,
                "failure_remedy": workorder.failure_remedy_id,
            },
            asset=workorder.asset,
            workorder=workorder,
            **form_ticket_kwargs,
        )

    return render(
        request,
        "assets/pages/workorder_close.html",
        {
            "page_title": f"Chiudi intervento #{workorder.id}",
            "workorder": workorder,
            "form": form,
            "close_submit_label": (
                "Annulla l'intervento"
                if form["esito"].value() == WorkOrderCloseForm.ESITO_CANCELED
                or form["status"].value() == WorkOrder.STATUS_CANCELED
                else "Chiudi definitivamente"
            ),
            "workorder_status": _workorder_status_payload(workorder.status),
            "workorder_kind": _workorder_kind_payload(workorder.kind),
            "workorder_coverage": _coverage_status_payload(
                is_covered=bool(workorder.covered_by_contract),
                contract=workorder.assistance_contract,
            ),
            "attachment_accept": _workorder_attachment_accept_attr(),
            "attachment_max_mb": int(ASSET_DOCUMENT_MAX_BYTES / (1024 * 1024)),
            "checklist_blocking_items": [item for item in workorder.checklist_items.all() if item.blocks_closure],
            "pending_occurrences": pending_occurrences if pending_confirmation else [],
            "pending_confirmation": pending_confirmation,
            "pending_reason_required": pending_reason_required,
            "pending_reason_value": pending_reason_value,
            "can_force_close": can_force_close,
            "linked_ticket": linked_ticket,
            "ticket_downtime_prefilled": bool(
                request.method != "POST" and not workorder.downtime_minutes and workorder.ticket_id
                and getattr(workorder.ticket, "ore_fermo_macchina", None)
            ),
            "occurrences_anchor": f"{reverse('assets:wo_view', kwargs={'id': workorder.id})}#manutenzioni-raccolte",
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
            "assets_section_nav": None,
        },
    )
