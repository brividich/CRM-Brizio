"""Data migration: assegna il NavigationItem `procedure_refresh` alla categoria
topbar "HR" (finora non categorizzato — nessuna migration lo aveva mai assegnato).

Emerso da riunione di presentazione del portale alla direzione: "procedure refresh
nella voce HR del menu topbar".
"""
from django.db import migrations


def assign_hr_category(apps, schema_editor):
    ModuleCategory = apps.get_model("core", "ModuleCategory")
    NavigationItem = apps.get_model("core", "NavigationItem")
    try:
        hr_category = ModuleCategory.objects.get(key="hr")
    except ModuleCategory.DoesNotExist:
        return
    NavigationItem.objects.filter(code="procedure_refresh", section="topbar").update(
        category=hr_category
    )


def unassign_hr_category(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="procedure_refresh", section="topbar").update(
        category=None
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0065_admin_subnav_notifiche_config"),
    ]

    operations = [
        migrations.RunPython(assign_hr_category, reverse_code=unassign_hr_category),
    ]
