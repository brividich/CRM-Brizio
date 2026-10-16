"""Helper condivisi delle viste Asset (estratti meccanicamente da views.py, refactor C4)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from django.db import DatabaseError
from django.db.models import Max, Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from core.acl import user_can_modulo_action

# Etichetta con cui le voci di audit si agganciano all'asset: e' la stessa che
# `core.audit.storico_oggetto` usa per ripescarle sulla scheda. Costante e non
# stringa sparsa perche' un refuso qui non romperebbe nulla — semplicemente la
# voce non comparirebbe mai nello storico, e non se ne accorgerebbe nessuno.
AUDIT_OGGETTO_ASSET = "assets.asset"
from core.module_branding import (
    resolve_module_logo,
)
from core.module_registry import resolve_module_label
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from ..forms import (
    IT_DEVICE_TYPES,
)
from ..models import (
    Asset,
    AssetCategory,
    AssetCategoryField,
    AssetCustomField,
    AssetDetailField,
    AssetListLayout,
    AssetSidebarButton,
    MaintenanceRule,
    PeriodicVerification,
    PlantLayout,
    WorkMachine,
    WorkOrder,
    WorkOrderAttachment,
    WorkOrderChecklist,
)
from ..maintenance import (
    build_day_based_maintenance_schedule_rows,
)
from ..services.sidebar_categories import (
    category_sidebar_active_match as _service_category_sidebar_active_match,
    category_sidebar_target as _service_category_sidebar_target,
)

from ._helpers import (  # noqa: F401
    ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
    ASSET_DOCUMENT_ALLOWED_MIMES,
    ASSET_DOCUMENT_MAX_BYTES,
    ASSET_LIST_COMMON_COLUMNS,
    ASSET_LIST_IT_COLUMNS,
    LIST_LAYOUT_ACTIONS,
    _as_int,
    _clean_string,
    _maintenance_rule_list_page_url,
    _maintenance_schedule_page_url,
    _workorder_create_page_url,
)
from ._helpers_b import (  # noqa: F401
    _create_default_sidebar_buttons,
    _default_sidebar_buttons,
    _default_sidebar_seed_rows,
    _periodic_verifications_page_url,
    _seed_default_asset_detail_fields,
    _sidebar_button_payload,
    _unique_asset_category_code,
    _unique_asset_category_field_code,
    _unique_detail_field_code,
    _unique_sidebar_button_code,
    _update_asset_category_values_after_delete,
)

def _nest_sidebar_items(flat_items: list[dict]) -> list[dict]:
    nested: list[dict] = []
    current_parent: dict | None = None

    for item in flat_items:
        payload = dict(item)
        payload["children"] = []
        payload["has_children"] = False
        payload["expanded"] = bool(payload.get("active"))

        if payload.get("is_subitem") and current_parent is not None:
            current_parent["children"].append(payload)
            current_parent["has_children"] = True
            if payload.get("active"):
                current_parent["expanded"] = True
            continue

        nested.append(payload)
        current_parent = payload if not payload.get("is_subitem") else None

    return nested


def _build_sidebar_groups(request: HttpRequest, rows: int = 25) -> list[dict]:
    section_label = dict(AssetSidebarButton.SECTION_CHOICES)
    section_order = {
        AssetSidebarButton.SECTION_MAIN: 0,
        AssetSidebarButton.SECTION_ANALYTICS: 1,
        AssetSidebarButton.SECTION_OPERATIONS: 2,
        # Ultima: e' la piu' lunga e la meno usata per navigare.
        AssetSidebarButton.SECTION_CATEGORIES: 3,
    }
    configured = list(
        AssetSidebarButton.objects.filter(is_visible=True)
        .select_related("parent")
        .order_by("section", "sort_order", "id")
    )
    grouped: dict[str, list[dict]] = defaultdict(list)

    if configured:
        visible_by_id = {button.id: button for button in configured}
        roots_by_section: dict[str, list[AssetSidebarButton]] = defaultdict(list)
        children_by_parent: dict[int, list[AssetSidebarButton]] = defaultdict(list)

        for button in configured:
            if button.parent_id and button.parent_id in visible_by_id:
                children_by_parent[button.parent_id].append(button)
            else:
                roots_by_section[button.section].append(button)

        for section, root_buttons in roots_by_section.items():
            for button in root_buttons:
                root_payload = _sidebar_button_payload(request, button, rows=rows, force_subitem=button.is_subitem)
                root_payload["children"] = []
                root_payload["has_children"] = False
                root_payload["expanded"] = bool(root_payload.get("active"))
                grouped[section].append(root_payload)
                for child in children_by_parent.get(button.id, []):
                    child_payload = _sidebar_button_payload(request, child, rows=rows, force_subitem=True)
                    child_payload["children"] = []
                    child_payload["has_children"] = False
                    child_payload["expanded"] = bool(child_payload.get("active"))
                    root_payload["children"].append(child_payload)
                    root_payload["has_children"] = True
                    if child_payload.get("active"):
                        root_payload["expanded"] = True
    else:
        for payload in _default_sidebar_buttons(request, rows=rows):
            grouped[payload["section"]].append(payload)
        for section, items in list(grouped.items()):
            grouped[section] = _nest_sidebar_items(items)

    output = []
    for section, items in sorted(grouped.items(), key=lambda row: section_order.get(row[0], 99)):
        output.append({"section": section, "label": section_label.get(section, section), "items": items})
    return output


def _category_sidebar_target(category_id: int) -> str:
    return _service_category_sidebar_target(category_id)


def _category_sidebar_active_match(category_id: int) -> str:
    return _service_category_sidebar_active_match(category_id)


def _category_subtree_ids(category) -> list[int]:
    """Ritorna gli id della categoria e di tutte le sue discendenti.

    L'albero categorie e' su due livelli (radice -> sotto-categorie); il terzo
    livello e' gestito per sicurezza nel caso venga introdotto in futuro.
    """
    ids = [category.id]
    child_ids = list(
        AssetCategory.objects.filter(parent_id=category.id).values_list("id", flat=True)
    )
    ids.extend(child_ids)
    if child_ids:
        ids.extend(
            AssetCategory.objects.filter(parent_id__in=child_ids).values_list("id", flat=True)
        )
    return ids


def _handle_sidebar_button_request(request: HttpRequest) -> tuple[bool, str]:
    # Una POST con due "action" diverse (form annidati: il browser fonde i
    # campi del form interno in quello esterno) e' ambigua: QueryDict.get()
    # restituisce l'ultimo valore, cosi' il tasto Salva finiva per eliminare
    # la voce. Meglio rifiutare che indovinare.
    if len({_clean_string(value) for value in request.POST.getlist("action")}) > 1:
        return False, "Richiesta menu ambigua: nessuna modifica applicata."
    action = _clean_string(request.POST.get("action"))
    valid_sections = {key for key, _ in AssetSidebarButton.SECTION_CHOICES}

    if action == "seed_sidebar_buttons":
        if AssetSidebarButton.objects.exists():
            return False, "Menu sidebar già configurato."
        payload = _default_sidebar_seed_rows()
        created = 0
        created_by_code: dict[str, AssetSidebarButton] = {}
        for row in payload:
            button, _created = AssetSidebarButton.objects.get_or_create(
                code=row["code"],
                defaults={
                    "section": row["section"],
                    "label": row["label"],
                    "target_url": row["target_url"],
                    "active_match": row["active_match"],
                    "is_subitem": row["is_subitem"],
                    "sort_order": row["sort_order"],
                    "is_visible": row["is_visible"],
                },
            )
            created_by_code[row["code"]] = button
            created += 1
        for row in payload:
            parent_code = _clean_string(row.get("parent_code"))
            if not parent_code:
                continue
            button = created_by_code.get(row["code"])
            parent = created_by_code.get(parent_code)
            if button is None or parent is None or button.parent_id == parent.id:
                continue
            button.parent = parent
            button.is_subitem = True
            button.section = parent.section
            button.save(update_fields=["parent", "is_subitem", "section", "updated_at"])
        return True, f"Menu sidebar inizializzato ({created} voci)."

    if action == "create_sidebar_button":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci etichetta menu."
        parent_id = _as_int(
            request.POST.get("parent_sidebar_button_id") or request.POST.get("parent_id"),
            default=0,
        )
        parent_button = AssetSidebarButton.objects.filter(pk=parent_id).first() if parent_id else None
        if parent_button and parent_button.parent_id:
            return False, "La voce padre deve essere di primo livello."
        section = _clean_string(request.POST.get("section")) or AssetSidebarButton.SECTION_MAIN
        if section not in valid_sections:
            section = AssetSidebarButton.SECTION_MAIN
        if parent_button is not None:
            section = parent_button.section
        code = _unique_sidebar_button_code(label, request.POST.get("code"))
        # Il form guidato propone le destinazioni da una tendina
        # (target_preset); il campo libero target_url vince se compilato.
        target_url = _clean_string(request.POST.get("target_url"))
        target_preset = _clean_string(request.POST.get("target_preset"))
        if not target_url and target_preset != "__custom__":
            target_url = target_preset
        # Ordine vuoto = in fondo, dopo l'ultima voce sorella.
        if _clean_string(request.POST.get("sort_order")):
            sort_order = _as_int(request.POST.get("sort_order"), default=100)
        else:
            siblings = AssetSidebarButton.objects.filter(section=section, parent=parent_button)
            last_order = siblings.aggregate(last=Max("sort_order"))["last"]
            sort_order = (last_order or 0) + 10
        AssetSidebarButton.objects.create(
            code=code,
            section=section,
            parent=parent_button,
            label=label[:120],
            target_url=target_url,
            active_match=_clean_string(request.POST.get("active_match")),
            is_subitem=True if parent_button is not None else bool(request.POST.get("is_subitem")),
            sort_order=sort_order,
            is_visible=bool(request.POST.get("is_visible")),
        )
        return True, f"Voce menu \"{label}\" creata."

    if action == "update_sidebar_button":
        button_id = _as_int(request.POST.get("sidebar_button_id"), default=0)
        button = AssetSidebarButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Voce menu non trovata."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Etichetta menu obbligatoria."
        parent_id = _as_int(
            request.POST.get("parent_sidebar_button_id") or request.POST.get("parent_id"),
            default=0,
        )
        parent_button = AssetSidebarButton.objects.filter(pk=parent_id).first() if parent_id else None
        if parent_button and parent_button.id == button.id:
            return False, "Una voce non puo essere padre di se stessa."
        if parent_button and parent_button.parent_id:
            return False, "La voce padre deve essere di primo livello."
        section = _clean_string(request.POST.get("section")) or button.section
        if section not in valid_sections:
            section = button.section
        if parent_button is not None:
            section = parent_button.section
        button.section = section
        button.parent = parent_button
        button.label = label[:120]
        button.target_url = _clean_string(request.POST.get("target_url"))
        if "target_preset" in request.POST:
            target_preset = _clean_string(request.POST.get("target_preset"))
            if target_preset != "__custom__":
                button.target_url = target_preset
        button.active_match = _clean_string(request.POST.get("active_match"))
        button.is_subitem = True if parent_button is not None else bool(request.POST.get("is_subitem"))
        button.sort_order = _as_int(request.POST.get("sort_order"), default=button.sort_order)
        button.is_visible = bool(request.POST.get("is_visible"))
        button.save(
            update_fields=[
                "section",
                "parent",
                "label",
                "target_url",
                "active_match",
                "is_subitem",
                "sort_order",
                "is_visible",
                "updated_at",
            ]
        )
        return True, f"Voce menu \"{button.label}\" aggiornata."

    if action == "delete_sidebar_button":
        button_id = _as_int(request.POST.get("sidebar_button_id"), default=0)
        button = AssetSidebarButton.objects.filter(pk=button_id).first()
        if not button:
            return False, "Voce menu non trovata."
        label = button.label
        button.delete()
        return True, f"Voce menu \"{label}\" eliminata."

    if action == "reset_sidebar_buttons":
        deleted, _ = AssetSidebarButton.objects.all().delete()
        payload = _default_sidebar_seed_rows()
        created = 0
        created_by_code: dict[str, AssetSidebarButton] = {}
        for row in payload:
            button, _ = AssetSidebarButton.objects.get_or_create(
                code=row["code"],
                defaults={
                    "section": row["section"],
                    "label": row["label"],
                    "target_url": row["target_url"],
                    "active_match": row["active_match"],
                    "is_subitem": row["is_subitem"],
                    "sort_order": row["sort_order"],
                    "is_visible": row["is_visible"],
                },
            )
            created_by_code[row["code"]] = button
            created += 1
        for row in payload:
            parent_code = _clean_string(row.get("parent_code"))
            if not parent_code:
                continue
            btn = created_by_code.get(row["code"])
            parent = created_by_code.get(parent_code)
            if btn is None or parent is None or btn.parent_id == parent.id:
                continue
            btn.parent = parent
            btn.is_subitem = True
            btn.section = parent.section
            btn.save(update_fields=["parent", "is_subitem", "section", "updated_at"])
        return True, f"Menu sidebar reimpostato ai valori predefiniti ({created} voci, {deleted} eliminate)."

    if action == "clear_sidebar_buttons":
        deleted, _ = AssetSidebarButton.objects.all().delete()
        return True, f"Menu sidebar svuotato ({deleted} voci eliminate). Il portale usa ora il menu predefinito aggiornato."

    return False, "Azione menu non valida."


def _assets_shell_context(
    request: HttpRequest,
    *,
    rows: int = 25,
    search_action: str | None = None,
    new_url: str | None = None,
    new_label: str | None = None,
    search_placeholder: str | None = None,
) -> dict[str, object]:
    logo_url = resolve_module_logo("assets", legacy_logo_keys=("assets_logo_image",)) or None
    display_label = resolve_module_label("assets", fallback="Assets", surface="display")
    return {
        "assets_sidebar_groups": _build_sidebar_groups(request, rows=rows),
        "assets_section_nav": _assets_section_nav(request),
        "assets_shell_search_action": search_action or reverse("assets:asset_list"),
        "assets_shell_new_url": new_url or reverse("assets:asset_create"),
        "assets_shell_new_label": new_label or "+ Nuovo asset",
        "assets_shell_search_placeholder": search_placeholder or "Ricerca rapida per asset, seriali o utenti (Ctrl + K)",
        "can_gestione_admin": user_can_modulo_action(request, "assets", "admin_assets"),
        "assets_logo_url": logo_url,
        "assets_brand_label": display_label,
    }


def _assets_section_nav(request: HttpRequest) -> dict[str, object] | None:
    """Barra di sezione Manutenzione, costruita da ``maintenance_nav``.

    Mostra le voci del ramo a cui appartiene la pagina (Manutenzione o
    Configurazione): stessa definizione, stesso ordine e stesse etichette della
    sidebar.
    """
    from ..maintenance_nav import GROUP_OPERATIVO, find_active

    current_route = _clean_string(getattr(getattr(request, "resolver_match", None), "url_name", ""))
    found = find_active(current_route)
    if found is None:
        return None
    group, active_item = found

    # Gli interventi chiusi sono lo Storico, anche se la rotta e' la lista OdL.
    if current_route == "wo_list" and (
        _clean_string(request.GET.get("view")).lower() == "closed"
        or _clean_string(request.GET.get("status")).upper() in {WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED}
    ):
        active_item = next((item for item in group.items if item.key == "storico"), active_item)

    items = []
    for item in group.items:
        url = reverse(f"assets:{item.route}")
        if item.query:
            url = f"{url}?{item.query}"
        items.append({"key": item.key, "label": item.label, "url": url, "active": item.key == active_item.key})

    workorders_url = reverse("assets:wo_list")
    breadcrumbs = [
        {"label": "Assets", "url": reverse("assets:asset_dashboard")},
        {"label": "Manutenzione", "url": reverse("assets:maintenance_responsabile")},
    ]
    if group.key != GROUP_OPERATIVO:
        breadcrumbs.append({"label": group.label, "url": reverse(f"assets:{group.items[0].route}")})
    breadcrumbs.append({"label": active_item.label, "url": ""})
    from ..maintenance_nav import help_for

    return {
        "label": group.label,
        "active_label": active_item.label,
        "help": help_for(active_item.key),
        "tour_key": f"assets-{active_item.key}",
        "items": items,
        "breadcrumbs": breadcrumbs,
        "actions": (
            [{
                "key": "new-workorder",
                "label": "+ Nuovo intervento",
                "url": f"{workorders_url}?create=1",
                "kind": "primary",
            }]
            if active_item.key in _SECTION_ACTION_NEW_WORKORDER
            else []
        ),
    }


# Pagine dove "+ Nuovo intervento" sta nella barra di sezione: le operative senza
# un pulsante proprio. Interventi ha il suo (con il selettore asset), la
# configurazione e i KPI non aprono lavoro.
_SECTION_ACTION_NEW_WORKORDER = frozenset({"panoramica", "da_fare", "calendario", "scadenzario", "storico"})


# Parent code delle AssetCategory considerate IT/ufficio: gli asset sotto questi
# rami (o con asset_type IT) NON sono posizionabili in planimetria. Tutto il resto
# (gru, impianti a pressione, macchine NO CE, Kardex, attrezzature varie...) e'
# inseribile. Filtro per esclusione cosi nuove categorie di produzione/officina
# restano incluse automaticamente.
_PLANT_LAYOUT_EXCLUDED_CATEGORY_PARENTS = ("information-technology", "physical-security")


def _plant_layout_machine_queryset():
    excluded_category_ids = list(
        AssetCategory.objects.filter(
            Q(code__in=_PLANT_LAYOUT_EXCLUDED_CATEGORY_PARENTS)
            | Q(code__startswith="information-technology")
            | Q(code__startswith="physical-security")
        ).values_list("id", flat=True)
    )
    return (
        Asset.objects.exclude(asset_type__in=IT_DEVICE_TYPES)
        .exclude(asset_category_id__in=excluded_category_ids)
        .select_related("work_machine")
        .order_by("reparto", "name", "asset_tag", "id")
    )


def _plant_layout_machine_catalog(machines=None) -> list[dict[str, object]]:
    machines = _plant_layout_machine_queryset() if machines is None else machines
    catalog: list[dict[str, object]] = []
    for asset in machines:
        machine = getattr(asset, "work_machine", None)
        catalog.append(
            {
                "id": asset.id,
                "asset_tag": asset.asset_tag,
                "internal_number": _clean_string(asset.internal_number),
                "name": asset.name,
                "reparto": _clean_string(asset.reparto),
                "status": asset.get_status_display(),
                "status_code": asset.status,
                "location": _clean_string(asset.assignment_location),
                "manufacturer": _clean_string(asset.manufacturer),
                "model": _clean_string(asset.model),
                "detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                "next_maintenance_date": (
                    machine.next_maintenance_date.strftime("%d-%m-%Y")
                    if isinstance(machine, WorkMachine) and machine.next_maintenance_date
                    else ""
                ),
                "cnc_controlled": bool(getattr(machine, "cnc_controlled", False)),
                "five_axes": bool(getattr(machine, "five_axes", False)),
            }
        )
    return catalog


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert #RRGGBB to rgba(r,g,b,alpha) for CSS compatibility without color-mix()."""
    h = str(hex_color or "").strip().lstrip("#")
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 37, 99, 235  # fallback #2563EB
    return f"rgba({r},{g},{b},{alpha})"


