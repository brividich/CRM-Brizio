from django.db import migrations, models

BINDING_NOTE = "[ASSET_DOC_ZIP] Cartella documenti in ZIP"
BINDING_CODE = "legacy.assets.assets_view"


def binding(apps, schema_editor):
    """Lo ZIP di una cartella documenti eredita il permesso del dettaglio asset."""
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    db = schema_editor.connection.alias
    Permission.objects.using(db).get_or_create(
        code=BINDING_CODE, defaults={"module": "assets", "label": "Assets - Dettaglio asset", "is_active": True})
    Binding.objects.using(db).get_or_create(
        route_name="", path_pattern=r"^/assets/view/\d+/documenti",
        defaults={"permission_id": BINDING_CODE, "match_strategy": "regex", "source_app": "assets",
                  "priority": 100, "is_active": True, "note": BINDING_NOTE},
    )


def binding_indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.using(schema_editor.connection.alias).filter(
        note=BINDING_NOTE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0174_cartella_categoria_facoltativa"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="assetdocument",
            name="data_scadenza",
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(binding, binding_indietro),
    ]
