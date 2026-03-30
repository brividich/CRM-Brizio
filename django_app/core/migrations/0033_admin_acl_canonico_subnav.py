from django.db import migrations


def seed_acl_canonico(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code="admin-acl-canonico",
        defaults={
            "label": "ACL Canonico",
            "section": "admin_subnav",
            "parent_code": "admin-portale",
            "group": "diagnostica",
            "route_name": "admin_portale:acl_canonico",
            "url_path": "",
            "order": 395,
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "icon": "V2",
            "active_patterns": "admin_portale:acl_canonico",
            "description": "Gestione permission code canonici, binding route/path e grant ruolo.",
        },
    )


def unseed_acl_canonico(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="admin-acl-canonico").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0032_admin_subnav_acl_nav_map"),
    ]

    operations = [
        migrations.RunPython(seed_acl_canonico, unseed_acl_canonico),
    ]
