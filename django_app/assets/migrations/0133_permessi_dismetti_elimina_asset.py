"""Permessi «Dismetti / riattiva» ed «Elimina» dalla scheda asset, gia' attivi per la manutenzione.

Due permessi canonici nuovi (``legacy.assets.asset_retire`` e ``legacy.assets.asset_delete``),
concessi subito ai ruoli legacy il cui nome indica la manutenzione («Manutenzione»,
«Manutentore»...). Gli altri ruoli li ricevono dal pannello Accessi. Gli amministratori
del modulo li hanno gia' senza grant.
"""
from django.db import DatabaseError, migrations, transaction

NOTE = "[ASSET_CICLO_VITA] Dismetti/elimina dalla scheda asset"
PERMESSI = (
    ("legacy.assets.asset_retire", "Assets - Dismetti / riattiva asset"),
    ("legacy.assets.asset_delete", "Assets - Elimina asset (senza storico)"),
)
RUOLI_MANUTENZIONE = ("manutenz", "manutent")


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Grant = apps.get_model("core", "RolePermissionGrant")
    Ruolo = apps.get_model("core", "Ruolo")
    db = schema_editor.connection.alias

    for code, label in PERMESSI:
        Permission.objects.using(db).update_or_create(
            code=code,
            defaults={"label": label, "module": "assets", "description": NOTE, "is_active": True},
        )

    try:
        with transaction.atomic(using=db):
            ruoli = list(Ruolo.objects.using(db).values_list("id", "nome"))
    except DatabaseError:
        # Tabella legacy ``ruoli`` assente (DB di sviluppo vuoto): i grant si danno da Accessi.
        return
    for role_id, nome in ruoli:
        if not any(chiave in str(nome or "").lower() for chiave in RUOLI_MANUTENZIONE):
            continue
        for code, _label in PERMESSI:
            Grant.objects.using(db).get_or_create(
                legacy_role_id=int(role_id),
                permission_id=code,
                defaults={"enabled": True, "note": NOTE},
            )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    codes = [code for code, _label in PERMESSI]
    apps.get_model("core", "RolePermissionGrant").objects.using(db).filter(permission_id__in=codes).delete()
    apps.get_model("core", "PermissionDefinition").objects.using(db).filter(code__in=codes).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0132_occorrenza_rinvio"),
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
    ]
    operations = [migrations.RunPython(forwards, backwards)]
