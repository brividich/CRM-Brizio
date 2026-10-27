"""Planimetrie: mappa officina ed editor.

Estratto meccanicamente da assets/views.py (refactor C4): nessun cambio di comportamento.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.acl import user_can_modulo_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from ..forms import (
    PlantLayoutForm,
)
from ..models import (
    Asset,
    PlantLayout,
    PlantLayoutMarker,
)

from ._helpers import (  # noqa: F401
    _as_int,
    _asset_plant_layout_marker,
    _clean_string,
    _plant_layout_image_size,
    _resolve_asset_plant_layout_detail,
)
from ._helpers_c import (  # noqa: F401
    _PLANT_ALERT_LABELS,
    _PLANT_ALERT_LEVELS,
    _assets_shell_context,
    _plant_layout_machine_catalog,
    _plant_layout_public_payload,
)

def _safe_editor_json_rows(raw_value) -> list[dict[str, object]]:
    if not raw_value:
        return []
    try:
        payload = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, dict)]


def _plant_layout_editor_area_rows(layout: PlantLayout | None) -> list[dict[str, object]]:
    if layout is None:
        return []
    return [
        {
            "id": area.id,
            "name": area.name,
            "reparto_code": area.reparto_code,
            "color": area.color,
            "notes": area.notes,
            "x_percent": float(area.x_percent),
            "y_percent": float(area.y_percent),
            "width_percent": float(area.width_percent),
            "height_percent": float(area.height_percent),
            "sort_order": area.sort_order,
        }
        for area in layout.areas.all().order_by("sort_order", "id")
    ]


def _plant_layout_editor_marker_rows(layout: PlantLayout | None) -> list[dict[str, object]]:
    from ..services.plant_layout_image import marker_is_unplaced

    if layout is None:
        return []
    return [
        {
            "id": marker.id,
            "asset_id": marker.asset_id,
            "label": marker.label,
            "x_percent": float(marker.x_percent),
            "y_percent": float(marker.y_percent),
            "sort_order": marker.sort_order,
            "unplaced": marker_is_unplaced(marker),
        }
        for marker in layout.markers.select_related("asset").all().order_by("sort_order", "id")
    ]


def _plant_layout_queryset():
    return PlantLayout.objects.prefetch_related("areas", "markers", "markers__asset", "markers__asset__work_machine")


def _preferred_plant_layout_category(
    active_layouts: list[PlantLayout],
    *,
    requested_category: str = "",
    fallback_category: str = PlantLayout.DEFAULT_CATEGORY,
) -> str:
    requested = _clean_string(requested_category)
    if requested:
        for layout in active_layouts:
            if _clean_string(layout.category).casefold() == requested.casefold():
                return layout.category
    for layout in active_layouts:
        if _clean_string(layout.category).casefold() == _clean_string(fallback_category).casefold():
            return layout.category
    return active_layouts[0].category if active_layouts else ""


def _plant_layout_category_switches(
    *,
    active_layouts: list[PlantLayout],
    selected_category: str,
    focus_asset_id: int = 0,
) -> list[dict[str, object]]:
    try:
        base_url = reverse("assets:plant_layout_map")
    except NoReverseMatch:
        base_url = "/assets/work-machines/map/"
    switches: list[dict[str, object]] = []
    seen_categories: set[str] = set()
    for layout in active_layouts:
        category_key = _clean_string(layout.category).casefold()
        if category_key in seen_categories:
            continue
        seen_categories.add(category_key)
        params = [f"category={quote(layout.category)}"]
        if focus_asset_id:
            params.append(f"asset={focus_asset_id}")
        switches.append(
            {
                "category": layout.category,
                "active": _clean_string(layout.category).casefold() == _clean_string(selected_category).casefold(),
                "url": f"{base_url}?{'&'.join(params)}",
                "layout_name": layout.name,
            }
        )
    return switches


def plant_layout_map(request: HttpRequest) -> HttpResponse:
    # ?format=json: lo stato aggiornato che la pagina rilegge ogni minuto (JSON 401, mai redirect)
    wants_json = request.GET.get("format") == "json"
    if not request.user.is_authenticated:
        if wants_json:
            return JsonResponse({"ok": False, "error": "Sessione scaduta: accedi di nuovo."}, status=401)
        return redirect_to_login(request.get_full_path())
    focus_asset_id = _as_int(request.GET.get("asset"), default=0)
    requested_category = _clean_string(request.GET.get("category"))
    if not requested_category and focus_asset_id:
        focus_asset = Asset.objects.filter(pk=focus_asset_id).first()
        focus_marker = _asset_plant_layout_marker(focus_asset) if focus_asset else None
        if focus_marker is not None:
            requested_category = focus_marker.layout.category

    active_layouts = list(_plant_layout_queryset().filter(is_active=True).order_by("category", "name", "id"))
    selected_category = _preferred_plant_layout_category(active_layouts, requested_category=requested_category)
    layout = next(
        (row for row in active_layouts if _clean_string(row.category).casefold() == _clean_string(selected_category).casefold()),
        active_layouts[0] if active_layouts else None,
    )
    payload = _plant_layout_public_payload(layout)
    if wants_json:
        return JsonResponse({
            "ok": True,
            "layout_id": getattr(layout, "id", None),
            "aggiornato": timezone.localtime().strftime("%H:%M"),
            "payload": payload,
        })
    image_size = _plant_layout_image_size(layout)
    if request.GET.get("stampa") == "1" and layout is not None:
        return render(
            request,
            "assets/pages/plant_layout_print.html",
            {
                "layout": layout,
                "rows": _plant_layout_print_rows(payload),
                "image_width": image_size[0],
                "image_height": image_size[1],
                "printed_at": timezone.localtime(),
                "alert_labels": _PLANT_ALERT_LABELS,
            },
        )
    category_switches = _plant_layout_category_switches(
        active_layouts=active_layouts,
        selected_category=selected_category,
        focus_asset_id=focus_asset_id,
    )

    return render(
        request,
        "assets/pages/plant_layout_map.html",
        {
            "page_title": "Planimetrie impianti",
            "layout": layout,
            "plant_layout_payload": payload,
            "focus_asset_id": focus_asset_id,
            "selected_layout_category": selected_category,
            "layout_category_switches": category_switches,
            "check_layouts": _plant_layout_check_links(),
            "image_width": image_size[0],
            "image_height": image_size[1],
            "alert_filters": [
                {"code": code, "label": _PLANT_ALERT_LABELS[code], "count": payload["alert_counts"][code]}
                for code in _PLANT_ALERT_LEVELS if payload["alert_counts"][code]
            ],
            "alert_total": sum(v for k, v in payload["alert_counts"].items() if k != "ok"),
            "can_manage_map": user_can_modulo_action(request, "assets", "admin_assets"),
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


def _plant_layout_print_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    """Macchine numerate per la stampa: per reparto, poi da sinistra a destra, dall'alto in basso."""
    markers = sorted(
        payload.get("markers") or [],
        key=lambda m: (
            _clean_string(str((m.get("machine") or {}).get("reparto") or "")).casefold() or "~",
            round(float(m["y_percent"]) / 10),
            float(m["x_percent"]),
        ),
    )
    rows = []
    for number, marker in enumerate(markers, start=1):
        machine = marker.get("machine") or {}
        rows.append({
            "n": number,
            "x": marker["x_percent"],
            "y": marker["y_percent"],
            "label": marker["label"],
            "name": machine.get("name") or marker["label"],
            "asset_tag": machine.get("asset_tag") or "",
            "internal_number": machine.get("internal_number") or "",
            "reparto": machine.get("reparto") or "",
            "alert": marker["alert"],
            "alert_label": marker["alert_label"],
            "cnc": bool(machine.get("live")),
        })
    return rows


