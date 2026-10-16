"""Ricambi: anagrafica, movimenti, scarico su intervento, sotto scorta.

Permessi (nessuna azione ACL nuova):
* lettura: binding della pagina (come «Da fare»);
* anagrafica, carichi e rettifiche: ``admin_assets`` (``can_manage_maintenance_plans``);
* scarico su un intervento: ``maintenance_execute`` (``can_execute_maintenance``).
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import Asset, AssetCategory, SparePart, SparePartMovement, WorkOrder
from .services.spare_parts import SparePartError, register_movement, workorder_parts_cost
from .views import _assets_shell_context, _clean_string, _xl_write_sheet
from .views_maintenance import can_execute_maintenance, can_manage_maintenance_plans


class SparePartForm(forms.ModelForm):
    class Meta:
        model = SparePart
        fields = [
            "code", "description", "unit", "min_qty", "location", "unit_cost_eur", "supplier",
            "compatible_categories", "compatible_assets", "is_active", "notes",
        ]
        labels = {
            "code": "Codice", "description": "Descrizione", "unit": "Unita'", "min_qty": "Scorta minima",
            "location": "Posizione (scaffale)", "unit_cost_eur": "Costo unitario (EUR)", "supplier": "Fornitore",
            "compatible_categories": "Categorie compatibili", "compatible_assets": "Asset compatibili",
            "is_active": "Attivo", "notes": "Note",
        }
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["compatible_assets"].queryset = Asset.objects.exclude(status=Asset.STATUS_RETIRED).order_by("asset_tag")
        self.fields["compatible_categories"].queryset = AssetCategory.objects.filter(is_active=True).order_by("label")
        for field in self.fields.values():
            if not isinstance(field.widget, (forms.CheckboxInput, forms.SelectMultiple)):
                field.widget.attrs.setdefault("class", "input")


def _deny(request: HttpRequest, message: str):
    messages.error(request, message)
    return redirect("assets:spare_part_list")


@login_required
def spare_part_list(request: HttpRequest) -> HttpResponse:
    parts = SparePart.objects.select_related("supplier").order_by("code")
    q = _clean_string(request.GET.get("q"))
    if q:
        parts = parts.filter(Q(code__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
    only_below = request.GET.get("sotto_scorta") == "1"
    if only_below:
        parts = parts.filter(is_active=True, stock_qty__lte=F("min_qty"))
    if request.GET.get("inattivi") != "1":
        parts = parts.filter(is_active=True)
    if request.GET.get("export") == "xlsx":
        return _export_parts_xlsx(list(parts))
    parts = list(parts[:500])
    below_total = SparePart.objects.filter(is_active=True, stock_qty__lte=F("min_qty")).count()
    return render(
        request,
        "assets/pages/spare_part_list.html",
        {
            **_assets_shell_context(request),
            "page_title": "Ricambi",
            "parts": parts,
            "q": q,
            "only_below": only_below,
            "below_total": below_total,
            "can_manage": can_manage_maintenance_plans(request),
            "export_url": f"{reverse('assets:spare_part_list')}?{_export_query(request)}",
        },
    )


def _export_query(request: HttpRequest) -> str:
    query = request.GET.copy()
    query["export"] = "xlsx"
    return query.urlencode()


def _export_parts_xlsx(parts: list[SparePart]) -> HttpResponse:
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Ricambi"
    headers = ["Codice", "Descrizione", "Unita'", "Giacenza", "Scorta minima", "Sotto scorta", "Posizione",
               "Costo unitario (EUR)", "Fornitore", "Attivo"]
    rows = [
        [
            part.code, part.description, part.unit, float(part.stock_qty), float(part.min_qty),
            "Si" if part.is_below_min else "No", part.location,
            float(part.unit_cost_eur) if part.unit_cost_eur is not None else "",
            getattr(part.supplier, "ragione_sociale", "") or "", "Si" if part.is_active else "No",
        ]
        for part in parts
    ]
    _xl_write_sheet(sheet, headers, rows)
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="ricambi_{timezone.localdate():%Y%m%d}.xlsx"'
    return response


@login_required
def spare_part_form(request: HttpRequest, part_id: int | None = None) -> HttpResponse:
    if not can_manage_maintenance_plans(request):
        return _deny(request, "Solo chi amministra il modulo Asset gestisce l'anagrafica dei ricambi.")
    part = get_object_or_404(SparePart, pk=part_id) if part_id else None
    form = SparePartForm(request.POST or None, instance=part)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        log_action(request, "spare_part_save", "assets", {"part_id": saved.pk, "code": saved.code, "nuovo": part is None})
        messages.success(request, f"Ricambio «{saved.code}» salvato.")
        return redirect("assets:spare_part_detail", part_id=saved.pk)
    return render(
        request,
        "assets/pages/spare_part_form.html",
        {**_assets_shell_context(request), "page_title": "Nuovo ricambio" if part is None else f"Modifica {part.code}",
         "form": form, "part": part},
    )


@login_required
def spare_part_detail(request: HttpRequest, part_id: int) -> HttpResponse:
    part = get_object_or_404(SparePart.objects.select_related("supplier"), pk=part_id)
    can_manage = can_manage_maintenance_plans(request)
    if request.method == "POST":
        if not can_manage:
            return _deny(request, "Carichi e rettifiche sono riservati a chi amministra il modulo Asset.")
        kind = _clean_string(request.POST.get("kind")).upper()
        if kind not in (SparePartMovement.KIND_IN, SparePartMovement.KIND_ADJUST):
            messages.error(request, "Da qui si registrano carichi e rettifiche: gli scarichi si fanno sull'intervento.")
            return redirect("assets:spare_part_detail", part_id=part.pk)
        try:
            unit_cost = _decimal_or_none(request.POST.get("unit_cost_eur"))
            movement = register_movement(
                part, kind, request.POST.get("qty"), user=request.user, unit_cost=unit_cost,
                note=_clean_string(request.POST.get("note")),
            )
        except SparePartError as exc:
            messages.error(request, str(exc))
        else:
            log_action(request, "spare_part_movement", "assets",
                       {"part_id": part.pk, "kind": kind, "qty": str(movement.qty), "stock_after": str(movement.stock_after)})
            messages.success(request, f"{movement.get_kind_display()} registrato: giacenza {movement.stock_after} {part.unit}.")
        return redirect("assets:spare_part_detail", part_id=part.pk)
    movements = list(part.movements.select_related("work_order", "user")[:200])
    return render(
        request,
        "assets/pages/spare_part_detail.html",
        {**_assets_shell_context(request), "page_title": f"Ricambio {part.code}", "part": part,
         "movements": movements, "can_manage": can_manage},
    )


def _decimal_or_none(raw):
    raw = _clean_string(raw)
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise SparePartError("Costo unitario non valido.") from None


def suggested_parts(work_order: WorkOrder, *, q: str = "", limit: int = 20) -> list[SparePart]:
    """Prima i ricambi compatibili con l'asset o la sua categoria, poi gli altri che corrispondono alla ricerca."""
    asset = work_order.asset
    compatible = SparePart.objects.filter(is_active=True).filter(
        Q(compatible_assets=asset) | Q(compatible_categories=asset.asset_category_id)
    ).distinct()
    if q:
        search = Q(code__icontains=q) | Q(description__icontains=q)
        compatible = compatible.filter(search)
        others = SparePart.objects.filter(is_active=True).filter(search).exclude(pk__in=compatible.values("pk"))
    else:
        others = SparePart.objects.none()
    rows = list(compatible.order_by("code")[:limit])
    for part in rows:
        part.is_compatible = True
    extra = list(others.order_by("code")[: max(0, limit - len(rows))])
    for part in extra:
        part.is_compatible = False
    return rows + extra


