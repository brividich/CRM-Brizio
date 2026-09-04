"""Viste del nuovo dominio manutenzione (Piano / Applicazione / Occorrenza / OdL).

Modulo separato da ``views.py``, che ha superato le 18.000 righe ed e' toccato in
parallelo da piu' rami: tenere qui il nuovo dominio lo rende leggibile e riduce i
conflitti. Gli helper condivisi (shell, gate, parsing) restano importati da
``views.py``, che non importa mai questo modulo: la dipendenza va in un verso solo.

Il linguaggio dell'interfaccia e' quello del documento di specifica: Piano,
Applicazione, Scadenza, Ordine di lavoro, Follow-up. Mai "regola", "override",
"threshold", "scope".
"""

from __future__ import annotations

import io
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.acl import user_can_modulo_action

from .forms_maintenance import (
    AssetGroupForm,
    AssetPlanCustomizationForm,
    ExecutionDayForm,
    FollowUpForm,
    MaintenancePlanAssignmentForm,
    MaintenanceHistoryImportForm,
    MaintenancePlanForm,
    OccurrenceCompletionForm,
    OccurrenceFilterForm,
    WorkOrderFromOccurrencesForm,
)
from .models import (
    Asset,
    AssetGroup,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    MaintenanceOccurrenceAttachment,
    MaintenancePlanAssignment,
    WorkOrder,
)
from .services import maintenance_domain as domain
from .services import maintenance_history_import as history_import
from .services.recurrence import RECURRENCE_PRESETS, describe_recurrence
from .views import _assets_shell_context, _as_int, _clean_string, _is_assets_admin

# ---------------------------------------------------------------------------
# Permessi
# ---------------------------------------------------------------------------
# Le tre platee della specifica. I gate non si fermano a "superuser o admin
# legacy": chi ha il permesso ACL granulare deve poter lavorare, altrimenti il
# pannello Accessi non serve a niente.


def can_manage_maintenance_plans(request: HttpRequest) -> bool:
    """Configura piani, applicazioni, gruppi. Amministratore / responsabile."""
    if _is_assets_admin(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "admin_assets"))


def can_plan_maintenance(request: HttpRequest) -> bool:
    """Organizza il lavoro: crea OdL, distribuisce le giornate, rimuove asset."""
    if can_manage_maintenance_plans(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "maintenance_planning"))


def can_execute_maintenance(request: HttpRequest) -> bool:
    """Esegue: chiude occorrenze, carica rapporti, apre follow-up."""
    if can_plan_maintenance(request):
        return True
    return bool(user_can_modulo_action(request, "assets", "maintenance_execute"))


def _deny(request: HttpRequest, message: str, fallback: str = "assets:maintenance_da_fare"):
    messages.error(request, message)
    return redirect(fallback)


# ---------------------------------------------------------------------------
# Query e presentazione delle occorrenze
# ---------------------------------------------------------------------------

_OCCURRENCE_SELECT = (
    "plan",
    "asset",
    "asset__asset_category",
    "assignment",
    "assignment__asset_group",
    "work_order",
    "work_order__assigned_to",
    "supplier",
)


def _base_occurrence_queryset():
    return (
        MaintenanceOccurrence.objects.select_related(*_OCCURRENCE_SELECT)
        .prefetch_related("attachments")
        .exclude(status=MaintenanceOccurrence.STATUS_CANCELED)
    )


def _apply_occurrence_filters(queryset, form: OccurrenceFilterForm, *, today: date):
    """Filtri della specifica §26, applicati in SQL dove possibile."""
    if not form.is_valid():
        return queryset
    data = form.cleaned_data

    if data.get("q"):
        term = data["q"].strip()
        queryset = queryset.filter(
            Q(plan__label__icontains=term)
            | Q(asset__asset_tag__icontains=term)
            | Q(asset__name__icontains=term)
            | Q(asset__internal_number__icontains=term)
        )
    if data.get("plan"):
        queryset = queryset.filter(plan=data["plan"])
    if data.get("group"):
        queryset = queryset.filter(asset__group_memberships__group=data["group"])
    if data.get("asset"):
        queryset = queryset.filter(asset=data["asset"])
    if data.get("reparto"):
        queryset = queryset.filter(asset__reparto=data["reparto"])
    if data.get("assignee"):
        queryset = queryset.filter(work_order__assigned_to=data["assignee"])
    if data.get("supplier"):
        queryset = queryset.filter(supplier=data["supplier"])

    plan_type = data.get("plan_type")
    if plan_type == "administrative":
        queryset = queryset.filter(plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)
    elif plan_type == "ordinary":
        queryset = queryset.exclude(plan__maintenance_type=MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE)

    mode = data.get("execution_mode")
    if mode:
        # La modalita' effettiva puo' venire dall'applicazione o dal piano: si
        # filtra su entrambe, con l'applicazione che vince quando valorizzata.
        queryset = queryset.filter(
            Q(assignment__execution_mode=mode)
            | (Q(assignment__execution_mode="") & Q(plan__execution_mode=mode))
            | (Q(assignment__isnull=True) & Q(plan__execution_mode=mode))
        )

    planning = data.get("planning")
    if planning == "unplanned":
        queryset = queryset.filter(work_order__isnull=True, status=MaintenanceOccurrence.STATUS_OPEN)
    elif planning == "planned":
        queryset = queryset.filter(work_order__isnull=False)

    window = data.get("window")
    if window == "overdue":
        queryset = queryset.filter(status=MaintenanceOccurrence.STATUS_OPEN, due_date__lt=today)
    elif window:
        queryset = queryset.filter(due_date__lte=today + timedelta(days=int(window)))

    return queryset.distinct()


