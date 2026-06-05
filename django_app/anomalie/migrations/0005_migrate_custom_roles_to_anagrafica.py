"""Migra i ruoli operativi CUSTOM locali di anomalie verso il catalogo unico
``anagrafica.RuoloOperativo``.

- ogni ``AnomalieRoleDefinition`` NON di sistema -> ``RuoloOperativo`` (per nome);
- le ``AnomalieRoleAccessRule`` con ``role_type`` = code custom -> ri-chiavate su
  ``ruolo_operativo``;
- le ``AnomalieRoleAssignment`` (user -> role custom) -> ``DipendenteRuoloOperativo``
  risolvendo Django user -> Profile.legacy_user_id -> anagrafica_dipendenti.id.

Idempotente: usa get_or_create e salta cio' che e' gia' migrato. I ruoli di
sistema (CC/CAR) restano su ``role_type`` e non vengono toccati.
"""
from django.db import migrations


SYSTEM_ROLE_CODES = {"CC", "CAR"}


def _anagrafica_id_for_user(schema_editor, legacy_user_id):
    """Risolve l'id anagrafica (anagrafica_dipendenti.id) per un legacy_user_id."""
    if not legacy_user_id:
        return None
    with schema_editor.connection.cursor() as cursor:
        try:
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE utente_id = %s",
                [int(legacy_user_id)],
            )
            row = cursor.fetchone()
        except Exception:
            return None
    return int(row[0]) if row else None


def forward(apps, schema_editor):
    RoleDefinition = apps.get_model("anomalie", "AnomalieRoleDefinition")
    RoleAssignment = apps.get_model("anomalie", "AnomalieRoleAssignment")
    AccessRule = apps.get_model("anomalie", "AnomalieRoleAccessRule")
    RuoloOperativo = apps.get_model("anagrafica", "RuoloOperativo")
    DipendenteRuoloOperativo = apps.get_model("anagrafica", "DipendenteRuoloOperativo")
    Profile = apps.get_model("core", "Profile")

    custom_defs = list(RoleDefinition.objects.filter(is_system=False))
    if not custom_defs:
        return

    profile_by_user = dict(Profile.objects.values_list("user_id", "legacy_user_id"))

    # 1) code custom -> RuoloOperativo (creando il catalogo anagrafica se assente)
    code_to_ruolo = {}
    for definition in custom_defs:
        ruolo, _ = RuoloOperativo.objects.get_or_create(
            nome=definition.name[:100],
            defaults={
                "descrizione": definition.description or "",
                "is_active": bool(definition.is_active),
            },
        )
        code_to_ruolo[definition.code] = ruolo

    # 2) regole accesso custom -> ri-chiavatura su ruolo_operativo
    for rule in AccessRule.objects.exclude(role_type="").filter(ruolo_operativo__isnull=True):
        if rule.role_type in SYSTEM_ROLE_CODES:
            continue
        ruolo = code_to_ruolo.get(rule.role_type)
        if ruolo is None:
            continue
        # evita duplicati: se esiste gia' una regola sul ruolo, rimuovi la legacy
        if AccessRule.objects.filter(ruolo_operativo=ruolo).exists():
            rule.delete()
            continue
        rule.ruolo_operativo = ruolo
        rule.role_type = ""
        rule.save(update_fields=["ruolo_operativo", "role_type"])

    # 3) assegnazioni utente -> DipendenteRuoloOperativo
    for assignment in RoleAssignment.objects.all():
        ruolo = code_to_ruolo.get(assignment.role_type)
        if ruolo is None:
            continue  # ruolo di sistema o non custom: nessuna assegnazione in anagrafica
        anagrafica_id = _anagrafica_id_for_user(
            schema_editor, profile_by_user.get(assignment.user_id)
        )
        if anagrafica_id is None:
            continue
        DipendenteRuoloOperativo.objects.get_or_create(
            legacy_anagrafica_id=anagrafica_id,
            ruolo=ruolo,
        )


def backward(apps, schema_editor):
    # Ri-chiavatura non perfettamente reversibile: ripristiniamo role_type dai
    # RuoloOperativo collegati alle regole, senza eliminare il catalogo anagrafica.
    AccessRule = apps.get_model("anomalie", "AnomalieRoleAccessRule")
    RoleDefinition = apps.get_model("anomalie", "AnomalieRoleDefinition")

    name_to_code = {
        d.name: d.code for d in RoleDefinition.objects.filter(is_system=False)
    }
    for rule in AccessRule.objects.filter(ruolo_operativo__isnull=False):
        code = name_to_code.get(getattr(rule.ruolo_operativo, "nome", ""))
        if not code:
            continue
        rule.role_type = code
        rule.ruolo_operativo = None
        rule.save(update_fields=["role_type", "ruolo_operativo"])


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0004_alter_anomalieroleaccessrule_options_and_more"),
        ("anagrafica", "0036_dipendenteanagraficacivile_figli_a_carico_and_more"),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