def workorder_spare_parts_context(request: HttpRequest, work_order: WorkOrder, *, q: str = "") -> dict:
    movements = list(
        SparePartMovement.objects.filter(work_order=work_order, kind=SparePartMovement.KIND_OUT)
        .select_related("part", "user").order_by("created_at", "id")
    )
    calculated = workorder_parts_cost(work_order)
    manual = work_order.materials_cost_eur
    return {
        "workorder": work_order,
        "sp_movements": movements,
        "sp_suggestions": suggested_parts(work_order, q=q) if work_order.status == WorkOrder.STATUS_OPEN else [],
        "sp_q": q,
        "sp_can_unload": can_execute_maintenance(request) and work_order.status == WorkOrder.STATUS_OPEN,
        "sp_calculated_cost": calculated,
        "sp_manual_cost": manual,
        "sp_cost_difference": (manual - calculated) if (manual is not None and calculated is not None) else None,
    }


@login_required
def workorder_spare_parts(request: HttpRequest, workorder_id: int) -> HttpResponse:
    """Riquadro «Ricambi usati» dell'intervento (HTMX): GET cerca, POST scarica."""
    work_order = get_object_or_404(WorkOrder.objects.select_related("asset", "asset__asset_category"), pk=workorder_id)
    error = ""
    if request.method == "POST":
        if not can_execute_maintenance(request):
            return HttpResponse("Non hai i permessi per scaricare ricambi su un intervento.", status=403)
        if work_order.status != WorkOrder.STATUS_OPEN:
            error = "L'intervento e' chiuso: i ricambi si scaricano sugli interventi aperti."
        else:
            part = SparePart.objects.filter(pk=request.POST.get("part_id"), is_active=True).first()
            if part is None:
                error = "Scegli un ricambio."
            else:
                try:
                    movement = register_movement(
                        part, SparePartMovement.KIND_OUT, request.POST.get("qty"), user=request.user,
                        work_order=work_order, note=f"Intervento #{work_order.display_number}",
                    )
                except SparePartError as exc:
                    error = str(exc)
                else:
                    log_action(request, "spare_part_movement", "assets", {
                        "part_id": part.pk, "kind": "OUT", "qty": str(movement.qty), "workorder_id": work_order.pk,
                    })
    context = workorder_spare_parts_context(request, work_order, q=_clean_string(request.GET.get("q")))
    context["sp_error"] = error
    return render(request, "assets/components/_workorder_spare_parts.html", context)
