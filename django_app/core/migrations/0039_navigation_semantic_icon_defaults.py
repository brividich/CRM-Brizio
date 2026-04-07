from __future__ import annotations

import re

from django.db import migrations


CATEGORY_ICON_DEFAULTS = {
    "hr": "users",
    "manutenzione": "wrench",
    "sicurezza": "shield-check",
}

ITEM_CODE_ICON_DEFAULTS = {
    "anagrafica": "id-card",
    "anomalie": "octagon-alert",
    "assets": "package",
    "assenze": "calendar",
    "dashboard": "layout-dashboard",
    "diario_preposto": "clipboard-list",
    "dpi": "shield-check",
    "notizie": "newspaper",
    "procedure_refresh": "file-check",
    "rentri": "recycle",
    "rilevazione_incidenti": "triangle-alert",
    "tasks": "list-todo",
    "tickets": "ticket",
    "timbri": "scan",
}

ITEM_LABEL_ICON_DEFAULTS = {
    "Accessi azienda": "key-round",
    "Anagrafica": "id-card",
    "Assets": "package",
    "Assenze": "calendar-x",
    "Dashboard": "layout-dashboard",
    "DPI": "shield-check",
    "Diario Preposto": "clipboard-list",
    "Gestione Anomalie": "octagon-alert",
    "Notizie": "newspaper",
    "Presa Visione": "file-check",
    "RENTRI": "recycle",
    "Rilevazione Incidenti": "triangle-alert",
    "Segnalazioni sicurezza": "siren",
    "Task": "list-todo",
    "Ticket": "ticket",
    "Tickets": "ticket",
    "Timbri": "scan",
    "Timbrature": "scan",
}


def _is_placeholder_icon(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return True
    compact = re.sub(r"[^A-Za-z0-9]+", "", raw)
    if not compact:
        return True
    return len(compact) <= 3


def apply_semantic_icon_defaults(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")

    for category in ModuleCategory.objects.filter(key__in=list(CATEGORY_ICON_DEFAULTS.keys())):
        if _is_placeholder_icon(category.icon):
            category.icon = CATEGORY_ICON_DEFAULTS[category.key]
            category.save(update_fields=["icon"])

    items = NavigationItem.objects.all()
    for item in items:
        target_icon = ITEM_CODE_ICON_DEFAULTS.get(item.code) or ITEM_LABEL_ICON_DEFAULTS.get(item.label)
        if not target_icon or not _is_placeholder_icon(item.icon):
            continue
        item.icon = target_icon
        item.save(update_fields=["icon"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_employeeboardtemplate"),
    ]

    operations = [
        migrations.RunPython(apply_semantic_icon_defaults, reverse_code=migrations.RunPython.noop),
    ]
