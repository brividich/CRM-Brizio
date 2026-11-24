"""Rotte nuove delle sessioni formative (verbale PDF, storico della persona, contatori delle matricole) e nome della voce in Formazione.

Permesso copiato da «Il mio team», come le altre pagine delle sessioni: che cosa si vede lo decide il
server (``views_sessioni.py``). Idempotente.
"""
from django.db import migrations

SORELLA = "anagrafica:mio_team"
NOTA = "[SESSIONI_0245] copiato da anagrafica:mio_team"
ROTTE = ("anagrafica:sessione_pdf", "anagrafica:storico_competenze_pdf", "anagrafica:sessioni_matricole")


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


def nome_in_formazione(apps, schema_editor):
    """In Competenze › Formazione la voce si chiama «Formazione su mansioni»: accanto c'è «Sessioni» (le edizioni dei corsi)."""
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    vicina = Link.objects.filter(url_value="anagrafica:formazione_sessioni_list").order_by("-is_active", "id").first()
    if vicina is None:
        return
    Link.objects.filter(url_value="anagrafica:sessioni", categoria=vicina.categoria, gruppo=vicina.gruppo,
                        etichetta="Sessioni formative").update(etichetta="Formazione su mansioni")


def indietro(apps, schema_editor):
    apps.get_model("core", "RoutePermissionBinding").objects.filter(route_name__in=ROTTE, note=NOTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0244_onboarding_matricola"),
    ]

    operations = [
        migrations.RunPython(binding, indietro),
        migrations.RunPython(nome_in_formazione, migrations.RunPython.noop),
    ]
