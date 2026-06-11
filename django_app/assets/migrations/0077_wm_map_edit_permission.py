from __future__ import annotations

from django.db import migrations

# Separa visualizzazione ed editing della mappa officina.
# Prima: la route editor (assets:plant_layout_editor) e la route mappa
# (assets:plant_layout_map) erano entrambe legate al permesso unico
# assets.wm_map.view. Questo impediva di dare "solo vista" senza dare anche
# l'editor. Introduciamo assets.wm_map.edit e ci ripuntiamo l'editor.

_VIEW_CODE = "assets.wm_map.view"
_EDIT_CODE = "assets.wm_map.edit"
_EDITOR_ROUTE = "assets:plant_layout_editor"


def _forwards(apps, schema_editor):
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")
    RolePermissionGrant = apps.get_model("core", "RolePermissionGrant")

    view_perm = PermissionDefinition.objects.filter(code=_VIEW_CODE).first()

    edit_perm, _ = PermissionDefinition.objects.update_or_create(
        code=_EDIT_CODE,
        defaults={
            "label": "Assets - Editor mappa officina",
            "module": "assets",
            "description": "Modifica della planimetria officina: reparti e posizionamento macchine.",
            "is_active": True,
        },
    )

    # Ripunta il binding dell'editor da .view a .edit (la mappa resta su .view).
    RoutePermissionBinding.objects.filter(route_name=_EDITOR_ROUTE).update(
        permission_id=_EDIT_CODE
    )

    # Preserva l'accesso: chi aveva il grant su .view (che prima abilitava anche
    # l'editor) ottiene ora anche .edit. Cosi nessun ruolo perde l'editor; per
    # togliere l'editor a un ruolo lasciandogli la vista basta disattivare .edit.
    if view_perm is not None:
        for grant in RolePermissionGrant.objects.filter(permission=view_perm, enabled=True):
            RolePermissionGrant.objects.update_or_create(
                legacy_role_id=grant.legacy_role_id,
                permission=edit_perm,
                defaults={"enabled": True},
            )


def _backwards(apps, schema_editor):
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")

    RoutePermissionBinding.objects.filter(route_name=_EDITOR_ROUTE).update(
        permission_id=_VIEW_CODE
    )
    PermissionDefinition.objects.filter(code=_EDIT_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0076_maintenance_sidebar_unified"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]

    operations = [
        migrations.RunPython(_forwards, reverse_code=_backwards),
    ]
