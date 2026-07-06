from django.db import migrations

ROW = {
    "code": "tasks-sub-da-gestire",
    "label": "Da gestire",
    "route_name": "tasks:da_gestire",
    "order": 15,
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
    dependencies = [("core", "0061_tasks_subnav")]
    operations = [migrations.RunPython(seed, unseed)]
