"""Voce di subnav «Recruiting» nel pilastro Persone.

Il modulo era raggiungibile solo dalla pill «Vai a» della dashboard HR: fuori
dal menu di modulo, quindi invisibile a chi naviga dalla topbar. La voce sta
appena prima di «Onboarding» (ordine 118 contro 120) perché la selezione
precede l'inserimento: l'ordine del menu segue quello del processo.

Link NON di sistema: riordinabile/nascondibile da Impostazioni → Navigazione.
"""
from django.db import migrations

URL_VALUE = "anagrafica:recruiting_list"
CATEGORIA = "Persone"
ETICHETTA = "Recruiting"
ORDINE = 118

# Tutte le pagine del modulo evidenziano la stessa voce di menu.
ACTIVE_VIEWS = ",".join([
    "anagrafica:recruiting_list",
    "anagrafica:recruiting_detail",
    "anagrafica:recruiting_create",
    "anagrafica:recruiting_edit",
    "anagrafica:recruiting_dashboard",
    "anagrafica:recruiting_criteri",
])


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()

    link = Link.objects.filter(url_value=URL_VALUE).order_by("id").first()
    if link is None:
        Link.objects.create(
            url_value=URL_VALUE, url_type="named", etichetta=ETICHETTA,
            icona="", gruppo="", categoria=cat, ordine=ORDINE,
            active_view_names=ACTIVE_VIEWS, is_active=True, is_sistema=False,
        )
    else:
        link.categoria = cat
        link.gruppo = ""
        link.etichetta = ETICHETTA
        link.ordine = ORDINE
        link.is_active = True
        if not link.active_view_names:
            link.active_view_names = ACTIVE_VIEWS
        link.save()


def reverse_subnav(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value=URL_VALUE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0088_recruiting_criteri_seed"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
