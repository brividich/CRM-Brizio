"""Data migration: categoria "Qualità / SGI" + voce topbar "Registro OFI".

Rende raggiungibile il registro OFI centralizzato (MOD.174) come strumento
trasversale del portale. La voce eredita il permesso dalla rotta
(`gestione_specifiche.specifica.view`, ACL-aware). Pattern come 0067/0068.
"""
from django.db import migrations

CATEGORY = ("qualita_sgi", "Qualità / SGI", "#0e7490", 68)  # key, label, topbar_color, order

NAV = dict(
    code="ofi_registro",
    label="Registro OFI",
    route_name="gestione_specifiche:ofi_registro",
    section="topbar",
    icon="tool",
    order=66,
    required_permission_code="gestione_specifiche.specifica.view",
)


def forwards(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")

    key, label, color, order = CATEGORY
    cat, _ = ModuleCategory.objects.get_or_create(
        key=key, defaults={"label": label, "topbar_color": color, "order": order}
    )
    changed = False
    if cat.label != label:
        cat.label = label; changed = True
    if cat.topbar_color != color:
        cat.topbar_color = color; changed = True
    if cat.order != order:
        cat.order = order; changed = True
    if changed:
        cat.save()

    # get_or_create sul code (mai update_or_create: non sovrascrive personalizzazioni NavBuilder)
    NavigationItem.objects.get_or_create(
        code=NAV["code"],
        defaults={
            "label": NAV["label"],
            "route_name": NAV["route_name"],
            "section": NAV["section"],
            "icon": NAV["icon"],
            "order": NAV["order"],
            "required_permission_code": NAV["required_permission_code"],
        },
    )
    # Campi "di codice" aggiornabili anche su record esistenti (solo questi):
    NavigationItem.objects.filter(code=NAV["code"]).update(
        route_name=NAV["route_name"],
        required_permission_code=NAV["required_permission_code"],
        category=cat,
    )


def backwards(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="ofi_registro").delete()
    ModuleCategory.objects.filter(key="qualita_sgi").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0068_soc_security_nav"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
