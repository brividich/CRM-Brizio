"""Binding ACL delle pagine «Struttura del Mansionario» (editor, export/import Excel)
e «Cambio ruoli in blocco», copiati da Mansionario e catalogo ruoli (schema delle
0168/0179). Nelle view vale comunque il controllo «amministratore dell'anagrafica»
(l'export: chi vede il Mansionario)."""
from django.db import migrations

ROTTE = {
    "anagrafica:mansionario_struttura": "anagrafica:mansionario",
    "anagrafica:mansionario_struttura_nuova": "anagrafica:mansionario",
    "anagrafica:mansionario_struttura_mansione": "anagrafica:mansionario",
    "anagrafica:mansionario_struttura_export": "anagrafica:mansionario",
    "anagrafica:mansionario_struttura_import": "anagrafica:mansionario",
    "anagrafica:ruoli_in_blocco": "anagrafica:ruoli_operativi_list",
}
NOTA = "[STRUTTURA_0185] copiato da {}"


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
        ("anagrafica", "0184_retention_acl"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
