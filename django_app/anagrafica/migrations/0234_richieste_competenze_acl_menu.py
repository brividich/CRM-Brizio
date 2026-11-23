"""Richieste su mansioni e competenze: permesso delle rotte copiato da «Il mio team» e voci di menu.

Le pagine si aprono a chi apre «Il mio team»; che cosa si vede lo decide il server pagina per
pagina (``services/richieste.py``). Voci «Da fare» e «Richieste» nel pilastro Competenze, gruppo
«Richieste». Idempotente: rotte e voci già presenti non si toccano.
"""
from django.db import migrations

SORELLA = "anagrafica:mio_team"
NOTA = "[RICHIESTE_0234] copiato da anagrafica:mio_team"
ROTTE = (
    "anagrafica:richieste_da_fare", "anagrafica:richieste", "anagrafica:richiesta_nuova",
    "anagrafica:richiesta", "anagrafica:richiesta_decidi",
)
# (destinazione, etichetta, ordine, pagine che la tengono accesa)
VOCI = (
    ("anagrafica:richieste_da_fare", "Da fare", 240, ("anagrafica:richieste_da_fare",)),
    ("anagrafica:richieste", "Richieste", 241,
     ("anagrafica:richieste", "anagrafica:richiesta", "anagrafica:richiesta_nuova")),
)
GRUPPO = "Richieste"


def binding(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    modello = None
    for candidata in (SORELLA, "anagrafica:mia_scheda"):
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


def voci_menu(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    vicino = Link.objects.filter(url_value="anagrafica:matrice_competenze").order_by("-is_active", "id").first()
    categoria = vicino.categoria if vicino is not None else Cat.objects.filter(nome="Competenze").order_by("id").first()
    if categoria is None:
        return
    for url, etichetta, ordine, pagine in VOCI:
        if Link.objects.filter(url_value=url).exists():
            continue
        Link.objects.create(
            url_value=url, url_type="named", etichetta=etichetta, icona="", gruppo=GRUPPO, categoria=categoria,
            ordine=ordine, active_view_names=",".join(pagine), is_active=True, is_sistema=False,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(
        url_value__in=[v[0] for v in VOCI], is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0233_richieste_competenze"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voci_menu, migrations.RunPython.noop),
    ]
