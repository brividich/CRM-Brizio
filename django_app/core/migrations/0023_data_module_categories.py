"""Data migration: crea le categorie Manutenzione / HR / Sicurezza
e assegna i NavigationItem (topbar) alle categorie corrispondenti.
"""
from django.db import migrations

CATEGORIES = [
    # key, label, topbar_color, order
    ("manutenzione", "Manutenzione", "#166534", 10),
    ("hr",           "HR",           "#1e40af", 20),
    ("sicurezza",    "Sicurezza",    "#9a3412", 30),
]

# code NavigationItem → category key
ITEM_CATEGORY_MAP = {
    # ── Manutenzione ─────────────────────────────────────────────
    "assets":       "manutenzione",
    "planimetria":  "manutenzione",
    "tickets":      "manutenzione",
    "anomalie":     "manutenzione",
    "rentri":       "manutenzione",
    # ── HR ───────────────────────────────────────────────────────
    "anagrafica":   "hr",
    "assenze":      "hr",
    "timbri":       "hr",
    "notizie":      "hr",
    # ── Sicurezza ────────────────────────────────────────────────
    "diario_preposto":       "sicurezza",
    "rilevazione_incidenti": "sicurezza",
}


def populate_categories(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")

    cat_map = {}
    for key, label, color, order in CATEGORIES:
        obj, _ = ModuleCategory.objects.get_or_create(
            key=key,
            defaults={"label": label, "topbar_color": color, "order": order},
        )
        # aggiorna label/colore se il record esiste già con valori vecchi
        changed = False
        if obj.label != label:
            obj.label = label
            changed = True
        if obj.topbar_color != color:
            obj.topbar_color = color
            changed = True
        if obj.order != order:
            obj.order = order
            changed = True
        if changed:
            obj.save()
        cat_map[key] = obj

    for code, cat_key in ITEM_CATEGORY_MAP.items():
        NavigationItem.objects.filter(code=code, section="topbar").update(
            category=cat_map[cat_key]
        )


def remove_categories(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")
    keys = [k for k, *_ in CATEGORIES]
    NavigationItem.objects.filter(section="topbar").update(category=None)
    ModuleCategory.objects.filter(key__in=keys).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_add_module_category"),
    ]

    operations = [
        migrations.RunPython(populate_categories, reverse_code=remove_categories),
    ]
