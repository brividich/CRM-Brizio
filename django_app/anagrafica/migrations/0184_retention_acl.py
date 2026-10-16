"""Binding ACL della pagina «Conservazione dei dati» (/anagrafica/impostazioni/retention/),
copiato da quello delle Impostazioni dell'anagrafica (schema delle 0168/0179).
Nella view vale comunque il controllo «amministratore dell'anagrafica»."""
from django.db import migrations

ROTTA = "anagrafica:retention"
SORELLE = ("anagrafica:impostazioni", "anagrafica:dipendenti_list")
NOTA = "[RETENTION_0184] copiato da {}"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name=ROTTA).exists():
        return
    for sorella in SORELLE:
        modello = Binding.objects.filter(route_name=sorella, is_active=True).order_by("-priority", "pk").first()
        if modello is None:
            continue
        Binding.objects.create(
            route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )
        return


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(
        route_name=ROTTA, note__startswith="[RETENTION_0184]").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0183_mio_team_menu"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
