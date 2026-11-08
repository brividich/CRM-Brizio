"""«Le mie azioni» nella barra del modulo KICK-OFF.

È il posto dove chi riceve un'attività, un'azione o un problema la gestisce:
prima ci si arrivava solo dalla dashboard o dalla mail.
"""
from django.db import migrations

CODE = "tasks-sub-mie-azioni"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults={
            "label": "Le mie azioni",
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": "tasks:mie_azioni",
            "order": 12,
            "required_permission_code": "tasks.kickoff.view",
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0111_tasks_subnav_report_fai")]
    operations = [migrations.RunPython(seed, unseed)]