def _open_tickets_by_asset(asset_ids) -> dict[int, list[dict[str, object]]]:
    """Mappa asset_id -> lista ticket aperti (una sola query batch, difensiva).

    Usata per l'overlay ticket sulla planimetria (marker in rosso quando l'asset
    ha ticket aperti). Stati aperti = APERTA/IN_CARICO/IN_ATTESA.
    """
    result: dict[int, list[dict[str, object]]] = defaultdict(list)
    ids = [i for i in (asset_ids or []) if i]
    if not ids:
        return result
    try:
        from tickets.models import StatoTicket, Ticket

        open_states = (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)
        rows = (
            Ticket.objects.filter(asset_id__in=ids, stato__in=open_states)
            .order_by("-created_at", "-id")
            .values("id", "asset_id", "numero_ticket", "titolo", "stato", "priorita")
        )
        label_map = dict(StatoTicket.choices)
        for row in rows:
            try:
                url = reverse("tickets:detail", args=[row["id"]])
            except Exception:
                url = ""
            result[row["asset_id"]].append({
                "id": row["id"],
                "numero": row["numero_ticket"] or f"T-{row['id']}",
                "titolo": row["titolo"] or "Ticket",
                "stato": label_map.get(row["stato"], row["stato"]),
                "priorita": row["priorita"] or "",
                "url": url,
            })
    except Exception:
        return result
    return result