def _decorate(occurrences: list[MaintenanceOccurrence], *, today: date) -> list[dict[str, Any]]:
    """Aggiunge lo stato visuale derivato senza toccare il DB."""
    rows = []
    for occurrence in occurrences:
        payload = domain.occurrence_state_payload(occurrence, today=today)
        days = payload.get("days_until_due")
        # Il ritardo si calcola qui: il template non deve fare aritmetica.
        payload["days_late"] = -days if days is not None and days < 0 else 0
        rows.append({"occurrence": occurrence, **payload})
    rows.sort(key=lambda row: (row["order"], row["occurrence"].due_date, row["occurrence"].id))
    return rows


def _report_missing_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row["state"] == MaintenanceOccurrence.VIEW_REPORT_MISSING]


def _group_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Stessa base dati, tre letture: per piano, per famiglia, per asset."""
    buckets: dict[Any, dict[str, Any]] = {}
    for row in rows:
        occurrence = row["occurrence"]
        if mode == "asset":
            key = occurrence.asset_id
            label = occurrence.asset.asset_tag or occurrence.asset.name
            sub = occurrence.asset.name
        elif mode == "group":
            group = occurrence.assignment.asset_group if occurrence.assignment_id else None
            key = getattr(group, "id", 0)
            label = getattr(group, "label", "") or (occurrence.asset.asset_category.label if occurrence.asset.asset_category_id else "Senza famiglia")
            sub = ""
        else:
            key = occurrence.plan_id
            label = occurrence.plan.label
            sub = occurrence.plan.get_maintenance_type_display()
        bucket = buckets.setdefault(key, {"label": label, "sub": sub, "rows": [], "overdue": 0})
        bucket["rows"].append(row)
        if row["state"] == MaintenanceOccurrence.VIEW_OVERDUE:
            bucket["overdue"] += 1
    groups = list(buckets.values())
    groups.sort(key=lambda item: (-item["overdue"], -len(item["rows"]), item["label"]))
    return groups


# ---------------------------------------------------------------------------
# Pagina "Da fare" — la giornata del manutentore
# ---------------------------------------------------------------------------

@login_required
def maintenance_da_fare(request: HttpRequest) -> HttpResponse:
    """Cosa devo fare, su quali macchine, entro quando.

    Non e' una dashboard di KPI: e' la lista del lavoro, ordinata per urgenza, da
    cui si aprono gli ordini di lavoro.
    """
    today = timezone.localdate()
    form = OccurrenceFilterForm(request.GET or None)
    form.is_valid()

    queryset = _apply_occurrence_filters(
        _base_occurrence_queryset().filter(status=MaintenanceOccurrence.STATUS_OPEN),
        form,
        today=today,
    )
    rows = _decorate(list(queryset[:1000]), today=today)

    week_end = today + timedelta(days=7)
    blocks = [
        {
            "key": "overdue",
            "title": "Scadute",
            "tone": "urgent",
            "rows": [r for r in rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE],
        },
        {
            "key": "week",
            "title": "Da fare entro 7 giorni",
            "tone": "warn",
            "rows": [
                r
                for r in rows
                if r["state"] in (MaintenanceOccurrence.VIEW_DUE_SOON, MaintenanceOccurrence.VIEW_TO_PLAN)
                and r["occurrence"].due_date <= week_end
            ],
        },
        {
            "key": "planned",
            "title": "Programmate",
            "tone": "",
            "rows": [
                r
                for r in rows
                if r["state"] in (MaintenanceOccurrence.VIEW_PLANNED, MaintenanceOccurrence.VIEW_IN_PROGRESS)
            ],
        },
        {
            "key": "waiting",
            "title": "In attesa",
            "tone": "",
            "rows": [r for r in rows if r["state"] == MaintenanceOccurrence.VIEW_WAITING],
        },
        {
            "key": "external",
            "title": "Esterne",
            "tone": "",
            "rows": [r for r in rows if r["occurrence"].is_external],
        },
    ]

    # Il parametro si chiama "by" e non "group": "group" e' gia' il filtro per gruppo.
    view_mode = _clean_string(request.GET.get("by")) or "plan"
    if view_mode not in {"plan", "group", "asset"}:
        view_mode = "plan"

    summary = {
        "overdue": len(blocks[0]["rows"]),
        "week": len(blocks[1]["rows"]),
        "planned": len(blocks[2]["rows"]),
        "external": sum(1 for r in rows if r["occurrence"].is_external and r["occurrence"].appointment_date),
    }

    return render(
        request,
        "assets/pages/maintenance_da_fare.html",
        {
            **_assets_shell_context(request),
            "page_title": "Da fare",
            "today": today,
            "filter_form": form,
            "blocks": blocks,
            "groups": _group_rows(rows, view_mode),
            "view_mode": view_mode,
            "summary": summary,
            "total": len(rows),
            "can_plan": can_plan_maintenance(request),
            "can_execute": can_execute_maintenance(request),
            "workorder_form": WorkOrderFromOccurrencesForm(),
        },
    )


# ---------------------------------------------------------------------------
# Pagina "Scadenze" — vista temporale completa
# ---------------------------------------------------------------------------

_SCADENZE_TABS = [
    ("overdue", "Scadute"),
    ("30", "30 giorni"),
    ("90", "90 giorni"),
    ("", "Tutte"),
]


@login_required
def maintenance_scadenze(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    initial = request.GET.copy()
    if "window" not in initial:
        initial["window"] = "30"
    form = OccurrenceFilterForm(initial)
    form.is_valid()

    queryset = _apply_occurrence_filters(_base_occurrence_queryset(), form, today=today)
    rows = _decorate(list(queryset[:2000]), today=today)
    if form.cleaned_data.get("report_missing"):
        rows = _report_missing_rows(rows)

    active_tab = _clean_string(initial.get("window"))
    return render(
        request,
        "assets/pages/maintenance_scadenze.html",
        {
            **_assets_shell_context(request),
            "page_title": "Scadenze",
            "today": today,
            "filter_form": form,
            "rows": rows,
            "total": len(rows),
            "tabs": _SCADENZE_TABS,
            "active_tab": active_tab,
            "can_plan": can_plan_maintenance(request),
            "workorder_form": WorkOrderFromOccurrencesForm(),
        },
    )


# ---------------------------------------------------------------------------
# Dashboard responsabile
# ---------------------------------------------------------------------------

@login_required
def maintenance_responsabile(request: HttpRequest) -> HttpResponse:
    """Quadro generale: cosa e' scaduto, cosa sta per scadere, cosa NON e' ancora
    pianificato. La distinzione fra "dovuta" e "pianificata" e' il punto della pagina."""
    today = timezone.localdate()
    open_rows = _decorate(
        list(_base_occurrence_queryset().filter(status=MaintenanceOccurrence.STATUS_OPEN)[:3000]),
        today=today,
    )
    done_rows = _decorate(
        list(
            _base_occurrence_queryset()
            .filter(status=MaintenanceOccurrence.STATUS_DONE, completed_on__gte=today - timedelta(days=120))
            .order_by("-completed_on")[:1000]
        ),
        today=today,
    )

    unplanned = [
        row
        for row in open_rows
        if row["occurrence"].work_order_id is None
        and row["state"] in (MaintenanceOccurrence.VIEW_OVERDUE, MaintenanceOccurrence.VIEW_DUE_SOON)
    ]
    report_missing = _report_missing_rows(done_rows)

    open_workorders = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, occurrences__isnull=False)
        .distinct()
        .select_related("asset", "assigned_to")
        .annotate(occurrence_count=Count("occurrences"))
        .order_by("opened_at")
    )
    follow_ups = (
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, follow_up_occurrence__isnull=False)
        .select_related("asset", "follow_up_occurrence", "follow_up_occurrence__plan")
        .order_by("-opened_at")[:50]
    )

    conflicts = [
        resolution
        for resolution in domain.build_plan_resolutions(
            asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE)
        ).values()
        if resolution.is_conflict
    ]

    kpi = {
        "overdue": sum(1 for r in open_rows if r["state"] == MaintenanceOccurrence.VIEW_OVERDUE),
        "due_soon": sum(1 for r in open_rows if r["state"] == MaintenanceOccurrence.VIEW_DUE_SOON),
        "unplanned": len(unplanned),
        "workorders_open": open_workorders.count(),
        "workorders_running": sum(1 for wo in open_workorders if wo.started_at and not wo.is_waiting),
        "waiting": sum(1 for wo in open_workorders if wo.is_waiting),
        "report_missing": len(report_missing),
        "follow_ups": follow_ups.count(),
        "conflicts": len(conflicts),
    }

    return render(
        request,
        "assets/pages/maintenance_responsabile.html",
        {
            **_assets_shell_context(request),
            "page_title": "Quadro manutenzione",
            "today": today,
            "kpi": kpi,
            "unplanned": unplanned[:60],
            "report_missing": report_missing[:40],
            "open_workorders": list(open_workorders[:40]),
            "follow_ups": list(follow_ups),
            "conflicts": conflicts[:40],
            "can_plan": can_plan_maintenance(request),
        },
    )


