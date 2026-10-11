"""QR asset: link pubblico opt-in (audit B3) e binding ACL v2 delle route QR.

- ``public_qr_enabled`` nasce False: i nuovi asset non sono raggiungibili senza
  login finche' un utente con permesso non abilita il link. Gli asset esistenti
  NON vengono toccati: le etichette gia' stampate continuano a funzionare.
- Le route QR per asset (``/assets/view/<id>/qr...``) e la stampa multipla
  (``/assets/view/qr-etichette/``) ricevono un binding canonico sul permesso del
  dettaglio asset.
"""
from django.db import migrations, models

NOTE = "[ASSET_QR] Immagine, pannello, link pubblico, etichette multiple"
CODE = "legacy.assets.assets_view"
BINDINGS = [
    (r"^/assets/view/\d+/qr", "regex"),
    ("/assets/view/qr-etichette/", "prefix"),
]


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    db = schema_editor.connection.alias
    Permission.objects.using(db).get_or_create(
        code=CODE, defaults={"module": "assets", "label": "Assets - Dettaglio asset", "is_active": True}
    )
    for pattern, strategy in BINDINGS:
        Binding.objects.using(db).get_or_create(
            route_name="",
            path_pattern=pattern,
            defaults={
                "permission_id": CODE,
                "match_strategy": strategy,
                "source_app": "assets",
                "priority": 100,
                "is_active": True,
                "note": NOTE,
            },
        )


def backwards(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.using(schema_editor.connection.alias).filter(
        note=NOTE
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0123_sidebar_inventario_it_codici_storici"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]
    operations = [
        migrations.AlterField(
            model_name="asset",
            name="public_qr_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(forwards, backwards),
    ]
