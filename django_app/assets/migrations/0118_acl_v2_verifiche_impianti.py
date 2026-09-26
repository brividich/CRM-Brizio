"""ACL v2 per «Verifiche periodiche» sugli impianti e per le sue «Categorie».

Fino a qui le rotte ``/assets/manutenzione/verifiche-impianti/...`` non avevano un
binding canonico e ricadevano nel prefisso generico ``/assets``
(``legacy.assets.view_assets``): chi vedeva gli asset vedeva anche le verifiche, e
dal pannello Accessi non si poteva concederle o toglierle a parte.

Aggiunge i due permessi canonici (stessi code che produrrebbe
``bootstrap_acl_v2 --import-legacy`` dai pulsanti di ``assets.acl_bootstrap``) e i
due binding a prefisso; il prefisso piu' lungo vince su ``/assets``.

Nessuno perde l'accesso: i grant di ruolo, utente e gruppo su
``legacy.assets.view_assets`` sono copiati sui due nuovi permessi con lo stesso
``enabled``. Configurare impianti/categorie resta dietro il gate della view
(``can_manage_maintenance_plans``). Idempotente e reversibile.
"""
from django.db import migrations

SOURCE_CODE = "legacy.assets.view_assets"
NOTE = "[ACL_V2_VERIFICHE_IMPIANTI] copiato da legacy.assets.view_assets"

PERMISSIONS = [
    (
        "legacy.assets.assets_periodic_checks",
        "Assets - Verifiche periodiche impianti",
        "/assets/manutenzione/verifiche-impianti",
    ),
    (
        "legacy.assets.assets_periodic_check_categories",
        "Assets - Categorie verifiche periodiche",
        "/assets/manutenzione/verifiche-impianti/categorie",
    ),
]


def _group_grant_model(apps):
    try:
        return apps.get_model("core", "GroupPermissionGrant")
    except LookupError:
        return None


def avanti(apps, schema_editor):
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")
    RolePermissionGrant = apps.get_model("core", "RolePermissionGrant")
    UserPermissionGrant = apps.get_model("core", "UserPermissionGrant")
    GroupPermissionGrant = _group_grant_model(apps)

    source_exists = PermissionDefinition.objects.filter(code=SOURCE_CODE).exists()

    for code, label, path in PERMISSIONS:
        permission, _ = PermissionDefinition.objects.get_or_create(
            code=code,
            defaults={"label": label, "module": "assets", "description": NOTE, "is_active": True},
        )
        RoutePermissionBinding.objects.get_or_create(
            route_name="",
            path_pattern=path,
            defaults={
                "match_strategy": "prefix",
                "permission_id": permission.code,
                "source_app": "assets",
                "note": NOTE,
                "priority": 100,
                "is_active": True,
            },
        )
        if not source_exists:
            continue
        for grant in RolePermissionGrant.objects.filter(permission_id=SOURCE_CODE):
            RolePermissionGrant.objects.get_or_create(
                legacy_role_id=grant.legacy_role_id,
                permission_id=code,
                defaults={"enabled": grant.enabled, "note": NOTE},
            )
        for grant in UserPermissionGrant.objects.filter(permission_id=SOURCE_CODE):
            UserPermissionGrant.objects.get_or_create(
                legacy_user_id=grant.legacy_user_id,
                permission_id=code,
                defaults={"enabled": grant.enabled, "note": NOTE},
            )
        if GroupPermissionGrant is not None:
            for grant in GroupPermissionGrant.objects.filter(permission_id=SOURCE_CODE):
                GroupPermissionGrant.objects.get_or_create(
                    group_id=grant.group_id,
                    permission_id=code,
                    defaults={"enabled": grant.enabled, "note": NOTE},
                )


def indietro(apps, schema_editor):
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    RoutePermissionBinding = apps.get_model("core", "RoutePermissionBinding")
    for code, _label, path in PERMISSIONS:
        RoutePermissionBinding.objects.filter(route_name="", path_pattern=path, note=NOTE).delete()
        # I grant cadono in cascata col permesso.
        PermissionDefinition.objects.filter(code=code, description=NOTE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0117_verifiche_periodiche_misure"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
