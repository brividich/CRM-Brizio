"""Data migration: voce topbar "Security Center" nell'area SOC IT - CN (già creata in 0067)."""
from django.db import migrations

NAV = dict(
    code="security_center",
    label="Security Center",
    route_name="security:dashboard",
    section="topbar",
    icon="shield",
    order=65,
    required_permission_code="security.dashboard.view",
)


def forwards(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")

    cat = ModuleCategory.objects.filter(key="soc_it_cn").first()

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
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="security_center").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0066_soc_it_cn_category"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
