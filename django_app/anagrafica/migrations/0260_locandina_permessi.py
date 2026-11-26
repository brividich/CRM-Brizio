"""Locandina con QR di corsi ed edizioni: permessi copiati dalla rotta sorella (chi gestisce le presenze)."""
from django.db import migrations

NOTA = "[LOCANDINA_0260] copiato dalla rotta sorella"
SORELLA = "anagrafica:formazione_presenza_set"
ROTTE = ("anagrafica:formazione_sessione_locandina", "anagrafica:formazione_corso_locandina")


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = Binding.objects.filter(route_name=SORELLA, is_active=True).order_by("-priority", "pk").first()
    if modello is None:
        return
    for rotta in ROTTE:
        if not Binding.objects.filter(route_name=rotta).exists():
            Binding.objects.create(route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
                                   permission_id=modello.permission_id, source_app="anagrafica",
                                   priority=modello.priority, is_active=True, note=NOTA)


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_permissiondefinition_rolepermissiongrant_and_more"),
        ("anagrafica", "0259_percorso_video_o_slide"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