# ---------------------------------------------------------------------------
# Piani
# ---------------------------------------------------------------------------

@login_required
def maintenance_plan_list(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    plans = list(
        MaintenanceInterventionTemplate.objects.annotate(
            assignment_count=Count("assignments", filter=Q(assignments__is_active=True), distinct=True)
        ).order_by("sort_order", "label")
    )
    plan_ids = [plan.id for plan in plans]

    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE), plan_ids=plan_ids
    )
    coverage: dict[int, dict[str, int]] = defaultdict(lambda: {"assets": 0, "conflicts": 0, "excluded": 0})
    for (plan_id, _asset_id), resolution in resolutions.items():
        bucket = coverage[plan_id]
        if resolution.is_applied:
            bucket["assets"] += 1
        elif resolution.is_conflict:
            bucket["conflicts"] += 1
        else:
            bucket["excluded"] += 1

    stats: dict[int, dict[str, Any]] = defaultdict(lambda: {"next_due": None, "overdue": 0})
    for plan_id, due_date in (
        MaintenanceOccurrence.objects.filter(plan_id__in=plan_ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .values_list("plan_id", "due_date")
        .order_by("due_date")
    ):
        bucket = stats[plan_id]
        if bucket["next_due"] is None:
            bucket["next_due"] = due_date
        if due_date < today:
            bucket["overdue"] += 1

    rows = []
    for plan in plans:
        rows.append(
            {
                "plan": plan,
                "coverage": coverage.get(plan.id, {"assets": 0, "conflicts": 0, "excluded": 0}),
                "stats": stats.get(plan.id, {"next_due": None, "overdue": 0}),
                "recurrences": sorted(
                    {describe_recurrence(a) for a in plan.assignments.all() if not a.is_excluded}
                ),
            }
        )

    return render(
        request,
        "assets/pages/maintenance_plan_list.html",
        {
            **_assets_shell_context(request),
            "page_title": "Piani di manutenzione",
            "rows": rows,
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def maintenance_plan_detail(request: HttpRequest, plan_id: int) -> HttpResponse:
    today = timezone.localdate()
    plan = get_object_or_404(
        MaintenanceInterventionTemplate.objects.select_related("default_supplier", "default_assignee"),
        pk=plan_id,
    )
    assignments = list(
        plan.assignments.select_related("asset", "asset_group", "asset_category", "supplier", "assigned_to").order_by(
            "-target_type", "id"
        )
    )
    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(status=Asset.STATUS_IN_USE), plan_ids=[plan.id]
    )
    per_assignment: dict[int, int] = defaultdict(int)
    conflicts = []
    for resolution in resolutions.values():
        if resolution.is_applied and resolution.assignment is not None:
            per_assignment[resolution.assignment.id] += 1
        elif resolution.is_conflict:
            conflicts.append(resolution)

    assignment_rows = [
        {
            "assignment": assignment,
            "recurrence": describe_recurrence(assignment),
            "asset_count": per_assignment.get(assignment.id, 0),
        }
        for assignment in assignments
    ]

    upcoming = _decorate(
        list(
            _base_occurrence_queryset()
            .filter(plan=plan, status=MaintenanceOccurrence.STATUS_OPEN)
            .order_by("due_date")[:60]
        ),
        today=today,
    )
    history = list(
        _base_occurrence_queryset()
        .filter(plan=plan, status=MaintenanceOccurrence.STATUS_DONE)
        .order_by("-completed_on")[:60]
    )
    open_workorders = list(
        WorkOrder.objects.filter(status=WorkOrder.STATUS_OPEN, occurrences__plan=plan)
        .distinct()
        .select_related("asset", "assigned_to")
        .annotate(occurrence_count=Count("occurrences"))[:30]
    )

    return render(
        request,
        "assets/pages/maintenance_plan_detail.html",
        {
            **_assets_shell_context(request),
            "page_title": plan.label,
            "plan": plan,
            "assignment_rows": assignment_rows,
            "conflicts": conflicts,
            "upcoming": upcoming,
            "history": history,
            "open_workorders": open_workorders,
            "checklist_steps": list(plan.checklist_steps.order_by("step_number", "id")),
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def maintenance_plan_form(request: HttpRequest, plan_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per configurare i piani di manutenzione.")
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id) if plan_id else None

    if request.method == "POST":
        form = MaintenancePlanForm(request.POST, instance=plan)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.full_clean()
            saved.save()
            messages.success(request, f"Piano «{saved.label}» salvato.")
            return redirect("assets:maintenance_plan_detail", plan_id=saved.pk)
    else:
        form = MaintenancePlanForm(instance=plan)

    return render(
        request,
        "assets/pages/maintenance_plan_form.html",
        {
            **_assets_shell_context(request),
            "page_title": "Modifica piano" if plan else "Nuovo piano di manutenzione",
            "form": form,
            "plan": plan,
        },
    )


# ---------------------------------------------------------------------------
# Applicazioni di un piano
# ---------------------------------------------------------------------------

@login_required
def maintenance_assignment_form(
    request: HttpRequest, plan_id: int, assignment_id: int | None = None
) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per configurare le applicazioni dei piani.")
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id)
    assignment = (
        get_object_or_404(MaintenancePlanAssignment, pk=assignment_id, plan=plan) if assignment_id else None
    )

    if request.method == "POST":
        form = MaintenancePlanAssignmentForm(request.POST, instance=assignment, plan=plan)
        if form.is_valid():
            saved = form.save()
            messages.success(request, f"Applicazione su «{saved.target_label}» salvata.")
            return redirect("assets:maintenance_plan_detail", plan_id=plan.pk)
    else:
        form = MaintenancePlanAssignmentForm(instance=assignment, plan=plan)

    return render(
        request,
        "assets/pages/maintenance_assignment_form.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Applicazione — {plan.label}",
            "form": form,
            "plan": plan,
            "assignment": assignment,
            "presets": RECURRENCE_PRESETS,
            "preview_url": reverse("assets:maintenance_assignment_preview"),
        },
    )


@login_required
@require_POST
def maintenance_assignment_delete(request: HttpRequest, plan_id: int, assignment_id: int) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per rimuovere le applicazioni.")
    assignment = get_object_or_404(MaintenancePlanAssignment, pk=assignment_id, plan_id=plan_id)
    if assignment.occurrences.exists():
        # Un'applicazione con storico non si cancella: si disattiva. Altrimenti le
        # occorrenze gia' eseguite perderebbero il riferimento a come erano nate.
        assignment.is_active = False
        assignment.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Applicazione disattivata (ha storico, quindi non viene eliminata).")
    else:
        assignment.delete()
        messages.success(request, "Applicazione rimossa.")
    return redirect("assets:maintenance_plan_detail", plan_id=plan_id)


@login_required
def maintenance_assignment_preview(request: HttpRequest) -> JsonResponse:
    """Anteprima non persistita: quanti asset tocca, prime scadenze, conflitti.

    Serve a non salvare alla cieca un'applicazione che coinvolge decine di macchine.
    """
    if not can_manage_maintenance_plans(request):
        return JsonResponse({"error": "forbidden"}, status=403)

    plan_id = _as_int(request.GET.get("plan"), default=0)
    target_type = _clean_string(request.GET.get("target_type"))
    target_id = _as_int(request.GET.get("target_id"), default=0)
    if not plan_id or not target_type or not target_id:
        return JsonResponse({"assets": 0, "first_due": [], "conflicts": 0, "already": 0})

    assets = Asset.objects.filter(status=Asset.STATUS_IN_USE)
    if target_type == MaintenancePlanAssignment.TARGET_ASSET:
        assets = assets.filter(pk=target_id)
    elif target_type == MaintenancePlanAssignment.TARGET_GROUP:
        assets = assets.filter(group_memberships__group_id=target_id)
    else:
        assets = assets.filter(asset_category_id=target_id)
    asset_ids = list(assets.values_list("pk", flat=True)[:2000])

    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(pk__in=asset_ids), plan_ids=[plan_id]
    )
    conflicts = sum(1 for resolution in resolutions.values() if resolution.is_conflict)
    already = MaintenanceOccurrence.objects.filter(
        plan_id=plan_id, asset_id__in=asset_ids, status=MaintenanceOccurrence.STATUS_OPEN
    ).count()

    return JsonResponse(
        {
            "assets": len(asset_ids),
            "conflicts": conflicts,
            "already": already,
        }
    )


# ---------------------------------------------------------------------------
# Gruppi di asset
# ---------------------------------------------------------------------------

@login_required
def asset_group_list(request: HttpRequest) -> HttpResponse:
    groups = list(
        AssetGroup.objects.annotate(
            member_count=Count("memberships", distinct=True),
            plan_count=Count("maintenance_plan_assignments", distinct=True),
        ).order_by("sort_order", "label")
    )
    return render(
        request,
        "assets/pages/asset_group_list.html",
        {
            **_assets_shell_context(request),
            "page_title": "Gruppi di asset",
            "groups": groups,
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def asset_group_form(request: HttpRequest, group_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per gestire i gruppi di asset.", "assets:asset_group_list")
    group = get_object_or_404(AssetGroup, pk=group_id) if group_id else None

    if request.method == "POST":
        form = AssetGroupForm(request.POST, instance=group)
        if form.is_valid():
            saved = form.save(user=request.user)
            messages.success(request, f"Gruppo «{saved.label}» salvato.")
            return redirect("assets:asset_group_list")
    else:
        form = AssetGroupForm(instance=group)

    return render(
        request,
        "assets/pages/asset_group_form.html",
        {
            **_assets_shell_context(request),
            "page_title": "Modifica gruppo" if group else "Nuovo gruppo di asset",
            "form": form,
            "group": group,
        },
    )


# ---------------------------------------------------------------------------
# Scheda asset: piani applicati
# ---------------------------------------------------------------------------

@login_required
def asset_maintenance_plans(request: HttpRequest, asset_id: int) -> HttpResponse:
    """I piani che riguardano una macchina, con l'origine della regola.

    Niente "override": qui si dice ereditato, personalizzato o escluso.
    """
    asset = get_object_or_404(Asset.objects.select_related("asset_category"), pk=asset_id)
    today = timezone.localdate()
    resolutions = domain.resolve_asset_plans(asset)

    next_due_by_plan = {}
    for plan_id, due_date in (
        MaintenanceOccurrence.objects.filter(asset=asset, status=MaintenanceOccurrence.STATUS_OPEN)
        .order_by("due_date")
        .values_list("plan_id", "due_date")
    ):
        next_due_by_plan.setdefault(plan_id, due_date)

    rows = [
        {
            "resolution": resolution,
            "next_due": next_due_by_plan.get(resolution.plan.id),
            "is_overdue": (next_due_by_plan.get(resolution.plan.id) or date.max) < today,
        }
        for resolution in resolutions
    ]

    return render(
        request,
        "assets/pages/asset_maintenance_plans.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Piani di manutenzione — {asset.asset_tag}",
            "asset": asset,
            "rows": rows,
            "history": list(
                _base_occurrence_queryset()
                .filter(asset=asset, status=MaintenanceOccurrence.STATUS_DONE)
                .order_by("-completed_on")[:40]
            ),
            "can_manage": can_manage_maintenance_plans(request),
        },
    )


@login_required
def asset_plan_customize(request: HttpRequest, asset_id: int, plan_id: int) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per personalizzare i piani sugli asset.")
    asset = get_object_or_404(Asset, pk=asset_id)
    plan = get_object_or_404(MaintenanceInterventionTemplate, pk=plan_id)
    assignment = MaintenancePlanAssignment.objects.filter(
        plan=plan, asset=asset, target_type=MaintenancePlanAssignment.TARGET_ASSET
    ).first()
    resolution = domain.resolve_plan_for_asset(plan_id=plan.pk, asset=asset)

    if request.method == "POST":
        form = AssetPlanCustomizationForm(request.POST, instance=assignment, plan=plan, asset=asset)
        if form.is_valid():
            mode = form.cleaned_data.get("mode")
            if mode == AssetPlanCustomizationForm.MODE_INHERIT:
                if assignment is not None:
                    # Tornare al gruppo non cancella lo storico: si toglie solo la
                    # regola specifica, le occorrenze gia' create restano.
                    MaintenanceOccurrence.objects.filter(assignment=assignment).update(assignment=None)
                    assignment.delete()
                messages.success(request, f"«{plan.label}» torna alle impostazioni del gruppo per {asset.asset_tag}.")
            else:
                saved = form.save()
                if saved.is_excluded:
                    messages.success(request, f"{asset.asset_tag} escluso dal piano «{plan.label}».")
                else:
                    messages.success(request, f"Periodicita personalizzata per {asset.asset_tag}.")
            return redirect("assets:asset_maintenance_plans", asset_id=asset.pk)
    else:
        form = AssetPlanCustomizationForm(instance=assignment, plan=plan, asset=asset)
        if assignment is None and resolution is not None and resolution.assignment is not None:
            # Si parte dai valori ereditati: personalizzare significa modificare
            # quello che c'e' gia', non ricominciare da un form vuoto.
            inherited = resolution.assignment
            for name in ("frequency", "interval", "weekday", "week_of_month", "day_of_month", "month_of_year", "warning_days"):
                form.initial.setdefault(name, getattr(inherited, name))
            form.initial["mode"] = AssetPlanCustomizationForm.MODE_INHERIT

    return render(
        request,
        "assets/pages/asset_plan_customize.html",
        {
            **_assets_shell_context(request),
            "page_title": f"{plan.label} — {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "plan": plan,
            "resolution": resolution,
            "presets": RECURRENCE_PRESETS,
        },
    )


# ---------------------------------------------------------------------------
# Occorrenze: pianificazione, chiusura, follow-up
# ---------------------------------------------------------------------------

def _selected_occurrences(request: HttpRequest) -> list[MaintenanceOccurrence]:
    ids = [int(value) for value in request.POST.getlist("occurrence_ids") if str(value).isdigit()]
    if not ids:
        return []
    occurrences = list(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "assignment")
        .filter(pk__in=ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .order_by("due_date", "asset__asset_tag")
    )
    return occurrences


@login_required
@require_POST
def occurrence_create_workorder(request: HttpRequest) -> HttpResponse:
    """Raccoglie le manutenzioni selezionate in un unico ordine di lavoro."""
    back = request.POST.get("next") or reverse("assets:maintenance_da_fare")
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per pianificare gli ordini di lavoro.")

    occurrences = _selected_occurrences(request)
    if not occurrences:
        messages.error(request, "Seleziona almeno una manutenzione da pianificare.")
        return redirect(back)

    form = WorkOrderFromOccurrencesForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Dati dell'ordine di lavoro non validi.")
        return redirect(back)

    try:
        work_order = domain.create_workorder_from_occurrences(
            occurrences,
            user=request.user,
            title=form.cleaned_data.get("title") or "",
            assigned_to=form.cleaned_data.get("assigned_to"),
            supplier=form.cleaned_data.get("supplier"),
            due_at=form.cleaned_data.get("due_at"),
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(back)

    messages.success(
        request,
        f"Ordine di lavoro #{work_order.pk} creato con {len(occurrences)} manutenzione/i.",
    )
    return redirect("assets:wo_view", id=work_order.pk)


@login_required
@require_POST
def workorder_occurrence_add(request: HttpRequest, workorder_id: int) -> HttpResponse:
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per modificare gli ordini di lavoro.")
    work_order = get_object_or_404(WorkOrder, pk=workorder_id)
    added = domain.add_occurrences_to_workorder(work_order, _selected_occurrences(request), user=request.user)
    if added:
        messages.success(request, f"Aggiunte {added} manutenzioni all'ordine di lavoro.")
    else:
        messages.info(request, "Nessuna manutenzione aggiunta.")
    return redirect("assets:wo_view", id=work_order.pk)


@login_required
@require_POST
def workorder_occurrence_remove(request: HttpRequest, workorder_id: int, occurrence_id: int) -> HttpResponse:
    """Togliere un asset dall'OdL NON chiude e NON annulla la manutenzione."""
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per modificare gli ordini di lavoro.")
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("asset", "work_order"),
        pk=occurrence_id,
        work_order_id=workorder_id,
    )
    domain.remove_occurrence_from_workorder(
        occurrence, user=request.user, reason=_clean_string(request.POST.get("reason"))
    )
    messages.success(
        request,
        f"{occurrence.asset.asset_tag} rimosso dall'ordine di lavoro: la manutenzione resta da pianificare.",
    )
    return redirect("assets:wo_view", id=workorder_id)


@login_required
@require_POST
def workorder_distribute_day(request: HttpRequest, workorder_id: int) -> HttpResponse:
    if not can_plan_maintenance(request):
        return _deny(request, "Non hai i permessi per distribuire il lavoro sulle giornate.")
    work_order = get_object_or_404(WorkOrder, pk=workorder_id)
    form = ExecutionDayForm(request.POST)
    occurrences = _selected_occurrences(request)
    if not form.is_valid() or not occurrences:
        messages.error(request, "Indica la giornata e almeno un asset da spostare.")
        return redirect("assets:wo_view", id=workorder_id)

    day = domain.assign_occurrences_to_day(
        work_order,
        occurrences,
        execution_date=form.cleaned_data["execution_date"],
        user=request.user,
    )
    messages.success(
        request,
        f"{len(occurrences)} asset programmati per il {day.execution_date:%d/%m/%Y}.",
    )
    return redirect("assets:wo_view", id=workorder_id)


@login_required
def occurrence_complete(request: HttpRequest, occurrence_id: int) -> HttpResponse:
    """Chiusura di una singola manutenzione: ogni asset avanza per conto suo."""
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "assignment", "work_order"),
        pk=occurrence_id,
    )
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai i permessi per registrare l'esecuzione delle manutenzioni.")
    if occurrence.status != MaintenanceOccurrence.STATUS_OPEN:
        messages.info(request, "Questa manutenzione risulta gia chiusa.")
        return redirect("assets:maintenance_da_fare")

    if request.method == "POST":
        form = OccurrenceCompletionForm(request.POST, request.FILES, occurrence=occurrence)
        if form.is_valid():
            upload = form.cleaned_data.get("attachment")
            if upload:
                MaintenanceOccurrenceAttachment.objects.create(
                    occurrence=occurrence, file=upload, uploaded_by=request.user
                )
            report_received = form.cleaned_data.get("report_received_at")
            if report_received:
                occurrence.report_received_at = report_received
                occurrence.save(update_fields=["report_received_at", "updated_at"])
            try:
                following = domain.complete_occurrence(
                    occurrence,
                    completed_on=form.cleaned_data["completed_on"],
                    user=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    downtime_minutes=form.cleaned_data.get("downtime_minutes"),
                )
            except domain.OccurrenceCompletionError as exc:
                messages.error(request, str(exc))
            else:
                if following is not None:
                    messages.success(
                        request,
                        f"Manutenzione registrata. Prossima scadenza: {following.due_date:%d/%m/%Y}.",
                    )
                else:
                    messages.success(request, "Manutenzione registrata.")
                if occurrence.work_order_id:
                    return redirect("assets:wo_view", id=occurrence.work_order_id)
                return redirect("assets:maintenance_da_fare")
    else:
        form = OccurrenceCompletionForm(occurrence=occurrence)

    return render(
        request,
        "assets/pages/occurrence_complete.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Registra — {occurrence.plan.label}",
            "form": form,
            "occurrence": occurrence,
            "state": domain.occurrence_state_payload(occurrence),
        },
    )


