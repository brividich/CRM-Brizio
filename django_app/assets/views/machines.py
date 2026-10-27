"""Macchine di lavoro: elenco, cruscotto officina, form, contatori, report mensile.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from core.audit import log_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.pdf import (
    PdfTheme,
    draw_canvas_footer,
    draw_canvas_header,
)
from ..forms import (
    WorkMachineAssetForm,
    PRODUCTION_ASSET_TYPES,
)
from ..models import (
    Asset,
    AssetDocument,
    AssetMeter,
    AssetMeterHistory,
    WorkOrder,
)
from ..maintenance import (
    get_workorder_overdue_days,
)
from ..services import storico_asset
from ..models import AssetFieldHistory

from ._helpers import (  # noqa: F401
    ASSET_DOCUMENT_UPLOAD_FIELDS,
    _apply_asset_document_changes,
    _as_int,
    _asset_document_folder_specs,
    _assignment_form_kwargs,
    _build_work_machine_maintenance_month_dataset,
    _clean_string,
    _coalesce_str,
    _ensure_asset_plant_layout_marker,
    _planned_maintenance_status,
    _truncate_pdf_text,
    _validate_asset_document_uploads,
    _work_machine_maintenance_month_pdf_url,
)
from ._helpers_b import (  # noqa: F401
    _build_asset_list_suggestions,
)
from ._helpers_c import (  # noqa: F401
    _assets_shell_context,
    _validate_asset_image,
)

def _draw_work_machine_maintenance_month_report_header(
    pdf: canvas.Canvas,
    *,
    theme: PdfTheme,
    page_width: float,
    page_height: float,
    dataset: dict[str, object],
    generated_at: datetime,
) -> float:
    margin_x = 14 * mm
    reparto_filter = _clean_string(str(dataset.get("reparto_filter") or ""))
    subtitle = f'Periodo: {dataset["month_label"]} ({dataset["period_label"]})'
    if reparto_filter:
        subtitle = f"{subtitle} | Reparto: {reparto_filter}"
    content_y = draw_canvas_header(
        pdf,
        theme=theme,
        page_width=page_width,
        page_height=page_height,
        left_margin=margin_x,
        right_margin=margin_x,
        title="Report manutenzioni macchine",
        subtitle=subtitle,
        right_subtitle=f'Generato il {generated_at.strftime("%d-%m-%Y %H:%M")}',
    )

    cards_top = content_y
    cards_height = 16 * mm
    cards_gap = 4 * mm
    cards_width = (page_width - (2 * margin_x) - (3 * cards_gap)) / 4
    cards = [
        ("Totale mese", int(dataset.get("total_count") or 0), theme.primary),
        ("Scadute", int(dataset.get("overdue_count") or 0), "#dc2626"),
        ("In soglia", int(dataset.get("warning_count") or 0), "#d97706"),
        ("Pianificate", int(dataset.get("ok_count") or 0), "#15803d"),
    ]
    for idx, (label, value, accent) in enumerate(cards):
        left = margin_x + idx * (cards_width + cards_gap)
        pdf.setFillColor(HexColor("#ffffff"))
        pdf.setStrokeColor(theme.c_border())
        pdf.roundRect(left, cards_top - cards_height, cards_width, cards_height, 6, fill=1, stroke=1)
        pdf.setFillColor(HexColor(accent))
        pdf.rect(left, cards_top - 4, cards_width, 4, fill=1, stroke=0)
        pdf.setFillColor(theme.c_muted())
        pdf.setFont("Helvetica", 8)
        pdf.drawString(left + 10, cards_top - 15, label.upper())
        pdf.setFillColor(theme.c_text())
        pdf.setFont("Helvetica-Bold", 19)
        pdf.drawString(left + 10, cards_top - 31, str(value))

    return cards_top - cards_height - (8 * mm)


def _draw_work_machine_maintenance_month_report_footer(
    pdf: canvas.Canvas,
    *,
    theme: PdfTheme,
    page_width: float,
    margin_x: float,
    bottom_limit: float,
    page_number: int,
) -> None:
    draw_canvas_footer(
        pdf,
        theme=theme,
        page_width=page_width,
        left_margin=margin_x,
        right_margin=margin_x,
        baseline_y=bottom_limit - 10,
        page_number=page_number,
    )


def _draw_work_machine_maintenance_month_table_header(
    pdf: canvas.Canvas,
    *,
    theme: PdfTheme,
    start_x: float,
    table_y: float,
    column_defs: list[tuple[str, float]],
) -> float:
    total_width = sum(width for _, width in column_defs)
    row_height = 10 * mm
    pdf.setFillColor(theme.c_primary())
    pdf.setStrokeColor(theme.c_primary())
    pdf.rect(start_x, table_y - row_height, total_width, row_height, fill=1, stroke=1)
    pdf.setFillColor(HexColor("#ffffff"))
    pdf.setFont("Helvetica-Bold", 8)

    current_x = start_x
    for label, width in column_defs:
        pdf.drawString(current_x + 6, table_y - 18, label.upper())
        current_x += width
    return table_y - row_height


def _draw_work_machine_maintenance_month_pdf(
    pdf: canvas.Canvas,
    *,
    theme: PdfTheme,
    dataset: dict[str, object],
    generated_at: datetime,
) -> None:
    page_width, page_height = landscape(A4)
    margin_x = 14 * mm
    bottom_limit = 16 * mm
    row_height = 9 * mm
    column_defs = [
        ("Data", 24 * mm),
        ("Tag", 28 * mm),
        ("Macchina", 82 * mm),
        ("Reparto", 32 * mm),
        ("Stato", 42 * mm),
        ("Manutenzione", 40 * mm),
    ]
    total_width = sum(width for _, width in column_defs)
    status_colors = {
        "overdue": HexColor("#b91c1c"),
        "warning": HexColor("#a16207"),
        "ok": HexColor("#15803d"),
    }

    page_number = 1
    table_y = _draw_work_machine_maintenance_month_report_header(
        pdf,
        theme=theme,
        page_width=page_width,
        page_height=page_height,
        dataset=dataset,
        generated_at=generated_at,
    )
    table_y = _draw_work_machine_maintenance_month_table_header(
        pdf,
        theme=theme,
        start_x=margin_x,
        table_y=table_y,
        column_defs=column_defs,
    )
    current_y = table_y

    rows = list(dataset.get("rows") or [])
    if not rows:
        pdf.setFillColor(theme.c_muted())
        pdf.setFont("Helvetica", 11)
        pdf.drawString(
            margin_x,
            current_y - 22,
            "Nessuna macchina con manutenzione pianificata nel periodo selezionato.",
        )
        _draw_work_machine_maintenance_month_report_footer(
            pdf,
            theme=theme,
            page_width=page_width,
            margin_x=margin_x,
            bottom_limit=bottom_limit,
            page_number=page_number,
        )
        return

    for index, row in enumerate(rows):
        if current_y - row_height < bottom_limit:
            _draw_work_machine_maintenance_month_report_footer(
                pdf,
                theme=theme,
                page_width=page_width,
                margin_x=margin_x,
                bottom_limit=bottom_limit,
                page_number=page_number,
            )
            pdf.showPage()
            page_number += 1
            table_y = _draw_work_machine_maintenance_month_report_header(
                pdf,
                theme=theme,
                page_width=page_width,
                page_height=page_height,
                dataset=dataset,
                generated_at=generated_at,
            )
            table_y = _draw_work_machine_maintenance_month_table_header(
                pdf,
                theme=theme,
                start_x=margin_x,
                table_y=table_y,
                column_defs=column_defs,
            )
            current_y = table_y

        asset = row["asset"]
        occurrence = row["occurrence"]
        state = row["state"]
        pdf.setFillColor(HexColor("#ffffff" if index % 2 == 0 else "#fbfdff"))
        pdf.setStrokeColor(theme.c_border())
        pdf.rect(margin_x, current_y - row_height, total_width, row_height, fill=1, stroke=1)

        values = [
            occurrence.due_date.strftime("%d-%m-%Y"),
            _coalesce_str(asset.asset_tag, "-"),
            _coalesce_str(asset.name, "-"),
            _coalesce_str(asset.reparto, "-"),
            _coalesce_str(str(state.get("label") or ""), "-"),
            _coalesce_str(occurrence.plan.label, "-"),
        ]
        font_name = "Helvetica"
        font_size = 8.5
        text_y = current_y - 17
        current_x = margin_x
        for value_idx, value in enumerate(values):
            width = column_defs[value_idx][1]
            pdf.setFillColor(theme.c_text())
            if value_idx == 4:
                pdf.setFillColor(status_colors.get(str(state.get("status") or ""), theme.c_text()))
            pdf.setFont(font_name, font_size)
            pdf.drawString(
                current_x + 6,
                text_y,
                _truncate_pdf_text(
                    pdf,
                    value,
                    font_name=font_name,
                    font_size=font_size,
                    max_width=width - 12,
                ),
            )
            current_x += width

        current_y -= row_height

    _draw_work_machine_maintenance_month_report_footer(
        pdf,
        theme=theme,
        page_width=page_width,
        margin_x=margin_x,
        bottom_limit=bottom_limit,
        page_number=page_number,
    )


def _build_uploaded_documents_context(asset: Asset | None) -> dict[str, list[AssetDocument]]:
    grouped: dict[str, list[AssetDocument]] = {
        spec["code"]: [] for spec in _asset_document_folder_specs(asset)
    }
    if not asset or not asset.pk:
        return grouped
    for document in asset.documents.all():
        grouped.setdefault(document.category, []).append(document)
    return grouped


@login_required
def work_machine_list(request: HttpRequest) -> HttpResponse:
    # La pagina "Asset produzione" e' confluita nell'inventario unico
    # (asset_list?group=production): stessa lista, colonne, ricerca rapida e
    # scheda. Manteniamo la rotta come redirect permanente per link, preferiti
    # e voci di navigazione esistenti, inoltrando i filtri compatibili.
    params: list[tuple[str, str]] = [("group", "production")]
    for key in ("q", "reparto", "cnc_only", "five_axes_only", "tcr_only"):
        value = _clean_string(request.GET.get(key))
        if value:
            params.append((key, value))
    asset_type_filter = _clean_string(request.GET.get("asset_type"))
    if asset_type_filter in PRODUCTION_ASSET_TYPES:
        params.append(("asset_type", asset_type_filter))
    return redirect(f"{reverse('assets:asset_list')}?{urlencode(params)}")


@login_required
def work_machine_dashboard(request: HttpRequest) -> HttpResponse:
    now = timezone.now()
    today = timezone.localdate()
    reparto_filter = _clean_string(request.GET.get("reparto"))
    report_month_value = _clean_string(request.GET.get("month"))
    maintenance_month_dataset = _build_work_machine_maintenance_month_dataset(
        month_value=report_month_value,
        reparto_filter=reparto_filter,
        today=today,
    )

    from ..services.visibilita import filtra as filtra_visibili

    machine_base_qs = filtra_visibili(
        request,
        Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES).select_related("work_machine").prefetch_related("documents"),
    )
    if reparto_filter:
        machine_base_qs = machine_base_qs.filter(reparto=reparto_filter)

    workorders_base = WorkOrder.objects.select_related("asset").filter(asset__asset_type__in=PRODUCTION_ASSET_TYPES)
    if reparto_filter:
        workorders_base = workorders_base.filter(asset__reparto=reparto_filter)

    open_workorders = workorders_base.filter(status=WorkOrder.STATUS_OPEN).order_by("opened_at", "id")
    wo_overdue_days = get_workorder_overdue_days()
    overdue_workorders = open_workorders.filter(opened_at__lt=now - timedelta(days=wo_overdue_days))
    recent_done_workorders = workorders_base.filter(
        status=WorkOrder.STATUS_DONE,
        closed_at__gte=now - timedelta(days=60),
    ).order_by("-closed_at", "-id")

    machine_rows = list(machine_base_qs.order_by("reparto", "name", "asset_tag"))
    manuals_count = 0
    specs_count = 0
    overdue_maintenance: list[dict[str, object]] = []
    warning_maintenance: list[dict[str, object]] = []
    missing_maintenance: list[dict[str, object]] = []
    for asset in machine_rows:
        extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
        raw_docs = extra.get("documents")
        categories = set()
        if isinstance(raw_docs, list):
            for row in raw_docs:
                if not isinstance(row, dict):
                    continue
                categories.add(_clean_string(str(row.get("category") or "SPECIFICHE")).upper())
        for uploaded in asset.documents.all():
            categories.add(uploaded.category)
        if "MANUALI" in categories:
            manuals_count += 1
        if "SPECIFICHE" in categories:
            specs_count += 1

    # Stato manutentivo dalle scadenze pianificate, non piu' dalla data sulla macchina.
    planned = _planned_maintenance_status(machine_rows, today)
    overdue_maintenance = planned["overdue"]
    warning_maintenance = planned["warning"]
    missing_maintenance = planned["missing"]

    total_machines = len(machine_rows)
    reparto_totals = list(
        Asset.objects.filter(asset_type__in=PRODUCTION_ASSET_TYPES)
        .exclude(reparto="")
        .values("reparto")
        .annotate(total=Count("id"))
        .order_by("reparto")
    )

    _wmd_overdue = len(overdue_maintenance)
    _wmd_missing = len(missing_maintenance)
    _wmd_da_fare = _wmd_overdue + _wmd_missing
    _wmd_manutentati = max(0, total_machines - _wmd_da_fare)
    wmd_maint_kpis = {
        "coinvolti": total_machines,
        "manutentati": _wmd_manutentati,
        "da_manutentare": _wmd_da_fare,
        "percent_done": int(_wmd_manutentati / total_machines * 100) if total_machines else 0,
    }

    # P3.5 — Contatori macchine: precarica AssetMeter per le macchine con almeno un contatore
    machine_ids = [asset.id for asset in machine_rows]
    meters_by_asset_id: dict[int, list] = {}
    if machine_ids:
        for meter in AssetMeter.objects.filter(asset_id__in=machine_ids).select_related("updated_by").order_by("meter_type"):
            meters_by_asset_id.setdefault(meter.asset_id, []).append(meter)
    # Solo macchine con almeno un contatore configurato
    machines_with_meters = [
        asset for asset in machine_rows
        if asset.id in meters_by_asset_id
    ]

    return render(
        request,
        "assets/pages/work_machine_dashboard.html",
        {
            "page_title": "Dashboard officina",
            "reparto_filter": reparto_filter,
            "reparto_totals": reparto_totals,
            "total_machines": total_machines,
            "in_use_machines": sum(1 for asset in machine_rows if asset.status == Asset.STATUS_IN_USE),
            "in_repair_machines": sum(1 for asset in machine_rows if asset.status == Asset.STATUS_IN_REPAIR),
            "manuals_count": manuals_count,
            "specs_count": specs_count,
            "open_workorders": open_workorders[:10],
            "open_count": open_workorders.count(),
            "overdue_workorders": overdue_workorders[:10],
            "overdue_count": overdue_workorders.count(),
            "wo_overdue_days": wo_overdue_days,
            "overdue_workorder_ids": set(overdue_workorders.values_list("id", flat=True)),
            "recent_done_workorders": recent_done_workorders[:10],
            "recent_done_count": recent_done_workorders.count(),
            "overdue_maintenance": overdue_maintenance[:12],
            "overdue_maintenance_count": len(overdue_maintenance),
            "warning_maintenance": warning_maintenance[:12],
            "warning_maintenance_count": len(warning_maintenance),
            "missing_maintenance": missing_maintenance[:12],
            "missing_maintenance_count": len(missing_maintenance),
            "due_count": len(overdue_maintenance) + len(warning_maintenance),
            "maint_kpis": wmd_maint_kpis,
            "maintenance_month_count": maintenance_month_dataset["total_count"],
            "maintenance_month_label": maintenance_month_dataset["month_label"],
            "maintenance_month_code": maintenance_month_dataset["month_code"],
            "maintenance_month_pdf_url": _work_machine_maintenance_month_pdf_url(
                month_code=str(maintenance_month_dataset["month_code"]),
                reparto_filter=reparto_filter,
            ),
            "today": today,
            "machines_with_meters": machines_with_meters,
            "meters_by_asset_id": meters_by_asset_id,
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


def _work_machine_image_errors(request: HttpRequest) -> list[str]:
    """Targhetta e foto macchina finiscono in MEDIA: solo immagini vere (no SVG/HTML)."""
    errors = []
    for field_name, label in (("foto_targhetta", "Foto targhetta"), ("photo", "Foto macchina")):
        upload = request.FILES.get(field_name)
        if upload is None:
            continue
        error = _validate_asset_image(upload)
        if error:
            errors.append(f"{label}: {error}")
    return errors


@login_required
def work_machine_create(request: HttpRequest) -> HttpResponse:
    list_suggestions = _build_asset_list_suggestions()
    assignment_kwargs = _assignment_form_kwargs()
    if request.method == "POST":
        uploads, upload_errors = _validate_asset_document_uploads(request)
        upload_errors = list(upload_errors) + _work_machine_image_errors(request)
        form = WorkMachineAssetForm(request.POST, list_suggestions=list_suggestions, **assignment_kwargs)
        if form.is_valid() and not upload_errors:
            with storico_asset.traccia(fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Nuova macchina di lavoro") as storico:
                asset = form.save()
                storico.aggiungi(asset.pk)
            if "foto_targhetta" in request.FILES:
                asset.foto_targhetta = request.FILES["foto_targhetta"]
                asset.save(update_fields=["foto_targhetta"])
            if form.cleaned_data.get("include_in_plant_layout"):
                marker_warning = _ensure_asset_plant_layout_marker(asset)
                if marker_warning:
                    messages.warning(request, marker_warning)
            _apply_asset_document_changes(
                asset,
                uploads=uploads,
                remove_ids=set(),
                actor=request.user,
            )
            messages.success(request, "Macchina di lavoro creata correttamente.")
            return redirect("assets:asset_view", id=asset.id)
        for error in upload_errors:
            form.add_error(None, error)
    else:
        form = WorkMachineAssetForm(
            initial={"status": Asset.STATUS_IN_USE},
            list_suggestions=list_suggestions,
            **assignment_kwargs,
        )

    return render(
        request,
        "assets/pages/work_machine_form.html",
        {
            "page_title": "Nuova macchina di lavoro",
            "form": form,
            "is_edit": False,
            "list_suggestions": list_suggestions,
            "assignment_department_choices": assignment_kwargs["assignment_department_choices"],
            "assignment_employee_details": assignment_kwargs["assignment_employee_details"],
            "asset_field_names": form.asset_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "machine_field_names": form.machine_field_names,
            "assignment_field_names": form.assignment_field_names,
            "verification_field_names": form.verification_field_names,
            "document_field_map": form.document_field_map,
            "uploaded_documents_by_category": _build_uploaded_documents_context(None),
            "document_upload_field_map": ASSET_DOCUMENT_UPLOAD_FIELDS,
            "asset_label_designer_url": reverse("assets:asset_label_designer") + f"?scope=asset_type&asset_type={Asset.TYPE_WORK_MACHINE}",
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def work_machine_edit(request: HttpRequest, id: int | None = None) -> HttpResponse:
    if id is None:
        return redirect("assets:work_machine_list")
    asset = get_object_or_404(
        Asset.objects.select_related("work_machine").prefetch_related("documents"),
        pk=id,
        asset_type__in=PRODUCTION_ASSET_TYPES,
    )
    list_suggestions = _build_asset_list_suggestions()
    assignment_kwargs = _assignment_form_kwargs(asset)

    if request.method == "POST":
        uploads, upload_errors = _validate_asset_document_uploads(request, asset)
        upload_errors = list(upload_errors) + _work_machine_image_errors(request)
        remove_ids = {_as_int(value, default=0) for value in request.POST.getlist("remove_document_ids")}
        remove_ids = {value for value in remove_ids if value > 0}
        form = WorkMachineAssetForm(
            request.POST,
            instance=asset,
            work_machine=getattr(asset, "work_machine", None),
            list_suggestions=list_suggestions,
            **assignment_kwargs,
        )
        if form.is_valid() and not upload_errors:
            with storico_asset.traccia([asset.pk], fonte=AssetFieldHistory.FONTE_FORM, utente=request.user,
                                       dettaglio="Modifica macchina di lavoro"):
                asset = form.save()
            if form.cleaned_data.get("include_in_plant_layout"):
                marker_warning = _ensure_asset_plant_layout_marker(asset)
                if marker_warning:
                    messages.warning(request, marker_warning)
            if request.POST.get("clear_foto_targhetta") == "1":
                if asset.foto_targhetta:
                    asset.foto_targhetta.delete(save=False)
                asset.foto_targhetta = None
                asset.save(update_fields=["foto_targhetta"])
            elif "foto_targhetta" in request.FILES:
                asset.foto_targhetta = request.FILES["foto_targhetta"]
                asset.save(update_fields=["foto_targhetta"])
            wm = getattr(asset, "work_machine", None)
            if wm:
                if request.POST.get("clear_photo") == "1":
                    if wm.photo:
                        wm.photo.delete(save=False)
                    wm.photo = None
                    wm.save(update_fields=["photo"])
                elif "photo" in request.FILES:
                    wm.photo = request.FILES["photo"]
                    wm.save(update_fields=["photo"])
            _apply_asset_document_changes(
                asset,
                uploads=uploads,
                remove_ids=remove_ids,
                actor=request.user,
            )
            messages.success(request, "Macchina di lavoro aggiornata.")
            return redirect("assets:asset_view", id=asset.id)
        for error in upload_errors:
            form.add_error(None, error)
    else:
        form = WorkMachineAssetForm(
            instance=asset,
            work_machine=getattr(asset, "work_machine", None),
            list_suggestions=list_suggestions,
            **assignment_kwargs,
        )

    return render(
        request,
        "assets/pages/work_machine_form.html",
        {
            "page_title": f"Modifica {asset.asset_tag}",
            "form": form,
            "asset": asset,
            "is_edit": True,
            "list_suggestions": list_suggestions,
            "assignment_department_choices": assignment_kwargs["assignment_department_choices"],
            "assignment_employee_details": assignment_kwargs["assignment_employee_details"],
            "asset_field_names": form.asset_field_names,
            "category_field_groups": form.category_field_groups,
            "category_dynamic_field_names": form.category_dynamic_field_names,
            "machine_field_names": form.machine_field_names,
            "assignment_field_names": form.assignment_field_names,
            "verification_field_names": form.verification_field_names,
            "document_field_map": form.document_field_map,
            "uploaded_documents_by_category": _build_uploaded_documents_context(asset),
            "document_upload_field_map": ASSET_DOCUMENT_UPLOAD_FIELDS,
            "asset_label_designer_url": reverse("assets:asset_label_designer") + f"?scope=asset&asset_id={asset.id}",
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=reverse("assets:work_machine_create"),
                new_label="+ Nuova macchina",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )


@login_required
def asset_meter_update(request: HttpRequest, asset_id: int) -> HttpResponse:
    """P2.2 — Aggiornamento rapido contatore (ore/km/cicli) di un asset.

    GET: restituisce il partial HTML con i contatori correnti e il form inline.
    POST: aggiorna il valore del contatore selezionato e restituisce lo stesso partial.
    Usato via HTMX (hx-post + hx-swap='outerHTML') dalla asset_detail e dalla work_machine_dashboard.
    """
    from ..services.meters import MeterReadingError, record_meter_reading
    from ..views_maintenance import can_execute_maintenance

    asset = get_object_or_404(Asset, pk=asset_id)
    meters = list(AssetMeter.objects.filter(asset=asset).order_by("meter_type"))
    error = None
    success_message = None
    can_record = can_execute_maintenance(request)

    if request.method == "POST":
        # Scrivere una lettura e' un'esecuzione di manutenzione: la lettura guida
        # le scadenze a contatore. Prima bastava essere autenticati.
        if not can_record:
            return HttpResponse("Non hai i permessi per registrare le letture dei contatori.", status=403)
        meter_id = _as_int(request.POST.get("meter_id"), default=0)
        is_reset = request.POST.get("is_reset") == "1"
        note = _clean_string(request.POST.get("note"))
        try:
            meter = AssetMeter.objects.get(pk=meter_id, asset=asset)
        except AssetMeter.DoesNotExist:
            error = "Contatore non trovato."
        else:
            try:
                history = record_meter_reading(
                    meter,
                    request.POST.get("new_value", ""),
                    read_at=timezone.now(),
                    source=AssetMeter.SOURCE_MANUAL,
                    user=request.user,
                    is_reset=is_reset,
                    note=note,
                )
            except MeterReadingError as exc:
                error = str(exc)
            else:
                # La firma è log_action(request, azione, modulo, dettaglio): passare
                # request.user come request faceva fallire l'audit in silenzio (fire-and-forget)
                # proprio sul dato che pilota la generazione delle scadenze a contatore.
                log_action(
                    request,
                    "asset_meter_update",
                    "assets",
                    {
                        "asset_id": asset.id,
                        "asset_tag": asset.asset_tag,
                        "meter_id": meter.id,
                        "meter_type": meter.meter_type,
                        "old_value": str(history.old_value),
                        "new_value": str(history.new_value),
                        "is_reset": history.is_reset,
                    },
                )
                meters = list(AssetMeter.objects.filter(asset=asset).order_by("meter_type"))
                success_message = f"Contatore aggiornato a {history.new_value}."

    recent_history = (
        AssetMeterHistory.objects
        .filter(meter__asset=asset)
        .select_related("meter", "recorded_by")
        .order_by("-recorded_at")[:10]
    )

    ctx = {
        "asset": asset,
        "meters": meters,
        "recent_history": recent_history,
        "error": error,
        "success_message": success_message,
        "can_record_meter": can_record,
    }
    return render(request, "assets/components/asset_meter_panel.html", ctx)


@login_required
def work_machine_maintenance_month_pdf(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    reparto_filter = _clean_string(request.GET.get("reparto"))
    dataset = _build_work_machine_maintenance_month_dataset(
        month_value=request.GET.get("month"),
        reparto_filter=reparto_filter,
        today=today,
    )
    generated_at = timezone.localtime()
    filename_parts = ["report", "macchine", "manutenzione", str(dataset["month_code"])]
    if reparto_filter:
        reparto_slug = slugify(reparto_filter)
        if reparto_slug:
            filename_parts.append(reparto_slug)

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{"_".join(filename_parts)}.pdf"'

    buffer = io.BytesIO()
    theme = PdfTheme.from_branding()
    pdf = canvas.Canvas(buffer, pagesize=landscape(A4))
    pdf.setTitle(f'Report manutenzioni macchine {dataset["month_label"]}')
    pdf.setAuthor(theme.portal_name)
    pdf.setSubject(f'Macchine con manutenzione pianificata nel periodo {dataset["period_label"]}')

    _draw_work_machine_maintenance_month_pdf(pdf, theme=theme, dataset=dataset, generated_at=generated_at)

    pdf.showPage()
    pdf.save()
    response.write(buffer.getvalue())
    return response
