"""Catalogo software (``/assets/software/``): binding ACL v2 e voce di menu accanto a Licenze software.

Il catalogo si legge con lo stesso permesso delle licenze: si riusa il permesso del binding
già esistente per ``/assets/licenze/`` (se manca, quello del dettaglio asset). La voce di
menu nasce solo se manca, sotto lo stesso genitore di «Licenze software».
"""
from django.db import migrations
from django.db.models import Q

NOTE = "[ASSET_SOFTWARE] Catalogo software"
PATH = "/assets/software/"
FALLBACK_CODE = "legacy.assets.assets_view"
BUTTON_CODE = "catalogo_software"


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias

    licenze = (
        Binding.objects.using(db)
        .filter(Q(path_pattern__startswith="/assets/licenze") | Q(route_name__icontains="software_license_list"), is_active=True)
        .order_by("-priority", "id")
        .first()
    )
    code = licenze.permission_id if licenze else FALLBACK_CODE
    if not licenze:
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
    sibling = Button.objects.using(db).filter(code="licenze").first()
    Button.objects.using(db).create(
        code=BUTTON_CODE,
        section=sibling.section if sibling else "OPERATIONS",
        parent=sibling.parent if sibling else None,
        label="Catalogo software",
        target_url="django:assets:software_catalog",
        active_match=PATH,
        is_subitem=bool(sibling and sibling.parent_id),
        sort_order=(sibling.sort_order + 5) if sibling else 75,
        is_visible=True,
    )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "RoutePermissionBinding").objects.using(db).filter(note=NOTE).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0129_licenza_rinnovi_catalogo_software"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