def _plant_layout_check_links() -> list[dict[str, object]]:
    """Le planimetrie delle verifiche periodiche (luci di emergenza, differenziali...):
    stanno nella loro scheda, qui solo il collegamento con lo stato della verifica."""
    from ..models import PeriodicCheckType
    from ..services import periodic_checks as checks

    links = []
    for check_type in (
        PeriodicCheckType.objects.filter(method=PeriodicCheckType.METHOD_LAYOUT, is_active=True, layouts__is_active=True)
        .distinct().order_by("name")
    ):
        state = checks.type_state(check_type)
        links.append({
            "name": check_type.name,
            "state": state,
            "state_label": checks.STATE_LABELS[state],
            "url": reverse("assets:periodic_check_type_detail", args=[check_type.id]) + "?tab=panoramica",
        })
    return links


def _apply_plant_layout_image_tool(request: HttpRequest, layout: PlantLayout) -> str | None:
    """Ruota/ritaglia dopo aver salvato reparti e marker del form (stesso invio).

    ``None`` se non è stato chiesto nessuno strumento immagine.
    """
    from ..services import plant_layout_image as image_tools

    tool = _clean_string(request.POST.get("image_tool"))
    if not tool:
        return None
    try:
        if tool in {"rotate_left", "rotate_right"}:
            result = image_tools.rotate_layout(layout, clockwise=tool == "rotate_right")
        elif tool == "crop":
            result = image_tools.crop_layout(
                layout,
                x_percent=_as_float(request.POST.get("crop_x")),
                y_percent=_as_float(request.POST.get("crop_y")),
                width_percent=_as_float(request.POST.get("crop_w")),
                height_percent=_as_float(request.POST.get("crop_h")),
            )
        else:
            messages.error(request, "Strumento immagine non riconosciuto.")
            return ""
    except (OSError, ValueError):
        messages.error(request, "Modifiche salvate, ma l'immagine non si è potuta trasformare: ricaricala.")
        return ""
    (messages.success if result.ok else messages.warning)(request, result.message)
    return result.message