@login_required
def occurrence_followup_create(request: HttpRequest, occurrence_id: int) -> HttpResponse:
    """Apre un follow-up per l'anomalia trovata su QUESTO asset.

    La manutenzione programmata resta eseguita e la periodicita' avanza lo stesso:
    "eseguita" e "problema risolto" non sono la stessa domanda.
    """
    occurrence = get_object_or_404(
        MaintenanceOccurrence.objects.select_related("plan", "asset", "work_order"), pk=occurrence_id
    )
    if not can_execute_maintenance(request):
        return _deny(request, "Non hai i permessi per aprire un follow-up.")

    checklist_item_id = _as_int(request.GET.get("step"), default=0) or _as_int(
        request.POST.get("checklist_item"), default=0
    )

    if request.method == "POST":
        form = FollowUpForm(request.POST)
        if form.is_valid():
            follow_up = WorkOrder.objects.create(
                asset=occurrence.asset,
                kind=WorkOrder.KIND_CORRECTIVE,
                origin=WorkOrder.ORIGIN_MANUAL,
                status=WorkOrder.STATUS_OPEN,
                title=form.cleaned_data["title"][:255],
                description=form.cleaned_data["reason"],
                assigned_to=form.cleaned_data.get("assigned_to"),
                due_at=form.cleaned_data.get("due_at"),
                follow_up_of=occurrence.work_order,
                follow_up_occurrence=occurrence,
                follow_up_checklist_item_id=checklist_item_id or None,
                follow_up_reason=form.cleaned_data["reason"],
            )
            messages.success(request, f"Follow-up #{follow_up.pk} aperto su {occurrence.asset.asset_tag}.")
            return redirect("assets:wo_view", id=follow_up.pk)
    else:
        form = FollowUpForm(
            initial={
                "title": f"Anomalia rilevata — {occurrence.asset.asset_tag}",
                "assigned_to": occurrence.work_order.assigned_to if occurrence.work_order_id else None,
            }
        )

    return render(
        request,
        "assets/pages/occurrence_followup_form.html",
        {
            **_assets_shell_context(request),
            "page_title": f"Follow-up — {occurrence.asset.asset_tag}",
            "form": form,
            "occurrence": occurrence,
            "checklist_item_id": checklist_item_id,
        },
    )


