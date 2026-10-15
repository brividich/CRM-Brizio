"""Binding ACL v2 della ricerca di Anagrafica (dashboard e sezioni), copiato dalla dashboard
del modulo (schema della 0164): chi apre la dashboard apre la ricerca. I gruppi di risultati
li filtra la view, con i permessi di ciascuna sezione.
"""
from django.db import migrations

ROTTE = {"anagrafica:ricerca": "anagrafica:index"}
NOTA = "[RICERCA_ANAGRAFICA_0168] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
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
    dependencies = [("anagrafica", "0167_visite_fasce_eta_esami")]
    operations = [migrations.RunPython(avanti, indietro)]
