"""Mansionario fase 3: dati.

1. Regola del livello sulla mansione = «media con tetto sulla voce bloccante»
   (decisione D16 del 15/10/2026), solo se la configurazione è ancora quella di
   partenza (MIN): una scelta fatta a mano dalle impostazioni non si tocca.
2. Binding ACL v2 delle nuove pagine del Mansionario, copiati dalla pagina
   principale (0171): chi apre il Mansionario apre anche queste.
"""
from django.db import migrations

ROTTE = (
    "anagrafica:mansionario_competenza_salva",
    "anagrafica:mansionario_competenza_disattiva",
    "anagrafica:mansionario_valuta",
    "anagrafica:mansionario_persona",
    "anagrafica:mansionario_lacune",
)
SORELLA = "anagrafica:mansionario"
NOTA = "[MANSIONARIO_0173] copiato da anagrafica:mansionario"


def regola(apps, schema_editor):
    Config = apps.get_model("anagrafica", "SkillMatrixConfig")
    Config.objects.filter(regola_multivoce="MIN").update(regola_multivoce="MEDIA_TETTO")


def binding_acl(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = None
    for candidata in (SORELLA, "anagrafica:skill_matrix_macchina", "anagrafica:index"):
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    for rotta in ROTTE:
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0172_mansionario_competenze")]
    operations = [
        migrations.RunPython(regola, migrations.RunPython.noop),
        migrations.RunPython(binding_acl, indietro),
    ]
