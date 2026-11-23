"""«Organizzazione»: pagina d'ingresso della sezione, prima voce del pilastro.

Voce «Panoramica» in Organizzazione → Struttura, prima delle altre: è la pagina che si apre
cliccando il pilastro. Permesso della rotta copiato da «Il mio team»: i numeri della struttura
e le tessere li filtra il server (``services/organizzazione_panoramica.py``). Idempotente.
"""
from django.db import migrations

ROTTA = "anagrafica:organizzazione"
SORELLA = "anagrafica:mio_team"
NOTA = "[ORGANIZZAZIONE_0237] copiato da anagrafica:mio_team"
VICINE = ("anagrafica:struttura_org", "anagrafica:esplora_struttura", "anagrafica:aree_list")


def binding(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    if Binding.objects.filter(route_name=ROTTA).exists():
        return
    modello = None
    for candidata in (SORELLA, "anagrafica:mia_scheda"):
        modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
        if modello is not None:
            break
    if modello is None:
        return
    Binding.objects.create(
        route_name=ROTTA, path_pattern="", match_strategy=modello.match_strategy, permission_id=modello.permission_id,
        source_app="anagrafica", priority=modello.priority, is_active=True, note=NOTA,
    )


def voce_menu(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=ROTTA).exists():
        return
    vicina = None
    for url in VICINE:
        vicina = Link.objects.filter(url_value=url).order_by("-is_active", "id").first()
        if vicina is not None and vicina.categoria_id:
            break
    if vicina is None or not vicina.categoria_id:
        return
    primo = Link.objects.filter(categoria_id=vicina.categoria_id).order_by("ordine", "id").first()
    Link.objects.create(
        url_value=ROTTA, url_type="named", etichetta="Panoramica", icona="", gruppo=vicina.gruppo,
        categoria_id=vicina.categoria_id, ordine=max((primo.ordine or 0) - 1, 0) if primo else 179,
        active_view_names=ROTTA, is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name=ROTTA, note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=ROTTA, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0236_processo_sezione_dedicata"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voce_menu, migrations.RunPython.noop),
    ]