def _as_float(value) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _plant_layout_previous_version(category) -> PlantLayout | None:
    """La versione da cui copiare reparti e macchine quando nasce una nuova
    versione della stessa pianta: l'attiva, altrimenti la più recente."""
    category = _clean_string(category)
    if not category:
        return None
    return (
        PlantLayout.objects.filter(category__iexact=category)
        .order_by("-is_active", "-updated_at", "-id")
        .first()
    )


def _plant_layout_machine_catalog_for(layout: PlantLayout | None) -> list[dict[str, object]]:
    """Catalogo macchine dell'editor con, per ognuna, le ALTRE piante attive su
    cui è già posizionata a mano: «Da posizionare» deve voler dire «da nessuna
    parte», non «non su questa pianta»."""
    elsewhere: dict[int, list[str]] = {}
    placed = (
        PlantLayoutMarker.objects.filter(layout__is_active=True)
        .exclude(x_percent=50, y_percent=50)
        .values_list("asset_id", "layout_id", "layout__name")
        .order_by("layout__category", "layout__name")
    )
    layout_id = getattr(layout, "id", None)
    for asset_id, row_layout_id, layout_name in placed:
        if row_layout_id == layout_id:
            continue
        names = elsewhere.setdefault(asset_id, [])
        if layout_name not in names:
            names.append(layout_name)
    catalog = _plant_layout_machine_catalog()
    for row in catalog:
        row["elsewhere"] = elsewhere.get(row["id"], [])
    return catalog


def _plant_layout_category_counts() -> dict[str, dict[str, int]]:
    """Per categoria (minuscola): macchine posizionate e segnaposti mai
    collocati sulla versione attiva."""
    counts: dict[str, dict[str, int]] = {}
    rows = PlantLayoutMarker.objects.filter(layout__is_active=True).values_list("layout__category", "x_percent", "y_percent")
    for category, x, y in rows:
        bucket = counts.setdefault(_clean_string(category).casefold(), {"placed": 0, "unplaced": 0})
        if x == 50 and y == 50:
            bucket["unplaced"] += 1
        else:
            bucket["placed"] += 1
    return counts


_POSITION_TITLES = {
    "collocata": "Collocata sulla planimetria",
    "spostata": "Spostata sulla planimetria",
    "tolta": "Tolta dalla planimetria",
}


def _record_plant_position_changes(request: HttpRequest, layout: PlantLayout, changes) -> None:
    """Ogni collocazione/spostamento finisce nella timeline della macchina (chi, quando, quale pianta)."""
    from ..models import AssetTimelineEntry

    if not changes:
        return
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    today = timezone.localdate()
    # una create per riga: su SQL Server l'INSERT a lotti rompe i savepoint
    for asset_id, kind in changes:
        AssetTimelineEntry.objects.create(
            asset_id=asset_id,
            event_date=today,
            title=_POSITION_TITLES[kind],
            tag="PLANIMETRIA",
            meta=layout.name[:120],
            description=f"Pianta «{layout.name}» ({layout.category}), dall'editor delle planimetrie.",
            color=AssetTimelineEntry.COLOR_BLUE,
            created_by=user,
        )


