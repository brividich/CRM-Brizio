"""Report e budget, template dei report.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.db.models import Avg
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from ..forms import (
    IT_DEVICE_TYPES,
    PRODUCTION_ASSET_TYPES,
)
from ..models import (
    Asset,
    AssetReportDefinition,
    AssetReportTemplate,
    WorkOrder,
)
from ..services.maintenance_kpi import build_maintenance_report_kpis

from ._helpers import (  # noqa: F401
    ASSET_DOCUMENT_ALLOWED_MIMES,
    ASSET_DOCUMENT_MAX_BYTES,
    REPORT_TEMPLATE_ALLOWED_EXTENSIONS,
    _as_int,
    _build_work_machine_maintenance_month_dataset,
    _clean_string,
    _is_assets_admin,
    _model_table_exists,
    _month_end,
    _month_label,
    _month_start_from_value,
    _planned_maintenance_status,
    _work_machine_maintenance_month_pdf_url,
)
from ._helpers_b import (  # noqa: F401
    _normalize_reports_scope,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _workorder_list_page_url,
)

REPORT_TEMPLATE_ALLOWED_MIMES = ASSET_DOCUMENT_ALLOWED_MIMES | {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
DEFAULT_REPORT_DEFINITIONS = [
    {
        "code": AssetReportTemplate.REPORT_ASSET_DETAIL,
        "label": "Scheda asset PDF",
        "description": "Report PDF del singolo asset con riepilogo, documenti e storico.",
        "sort_order": 10,
    },
    {
        "code": AssetReportTemplate.REPORT_WORK_MACHINE_MAINTENANCE,
        "label": "Manutenzioni macchine mese",
        "description": "Report mensile delle manutenzioni pianificate per le macchine di lavoro.",
        "sort_order": 20,
    },
]


def _default_asset_report_definition_objects() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            id=0,
            code=str(item["code"]),
            label=str(item["label"]),
            description=str(item["description"]),
            sort_order=int(item["sort_order"]),
            is_active=True,
        )
        for item in DEFAULT_REPORT_DEFINITIONS
    ]


def _ensure_default_asset_report_definitions() -> list[AssetReportDefinition | SimpleNamespace]:
    if not _model_table_exists(AssetReportDefinition):
        return _default_asset_report_definition_objects()
    try:
        existing = {row.code: row for row in AssetReportDefinition.objects.all()}
        for item in DEFAULT_REPORT_DEFINITIONS:
            code = str(item["code"])
            row = existing.get(code)
            if row is None:
                row = AssetReportDefinition.objects.create(
                    code=code,
                    label=str(item["label"]),
                    description=str(item["description"]),
                    sort_order=int(item["sort_order"]),
                    is_active=True,
                )
                existing[code] = row
                continue
            changed = False
            if not row.label:
                row.label = str(item["label"])
                changed = True
            if not row.description:
                row.description = str(item["description"])
                changed = True
            if row.sort_order != int(item["sort_order"]):
                row.sort_order = int(item["sort_order"])
                changed = True
            if changed:
                row.save(update_fields=["label", "description", "sort_order", "updated_at"])
        return list(AssetReportDefinition.objects.order_by("sort_order", "label", "id"))
    except DatabaseError:
        return _default_asset_report_definition_objects()


def _asset_report_definition_map() -> dict[str, AssetReportDefinition | SimpleNamespace]:
    return {row.code: row for row in _ensure_default_asset_report_definitions()}


def _report_templates_grouped() -> list[dict[str, object]]:
    grouped: list[dict[str, object]] = []
    templates_table_exists = _model_table_exists(AssetReportTemplate)
    for definition in _ensure_default_asset_report_definitions():
        report_code = definition.code
        if not templates_table_exists:
            rows = []
        else:
            try:
                rows = list(
                    AssetReportTemplate.objects.filter(report_code=report_code)
                    .select_related("uploaded_by")
                    .order_by("-is_active", "-updated_at", "-id")
                )
            except DatabaseError:
                rows = []
        grouped.append(
            {
                "code": report_code,
                "label": definition.label,
                "description": definition.description,
                "definition": definition,
                "active": next((row for row in rows if row.is_active), None),
                "rows": rows,
            }
        )
    return grouped


def _reports_scope_context(scope: str) -> dict[str, object]:
    if scope == "it":
        return {
            "scope": "it",
            "title": "Report dispositivi IT",
            "subtitle": "KPI e interventi filtrati su PC, server, rete, fonia, TVCC e dispositivi IT.",
            "asset_types": IT_DEVICE_TYPES,
            "maintenance_month_enabled": False,
            "empty_month_message": "Il piano mese e il PDF mensile sono disponibili nei report asset produzione.",
        }
    return {
        "scope": "production",
        "title": "Report asset produzione",
        "subtitle": "KPI e interventi filtrati su CNC, macchine utensili e carroponti.",
        "asset_types": PRODUCTION_ASSET_TYPES,
        "maintenance_month_enabled": True,
        "empty_month_message": "",
    }


@login_required
def reports_dashboard(request: HttpRequest) -> HttpResponse:
    if "scope" not in request.GET:
        query = request.GET.copy()
        query["scope"] = "production"
        return redirect(f"{reverse('assets:reports')}?{query.urlencode()}")

    now = timezone.now()
    today = timezone.localdate()
    period_start = now - timedelta(days=90)
    reports_scope = _normalize_reports_scope(request.GET.get("scope"))
    reports_context = _reports_scope_context(reports_scope)
    report_asset_types = list(reports_context["asset_types"])
    scoped_asset_qs = Asset.objects.filter(asset_type__in=report_asset_types).select_related("asset_category")
    # Budget e costi dagli OdL; lo stato delle manutenzioni dalle occorrenze,
    # come Scadenzario e KPI (il vecchio motore a regole non entra piu' nel conto).
    maintenance_report_kpis = build_maintenance_report_kpis(
        asset_queryset=scoped_asset_qs,
        schedule_rows=[],
        today=today,
    )
    planned = _planned_maintenance_status(scoped_asset_qs, today)
    pm_kpi = planned["kpi"]
    budget_kpi = maintenance_report_kpis["budget"]
    budget_rows = []
    for row in budget_kpi["rows"][:8]:
        row = dict(row)
        category = row.get("category")
        category_id = getattr(category, "id", 0)
        row["workorders_url"] = (
            _workorder_list_page_url(status=WorkOrder.STATUS_DONE, category=category_id)
            if category_id
            else ""
        )
        budget_rows.append(row)

    open_workorders = WorkOrder.objects.select_related("asset", "supplier").filter(
        status=WorkOrder.STATUS_OPEN,
        asset__asset_type__in=report_asset_types,
    )
    late_open_workorders = open_workorders.filter(opened_at__lt=now - timedelta(days=30)).order_by("opened_at")
    open_workorder_rows: list[dict[str, object]] = []
    for workorder in open_workorders.order_by("opened_at", "id")[:12]:
        opened_at = workorder.opened_at
        opened_on = timezone.localtime(opened_at).date() if timezone.is_aware(opened_at) else opened_at.date()
        open_days = max((today - opened_on).days, 0)
        open_workorder_rows.append(
            {
                "workorder": workorder,
                "open_days": open_days,
                "is_late": open_days > 30,
            }
        )
    recent_done_workorders = (
        WorkOrder.objects.select_related(
            "asset",
            "asset__asset_category",
            "supplier",
            "assistance_contract",
        )
        .filter(status=WorkOrder.STATUS_DONE, closed_at__gte=period_start)
        .filter(asset__asset_type__in=report_asset_types)
        .order_by("-closed_at", "-id")
    )
    if reports_context["maintenance_month_enabled"]:
        maintenance_month_dataset = _build_work_machine_maintenance_month_dataset(
            month_value=request.GET.get("month"),
            today=today,
        )
    else:
        month_start = _month_start_from_value(request.GET.get("month"), today=today)
        month_end = _month_end(month_start)
        maintenance_month_dataset = {
            "rows": [],
            "total_count": 0,
            "overdue_count": 0,
            "warning_count": 0,
            "ok_count": 0,
            "month_code": month_start.strftime("%Y-%m"),
            "month_label": _month_label(month_start),
            "period_label": f'{month_start.strftime("%d-%m-%Y")} - {month_end.strftime("%d-%m-%Y")}',
        }
    done_rows = list(recent_done_workorders)
    total_cost = sum((workorder.resolved_total_cost_eur or Decimal("0")) for workorder in done_rows)
    duration_values = [
        workorder.intervention_duration_minutes
        for workorder in done_rows
        if workorder.intervention_duration_minutes is not None
    ]
    avg_duration_minutes = round(sum(duration_values) / len(duration_values), 1) if duration_values else None
    avg_downtime_minutes = (
        WorkOrder.objects.filter(
            status=WorkOrder.STATUS_DONE,
            closed_at__gte=period_start,
            asset__asset_type__in=report_asset_types,
        )
        .aggregate(value=Avg("downtime_minutes"))
        .get("value")
    )
    covered_count = sum(1 for workorder in done_rows if workorder.covered_by_contract)
    uncovered_count = len(done_rows) - covered_count

    def _summary_rows(key_builder, label_builder):
        grouped: dict[tuple, dict[str, object]] = {}
        for workorder in done_rows:
            key = key_builder(workorder)
            bucket = grouped.setdefault(
                key,
                {
                    "label": label_builder(workorder),
                    "count": 0,
                    "cost": Decimal("0"),
                    "covered_count": 0,
                },
            )
            bucket["count"] += 1
            bucket["cost"] += workorder.resolved_total_cost_eur or Decimal("0")
            if workorder.covered_by_contract:
                bucket["covered_count"] += 1
        rows = list(grouped.values())
        rows.sort(key=lambda row: (-int(row["cost"] > 0), -row["cost"], -row["count"], str(row["label"]).casefold()))
        return rows

    asset_summary_rows = _summary_rows(
        lambda workorder: (workorder.asset_id,),
        lambda workorder: f"{workorder.asset.asset_tag} - {workorder.asset.name}",
    )[:8]
    category_summary_rows = _summary_rows(
        lambda workorder: (getattr(workorder.asset, "asset_category_id", 0),),
        lambda workorder: (
            getattr(getattr(workorder.asset, "asset_category", None), "label", "")
            or "Senza categoria"
        ),
    )[:8]
    supplier_summary_rows = _summary_rows(
        lambda workorder: (workorder.supplier_id or 0,),
        lambda workorder: str(workorder.supplier) if workorder.supplier_id else "Fornitore non indicato",
    )[:8]

    overdue_rows = planned["overdue"]
    warning_rows = planned["warning"]
    upcoming_rows = planned["ok"]
    missing_rows = planned["missing"]
    critical_count = len(overdue_rows) + len(warning_rows) + len(missing_rows)
    critical_rows: list[dict[str, object]] = []
    for row in overdue_rows + warning_rows + missing_rows:
        asset = row["asset"]
        occurrence = row["occurrence"]
        critical_rows.append(
            {
                "asset": asset,
                "asset_detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                "effective_intervention_template": occurrence.plan if occurrence else None,
                "schedule_label": row["state"]["label"],
                "schedule_badge_class": {"overdue": "danger", "warning": "warning"}.get(row["state"]["status"], "muted"),
                "due_date": row["state"]["date"],
                "primary_action": (
                    {"label": "Registra", "url": reverse("assets:occurrence_complete", args=[occurrence.id])}
                    if occurrence
                    else {"label": "Applica un piano", "url": reverse("assets:asset_maintenance_plans", args=[asset.id])}
                ),
            }
        )

    return render(
        request,
        "assets/pages/reports_dashboard.html",
        {
            "page_title": reports_context["title"],
            "reports_scope": reports_context["scope"],
            "reports_page_title": reports_context["title"],
            "reports_page_subtitle": reports_context["subtitle"],
            "maintenance_month_enabled": reports_context["maintenance_month_enabled"],
            "maintenance_month_empty_message": reports_context["empty_month_message"],
            "open_workorders": open_workorders.order_by("opened_at", "id")[:8],
            "open_workorder_rows": open_workorder_rows,
            "late_open_workorders": late_open_workorders[:8],
            "recent_done_workorders": done_rows[:8],
            "asset_summary_rows": asset_summary_rows,
            "category_summary_rows": category_summary_rows,
            "supplier_summary_rows": supplier_summary_rows,
            "critical_rows": critical_rows[:12],
            "overdue_rows": overdue_rows[:8],
            "warning_rows": warning_rows[:8],
            "upcoming_rows": upcoming_rows[:8],
            "open_count": open_workorders.count(),
            "late_count": late_open_workorders.count(),
            "done_recent_count": len(done_rows),
            "total_cost": total_cost,
            "avg_duration_minutes": avg_duration_minutes,
            "avg_downtime_minutes": round(avg_downtime_minutes, 1) if avg_downtime_minutes is not None else None,
            "covered_count": covered_count,
            "uncovered_count": uncovered_count,
            "critical_count": critical_count,
            "overdue_count": len(overdue_rows),
            "warning_count": len(warning_rows),
            "upcoming_count": len(upcoming_rows),
            "missing_count": len(missing_rows),
            "pm_kpi": pm_kpi,
            "budget_kpi": budget_kpi,
            "budget_rows": budget_rows,
            "open_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_OPEN),
            "late_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_OPEN, open_age=30),
            "done_workorders_url": _workorder_list_page_url(status=WorkOrder.STATUS_DONE),
            "maintenance_schedule_due_url": f"{reverse('assets:maintenance_scadenze')}?window=overdue",
            "maintenance_schedule_missing_url": reverse("assets:maintenance_coverage"),
            "maintenance_month_rows": maintenance_month_dataset["rows"][:10],
            "maintenance_month_count": maintenance_month_dataset["total_count"],
            "maintenance_month_overdue_count": maintenance_month_dataset["overdue_count"],
            "maintenance_month_warning_count": maintenance_month_dataset["warning_count"],
            "maintenance_month_ok_count": maintenance_month_dataset["ok_count"],
            "maintenance_month_label": maintenance_month_dataset["month_label"],
            "maintenance_month_period_label": maintenance_month_dataset["period_label"],
            "maintenance_month_code": maintenance_month_dataset["month_code"],
            "maintenance_month_pdf_base_url": reverse("assets:work_machine_maintenance_month_pdf"),
            "maintenance_month_pdf_url": _work_machine_maintenance_month_pdf_url(
                month_code=str(maintenance_month_dataset["month_code"])
            ),
            "maintenance_schedule_url": reverse("assets:maintenance_schedule"),
            "assistance_contracts_url": reverse("assets:assistance_contract_list"),
            "report_templates_manage_url": (
                reverse("assets:report_template_admin")
                if _is_assets_admin(request)
                else ""
            ),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )


@login_required
def report_template_admin(request: HttpRequest) -> HttpResponse:
    if not _is_assets_admin(request):
        messages.error(request, "Solo admin puo gestire i template report.")
        return redirect("assets:reports")

    report_tables_ready = _model_table_exists(AssetReportDefinition) and _model_table_exists(AssetReportTemplate)
    _ensure_default_asset_report_definitions()

    if request.method == "POST":
        if not report_tables_ready:
            messages.error(request, "Le tabelle dei template report non sono ancora disponibili. Esegui prima le migrazioni.")
            return redirect("assets:report_template_admin")
        action = _clean_string(request.POST.get("action"))
        redirect_url = reverse("assets:report_template_admin")
        definition_map = _asset_report_definition_map()

        try:
            if action == "create_report_definition":
                code = slugify(request.POST.get("code", ""))[:80]
                label = _clean_string(request.POST.get("label"))[:120]
                description = _clean_string(request.POST.get("description"))[:255]
                sort_order = _as_int(request.POST.get("sort_order"), default=100)
                if not code or not label:
                    messages.error(request, "Inserisci codice e nome del report.")
                    return redirect(redirect_url)
                if AssetReportDefinition.objects.filter(code=code).exists():
                    messages.error(request, "Esiste gia un report con questo codice.")
                    return redirect(redirect_url)
                AssetReportDefinition.objects.create(
                    code=code,
                    label=label,
                    description=description,
                    sort_order=sort_order,
                    is_active=True,
                )
                messages.success(request, f'Report "{label}" creato.')
                return redirect(redirect_url)

            if action == "upload_report_template":
                report_code = _clean_string(request.POST.get("report_code"))
                name = _clean_string(request.POST.get("name"))[:120]
                version = _clean_string(request.POST.get("version"))[:40]
                description = _clean_string(request.POST.get("description"))[:255]
                uploaded_file = request.FILES.get("template_file")

                if report_code not in definition_map:
                    messages.error(request, "Tipo report non valido.")
                    return redirect(redirect_url)
                if not name:
                    messages.error(request, "Inserisci il nome del template.")
                    return redirect(redirect_url)
                if not uploaded_file:
                    messages.error(request, "Seleziona un file template.")
                    return redirect(redirect_url)

                suffix = Path(uploaded_file.name or "").suffix.lower()
                if suffix not in REPORT_TEMPLATE_ALLOWED_EXTENSIONS:
                    messages.error(request, "Formato template non supportato.")
                    return redirect(redirect_url)
                try:
                    validate_extension_and_mime(
                        uploaded_file,
                        allowed_extensions=REPORT_TEMPLATE_ALLOWED_EXTENSIONS,
                        allowed_mimes=REPORT_TEMPLATE_ALLOWED_MIMES,
                        max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                        label="Template",
                    )
                except UploadMimeValidationError as exc:
                    messages.error(request, str(exc))
                    return redirect(redirect_url)
                finally:
                    uploaded_file.seek(0)

                should_activate = bool(request.POST.get("is_active")) or not AssetReportTemplate.objects.filter(
                    report_code=report_code
                ).exists()
                AssetReportTemplate.objects.create(
                    report_code=report_code,
                    name=name,
                    version=version,
                    description=description,
                    file=uploaded_file,
                    original_name=(uploaded_file.name or "")[:255],
                    is_active=should_activate,
                    uploaded_by=request.user,
                )
                messages.success(request, f'Template report "{name}" caricato.')
                return redirect(redirect_url)

            if action == "activate_report_template":
                template_id = _as_int(request.POST.get("template_id"), default=0)
                template = AssetReportTemplate.objects.filter(pk=template_id).first()
                if not template:
                    messages.error(request, "Template report non trovato.")
                    return redirect(redirect_url)
                template.is_active = True
                template.save(update_fields=["is_active", "updated_at"])
                report_label = getattr(definition_map.get(template.report_code), "label", template.report_code)
                messages.success(request, f"Template attivo aggiornato per {report_label.lower()}.")
                return redirect(redirect_url)

            if action == "delete_report_template":
                template_id = _as_int(request.POST.get("template_id"), default=0)
                template = AssetReportTemplate.objects.filter(pk=template_id).first()
                if not template:
                    messages.error(request, "Template report non trovato.")
                    return redirect(redirect_url)
                report_label = getattr(definition_map.get(template.report_code), "label", template.report_code)
                template_name = template.name
                template.delete()
                messages.success(request, f'Template "{template_name}" eliminato ({report_label}).')
                return redirect(redirect_url)

            if action == "delete_report_definition":
                report_id = _as_int(request.POST.get("report_definition_id"), default=0)
                definition = AssetReportDefinition.objects.filter(pk=report_id).first()
                if not definition:
                    messages.error(request, "Report non trovato.")
                    return redirect(redirect_url)
                if definition.code in {
                    AssetReportTemplate.REPORT_ASSET_DETAIL,
                    AssetReportTemplate.REPORT_WORK_MACHINE_MAINTENANCE,
                }:
                    messages.error(request, "I report base non possono essere eliminati.")
                    return redirect(redirect_url)
                AssetReportTemplate.objects.filter(report_code=definition.code).delete()
                report_label = definition.label
                definition.delete()
                messages.success(request, f'Report "{report_label}" eliminato.')
                return redirect(redirect_url)
        except DatabaseError:
            messages.error(request, "Le tabelle dei template report non sono ancora disponibili. Esegui prima le migrazioni.")
            return redirect(redirect_url)

    return render(
        request,
        "assets/pages/report_template_admin.html",
        {
            "page_title": "Gestione template report",
            "report_template_groups": _report_templates_grouped(),
            "report_template_choices": [
                (row.code, row.label) for row in _ensure_default_asset_report_definitions() if row.is_active
            ],
            "report_definitions": _ensure_default_asset_report_definitions(),
            "report_template_extensions": ", ".join(sorted(REPORT_TEMPLATE_ALLOWED_EXTENSIONS)),
            **_assets_shell_context(request, rows=_as_int(request.GET.get("rows"), default=25)),
        },
    )
