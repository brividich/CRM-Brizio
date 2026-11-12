from django.db import migrations

CODE = "tasks-sub-registro-fai"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults={
            "label": "Registro FAI",
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": "tasks:fai_registro",
            "order": 25,
            "required_permission_code": "tasks.kickoff.projects",
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0108_nav_home_azioni_rapide")]
    operations = [migrations.RunPython(seed, unseed)]