@login_required
def occurrence_attachment_download(request: HttpRequest, attachment_id: int) -> HttpResponse:
    """I rapporti stanno fuori dalla webroot: si servono solo a utente autenticato."""
    from django.http import FileResponse

    attachment = get_object_or_404(
        MaintenanceOccurrenceAttachment.objects.select_related("occurrence", "occurrence__asset"),
        pk=attachment_id,
    )
    if not attachment.file:
        raise Http404
    return FileResponse(
        attachment.file.open("rb"),
        as_attachment=True,
        filename=attachment.original_name or "allegato",
    )


# ---------------------------------------------------------------------------
# Matrice di copertura
# ---------------------------------------------------------------------------

@login_required
def maintenance_coverage(request: HttpRequest) -> HttpResponse:
    """Asset x Piani: dove il piano e' ereditato, personalizzato, escluso, in conflitto.

    Serve a vedere i buchi senza aprire una macchina alla volta.
    """
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Non hai i permessi per la matrice di copertura.")

    assets = list(
        Asset.objects.filter(status=Asset.STATUS_IN_USE)
        .select_related("asset_category")
        .order_by("reparto", "asset_tag", "name")[:400]
    )
    plans = list(MaintenanceInterventionTemplate.objects.filter(is_active=True).order_by("sort_order", "label"))
    resolutions = domain.build_plan_resolutions(
        asset_queryset=Asset.objects.filter(pk__in=[a.pk for a in assets]),
        plan_ids=[p.pk for p in plans],
    )

    legend = {
        domain.SOURCE_ASSET: ("P", "Personalizzato"),
        domain.SOURCE_GROUP: ("✓", "Ereditato dal gruppo"),
        domain.SOURCE_CATEGORY: ("✓", "Ereditato dalla categoria"),
    }

    rows = []
    for asset in assets:
        cells = []
        for plan in plans:
            resolution = resolutions.get((plan.pk, asset.pk))
            if resolution is None:
                cells.append({"symbol": "–", "title": "Non applicato", "tone": "none", "plan": plan, "asset": asset})
            elif resolution.is_conflict:
                cells.append({"symbol": "!", "title": "Conflitto fra gruppi", "tone": "conflict", "plan": plan, "asset": asset})
            elif resolution.is_excluded:
                cells.append({"symbol": "X", "title": "Escluso", "tone": "excluded", "plan": plan, "asset": asset})
            else:
                symbol, title = legend.get(resolution.source, ("✓", "Applicato"))
                cells.append(
                    {
                        "symbol": symbol,
                        "title": f"{title} — {resolution.recurrence_label}",
                        "tone": "custom" if resolution.source == domain.SOURCE_ASSET else "inherited",
                        "plan": plan,
                        "asset": asset,
                    }
                )
        rows.append({"asset": asset, "cells": cells})

    return render(
        request,
        "assets/pages/maintenance_coverage.html",
        {
            **_assets_shell_context(request),
            "page_title": "Copertura piani",
            "plans": plans,
            "rows": rows,
        },
    )


