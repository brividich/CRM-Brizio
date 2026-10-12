"""Campi extra per tipo attivita': render, serializzazione, salvataggio."""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.urls import reverse


from ..models import (
    Task,
    TaskCategoryFieldType,
    TaskExtraRef,
)

logger = logging.getLogger(__name__)
User = get_user_model()


def _render_task_extra_data(task) -> list[dict]:
    """Risolve i valori salvati in task.extra_data in righe display-ready
    per il template detail: [{'label', 'value', 'href'}]. Per i campi FK
    restituisce display name + link alla scheda.
    """
    if not task.category_id:
        return []
    rows: list[dict] = []
    data = task.extra_data or {}
    fields = list(task.category.fields.all().order_by("order_index", "id"))
    user_ids = {v for v in (data.get(f.code) for f in fields if f.field_type == TaskCategoryFieldType.USER) if v}
    asset_ids = {v for v in (data.get(f.code) for f in fields if f.field_type == TaskCategoryFieldType.ASSET) if v}
    users_map: dict[int, str] = {}
    assets_map: dict[int, tuple[str, str]] = {}
    if user_ids:
        users_map = {
            u.id: (u.get_full_name() or u.username)
            for u in User.objects.filter(pk__in=user_ids)
        }
    if asset_ids:
        try:
            from assets.models import Asset
            for a in Asset.objects.filter(pk__in=asset_ids):
                tag = getattr(a, "asset_tag", "") or getattr(a, "code", "")
                label = f"{tag} - {a.name}" if tag else a.name
                try:
                    href = reverse("assets:asset_view", kwargs={"id": a.id})
                except Exception:
                    href = ""
                assets_map[a.id] = (label, href)
        except Exception:
            pass

    for f in fields:
        raw = data.get(f.code)
        value: str = ""
        href: str = ""
        if f.field_type == TaskCategoryFieldType.CHECKBOX:
            value = "Si" if raw else "No"
        elif f.field_type == TaskCategoryFieldType.MULTISELECT:
            labels = {c["value"]: c["label"] for c in f.normalized_choices()}
            value = ", ".join(labels.get(v, str(v)) for v in (raw or []))
        elif f.field_type == TaskCategoryFieldType.SELECT:
            labels = {c["value"]: c["label"] for c in f.normalized_choices()}
            value = labels.get(raw, str(raw or ""))
        elif f.field_type == TaskCategoryFieldType.USER:
            if raw:
                value = users_map.get(int(raw), f"Utente #{raw}")
        elif f.field_type == TaskCategoryFieldType.ASSET:
            if raw:
                label, href = assets_map.get(int(raw), (f"Asset #{raw}", ""))
                value = label
        else:
            value = "" if raw in (None, "") else str(raw)
        if value == "":
            continue
        rows.append({"label": f.label, "value": value, "href": href, "code": f.code})
    return rows


def _serialize_category_field(field) -> dict:
    return {
        "id": field.id,
        "code": field.code,
        "label": field.label,
        "field_type": field.field_type,
        "required": field.required,
        "order": field.order_index,
        "help_text": field.help_text,
        "placeholder": field.placeholder,
        "choices": field.normalized_choices(),
        "depends_on_code": field.depends_on_code,
        "depends_on_value": field.depends_on_value,
        "asset_type_filter": field.asset_type_filter or "",
        "asset_category_filter": field.asset_category_filter or "",
    }


def _build_asset_options_for_field(field) -> list[dict]:
    """Opzioni asset per un TaskCategoryField di tipo asset.

    Applica i filtri configurati (asset_type_filter, asset_category_filter) e
    esclude in ogni caso gli asset con status RETIRED o IN_STOCK (non sono
    candidati ad attivita operative).
    """
    try:
        from assets.models import Asset
    except ImportError:
        return []
    qs = Asset.objects.exclude(status__in=[Asset.STATUS_RETIRED, Asset.STATUS_IN_STOCK])
    types = field.asset_type_filter_list()
    if types:
        qs = qs.filter(asset_type__in=types)
    cat_ids = field.asset_category_filter_ids()
    if cat_ids:
        qs = qs.filter(asset_category_id__in=cat_ids)
    out: list[dict] = []
    for a in qs.order_by("name")[:500]:
        tag = getattr(a, "asset_tag", "") or ""
        label = f"{tag} - {a.name}" if tag else a.name
        out.append({"value": a.id, "label": label})
    return out


def _persist_task_extra_data(task: "Task", post_data) -> None:
    """Legge i campi extra dal POST per la categoria di `task`, valida i
    valori secondo il catalogo TaskCategoryField e salva:
      - task.extra_data (JSON)
      - TaskExtraRef (righe normalizzate per FK user/asset)
    """
    task.extra_data = task.extra_data or {}

    if not task.category_id:
        if task.extra_data:
            task.extra_data = {}
            task.save(update_fields=["extra_data"])
        TaskExtraRef.objects.filter(task=task).delete()
        return

    fields = list(task.category.fields.all().order_by("order_index", "id"))
    parsed: dict[str, object] = {}
    refs_to_create: list[TaskExtraRef] = []

    for f in fields:
        name = f"extra__{f.code}"
        if f.field_type == TaskCategoryFieldType.CHECKBOX:
            parsed[f.code] = bool(post_data.get(name))
            continue
        if f.field_type == TaskCategoryFieldType.MULTISELECT:
            raw = post_data.getlist(name) if hasattr(post_data, "getlist") else post_data.get(name) or []
            if isinstance(raw, str):
                raw = [raw]
            allowed = {c["value"] for c in f.normalized_choices()}
            parsed[f.code] = [v for v in raw if v in allowed]
            continue
        raw_value = (post_data.get(name) or "").strip()
        if not raw_value:
            parsed[f.code] = ""
            continue
        if f.field_type == TaskCategoryFieldType.NUMBER:
            try:
                parsed[f.code] = float(raw_value) if "." in raw_value else int(raw_value)
            except (TypeError, ValueError):
                parsed[f.code] = raw_value
        elif f.field_type == TaskCategoryFieldType.SELECT:
            allowed = {c["value"] for c in f.normalized_choices()}
            parsed[f.code] = raw_value if raw_value in allowed else ""
        elif f.field_type == TaskCategoryFieldType.USER:
            try:
                uid = int(raw_value)
                if User.objects.filter(pk=uid).exists():
                    parsed[f.code] = uid
                    refs_to_create.append(TaskExtraRef(task=task, field_code=f.code, user_id=uid))
                else:
                    parsed[f.code] = ""
            except (TypeError, ValueError):
                parsed[f.code] = ""
        elif f.field_type == TaskCategoryFieldType.ASSET:
            try:
                aid = int(raw_value)
                from assets.models import Asset
                if Asset.objects.filter(pk=aid).exists():
                    parsed[f.code] = aid
                    refs_to_create.append(TaskExtraRef(task=task, field_code=f.code, asset_id=aid))
                else:
                    parsed[f.code] = ""
            except (TypeError, ValueError, ImportError):
                parsed[f.code] = ""
        else:
            parsed[f.code] = raw_value

    task.extra_data = parsed
    task.save(update_fields=["extra_data"])
    TaskExtraRef.objects.filter(task=task).delete()
    if refs_to_create:
        TaskExtraRef.objects.bulk_create(refs_to_create)
