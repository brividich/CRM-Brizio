from __future__ import annotations

from django.db import migrations


def add_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code="tasks",
        defaults={
            "label": "Task",
            "section": "topbar",
            "order": 45,
            "route_name": "tasks:list",
            "url_path": "",
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "description": "Task management",
        },
    )


def remove_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="tasks").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0001_initial"),
        ("core", "0011_alter_notifica_tipo"),
    ]

    operations = [
        migrations.RunPython(add_nav_item, reverse_code=remove_nav_item),
    ]