# ---------------------------------------------------------------------------
# Import dello storico
# ---------------------------------------------------------------------------

def _import_payload(report) -> str:
    """Righe importabili serializzate per il passo di conferma.

    La conferma ripassa dalla stessa ``analyze``: il payload non e' una scorciatoia
    che salta la validazione, e' solo il modo di non far ricaricare il file.
    """
    return json.dumps(
        [
            [row.asset_tag, row.plan_label, row.last_execution.isoformat(), row.notes]
            for row in report.valid_rows
        ]
    )


def _table_from_payload(raw: str) -> list[list[Any]]:
    try:
        rows = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    table: list[list[Any]] = [list(history_import.TEMPLATE_HEADERS)]
    for row in rows:
        if isinstance(row, list) and len(row) == 4:
            table.append([str(value or "") for value in row])
    return table


@login_required
def maintenance_history_import(request: HttpRequest) -> HttpResponse:
    """Carica lo storico: anteprima riga per riga, poi conferma.

    Senza la data dell'ultima esecuzione il motore considera ogni piano dovuto
    subito: il giorno del passaggio il portale aprirebbe centinaia di scadenze
    false. Questa e' la pagina che evita quel giorno.
    """
    if not can_manage_maintenance_plans(request):
        raise Http404

    form = MaintenanceHistoryImportForm()
    report = None
    payload = ""

    if request.method == "POST" and request.POST.get("confirm") == "1":
        report = history_import.analyze(_table_from_payload(request.POST.get("payload", "")))
        if report.can_apply:
            history_import.apply_report(report, user=request.user)
            avviso = (
                f" {report.kept_open} scadenze gia' aperte sono state lasciate come stavano."
                if report.kept_open
                else ""
            )
            messages.success(
                request,
                f"Storico importato: {report.created_history} esecuzioni registrate, "
                f"{report.created_next} prossime scadenze aperte.{avviso}",
            )
            return redirect("assets:maintenance_scadenze")
        messages.error(request, report.header_error or "Nessuna riga importabile: ricarica il file.")
        payload = _import_payload(report)

    elif request.method == "POST":
        form = MaintenanceHistoryImportForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                table = history_import.read_table(form.cleaned_data["file"])
            except Exception as exc:  # file corrotto o non leggibile
                messages.error(request, f"File non leggibile: {exc}")
                table = []
            if table:
                report = history_import.analyze(table)
                payload = _import_payload(report)

    return render(
        request,
        "assets/pages/maintenance_history_import.html",
        {
            **_assets_shell_context(request),
            "page_title": "Importa storico manutenzioni",
            "form": form,
            "report": report,
            "payload": payload,
            "headers": history_import.TEMPLATE_HEADERS,
        },
    )


@login_required
def maintenance_history_template(request: HttpRequest) -> HttpResponse:
    """Modello Excel da compilare."""
    if not can_manage_maintenance_plans(request):
        raise Http404

    buffer = io.BytesIO()
    history_import.build_template_workbook().save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="storico_manutenzioni_modello.xlsx"'
    return response
