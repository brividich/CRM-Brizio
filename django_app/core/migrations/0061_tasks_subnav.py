from django.db import migrations

SEED = [
    {"code": "tasks-sub-dashboard", "label": "Dashboard",
     "route_name": "tasks:list", "order": 10, "perm": "tasks.kickoff.view"},
    {"code": "tasks-sub-kickoff", "label": "Kickoff",
     "route_name": "tasks:project_list", "order": 20, "perm": "tasks.kickoff.projects"},
    {"code": "tasks-sub-impostazioni", "label": "Impostazioni",
     "route_name": "tasks:impostazioni", "order": 30, "perm": "tasks.kickoff.admin"},
]


def _tasks_parent_code(NavigationItem):
    """Codice della NavigationItem top di tasks (fallback 'tasks')."""
    top = (
        NavigationItem.objects.filter(section="topbar", route_name="tasks:list")
        .order_by("id")
        .first()
    )
    return top.code if top else "tasks"


def seed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    parent_code = _tasks_parent_code(NavigationItem)
    for row in SEED:
        NavigationItem.objects.get_or_create(
            code=row["code"],
            defaults={
                "label": row["label"],
                "section": "subnav",
                "parent_code": parent_code,
                "route_name": row["route_name"],
                "order": row["order"],
                "required_permission_code": row["perm"],
                "is_visible": True,
                "is_enabled": True,
            },
        )


def unseed(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code__in=[r["code"] for r in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0060_navitem_bacheca")]
    operations = [migrations.RunPython(seed, unseed)]
