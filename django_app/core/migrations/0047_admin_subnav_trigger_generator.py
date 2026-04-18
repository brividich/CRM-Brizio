from django.db import migrations


def add_entry(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.update_or_create(
        code="admin-automazioni-trigger-generator",
        defaults={
            "label": "Generatore Trigger SQL",
            "section": "admin_subnav",
            "parent_code": "",
            "route_name": "admin_portale:automazioni_trigger_generator",
            "url_path": "",
            "order": 135,
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "icon": "TRIGGER",
            "group": "automazioni",
            "active_patterns": "admin_portale:automazioni_trigger_generator",
            "description": "Generatore Trigger SQL: crea e applica trigger SQL Server INSERT/UPDATE per le sorgenti automazioni direttamente dal portale.",
        },
    )


def remove_entry(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="admin-automazioni-trigger-generator").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0046_navigation_fix_icons"),
    ]

    operations = [
        migrations.RunPython(add_entry, remove_entry),
    ]