@login_required
def plant_layout_editor(request: HttpRequest) -> HttpResponse:
    all_layouts = list(
        _plant_layout_queryset().all().order_by("category", "-is_active", "-updated_at", "name", "id")
    )
    current_category = _clean_string(
        request.POST.get("category_filter") or request.POST.get("category") or request.GET.get("category")
    )
    current_layout_id = _as_int(request.POST.get("layout_id") or request.GET.get("layout"), default=0)
    focus_asset_id = _as_int(request.GET.get("asset"), default=0)
    if not current_layout_id and focus_asset_id and request.method != "POST":
        # Dalla scheda senza pianta scelta: si apre quella dove la macchina è
        # già, oppure quella dedotta (mai la «prima in ordine alfabetico»).
        focus_asset = Asset.objects.filter(pk=focus_asset_id).first()
        if focus_asset is not None:
            focus_marker = _asset_plant_layout_marker(focus_asset)
            if focus_marker is not None:
                current_layout_id = focus_marker.layout_id
            else:
                guessed, reason = _resolve_asset_plant_layout_detail(focus_asset)
                if guessed is not None and reason != "primo":
                    current_layout_id = guessed.id
    create_new = _clean_string(request.POST.get("layout_mode") or request.GET.get("new")) in {"1", "new", "true"}
    selected_layout = None
    filtered_layouts = [
        row for row in all_layouts if not current_category or _clean_string(row.category).casefold() == current_category.casefold()
    ]
    if not create_new:
        selected_layout = next((row for row in all_layouts if row.id == current_layout_id), None)
        if selected_layout is not None and not current_category:
            current_category = selected_layout.category
            filtered_layouts = [
                row for row in all_layouts if _clean_string(row.category).casefold() == current_category.casefold()
            ]
        if selected_layout is None and filtered_layouts:
            selected_layout = next((row for row in filtered_layouts if row.is_active), None) or filtered_layouts[0]
        if selected_layout is None and all_layouts:
            selected_layout = next((row for row in all_layouts if row.is_active), None) or all_layouts[0]
            current_category = current_category or getattr(selected_layout, "category", "")
            filtered_layouts = [
                row for row in all_layouts
                if not current_category or _clean_string(row.category).casefold() == current_category.casefold()
            ]

    area_rows = _plant_layout_editor_area_rows(selected_layout)
    marker_rows = _plant_layout_editor_marker_rows(selected_layout)

    if request.method == "POST":
        action = _clean_string(request.POST.get("action")) or "save_layout"
        if action == "activate_layout":
            if selected_layout is None:
                messages.error(request, "Planimetria non trovata.")
            else:
                selected_layout.is_active = True
                selected_layout.save()
                messages.success(request, f"Planimetria \"{selected_layout.name}\" pubblicata nella categoria {selected_layout.category}.")
            layout_id = selected_layout.id if selected_layout else ""
            category_qs = f"&category={quote(selected_layout.category)}" if selected_layout else ""
            return redirect(f"{reverse('assets:plant_layout_editor')}?layout={layout_id}{category_qs}")

        if action == "deactivate_layout":
            if selected_layout is None:
                messages.error(request, "Planimetria non trovata.")
            else:
                selected_layout.is_active = False
                selected_layout.save()
                messages.success(request, f"Planimetria \"{selected_layout.name}\" tolta dalla mappa: resta come bozza.")
            layout_id = selected_layout.id if selected_layout else ""
            category_qs = f"&category={quote(selected_layout.category)}" if selected_layout else ""
            return redirect(f"{reverse('assets:plant_layout_editor')}?layout={layout_id}{category_qs}")

        if action == "delete_layout":
            if selected_layout is None:
                messages.error(request, "Planimetria non trovata.")
            else:
                deleted_name = selected_layout.name
                deleted_category = selected_layout.category
                selected_layout.delete()
                messages.success(request, f"Planimetria \"{deleted_name}\" eliminata.")
            if current_category:
                return redirect(f"{reverse('assets:plant_layout_editor')}?category={quote(current_category or deleted_category)}")
            return redirect("assets:plant_layout_editor")

        form = PlantLayoutForm(
            request.POST,
            request.FILES,
            instance=None if create_new else selected_layout,
        )
        if form.is_valid():
            copy_source = None
            if create_new and _clean_string(request.POST.get("copy_previous")) == "1":
                copy_source = _plant_layout_previous_version(form.cleaned_data.get("category"))
            layout = form.save()
            _record_plant_position_changes(request, layout, getattr(form, "position_changes", []))
            if copy_source is not None:
                from ..services.plant_layout_image import copy_layout_content

                copied_areas, copied_markers = copy_layout_content(copy_source, layout)
                messages.info(
                    request,
                    f"Dalla versione «{copy_source.name}» copiati {copied_areas} reparti e {copied_markers} macchine: "
                    "se la nuova pianta ha un'inquadratura diversa, controlla le posizioni.",
                )
            tool_message = _apply_plant_layout_image_tool(request, layout)
            if tool_message is None:
                messages.success(request, f"Planimetria \"{layout.name}\" aggiornata nella categoria {layout.category}.")
            return redirect(f"{reverse('assets:plant_layout_editor')}?layout={layout.id}&category={quote(layout.category)}")
        area_rows = _safe_editor_json_rows(request.POST.get("areas_payload"))
        marker_rows = _safe_editor_json_rows(request.POST.get("markers_payload"))
    else:
        form = PlantLayoutForm(
            instance=selected_layout,
            initial={"category": current_category or getattr(selected_layout, "category", "") or PlantLayout.DEFAULT_CATEGORY},
        )

    editor_payload = {
        "layout": {
            "id": getattr(selected_layout, "id", None),
            "category": getattr(selected_layout, "category", current_category or PlantLayout.DEFAULT_CATEGORY),
            "name": getattr(selected_layout, "name", ""),
            "description": getattr(selected_layout, "description", ""),
            "image_url": (
                selected_layout.image.url
                if selected_layout is not None and selected_layout.image
                else ""
            ),
            "is_active": bool(getattr(selected_layout, "is_active", False)),
        },
        "areas": area_rows,
        "markers": marker_rows,
        "machines": _plant_layout_machine_catalog_for(None if create_new else selected_layout),
        "focus_asset_id": focus_asset_id,
    }
    image_size = _plant_layout_image_size(selected_layout)
    available_categories = []
    seen_categories: set[str] = set()
    for row in all_layouts:
        category_key = _clean_string(row.category).casefold()
        if category_key in seen_categories:
            continue
        seen_categories.add(category_key)
        available_categories.append(row.category)
    layout_choices = [
        {
            "id": row.id,
            "category": row.category,
            "name": row.name,
            "is_active": row.is_active,
            "updated_at": timezone.localtime(row.updated_at).strftime("%d-%m-%Y %H:%M"),
            "edit_url": f"{reverse('assets:plant_layout_editor')}?layout={row.id}&category={quote(row.category)}",
        }
        for row in (filtered_layouts if current_category else all_layouts)
    ]
    layout_category_filters = [
        {
            "label": "Tutte",
            "active": not current_category,
            "url": reverse("assets:plant_layout_editor"),
        }
    ]
    category_counts = _plant_layout_category_counts()
    for category in available_categories:
        counts = category_counts.get(_clean_string(category).casefold(), {"placed": 0, "unplaced": 0})
        layout_category_filters.append(
            {
                "label": category,
                "counted": True,
                "placed": counts["placed"],
                "unplaced": counts["unplaced"],
                "active": _clean_string(category).casefold() == current_category.casefold(),
                "url": f"{reverse('assets:plant_layout_editor')}?category={quote(category)}",
            }
        )

    return render(
        request,
        "assets/pages/plant_layout_editor.html",
        {
            "page_title": "Editor planimetrie impianti",
            "form": form,
            "selected_layout": selected_layout,
            "layout_choices": layout_choices,
            "layout_category_filters": layout_category_filters,
            "current_layout_category": current_category or getattr(selected_layout, "category", PlantLayout.DEFAULT_CATEGORY),
            "create_new": create_new,
            "copy_source": _plant_layout_previous_version(current_category) if create_new else None,
            "editor_payload": editor_payload,
            "image_width": image_size[0],
            "image_height": image_size[1],
            **_assets_shell_context(
                request,
                rows=_as_int(request.GET.get("rows"), default=25),
                search_action=reverse("assets:work_machine_list"),
                new_url=(
                    f"{reverse('assets:plant_layout_editor')}?new=1&category={quote(current_category)}"
                    if current_category
                    else f"{reverse('assets:plant_layout_editor')}?new=1"
                ),
                new_label="+ Nuova planimetria",
                search_placeholder="Ricerca rapida per macchina, tag, reparto o seriale",
            ),
        },
    )
