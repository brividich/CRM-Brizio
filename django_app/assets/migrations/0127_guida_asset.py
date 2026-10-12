"""Guida Asset in-app (``/assets/guida/``): binding ACL v2 e voce della sidebar.

La guida si legge con lo stesso permesso del dettaglio asset. La voce di menu
viene creata solo se manca: se un amministratore l'ha spostata o nascosta, resta
com'e'.
"""
from django.db import migrations

NOTE = "[ASSET_GUIDA] Guida d'uso del modulo Asset"
CODE = "legacy.assets.assets_view"
PATH = "/assets/guida/"
BUTTON_CODE = "guida_asset"


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias
    Permission.objects.using(db).get_or_create(
        code=CODE, defaults={"module": "assets", "label": "Assets - Dettaglio asset", "is_active": True}
    )
    Binding.objects.using(db).get_or_create(
        route_name="",
        path_pattern=PATH,
        defaults={
            "permission_id": CODE,
            "match_strategy": "prefix",
            "source_app": "assets",
            "priority": 100,
            "is_active": True,
            "note": NOTE,
        },
    )
    if not Button.objects.using(db).filter(code=BUTTON_CODE).exists():
        Button.objects.using(db).create(
            code=BUTTON_CODE,
            section="OPERATIONS",
            label="Guida Asset",
            target_url="django:assets:guida",
            active_match=PATH,
            is_subitem=False,
            sort_order=99,
            is_visible=True,
        )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "RoutePermissionBinding").objects.using(db).filter(note=NOTE).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0126_report_salvati"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
