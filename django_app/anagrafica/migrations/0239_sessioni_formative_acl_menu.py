"""Sessioni formative: permesso delle rotte copiato da «Il mio team» e voci di menu.

Le pagine si aprono a chi apre «Il mio team»; che cosa si vede e che cosa si può fare lo decide il
server pagina per pagina (``services/sessioni.py``). Voce «Sessioni formative» in Organizzazione,
gruppo «Richieste» (dopo «Richieste»), e in Competenze, gruppo «Formazione» (dopo «Sessioni»,
le edizioni dei corsi): l'utente le vuole vedere in tutti e due i posti. Idempotente.
"""
from django.db import migrations

SORELLA = "anagrafica:mio_team"
NOTA = "[SESSIONI_0239] copiato da anagrafica:mio_team"
ROTTE = (
    "anagrafica:sessioni", "anagrafica:sessione", "anagrafica:sessione_apri", "anagrafica:sessione_valuta",
    "anagrafica:sessione_firma", "anagrafica:sessione_firma_persona", "anagrafica:sessione_chiudi",
    "anagrafica:sessione_file", "anagrafica:sessione_file_riga",
)
URL = "anagrafica:sessioni"
PAGINE = "anagrafica:sessioni,anagrafica:sessione"
ETICHETTA = "Sessioni formative"


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
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=URL).exists():
        return
    # (voce vicina, ordine dopo di lei, pagine che la accendono). In Formazione la voce non accende
    # niente: altrimenti sulle pagine delle sessioni si illuminerebbero due pilastri insieme.
    for vicina, scarto, pagine in (("anagrafica:richieste", 1, PAGINE), ("anagrafica:formazione_sessioni_list", 1, "")):
        accanto = Link.objects.filter(url_value=vicina).order_by("-is_active", "id").first()
        if accanto is None:
            continue
        Link.objects.create(
            url_value=URL, url_type="named", etichetta=ETICHETTA, icona="", gruppo=accanto.gruppo,
            categoria=accanto.categoria, ordine=accanto.ordine + scarto, active_view_names=pagine,
            is_active=True, is_sistema=False,
        )


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL, is_sistema=False).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0238_sessioni_formative"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(voci_menu, migrations.RunPython.noop),
    ]
