"""Permesso della pagina «Collega ingresso»: stesso di «Accessi esterni».

La pagina mostra i dati dell'ingresso (dati personali del visitatore), quindi
segue il permesso della pagina da cui si parte. Il collegamento al singolo
ticket/OdL è verificato nella view con la regola del riquadro (gestore del
ticket / chi esegue le manutenzioni). Schema create-only come la 0005.
"""
from django.db import migrations

ROTTE = {"fornitori:ingresso_collega": "fornitori:accessi_esterni"}
NOTA = "[INGRESSO_COLLEGA_0006] copiato da {}"


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
            permission_id=modello.permission_id, source_app="fornitori", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("fornitori", "0005_guestportal_ditte_acl"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
