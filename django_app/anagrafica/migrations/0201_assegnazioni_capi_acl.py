"""Binding ACL di «Ruoli e mansioni in blocco» (export/import Excel) e delle
azioni di «Reparti, aree e capi», copiati dalle pagine sorelle (schema della
0185). Nelle view vale comunque il controllo «amministratore dell'anagrafica»."""
from django.db import migrations

ROTTE = {
    "anagrafica:assegnazioni_export": "anagrafica:ruoli_in_blocco",
    "anagrafica:assegnazioni_import": "anagrafica:ruoli_in_blocco",
    "anagrafica:capi_passaggio": "anagrafica:aree_list",
    "anagrafica:capi_ruolo_aree": "anagrafica:aree_list",
    "anagrafica:capo_assegna": "anagrafica:aree_list",
    "anagrafica:capo_togli": "anagrafica:aree_list",
}
NOTA = "[CAPI_0201] copiato da {}"


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
        ("anagrafica", "0200_responsabilita_area"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
