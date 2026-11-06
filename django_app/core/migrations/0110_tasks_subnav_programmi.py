from django.db import migrations

CODE = "tasks-sub-programmi"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=CODE,
        defaults={
            "label": "Programmi",
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": "tasks:programmi_registro",
            "order": 24,
            "required_permission_code": "tasks.kickoff.projects",
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=CODE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0109_tasks_subnav_registro_fai")]
    operations = [migrations.RunPython(seed, unseed)]
