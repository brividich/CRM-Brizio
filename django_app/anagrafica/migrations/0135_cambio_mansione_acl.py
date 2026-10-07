"""Binding ACL v2 delle pagine del cambio mansione, copiati dalle rotte sorelle.

Con ACL_STRICT_CANONICAL una route senza binding e' negata ai non superuser. I
binding delle pagine di anagrafica vivono nel DB (non nel codice), quindi le
nuove rotte **ereditano il binding della rotta che fa la stessa cosa**: chi oggi
registra/modifica uno spostamento puo' gestirne il piano di adeguamento. Dentro
le view resta il controllo esistente (amministrazione anagrafica / dati HR).

Create-only: un binding gia' presente (anche disattivato a mano) non si tocca.
Se la rotta sorella non ha un binding proprio (coperta da un prefisso), non si
crea nulla: vale lo stesso prefisso.
"""
from django.db import migrations

ROTTE = {
    "anagrafica:adempimento_cambio_mansione_stato": "anagrafica:dipendente_assegnazione_modifica",
    "anagrafica:cambi_mansione": "anagrafica:dipendente_assegnazione_create",
}
NOTA = "[CAMBIO_MANSIONE_0135] copiato da {}"


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
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0134_adempimenti_cambio_mansione"),
        ("core", "0074_admin_subnav_accessi_negati"),
    ]

    operations = [
        migrations.RunPython(avanti, indietro),
    ]
