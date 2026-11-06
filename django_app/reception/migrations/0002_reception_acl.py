"""Permessi del pannello: gli stessi di «Accessi esterni» (schema create-only come fornitori 0014)."""
from django.db import migrations

ROTTE = {
    "reception:cruscotto": "fornitori:accessi_esterni",
    "reception:registra": "fornitori:accessi_esterni",
    "reception:storico": "fornitori:accessi_esterni",
    "reception:visita_scheda": "fornitori:accessi_esterni",
    "reception:visita_uscita": "fornitori:accessi_esterni",
    "reception:preregistrazioni": "fornitori:accessi_esterni",
    "reception:preregistrazione_azione": "fornitori:accessi_esterni",
    "reception:referenti": "fornitori:accessi_esterni",
    "reception:ditte": "fornitori:accessi_esterni",
    "reception:cartellini": "fornitori:accessi_esterni",
    "reception:impostazioni": "fornitori:accessi_esterni",
}
NOTA = "[RECEPTION_0002] copiato da {}"


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
            permission_id=modello.permission_id, source_app="reception", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):
    dependencies = [("reception", "0001_initial"), ("fornitori", "0014_ingresso_non_serve_acl")]
    operations = [migrations.RunPython(avanti, indietro)]
