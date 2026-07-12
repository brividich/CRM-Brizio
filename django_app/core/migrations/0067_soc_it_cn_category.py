"""Data migration: crea la categoria "SOC IT - CN" e la voce topbar del modulo Contatori."""
from django.db import migrations

CATEGORY = ("soc_it_cn", "SOC IT - CN", "#0f766e", 70)  # key, label, topbar_color, order

NAV = dict(
    code="contatori",
    label="Contatori MFC",
    route_name="contatori:dashboard",
    section="topbar",
    icon="printer",
    order=64,
    required_permission_code="contatori.dashboard.view",
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
    NavigationItem.objects.filter(code="contatori").delete()
    ModuleCategory.objects.filter(key="soc_it_cn").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0066_procedure_refresh_hr_category"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
