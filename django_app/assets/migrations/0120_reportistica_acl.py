from django.db import migrations

NOTE = "[ASSET_REPORTING] Impostazioni e archivio privato"
BINDINGS = [
    ("/assets/impostazioni/reportistica", "legacy.assets.admin_assets", "Assets - Impostazioni"),
    ("/assets/reports/archivio", "legacy.assets.assets_reports", "Assets - Reports"),
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    db = schema_editor.connection.alias
    for path, code, label in BINDINGS:
        Permission.objects.using(db).get_or_create(code=code, defaults={"module": "assets", "label": label, "is_active": True})
        Binding.objects.using(db).get_or_create(
            route_name="", path_pattern=path,
            defaults={"permission_id": code, "match_strategy": "prefix", "source_app": "assets", "priority": 100, "is_active": True, "note": NOTE},
        )


def backwards(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.using(schema_editor.connection.alias).filter(note=NOTE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0119_assetreportschedule_assetreportrun"),
        ("contatori", "0007_letturamensilecontatori"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
