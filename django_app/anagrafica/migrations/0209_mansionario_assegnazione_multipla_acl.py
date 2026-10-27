"""Binding ACL v2 di «Aggiungi mansioni» dalla scheda persona e del cambio livello
in riga del Mansionario, copiati da «Assegna» della scheda mansione (stessa
operazione e stesso permesso)."""
from django.db import migrations

ROTTE = ("anagrafica:mansionario_persona_assegna", "anagrafica:mansionario_livello")
SORELLE = ("anagrafica:mansionario_assegna", "anagrafica:mansionario", "anagrafica:skill_matrix_macchina")
NOTA = "[MANSIONARIO_0209] copiato da anagrafica:mansionario_assegna"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = None
    for candidata in SORELLE:
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    for rotta in ROTTE:
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("anagrafica", "0208_costo_orario_storico"),
        ("core", "0001_initial"),
    ]
    operations = [migrations.RunPython(avanti, indietro)]
