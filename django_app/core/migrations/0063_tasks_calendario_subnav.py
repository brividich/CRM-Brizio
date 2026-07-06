from django.db import migrations

ROW = {
    "code": "tasks-sub-calendario",
    "label": "Calendario",
    "route_name": "tasks:incontri_calendario",
    "order": 25,
    "perm": "tasks.kickoff.view",
}


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code=ROW["code"],
        defaults={
            "label": ROW["label"],
            "section": "subnav",
            "parent_code": "tasks",
            "route_name": ROW["route_name"],
            "order": ROW["order"],
            "required_permission_code": ROW["perm"],
            "is_visible": True,
            "is_enabled": True,
        },
    )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code=ROW["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0062_tasks_da_gestire_subnav")]
    operations = [migrations.RunPython(seed, unseed)]
