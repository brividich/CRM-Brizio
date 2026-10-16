"""Ricambi (``/assets/manutenzione/ricambi/``): binding ACL v2 e voce del menu Manutenzione.

La pagina si legge con lo stesso permesso di «Da fare» (chi lavora in manutenzione
vede cosa c'e' a magazzino); le scritture sono controllate nella vista: anagrafica
e rettifiche con ``admin_assets``, scarico su intervento con ``maintenance_execute``.
Nessuna azione ACL nuova. La voce di menu nasce solo se manca, in coda al ramo
«Manutenzione» (deve coincidere con ``maintenance_nav``).
"""
from django.db import migrations
from django.db.models import Max, Q

NOTE = "[ASSET_RICAMBI] Ricambi"
PATH = "/assets/manutenzione/ricambi/"
FALLBACK_CODE = "legacy.assets.assets_view"
BUTTON_CODE = "maintenance_ricambi"


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias

    da_fare = (
        Binding.objects.using(db)
        .filter(Q(path_pattern__startswith="/assets/manutenzione/da-fare") | Q(route_name="maintenance_da_fare"), is_active=True)
        .order_by("-priority", "id")
        .first()
    )
    code = da_fare.permission_id if da_fare else FALLBACK_CODE
    if not da_fare:
        Permission.objects.using(db).get_or_create(
            code=FALLBACK_CODE, defaults={"module": "assets", "label": "Assets - Dettaglio asset", "is_active": True}
        )
    Binding.objects.using(db).get_or_create(
        route_name="",
        path_pattern=PATH,
        defaults={
            "permission_id": code,
            "match_strategy": "prefix",
            "source_app": "assets",
            "priority": 100,
            "is_active": True,
            "note": NOTE,
        },
    )

    if Button.objects.using(db).filter(code=BUTTON_CODE).exists():
        return
    hub = Button.objects.using(db).filter(code="maintenance_hub").first()
    if hub is None:
        return
    last = Button.objects.using(db).filter(parent=hub).aggregate(top=Max("sort_order"))["top"] or 0
    Button.objects.using(db).create(
        code=BUTTON_CODE,
        section=hub.section,
        parent=hub,
        label="Ricambi",
        target_url="django:assets:spare_part_list",
        active_match=PATH,
        is_subitem=True,
        sort_order=last + 10,
        is_visible=True,
    )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "RoutePermissionBinding").objects.using(db).filter(note=NOTE).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0140_ricambi"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