# Stato di ogni macchina sulla mappa officina, dal piu' grave: ticket aperti,
# manutenzione scaduta, OdL aperti, manutenzione in scadenza, in riparazione.
_PLANT_ALERT_LEVELS = ("ticket", "overdue", "workorder", "due_soon", "repair", "ok")
_PLANT_ALERT_LABELS = {
    "ticket": "Ticket aperto",
    "overdue": "Manutenzione scaduta",
    "workorder": "OdL aperto",
    "due_soon": "Manutenzione in scadenza",
    "repair": "In riparazione",
    "ok": "In ordine",
}


def _plant_layout_machine_alerts(assets, *, today=None) -> dict[int, dict[str, object]]:
    """asset_id -> OdL aperti, manutenzioni scadute/in scadenza, in riparazione.

    Due query batch per tutta la mappa; i ticket arrivano da ``_open_tickets_by_asset``."""
    from ..models import MaintenanceOccurrence

    today = today or timezone.localdate()
    now = timezone.now()
    ids = [a.id for a in assets]
    result: dict[int, dict[str, object]] = {
        a.id: {"workorders": [], "workorders_total": 0, "overdue": 0, "due_soon": 0, "next_due": "",
               "in_repair": a.status == Asset.STATUS_IN_REPAIR}
        for a in assets
    }
    if not ids:
        return result
    for wo in (
        WorkOrder.objects.filter(asset_id__in=ids, status=WorkOrder.STATUS_OPEN)
        .only("id", "asset_id", "title", "due_at", "kind", "status")
        .order_by("due_at", "id")
    ):
        row = result[wo.asset_id]
        row["workorders_total"] += 1
        if len(row["workorders"]) < 5:
            row["workorders"].append({
                "id": wo.id,
                "titolo": wo.title or f"OdL #{wo.id}",
                "tipo": wo.get_kind_display(),
                "scadenza": timezone.localtime(wo.due_at).strftime("%d/%m/%Y") if wo.due_at else "",
                "in_ritardo": bool(wo.due_at and wo.due_at < now),
                "url": reverse("assets:wo_view", args=[wo.id]),
            })
    for occ in (
        MaintenanceOccurrence.objects.filter(asset_id__in=ids, status=MaintenanceOccurrence.STATUS_OPEN)
        .only("asset_id", "due_date", "warning_days")
        .order_by("due_date")
    ):
        row = result[occ.asset_id]
        if not row["next_due"]:
            row["next_due"] = occ.due_date.strftime("%d/%m/%Y")
        if occ.due_date < today:
            row["overdue"] += 1
        elif (occ.due_date - today).days <= (occ.warning_days or 0):
            row["due_soon"] += 1
    return result


def _plant_alert_level(alerts: dict[str, object], open_tickets: int) -> str:
    if open_tickets:
        return "ticket"
    if alerts.get("overdue"):
        return "overdue"
    if alerts.get("workorders_total"):
        return "workorder"
    if alerts.get("due_soon"):
        return "due_soon"
    if alerts.get("in_repair"):
        return "repair"
    return "ok"


def _plant_layout_public_payload(layout: PlantLayout | None) -> dict[str, object]:
    empty_counts = {level: 0 for level in _PLANT_ALERT_LEVELS}
    if layout is None:
        return {"layout": None, "areas": [], "markers": [], "markers_with_tickets": 0,
                "alert_counts": empty_counts, "alert_labels": _PLANT_ALERT_LABELS}

    machines = list(_plant_layout_machine_queryset())
    machine_catalog = _plant_layout_machine_catalog(machines)
    alerts = _plant_layout_machine_alerts(machines)
    # ticket solo per le macchine posizionate o nei reparti mappati: sono quelle che la mappa mostra
    area_repartos = {_clean_string(code) for code in layout.areas.values_list("reparto_code", flat=True) if _clean_string(code)}
    shown_ids = set(layout.markers.values_list("asset_id", flat=True)) | {
        row["id"] for row in machine_catalog if _clean_string(str(row.get("reparto") or "")) in area_repartos
    }
    ticket_map = _open_tickets_by_asset(shown_ids)
    for row in machine_catalog:
        info = alerts.get(row["id"], {})
        tickets = ticket_map.get(row["id"], [])
        row["alert"] = _plant_alert_level(info, len(tickets))
        row["alert_label"] = _PLANT_ALERT_LABELS[row["alert"]]
        row["tickets"] = tickets
        row["workorders"] = info.get("workorders", [])
        row["workorders_total"] = info.get("workorders_total", 0)
        row["overdue"] = info.get("overdue", 0)
        row["due_soon"] = info.get("due_soon", 0)
        row["next_due"] = info.get("next_due", "") or row.get("next_maintenance_date", "")
        row["create_wo_url"] = reverse("assets:wo_create", args=[row["id"]])
    machines_by_id = {row["id"]: row for row in machine_catalog}
    reparto_machine_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in machine_catalog:
        reparto_machine_rows[_clean_string(str(row.get("reparto") or ""))].append(row)

    reparto_area_ids: dict[str, list[int]] = defaultdict(list)
    area_payload: list[dict[str, object]] = []
    for area in layout.areas.all().order_by("sort_order", "id"):
        reparto_code = _clean_string(area.reparto_code)
        reparto_area_ids[reparto_code].append(area.id)
        rows = reparto_machine_rows.get(reparto_code, []) if reparto_code else []
        area_payload.append(
            {
                "id": area.id,
                "name": area.name,
                "reparto_code": reparto_code,
                "color": area.color,
                "bg_color": _hex_to_rgba(area.color, 0.22),
                "active_bg_color": _hex_to_rgba(area.color, 0.40),
                "notes": area.notes,
                "x_percent": float(area.x_percent),
                "y_percent": float(area.y_percent),
                "width_percent": float(area.width_percent),
                "height_percent": float(area.height_percent),
                "machine_count": len(rows),
                "alert_count": sum(1 for r in rows if r["alert"] != "ok"),
                "machines": sorted(rows, key=lambda r: _PLANT_ALERT_LEVELS.index(r["alert"])),
                "list_url": (f"{reverse('assets:work_machine_list')}?{urlencode({'reparto': reparto_code})}"
                             if reparto_code else ""),
            }
        )

    marker_payload: list[dict[str, object]] = []
    alert_counts = dict(empty_counts)
    markers_with_tickets = 0
    for marker in layout.markers.all().order_by("sort_order", "id"):
        asset_payload = dict(machines_by_id.get(marker.asset_id) or {})
        tickets = ticket_map.get(marker.asset_id, [])
        alert = asset_payload.get("alert") or ("ticket" if tickets else "ok")
        alert_counts[alert] += 1
        if tickets:
            markers_with_tickets += 1
        asset_payload["marker_id"] = marker.id
        marker_payload.append(
            {
                "id": marker.id,
                "asset_id": marker.asset_id,
                "label": marker.label or asset_payload.get("asset_tag") or asset_payload.get("name") or f"Marker {marker.id}",
                "x_percent": float(marker.x_percent),
                "y_percent": float(marker.y_percent),
                "area_ids": list(reparto_area_ids.get(_clean_string(str(asset_payload.get("reparto") or "")), [])),
                "machine": asset_payload,
                "alert": alert,
                "alert_label": _PLANT_ALERT_LABELS[alert],
                "open_tickets": len(tickets),
                "tickets": tickets,
            }
        )

    return {
        "layout": {
            "id": layout.id,
            "name": layout.name,
            "description": layout.description,
            "image_url": layout.image.url if layout.image else "",
            "is_active": layout.is_active,
        },
        "areas": area_payload,
        "markers": marker_payload,
        "markers_with_tickets": markers_with_tickets,
        "alert_counts": alert_counts,
        "alert_labels": _PLANT_ALERT_LABELS,
    }


