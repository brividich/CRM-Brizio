"""Binding ACL v2 della ricerca «Account portale» del wizard di creazione dipendente (prompt 03 B).

Copiato dalla route sorella ``anagrafica:dipendente_create`` (stesso schema della 0142/0159):
create-only e idempotente; nella view resta il cancello «amministrazione anagrafica».
"""
from django.db import migrations

ROTTE = {"anagrafica:account_portale_cerca": "anagrafica:dipendente_create"}
NOTA = "[ACCOUNT_PORTALE_0160] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
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
    dependencies = [("anagrafica", "0159_viste_elenco_acl")]
    operations = [migrations.RunPython(avanti, indietro)]
