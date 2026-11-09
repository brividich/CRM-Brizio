"""«Le mie commesse» nella barra del modulo KICK-OFF: il cruscotto del capocommessa."""
from django.db import migrations

CODE = "tasks-sub-cruscotto"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults={
            "label": "Le mie commesse",
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": "tasks:cruscotto_commesse",
            "order": 13,
            "required_permission_code": "tasks.kickoff.view",
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0112_tasks_subnav_mie_azioni")]
    operations = [migrations.RunPython(seed, unseed)]