def _handle_detail_field_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_sections = {key for key, _ in AssetDetailField.SECTION_CHOICES}
    valid_scopes = {key for key, _ in AssetDetailField.SCOPE_CHOICES}
    valid_formats = {key for key, _ in AssetDetailField.FORMAT_CHOICES}
    valid_card_sizes = {key for key, _ in AssetDetailField.CARD_SIZE_CHOICES}

    if action == "seed_detail_fields":
        created = _seed_default_asset_detail_fields(create_only_if_empty=True)
        if created <= 0:
            return False, "Campi dettaglio gia configurati."
        return True, f"Schema dettaglio asset inizializzato ({created} campi)."

    if action == "create_detail_field":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci etichetta campo dettaglio."
        section = _clean_string(request.POST.get("section")) or AssetDetailField.SECTION_SPECS
        if section not in valid_sections:
            section = AssetDetailField.SECTION_SPECS
        asset_scope = _clean_string(request.POST.get("asset_scope")) or AssetDetailField.SCOPE_ALL
        if asset_scope not in valid_scopes:
            asset_scope = AssetDetailField.SCOPE_ALL
        value_format = _clean_string(request.POST.get("value_format")) or AssetDetailField.FORMAT_AUTO
        if value_format not in valid_formats:
            value_format = AssetDetailField.FORMAT_AUTO
        card_size = _clean_string(request.POST.get("card_size")) or AssetDetailField.CARD_THIRD
        if card_size not in valid_card_sizes:
            card_size = AssetDetailField.CARD_THIRD
        source_ref = _clean_string(request.POST.get("source_ref"))
        if not source_ref:
            return False, "Seleziona il dato da mostrare."
        AssetDetailField.objects.create(
            code=_unique_detail_field_code(label, request.POST.get("code")),
            label=label[:120],
            section=section,
            asset_scope=asset_scope,
            source_ref=source_ref[:120],
            value_format=value_format,
            card_size=card_size,
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            show_if_empty=bool(request.POST.get("show_if_empty")),
            is_active=bool(request.POST.get("is_active")),
        )
        return True, f"Campo dettaglio \"{label}\" creato."

    if action == "update_detail_field_bulk":
        bulk_field = _clean_string(request.POST.get("bulk_field"))
        apply_scope = _clean_string(request.POST.get("apply_scope")) or "selected"
        selected_ids = [
            row
            for row in {
                _as_int(value, default=0)
                for value in request.POST.getlist("selected_detail_field_ids")
            }
            if row > 0
        ]

        if apply_scope == "all":
            detail_fields = list(
                AssetDetailField.objects.order_by("section", "asset_scope", "sort_order", "label", "id")
            )
        else:
            detail_fields = list(
                AssetDetailField.objects.filter(pk__in=selected_ids).order_by(
                    "section", "asset_scope", "sort_order", "label", "id"
                )
            )

        if not detail_fields:
            return False, "Seleziona almeno un campo oppure usa l'opzione per applicare a tutti."

        if bulk_field == "section":
            bulk_value = _clean_string(request.POST.get("bulk_section"))
            if bulk_value not in valid_sections:
                return False, "Sezione bulk non valida."
            for detail_field in detail_fields:
                detail_field.section = bulk_value
                detail_field.save(update_fields=["section", "updated_at"])
            return True, f"Sezione aggiornata per {len(detail_fields)} campi."

        if bulk_field == "asset_scope":
            bulk_value = _clean_string(request.POST.get("bulk_asset_scope"))
            if bulk_value not in valid_scopes:
                return False, "Ambito bulk non valido."
            for detail_field in detail_fields:
                detail_field.asset_scope = bulk_value
                detail_field.save(update_fields=["asset_scope", "updated_at"])
            return True, f"Ambito aggiornato per {len(detail_fields)} campi."

        if bulk_field == "value_format":
            bulk_value = _clean_string(request.POST.get("bulk_value_format"))
            if bulk_value not in valid_formats:
                return False, "Formato bulk non valido."
            for detail_field in detail_fields:
                detail_field.value_format = bulk_value
                detail_field.save(update_fields=["value_format", "updated_at"])
            return True, f"Formato aggiornato per {len(detail_fields)} campi."

        if bulk_field == "card_size":
            bulk_value = _clean_string(request.POST.get("bulk_card_size"))
            if bulk_value not in valid_card_sizes:
                return False, "Dimensione bulk non valida."
            for detail_field in detail_fields:
                detail_field.card_size = bulk_value
                detail_field.save(update_fields=["card_size", "updated_at"])
            return True, f"Dimensione aggiornata per {len(detail_fields)} campi."

        if bulk_field == "show_if_empty":
            bulk_value = _clean_string(request.POST.get("bulk_show_if_empty"))
            if bulk_value not in {"show", "hide"}:
                return False, "Valore bulk per campi vuoti non valido."
            show_if_empty = bulk_value == "show"
            for detail_field in detail_fields:
                detail_field.show_if_empty = show_if_empty
                detail_field.save(update_fields=["show_if_empty", "updated_at"])
            return True, f"Visibilita campi vuoti aggiornata per {len(detail_fields)} campi."

        if bulk_field == "is_active":
            bulk_value = _clean_string(request.POST.get("bulk_is_active"))
            if bulk_value not in {"active", "inactive"}:
                return False, "Stato attivo bulk non valido."
            is_active = bulk_value == "active"
            for detail_field in detail_fields:
                detail_field.is_active = is_active
                detail_field.save(update_fields=["is_active", "updated_at"])
            return True, f"Stato attivo aggiornato per {len(detail_fields)} campi."

        return False, "Parametro bulk non valido."

    if action == "update_detail_field":
        detail_field_id = _as_int(request.POST.get("detail_field_id"), default=0)
        detail_field = AssetDetailField.objects.filter(pk=detail_field_id).first()
        if not detail_field:
            return False, "Campo dettaglio non trovato."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Etichetta campo dettaglio obbligatoria."
        section = _clean_string(request.POST.get("section")) or detail_field.section
        if section not in valid_sections:
            section = detail_field.section
        asset_scope = _clean_string(request.POST.get("asset_scope")) or detail_field.asset_scope
        if asset_scope not in valid_scopes:
            asset_scope = detail_field.asset_scope
        value_format = _clean_string(request.POST.get("value_format")) or detail_field.value_format
        if value_format not in valid_formats:
            value_format = detail_field.value_format
        card_size = _clean_string(request.POST.get("card_size")) or detail_field.card_size
        if card_size not in valid_card_sizes:
            card_size = detail_field.card_size
        source_ref = _clean_string(request.POST.get("source_ref"))
        if not source_ref:
            return False, "Seleziona il dato da mostrare."
        detail_field.label = label[:120]
        detail_field.section = section
        detail_field.asset_scope = asset_scope
        detail_field.source_ref = source_ref[:120]
        detail_field.value_format = value_format
        detail_field.card_size = card_size
        detail_field.sort_order = _as_int(request.POST.get("sort_order"), default=detail_field.sort_order)
        detail_field.show_if_empty = bool(request.POST.get("show_if_empty"))
        detail_field.is_active = bool(request.POST.get("is_active"))
        detail_field.save(
            update_fields=[
                "label",
                "section",
                "asset_scope",
                "source_ref",
                "value_format",
                "card_size",
                "sort_order",
                "show_if_empty",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Campo dettaglio \"{detail_field.label}\" aggiornato."

    if action == "delete_detail_field":
        detail_field_id = _as_int(request.POST.get("detail_field_id"), default=0)
        detail_field = AssetDetailField.objects.filter(pk=detail_field_id).first()
        if not detail_field:
            return False, "Campo dettaglio non trovato."
        label = detail_field.label
        detail_field.delete()
        return True, f"Campo dettaglio \"{label}\" eliminato."

    return False, "Azione dettaglio asset non valida."


def _handle_asset_list_layout_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    if action not in LIST_LAYOUT_ACTIONS:
        return False, "Azione layout lista non valida."

    try:
        layout_id = _as_int(request.POST.get("layout_id"), default=0)
        layout = AssetListLayout.objects.filter(pk=layout_id).first()
        if not layout:
            return False, "Preset lista non trovato."

        definition = _asset_list_context_definition_map().get(layout.context_key, {})
        default_columns = list(definition.get("visible_columns", []) or definition.get("default_columns", []) or [])
        custom_fields = list(AssetCustomField.objects.filter(is_active=True).order_by("sort_order", "id"))
        valid_keys = _asset_list_valid_column_keys(custom_fields)

        if action == "reset_asset_list_layout":
            layout.visible_columns = list(default_columns)
            layout.is_customized = False
            layout.save(update_fields=["visible_columns", "is_customized", "updated_at"])
            return True, f"Vista \"{layout.get_context_key_display()}\" ripristinata."

        selected_columns = _sanitize_asset_list_visible_columns(
            request.POST.getlist("visible_columns"),
            valid_keys,
            fallback=[],
        )
        if not selected_columns:
            return False, "Seleziona almeno una colonna per il preset centrale."

        layout.visible_columns = selected_columns
        layout.is_customized = True
        layout.save(update_fields=["visible_columns", "is_customized", "updated_at"])
        return True, f"Vista \"{layout.get_context_key_display()}\" aggiornata."
    except DatabaseError:
        return False, "Preset lista non disponibile finche il database non e' allineato con le migration."


def _handle_asset_category_request(request: HttpRequest) -> tuple[bool, str]:
    action = _clean_string(request.POST.get("action"))
    valid_asset_types = {key for key, _ in Asset.TYPE_CHOICES}
    valid_field_types = {key for key, _ in AssetCategoryField.TYPE_CHOICES}
    valid_sections = {key for key, _ in AssetDetailField.SECTION_CHOICES}
    valid_formats = {key for key, _ in AssetDetailField.FORMAT_CHOICES}
    valid_card_sizes = {key for key, _ in AssetDetailField.CARD_SIZE_CHOICES}
    valid_sidebar_sections = {key for key, _ in AssetSidebarButton.SECTION_CHOICES}

    if action == "create_asset_category":
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci il nome categoria."
        base_asset_type = _clean_string(request.POST.get("base_asset_type")) or Asset.TYPE_OTHER
        if base_asset_type not in valid_asset_types:
            base_asset_type = Asset.TYPE_OTHER
        parent_id = _as_int(request.POST.get("parent_id"), default=0)
        parent = AssetCategory.objects.filter(pk=parent_id).first() if parent_id else None
        AssetCategory.objects.create(
            code=_unique_asset_category_code(label, request.POST.get("code")),
            label=label[:120],
            parent=parent,
            base_asset_type=base_asset_type,
            description=_clean_string(request.POST.get("description")),
            detail_specs_title=_clean_string(request.POST.get("detail_specs_title"))[:120],
            detail_profile_title=_clean_string(request.POST.get("detail_profile_title"))[:120],
            detail_assignment_title=_clean_string(request.POST.get("detail_assignment_title"))[:120],
            detail_timeline_title=_clean_string(request.POST.get("detail_timeline_title"))[:120],
            detail_maintenance_title=_clean_string(request.POST.get("detail_maintenance_title"))[:120],
            detail_timeline_manual_enabled=bool(request.POST.get("detail_timeline_manual_enabled")),
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_active=bool(request.POST.get("is_active")),
        )
        return True, f"Categoria asset \"{label}\" creata."

    if action == "update_asset_category":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Il nome categoria e obbligatorio."
        base_asset_type = _clean_string(request.POST.get("base_asset_type")) or category.base_asset_type
        if base_asset_type not in valid_asset_types:
            base_asset_type = category.base_asset_type
        parent_id = _as_int(request.POST.get("parent_id"), default=0)
        parent = AssetCategory.objects.filter(pk=parent_id).first() if parent_id else None
        if parent and parent.id == category.id:
            return False, "Una categoria non puo essere padre di se stessa."
        category.label = label[:120]
        category.parent = parent
        category.base_asset_type = base_asset_type
        category.description = _clean_string(request.POST.get("description"))
        category.detail_specs_title = _clean_string(request.POST.get("detail_specs_title"))[:120]
        category.detail_profile_title = _clean_string(request.POST.get("detail_profile_title"))[:120]
        category.detail_assignment_title = _clean_string(request.POST.get("detail_assignment_title"))[:120]
        category.detail_timeline_title = _clean_string(request.POST.get("detail_timeline_title"))[:120]
        category.detail_maintenance_title = _clean_string(request.POST.get("detail_maintenance_title"))[:120]
        category.detail_timeline_manual_enabled = bool(request.POST.get("detail_timeline_manual_enabled"))
        category.sort_order = _as_int(request.POST.get("sort_order"), default=category.sort_order)
        category.is_active = bool(request.POST.get("is_active"))
        category.save(
            update_fields=[
                "label",
                "parent",
                "base_asset_type",
                "description",
                "detail_specs_title",
                "detail_profile_title",
                "detail_assignment_title",
                "detail_timeline_title",
                "detail_maintenance_title",
                "detail_timeline_manual_enabled",
                "sort_order",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Categoria asset \"{category.label}\" aggiornata."

    if action == "create_sidebar_button_for_category":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        if not AssetSidebarButton.objects.exists():
            _create_default_sidebar_buttons()
        target_url = _category_sidebar_target(category.id)
        active_match = _category_sidebar_active_match(category.id)
        existing = AssetSidebarButton.objects.filter(Q(target_url=target_url) | Q(active_match=active_match)).first()
        if existing:
            return False, f"La categoria \"{category.label}\" ha gia una voce menu: {existing.label}."

        parent_id = _as_int(request.POST.get("parent_sidebar_button_id") or request.POST.get("parent_id"), default=0)
        parent_button = AssetSidebarButton.objects.filter(pk=parent_id).first() if parent_id else None
        if parent_button and parent_button.parent_id:
            return False, "La voce padre deve essere di primo livello."
        section = _clean_string(request.POST.get("section")) or AssetSidebarButton.SECTION_MAIN
        if section not in valid_sidebar_sections:
            section = AssetSidebarButton.SECTION_MAIN
        if parent_button is not None:
            section = parent_button.section

        label = _clean_string(request.POST.get("sidebar_label")) or category.label
        AssetSidebarButton.objects.create(
            code=_unique_sidebar_button_code(f"categoria-{category.code}", request.POST.get("code")),
            section=section,
            parent=parent_button,
            label=label[:120],
            target_url=target_url,
            active_match=active_match,
            is_subitem=True if parent_button is not None else bool(request.POST.get("is_subitem")),
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_visible=True,
        )
        return True, f"Voce menu per categoria \"{category.label}\" creata."

    if action == "delete_asset_category":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non trovata."
        linked_assets = category.assets.count()
        if linked_assets:
            return False, f"La categoria \"{category.label}\" e assegnata a {linked_assets} asset: rimuovila prima dagli asset collegati."
        label = category.label
        category.delete()
        return True, f"Categoria asset \"{label}\" eliminata."

    if action == "create_asset_category_field":
        category_id = _as_int(request.POST.get("category_id"), default=0)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Seleziona una categoria valida."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Inserisci il nome campo categoria."
        field_type = _clean_string(request.POST.get("field_type")) or AssetCategoryField.TYPE_TEXT
        if field_type not in valid_field_types:
            field_type = AssetCategoryField.TYPE_TEXT
        detail_section = _clean_string(request.POST.get("detail_section")) or AssetDetailField.SECTION_SPECS
        if detail_section not in valid_sections:
            detail_section = AssetDetailField.SECTION_SPECS
        detail_value_format = _clean_string(request.POST.get("detail_value_format")) or AssetDetailField.FORMAT_AUTO
        if detail_value_format not in valid_formats:
            detail_value_format = AssetDetailField.FORMAT_AUTO
        detail_card_size = _clean_string(request.POST.get("detail_card_size")) or AssetDetailField.CARD_THIRD
        if detail_card_size not in valid_card_sizes:
            detail_card_size = AssetDetailField.CARD_THIRD
        AssetCategoryField.objects.create(
            category=category,
            code=_unique_asset_category_field_code(label, request.POST.get("code")),
            label=label[:120],
            field_type=field_type,
            detail_section=detail_section,
            detail_value_format=detail_value_format,
            detail_card_size=detail_card_size,
            placeholder=_clean_string(request.POST.get("placeholder"))[:160],
            help_text=_clean_string(request.POST.get("help_text"))[:255],
            sort_order=_as_int(request.POST.get("sort_order"), default=100),
            is_required=bool(request.POST.get("is_required")),
            show_in_form=bool(request.POST.get("show_in_form", "1")),
            show_in_detail=bool(request.POST.get("show_in_detail", "1")),
            show_if_empty=bool(request.POST.get("show_if_empty")),
            is_active=bool(request.POST.get("is_active", "1")),
        )
        return True, f"Campo categoria \"{label}\" creato."

    if action == "update_asset_category_field":
        field_id = _as_int(request.POST.get("category_field_id"), default=0)
        field = AssetCategoryField.objects.select_related("category").filter(pk=field_id).first()
        if not field:
            return False, "Campo categoria non trovato."
        category_id = _as_int(request.POST.get("category_id"), default=field.category_id)
        category = AssetCategory.objects.filter(pk=category_id).first()
        if not category:
            return False, "Categoria asset non valida."
        label = _clean_string(request.POST.get("label"))
        if not label:
            return False, "Il nome campo categoria e obbligatorio."
        field_type = _clean_string(request.POST.get("field_type")) or field.field_type
        if field_type not in valid_field_types:
            field_type = field.field_type
        detail_section = _clean_string(request.POST.get("detail_section")) or field.detail_section
        if detail_section not in valid_sections:
            detail_section = field.detail_section
        detail_value_format = _clean_string(request.POST.get("detail_value_format")) or field.detail_value_format
        if detail_value_format not in valid_formats:
            detail_value_format = field.detail_value_format
        detail_card_size = _clean_string(request.POST.get("detail_card_size")) or field.detail_card_size
        if detail_card_size not in valid_card_sizes:
            detail_card_size = field.detail_card_size
        field.category = category
        field.label = label[:120]
        field.field_type = field_type
        field.detail_section = detail_section
        field.detail_value_format = detail_value_format
        field.detail_card_size = detail_card_size
        field.placeholder = _clean_string(request.POST.get("placeholder"))[:160]
        field.help_text = _clean_string(request.POST.get("help_text"))[:255]
        field.sort_order = _as_int(request.POST.get("sort_order"), default=field.sort_order)
        field.is_required = bool(request.POST.get("is_required"))
        field.show_in_form = bool(request.POST.get("show_in_form"))
        field.show_in_detail = bool(request.POST.get("show_in_detail"))
        field.show_if_empty = bool(request.POST.get("show_if_empty"))
        field.is_active = bool(request.POST.get("is_active"))
        field.save(
            update_fields=[
                "category",
                "label",
                "field_type",
                "detail_section",
                "detail_value_format",
                "detail_card_size",
                "placeholder",
                "help_text",
                "sort_order",
                "is_required",
                "show_in_form",
                "show_in_detail",
                "show_if_empty",
                "is_active",
                "updated_at",
            ]
        )
        return True, f"Campo categoria \"{field.label}\" aggiornato."

    if action == "delete_asset_category_field":
        field_id = _as_int(request.POST.get("category_field_id"), default=0)
        field = AssetCategoryField.objects.filter(pk=field_id).first()
        if not field:
            return False, "Campo categoria non trovato."
        label = field.label
        code = field.code
        field.delete()
        touched = _update_asset_category_values_after_delete(code)
        return True, f"Campo categoria \"{label}\" eliminato ({touched} asset ripuliti)."

    return False, "Azione categoria asset non valida."


def _query_url(request: HttpRequest, **overrides) -> str:
    params = request.GET.copy()
    for key, value in overrides.items():
        if value is None:
            params.pop(key, None)
            continue
        params[key] = str(value)
    query = params.urlencode()
    return f"?{query}" if query else ""


def _asset_list_context_definitions() -> list[dict[str, object]]:
    default_columns = list(ASSET_LIST_COMMON_COLUMNS)
    return [
        {
            "key": AssetListLayout.CONTEXT_ALL,
            "label": "Inventario completo",
            "asset_type": "",
            "default_columns": default_columns,
            "sort_order": 100,
        },
        {
            "key": AssetListLayout.CONTEXT_DEVICES,
            "label": "Dispositivi",
            "asset_type": Asset.TYPE_HW,
            "default_columns": default_columns,
            "sort_order": 110,
        },
        {
            "key": AssetListLayout.CONTEXT_SERVERS,
            "label": "Server",
            "asset_type": Asset.TYPE_SERVER,
            "default_columns": default_columns,
            "sort_order": 120,
        },
        {
            "key": AssetListLayout.CONTEXT_WORKSTATIONS,
            "label": "Postazioni di lavoro",
            "asset_type": Asset.TYPE_PC,
            "default_columns": default_columns,
            "sort_order": 130,
        },
        {
            "key": AssetListLayout.CONTEXT_NETWORK,
            "label": "Rete",
            "asset_type": Asset.TYPE_FIREWALL,
            "default_columns": default_columns,
            "sort_order": 140,
        },
        {
            "key": AssetListLayout.CONTEXT_VIRTUAL_MACHINES,
            "label": "Macchine virtuali",
            "asset_type": Asset.TYPE_VM,
            "default_columns": default_columns,
            "sort_order": 150,
        },
        {
            "key": AssetListLayout.CONTEXT_CCTV,
            "label": "Videosorveglianza",
            "asset_type": Asset.TYPE_CCTV,
            "default_columns": default_columns,
            "sort_order": 160,
        },
    ]


def _asset_list_context_definition_map() -> dict[str, dict[str, object]]:
    return {
        str(row["key"]): row
        for row in _asset_list_context_definitions()
    }


def _asset_list_valid_column_keys(custom_fields: list[AssetCustomField]) -> set[str]:
    return set(ASSET_LIST_COMMON_COLUMNS) | set(ASSET_LIST_IT_COLUMNS) | {"qr"}


def _sanitize_asset_list_visible_columns(columns: object, valid_keys: set[str], fallback: list[str] | None = None) -> list[str]:
    cleaned: list[str] = []
    for value in columns if isinstance(columns, list) else []:
        key = _clean_string(value)
        if key and key in valid_keys and key not in cleaned:
            cleaned.append(key)
    if cleaned:
        return cleaned
    return list(fallback or [])


def _asset_list_preview_url(context_key: str, rows: int = 25) -> str:
    definition = _asset_list_context_definition_map().get(context_key, {})
    base_url = reverse("assets:asset_list")
    asset_type = _clean_string(definition.get("asset_type"))
    if asset_type:
        return f"{base_url}?asset_type={quote(asset_type)}&rows={rows}"
    return f"{base_url}?rows={rows}"


def _asset_extra_has_custom_value(extra: object, field: AssetCustomField) -> bool:
    if not isinstance(extra, dict) or field is None:
        return False
    sentinel = object()
    value = extra.get(field.code, sentinel)
    if value is sentinel:
        value = extra.get(field.label, sentinel)
    if value is sentinel:
        return False
    if value in ("", None, [], {}):
        return False
    return True


def _asset_list_relevant_custom_columns(assets_qs, custom_fields: list[AssetCustomField], sample_size: int = 250) -> list[str]:
    if not custom_fields:
        return []
    relevant_codes: list[str] = []
    remaining = {field.code: field for field in custom_fields}
    for asset in assets_qs[:sample_size]:
        extra = asset.extra_columns if isinstance(asset.extra_columns, dict) else {}
        for code, field in list(remaining.items()):
            if _asset_extra_has_custom_value(extra, field):
                relevant_codes.append(code)
                remaining.pop(code, None)
        if not remaining:
            break
    return relevant_codes


ASSET_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ASSET_IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
ASSET_IMAGE_MAX_BYTES = 10 * 1024 * 1024


def _can_edit_asset(request: HttpRequest, asset_id: int) -> bool:
    """Chi puo' aprire la modifica dell'asset puo' anche cambiarne l'immagine."""
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(reverse("assets:asset_edit", args=[asset_id]),
                                    django_user=request.user, request=request))
    except Exception:
        return False


def _validate_asset_image(upload) -> str:
    """Ritorna un messaggio d'errore, oppure stringa vuota se l'immagine e' valida."""
    from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

    if Path(getattr(upload, "name", "") or "").suffix.lower() not in ASSET_IMAGE_EXTENSIONS:
        return "Carica un'immagine PNG, JPG o WEBP."
    if int(getattr(upload, "size", 0) or 0) > ASSET_IMAGE_MAX_BYTES:
        return "L'immagine non puo' superare 10 MB."
    # MIME reale dal contenuto: un SVG/HTML rinominato .png non passa (audit A9).
    try:
        validate_extension_and_mime(
            upload,
            allowed_extensions=ASSET_IMAGE_EXTENSIONS,
            allowed_mimes=ASSET_IMAGE_MIMES,
            max_bytes=ASSET_IMAGE_MAX_BYTES,
            allow_empty=False,
        )
    except UploadMimeValidationError as exc:
        return str(exc)
    finally:
        upload.seek(0)
    try:
        from PIL import Image

        with Image.open(upload) as image:
            image.verify()
    except Exception:
        return "Il file non e' un'immagine valida."
    finally:
        upload.seek(0)
    return ""


def _asset_maintenance_status_payload(status: str) -> dict[str, str]:
    if status == "disabled":
        return {"label": "Disabilitata", "badge_class": "muted"}
    if status == "overridden":
        return {"label": "Personalizzata", "badge_class": "warn"}
    return {"label": "Ereditata", "badge_class": "ok"}


def _maintenance_schedule_status_choices() -> list[tuple[str, str]]:
    return [
        ("attive", "Attive (escludi senza storico)"),
        ("all", "Tutte"),
        ("due", "Solo da gestire"),
        ("overdue", "Scadute"),
        ("warning", "In warning"),
        ("upcoming", "Programmate"),
        ("missing", "Senza storico"),
    ]


def _periodic_verification_schedule_status(
    *, due_date: "date | None", today: date, warning_days: int = 30
) -> dict[str, str]:
    if due_date is None:
        return {"status": "missing", "label": "Da pianificare", "badge_class": "muted"}
    delta = (due_date - today).days
    if delta < 0:
        return {"status": "overdue", "label": f"Scaduta da {abs(delta)} gg", "badge_class": "danger"}
    if delta <= max(0, int(warning_days)):
        if delta == 0:
            return {"status": "warning", "label": "Scade oggi", "badge_class": "warn"}
        return {"status": "warning", "label": f"In scadenza ({delta} gg)", "badge_class": "warn"}
    return {"status": "upcoming", "label": f"Pianificata tra {delta} gg", "badge_class": "ok"}


def _build_maintenance_lookahead_rows(
    *,
    asset_queryset,
    today: date,
    days: int = 90,
) -> list[dict[str, object]]:
    """Costruisce le righe look-ahead raggruppate per settimana ISO su un orizzonte di `days` giorni.
    Ritorna una lista di dict con chiave `week_label`, `week_start`, `week_end`, `rows`."""
    from datetime import timedelta
    horizon = today + timedelta(days=days)
    all_rows = build_day_based_maintenance_schedule_rows(asset_queryset=asset_queryset)
    week_map: dict[tuple, dict] = {}
    for row in all_rows:
        due_date = row.get("due_date")
        if not isinstance(due_date, date):
            continue
        if due_date < today or due_date > horizon:
            continue
        iso = due_date.isocalendar()
        week_key = (iso.year, iso.week)
        if week_key not in week_map:
            week_start = due_date - timedelta(days=due_date.weekday())
            week_end = week_start + timedelta(days=6)
            week_map[week_key] = {
                "week_label": f"Settimana {iso.week}/{iso.year}  ({week_start:%d/%m} - {week_end:%d/%m})",
                "week_start": week_start,
                "week_end": week_end,
                "rows": [],
            }
        row["asset_detail_url"] = reverse("assets:asset_view", kwargs={"id": row["asset"].id})
        week_map[week_key]["rows"].append(row)
    return [week_map[k] for k in sorted(week_map)]


def _maintenance_schedule_periodic_rows(
    *,
    asset_queryset,
    status_filter: str,
    q: str,
    today: date,
) -> list[dict[str, object]]:
    asset_ids = list(asset_queryset.values_list("id", flat=True))
    if not asset_ids:
        return []
    verifications = list(
        PeriodicVerification.objects.select_related("supplier")
        .prefetch_related("assets")
        .filter(is_active=True, assets__id__in=asset_ids)
        .distinct()
    )
    if not verifications:
        return []
    asset_map = {asset.id: asset for asset in asset_queryset}
    rows: list[dict[str, object]] = []
    q_lower = q.casefold() if q else ""
    for verification in verifications:
        for asset in verification.assets.all():
            if asset.id not in asset_map:
                continue
            local_asset = asset_map[asset.id]
            due_date = verification.next_verification_date if isinstance(verification.next_verification_date, date) else None
            schedule = _periodic_verification_schedule_status(due_date=due_date, today=today)
            if status_filter == "due" and schedule["status"] not in {"overdue", "warning", "missing"}:
                continue
            if status_filter == "attive" and schedule["status"] == "missing":
                continue
            if status_filter in {"overdue", "warning", "upcoming", "missing"} and schedule["status"] != status_filter:
                continue
            if q_lower:
                searchable = [
                    local_asset.asset_tag,
                    local_asset.name,
                    local_asset.reparto or "",
                    verification.name or "",
                    str(verification.supplier or ""),
                ]
                if not any(q_lower in (str(chunk) or "").casefold() for chunk in searchable):
                    continue
            rows.append(
                {
                    "asset": local_asset,
                    "asset_detail_url": reverse("assets:asset_view", kwargs={"id": local_asset.id}),
                    "verification": verification,
                    "supplier_label": str(verification.supplier) if verification.supplier_id else "",
                    "frequency_months": verification.frequency_months,
                    "last_execution_date": verification.last_verification_date,
                    "due_date": due_date,
                    "schedule_status": schedule["status"],
                    "schedule_label": schedule["label"],
                    "schedule_badge_class": schedule["badge_class"],
                    "edit_url": _periodic_verifications_page_url(
                        asset_id=local_asset.id,
                        edit_id=verification.id,
                    ),
                    "open_url": _periodic_verifications_page_url(asset_id=local_asset.id),
                    "workorder_create_url": _workorder_create_page_url(
                        asset_id=local_asset.id,
                        periodic_verification_id=verification.id,
                        source="maintenance_schedule",
                    ),
                }
            )
    rows.sort(
        key=lambda row: (
            {"overdue": 0, "warning": 1, "upcoming": 2, "missing": 3}.get(str(row["schedule_status"]), 9),
            row["due_date"] or date.max,
            (row["asset"].reparto or "").casefold(),
            (row["asset"].name or "").casefold(),
            row["asset"].id,
            row["verification"].id,
        )
    )
    return rows


def _machine_availability_map(asset_ids: list[int]) -> dict[int, str]:
    """Ritorna un dict {asset_id: stato} per le macchine richieste.

    Stati: 'occupata' | 'manutenzione' | 'libera'
    """
    if not asset_ids:
        return {}
    today = timezone.localdate()
    result = {aid: "libera" for aid in asset_ids}

    # Macchine in manutenzione (OdL aperto)
    maint_ids = set(
        WorkOrder.objects
        .filter(asset_id__in=asset_ids, status=WorkOrder.STATUS_OPEN)
        .values_list("asset_id", flat=True)
    )
    for aid in maint_ids:
        result[aid] = "manutenzione"

    # Macchine occupate da task lavoro macchina attivi oggi
    try:
        from tasks.models import TaskExtraRef, TaskStatus
        occupied_ids = set(
            TaskExtraRef.objects
            .filter(
                asset_id__in=asset_ids,
                task__category__is_machine_work=True,
                task__status__in=[TaskStatus.TODO, TaskStatus.IN_PROGRESS],
                task__next_step_due__lte=today,
                task__due_date__gte=today,
            )
            .values_list("asset_id", flat=True)
        )
        for aid in occupied_ids:
            result[aid] = "occupata"
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# EXPORT: shared helpers
# ---------------------------------------------------------------------------

def _xl_write_sheet(ws, headers: list, rows: list) -> None:
    import openpyxl.styles as xlst

    # Nomi/note/descrizioni degli asset sono testo libero: le celle passano da
    # core.excel_export (sede unica) per non finire scritte come formula viva.
    from core.excel_export import write_cell, write_row

    fill = xlst.PatternFill(fill_type="solid", fgColor="2563EB")
    hfont = xlst.Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    halign = xlst.Alignment(horizontal="center", vertical="center", wrap_text=True)
    for ci, h in enumerate(headers, 1):
        cell = write_cell(ws, 1, ci, h)
        cell.fill = fill
        cell.font = hfont
        cell.alignment = halign
    ws.row_dimensions[1].height = 20
    for ri, row in enumerate(rows, 2):
        write_row(ws, ri, row)
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max(len(str(col[0].value or "")) + 3, 10), 50)


def _workorder_attachment_accept_attr() -> str:
    return ",".join(sorted(ASSET_DOCUMENT_ALLOWED_EXTENSIONS))


def _validate_workorder_attachment_uploads(
    request: HttpRequest, *, field_name: str = "attachments"
) -> tuple[list, list[str]]:
    uploads = []
    errors: list[str] = []
    for upload in request.FILES.getlist(field_name):
        file_name = Path(getattr(upload, "name", "") or "").name
        try:
            validate_extension_and_mime(
                upload,
                allowed_extensions=ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
                allowed_mimes=ASSET_DOCUMENT_ALLOWED_MIMES,
                max_bytes=ASSET_DOCUMENT_MAX_BYTES,
                label=file_name or "Allegato",
            )
        except UploadMimeValidationError as exc:
            errors.append(str(exc))
            continue
        uploads.append(upload)
    return uploads, errors


def _save_workorder_attachments(
    *, workorder: WorkOrder, uploads: list, user, checklist_item: "WorkOrderChecklist | None" = None
) -> list[WorkOrderAttachment]:
    created: list[WorkOrderAttachment] = []
    for upload in uploads:
        created.append(
            WorkOrderAttachment.objects.create(
                work_order=workorder,
                checklist_item=checklist_item,
                file=upload,
                original_name=Path(getattr(upload, "name", "") or "").name[:255],
                uploaded_by=user if getattr(user, "is_authenticated", False) else None,
            )
        )
    return created


def _apply_workorder_list_filters(get_params, *, include_filters: bool = True):
    qs = (
        WorkOrder.objects
        .select_related(
            "asset",
            "asset__asset_category",
            "periodic_verification",
            "supplier",
            "maintenance_rule",
            "maintenance_rule__intervention_template",
            "assistance_contract",
            "assigned_to",
            "executed_by",
        )
        .all()
    )
    if not include_filters:
        return qs

    status = _clean_string(get_params.get("status"))
    kind = _clean_string(get_params.get("kind"))
    origin = _clean_string(get_params.get("origin"))
    coverage = _clean_string(get_params.get("coverage")) or "all"
    reparto = _clean_string(get_params.get("reparto"))
    category_id = _as_int(get_params.get("category"), default=0)
    assigned_id = _as_int(get_params.get("assigned"), default=0)
    open_age_days = _as_int(get_params.get("open_age"), default=0)
    asset_id = _as_int(get_params.get("asset"), default=0)
    priority = _clean_string(get_params.get("priority"))
    q = _clean_string(get_params.get("q"))

    if priority in dict(WorkOrder.PRIORITY_CHOICES):
        qs = qs.filter(priority=priority)
    if status:
        qs = qs.filter(status=status)
    if kind:
        qs = qs.filter(kind=kind)
    if origin:
        qs = qs.filter(origin=origin)
    if asset_id:
        qs = qs.filter(asset_id=asset_id)
    if coverage == "covered":
        qs = qs.filter(covered_by_contract=True)
    elif coverage == "uncovered":
        qs = qs.filter(covered_by_contract=False)
    if reparto:
        qs = qs.filter(asset__reparto__iexact=reparto)
    if category_id:
        qs = qs.filter(asset__asset_category_id=category_id)
    if assigned_id:
        qs = qs.filter(Q(assigned_to_id=assigned_id) | Q(executed_by_id=assigned_id))
    if open_age_days:
        qs = qs.filter(
            status=WorkOrder.STATUS_OPEN,
            opened_at__lte=timezone.now() - timedelta(days=max(0, open_age_days)),
        )
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(asset__asset_tag__icontains=q)
            | Q(asset__internal_number__icontains=q)
            | Q(asset__name__icontains=q)
            | Q(asset__reparto__icontains=q)
            | Q(asset__asset_category__label__icontains=q)
            | Q(description__icontains=q)
            | Q(resolution__icontains=q)
            | Q(supplier__ragione_sociale__icontains=q)
        )
    return qs


def _resolve_workorder_operational_view(get_params) -> str:
    requested_view = _clean_string(get_params.get("view")).lower()
    if requested_view in {"open", "mine", "unassigned", "closed", "all"}:
        return requested_view
    requested_status = _clean_string(get_params.get("status"))
    if requested_status in {WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED}:
        return "closed"
    return "open"


def _apply_workorder_operational_view(qs, *, operational_view: str, user):
    if operational_view == "mine":
        return qs.filter(status=WorkOrder.STATUS_OPEN, assigned_to=user)
    if operational_view == "unassigned":
        return qs.filter(status=WorkOrder.STATUS_OPEN, assigned_to__isnull=True)
    if operational_view == "closed":
        return qs.filter(status__in=[WorkOrder.STATUS_DONE, WorkOrder.STATUS_CANCELED])
    if operational_view == "all":
        return qs
    return qs.filter(status=WorkOrder.STATUS_OPEN)


def _workorder_list_page_url(**filters) -> str:
    query = {
        key: str(value)
        for key, value in filters.items()
        if value not in (None, "", 0, "0", False)
    }
    base_url = reverse("assets:wo_list")
    query_string = urlencode(query)
    return f"{base_url}?{query_string}" if query_string else base_url


def _due_state(due_date, today):
    """Sorgente unica per lo stato 'giorni residui → danger/warn/ok/muted'.

    Restituisce (state, days_left, days_abs). Usato dalle tabelle dello
    scadenzario (verifiche / scadenze amm. / contratti), che prima
    ricalcolavano questo stesso blocco a mano tre volte.
    """
    if due_date is None:
        return "muted", None, None
    days_left = (due_date - today).days
    if days_left < 0:
        state = "danger"
    elif days_left <= 30:
        state = "warn"
    else:
        state = "ok"
    return state, days_left, abs(days_left)


# Sotto questa copertura un totale e' aneddotico: si mostra quanto e' compilato il
# campo, non la somma. Un numero coperto all'1% non diventa affidabile aggiungendoci
# un'avvertenza.
SOGLIA_DATO_AFFIDABILE = 20


def _copertura_dato(quante: int, totale: int) -> dict[str, object]:
    """Quanto e' compilato un campo facoltativo, e se il totale costruito sopra e'
    presentabile. ``label`` scrive "<1%" e non "0%" quando il dato c'e' ma sta sotto
    l'unita' percentuale: "0%" accanto a "3 su 661" stona.

    Attenzione: durata, fermo macchina e costi hanno default ``0``, non ``NULL``.
    Si contano con ``> 0``, mai con ``exclude(campo=None)`` che restituirebbe il 100%.
    """
    pct = round(100 * quante / totale) if totale else 0
    if not quante:
        label = "0%"
    else:
        label = "<1%" if pct == 0 else f"{pct}%"
    return {
        "rows": quante,
        "total": totale,
        "pct": pct,
        "label": label,
        "reliable": pct >= SOGLIA_DATO_AFFIDABILE,
    }


def _maintenance_plan_by_category_rows() -> list[dict[str, object]]:
    """Piano di manutenzione aggregato per categoria asset (filo conduttore Impostazioni → operativo).

    Per ogni categoria con almeno una regola attiva: conta regole, asset coinvolti e la
    salute della pianificazione (scadute / in scadenza / pianificate / mai eseguite),
    riusando lo scadenzario a giorni. Le regole a contatore (ore/km/cicli) sono conteggiate
    a parte: non rientrano ancora nello scadenzario giornaliero.
    """
    rules_by_cat: dict[int, list[MaintenanceRule]] = {}
    for rule in (
        MaintenanceRule.objects.filter(is_active=True)
        .select_related("asset_category", "intervention_template")
        .order_by("asset_category__sort_order", "asset_category__label", "sort_order", "id")
    ):
        if not rule.asset_category_id:
            continue
        rules_by_cat.setdefault(rule.asset_category_id, []).append(rule)

    agg: dict[int, dict[str, object]] = {}
    try:
        for row in build_day_based_maintenance_schedule_rows():
            asset = row["asset"]
            bucket = agg.setdefault(
                asset.asset_category_id,
                {"assets": set(), "overdue": 0, "warning": 0, "upcoming": 0, "missing": 0},
            )
            bucket["assets"].add(asset.id)
            status = str(row.get("schedule_status") or "")
            if status in ("overdue", "warning", "upcoming", "missing"):
                bucket[status] += 1
    except Exception:
        agg = {}

    rows: list[dict[str, object]] = []
    for cat_id, rules in rules_by_cat.items():
        category = rules[0].asset_category
        bucket = agg.get(cat_id, {"assets": set(), "overdue": 0, "warning": 0, "upcoming": 0, "missing": 0})
        meter_rules = sum(1 for r in rules if r.threshold_type != MaintenanceRule.THRESHOLD_DAYS)
        overdue = int(bucket["overdue"])
        warning = int(bucket["warning"])
        upcoming = int(bucket["upcoming"])
        missing = int(bucket["missing"])
        rows.append(
            {
                "category": category,
                "rules_count": len(rules),
                "day_rules_count": len(rules) - meter_rules,
                "meter_rules_count": meter_rules,
                "assets_count": len(bucket["assets"]),
                "overdue": overdue,
                "warning": warning,
                "upcoming": upcoming,
                "missing": missing,
                "due_total": overdue + warning + missing,
                "schedule_url": _maintenance_schedule_page_url(category_id=cat_id),
                "schedule_due_url": _maintenance_schedule_page_url(category_id=cat_id, status="due"),
                "rules_url": _maintenance_rule_list_page_url(category_id=cat_id),
            }
        )
    rows.sort(
        key=lambda r: (-int(r["overdue"]), -int(r["warning"]), -int(r["missing"]), str(r["category"].label).casefold())
    )
    return rows
