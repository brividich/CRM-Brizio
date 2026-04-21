from django.db import migrations


_ANOMALIE_ROLE_GRANTS: dict[str, tuple[int, ...]] = {
    "api.anomalie_db.manage": (1, 704),
    "api.anomalie_config.manage": (1,),
    "api.anomalie_config.run": (1,),
    "api.anomalie_config.export": (1,),
    "api.anomalie_filtrato.export": (1, 704),
}

_SEED_NOTE = "[ACL_CUTOVER] seeded da permessi legacy anomalie"


def seed_anomalie_api_role_grants(apps, schema_editor):
    PermissionDefinition = apps.get_model("core", "PermissionDefinition")
    RolePermissionGrant = apps.get_model("core", "RolePermissionGrant")

    available_permissions = {
        code
        for code in PermissionDefinition.objects.filter(code__in=_ANOMALIE_ROLE_GRANTS.keys()).values_list("code", flat=True)
    }

    for permission_code, role_ids in _ANOMALIE_ROLE_GRANTS.items():
        if permission_code not in available_permissions:
            continue
        for role_id in role_ids:
            grant, created = RolePermissionGrant.objects.get_or_create(
                legacy_role_id=role_id,
                permission_id=permission_code,
                defaults={
                    "enabled": True,
                    "note": _SEED_NOTE,
                },
            )
            if created:
                continue
            fields_to_update: list[str] = []
            if not bool(getattr(grant, "enabled", False)):
                grant.enabled = True
                fields_to_update.append("enabled")
            if str(getattr(grant, "note", "") or "") != _SEED_NOTE:
                grant.note = _SEED_NOTE
                fields_to_update.append("note")
            if fields_to_update:
                grant.save(update_fields=fields_to_update)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0049_backfill_navigationitem_required_permission_code"),
    ]

    operations = [
        migrations.RunPython(seed_anomalie_api_role_grants, migrations.RunPython.noop),
    ]
