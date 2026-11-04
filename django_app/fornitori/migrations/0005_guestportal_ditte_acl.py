"""Permesso della pagina «Ditte GuestPortal»: stesso di «Modifica fornitore».

Schema delle migrazioni create-only (anagrafica 0148): il binding si copia dalla
rotta sorella; nessun binding se la sorella non ne ha. I riquadri «Presenze in
azienda» sono rotte condivise (core/middleware.py) con il controllo nella view.
"""
from django.db import migrations

ROTTE = {"fornitori:guestportal_ditte": "fornitori:fornitore_edit"}
NOTA = "[GUESTPORTAL_DITTE_0005] copiato da {}"


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
        ("fornitori", "0004_ingressi_interventi"),
        ("core", "0108_nav_home_azioni_rapide"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
