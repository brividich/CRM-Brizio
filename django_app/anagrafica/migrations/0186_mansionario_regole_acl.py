"""Binding ACL della pagina «Regole del Mansionario» (soglia operativa, regola di
calcolo, uomo solo), copiato dal Mansionario come le 0185. Nella view vale comunque
il controllo: amministrazione anagrafica o gestione della skill matrix."""
from django.db import migrations

ROTTE = {
    "anagrafica:mansionario_regole": "anagrafica:mansionario",
}
NOTA = "[REGOLE_0186] copiato da {}"


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

    dependencies = [
        ("anagrafica", "0185_struttura_mansionario_acl"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
