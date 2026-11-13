"""Registrare da «Presenti in azienda»: stesso permesso di «Registra ingresso» (reception.pannello.manage).

Si copia il binding attivo di ``reception:registra`` (schema create-only come reception 0002):
chi registra gli ingressi alla reception li registra anche da Presenti, nessun altro.
"""
from django.db import migrations

SORELLA = "reception:registra"
ROTTE = ("reception:presenti_registra", "reception:presenti_come_fornitore")
NOTA = "[RECEPTION_0010] copiato da reception:registra"


def avanti(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = Binding.objects.filter(route_name=SORELLA, is_active=True).order_by("-priority", "pk").first()
    if modello is None:
        return
    for rotta in ROTTE:
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="reception", priority=modello.priority,
            is_active=True, note=NOTA,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()


class Migration(migrations.Migration):
    dependencies = [("reception", "0009_ospite_informativa_versione")]
    operations = [migrations.RunPython(avanti, indietro)]
