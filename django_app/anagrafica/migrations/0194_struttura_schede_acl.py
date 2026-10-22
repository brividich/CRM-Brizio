"""Binding ACL delle schede laterali della Struttura organizzativa (ruolo, mansione,
reparto) e della rinomina del reparto: copiati da quello della pagina. Nelle view
restano i controlli propri (vedere = chi vede il Mansionario, modificare =
amministrazione anagrafica)."""
from django.db import migrations

ROTTE = {
    "anagrafica:struttura_scheda_ruolo": "anagrafica:struttura_org",
    "anagrafica:struttura_scheda_mansione": "anagrafica:struttura_org",
    "anagrafica:struttura_scheda_reparto": "anagrafica:struttura_org",
    "anagrafica:struttura_reparto_rinomina": "anagrafica:struttura_org",
}
NOTA = "[STRUTTURA_ORG_0194] copiato da {}"


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
        ("anagrafica", "0193_mansione_nomi_precedenti"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
