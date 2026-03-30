from django.db import migrations


def add_admin_subnav_map_entry(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.update_or_create(
        code="admin-mappa-permessi-nav",
        defaults={
            "label": "Mappa Permessi",
            "section": "admin_subnav",
            "parent_code": "",
            "route_name": "admin_portale:mappa_permessi_navigazione",
            "url_path": "",
            "order": 205,
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "icon": "MAP",
            "group": "sistema",
            "active_patterns": "admin_portale:mappa_permessi_navigazione",
            "description": "Mappa Permessi/Navigazione: vista unica route, menu, ruoli, override utente e redirect legacy con badge diagnostici.",
        },
    )


def remove_admin_subnav_map_entry(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="admin-mappa-permessi-nav").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0031_admin_subnav_seed"),
    ]

    operations = [
        migrations.RunPython(add_admin_subnav_map_entry, remove_admin_subnav_map_entry),
    ]
