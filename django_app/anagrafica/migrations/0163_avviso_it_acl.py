"""Binding ACL v2 del salvataggio «Avviso IT ai nuovi ingressi» (Impostazioni anagrafica).

Copiato da ``anagrafica:workflow_campo_create`` (stessa scheda Onboarding/offboarding), schema della
0160: create-only e idempotente; nella view resta il cancello amministrazione impostazioni.
"""
from django.db import migrations

ROTTE = {"anagrafica:avviso_it_save": "anagrafica:workflow_campo_create"}
NOTA = "[AVVISO_IT_0163] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:impostazioni"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):
    dependencies = [("anagrafica", "0162_account_scheda_acl")]
    operations = [migrations.RunPython(avanti, indietro)]
