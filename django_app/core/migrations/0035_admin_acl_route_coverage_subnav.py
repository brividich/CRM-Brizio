from django.db import migrations


def seed_acl_route_coverage(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(
        code="admin-acl-route-coverage",
        defaults={
            "label": "ACL Route Coverage",
            "section": "admin_subnav",
            "parent_code": "admin-portale",
            "group": "diagnostica",
            "route_name": "admin_portale:acl_route_coverage",
            "url_path": "",
            "order": 396,
            "is_visible": True,
            "is_enabled": True,
            "open_in_new_tab": False,
            "icon": "MAP",
            "active_patterns": "admin_portale:acl_route_coverage",
            "description": "Report route con stati canonical/legacy/unbound per governare la migrazione ACL v2.",
        },
    )


def unseed_acl_route_coverage(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="admin-acl-route-coverage").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_acl_route_coverage, unseed_acl_route_coverage),
    ]
