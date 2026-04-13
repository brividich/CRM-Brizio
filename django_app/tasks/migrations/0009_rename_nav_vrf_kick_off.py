from __future__ import annotations

from django.db import migrations


def rename_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="tasks").update(
        label="VRF - Kick Off",
        description="VRF - Kick Off",
    )


def revert_nav_item(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="tasks").update(
        label="Task",
        description="Task management",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0008_taskimpostazioni_singleton"),
        ("core", "0011_alter_notifica_tipo"),
    ]

    operations = [
        migrations.RunPython(rename_nav_item, reverse_code=revert_nav_item),
    ]
