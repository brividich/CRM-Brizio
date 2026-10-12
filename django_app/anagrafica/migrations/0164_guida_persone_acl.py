"""Binding ACL v2 della «Guida: persone e account», copiato dall'elenco dipendenti (schema della 0160):
chi apre l'elenco apre la guida; la parte di gestione la filtra la view.
"""
from django.db import migrations

ROTTE = {"anagrafica:guida_persone_account": "anagrafica:dipendenti_list"}
NOTA = "[GUIDA_PERSONE_0164] copiato da {}"


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
    dependencies = [("anagrafica", "0163_avviso_it_acl")]
    operations = [migrations.RunPython(avanti, indietro)]
