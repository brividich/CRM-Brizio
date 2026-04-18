"""
Migration 0046: corregge le icone NavigationItem che usano nomi Lucide non riconosciuti.

Problema: il bootstrap legacy assegna icona="tool" come default a tutti i pulsanti.
"tool" non veniva riconosciuto da icon_utils -> compariva come testo nel menu.

Questa migration aggiorna i NavigationItem esistenti:
- icon="tool"   → icona semantica appropriata in base a code/label
- icon="bell"   → già riconosciuto dopo fix icon_utils, ma normalizziamo il valore
- icon="zap"    → idem
- icon="trash-2"→ idem

Dopo la migration 0039 (semantic icon defaults), gli item con icon="" o icona breve
avevano già ricevuto l'icona giusta. Questa migration copre i casi rimasti con "tool".
"""
from __future__ import annotations

from django.db import migrations


_CODE_ICON_MAP = {
    "anagrafica": "id-card",
    "anomalie": "octagon-alert",
    "assets": "package",
    "assenze": "calendar-x",
    "automazioni": "zap",
    "dashboard": "layout-dashboard",
    "diario_preposto": "clipboard-list",
    "diario-preposto": "clipboard-list",
    "dpi": "shield-check",
    "notizie": "newspaper",
    "planimetria": "map",
    "procedure_refresh": "file-check",
    "procedure-refresh": "file-check",
    "rentri": "recycle",
    "rilevazione_incidenti": "triangle-alert",
    "rilevazione-incidenti": "triangle-alert",
    "tasks": "list-todo",
    "tickets": "ticket",
    "timbri": "scan",
}

_LABEL_ICON_MAP = {
    "accessi azienda": "key-round",
    "anagrafica": "id-card",
    "anomalie": "octagon-alert",
    "assets": "package",
    "inventario asset": "package",
    "assenze": "calendar-x",
    "automazioni": "zap",
    "dashboard": "layout-dashboard",
    "diario preposto": "clipboard-list",
    "dpi": "shield-check",
    "gestione anomalie": "octagon-alert",
    "kick-off": "list-todo",
    "notizie": "newspaper",
    "planimetria": "map",
    "presa visione": "file-check",
    "procedure refresh": "file-check",
    "rentri": "recycle",
    "rilevazione incidenti": "triangle-alert",
    "tasks": "list-todo",
    "task": "list-todo",
    "ticket": "ticket",
    "tickets": "ticket",
    "timbri": "scan",
    "timbrature": "scan",
}

_ICONS_TO_FIX = {"tool", ""}


def fix_navigation_icons(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    updated = 0
    for item in NavigationItem.objects.filter(icon__in=_ICONS_TO_FIX):
        code_key = str(item.code or "").strip().lower().replace("_", "-")
        label_key = str(item.label or "").strip().lower()

        new_icon = (
            _CODE_ICON_MAP.get(item.code or "")
            or _CODE_ICON_MAP.get(code_key)
            or _LABEL_ICON_MAP.get(label_key)
        )
        if new_icon:
            item.icon = new_icon
            item.save(update_fields=["icon"])
            updated += 1


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0045_fix_assets_nav_url"),
    ]

    operations = [
        migrations.RunPython(fix_navigation_icons, reverse_code=migrations.RunPython.noop),
    ]
