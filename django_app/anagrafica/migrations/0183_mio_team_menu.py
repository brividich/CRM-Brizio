"""Pagina «Il mio team» (analisi modulo HR, 16/10/2026): voce di menu in
Persone → Dipendenti.

Nessun binding ACL: la pagina è un percorso condiviso del middleware
(``core.middleware._ACL_SHARED_PREFIXES``, come corsi online e CAPA) perché il
filtro è nella view: ognuno vede solo le persone di cui è responsabile effettivo.
"""
from django.db import migrations

ROTTA = "anagrafica:mio_team"


def voce_menu(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=ROTTA).exists():
        return
    persone = Cat.objects.filter(landing_url_value="anagrafica:dipendenti_list", is_active=True).order_by("id").first()
    if persone is None:
        return
    Link.objects.create(
        categoria=persone, etichetta="Il mio team", icona="", gruppo="Dipendenti",
        url_type="named", url_value=ROTTA, active_view_names=ROTTA,
        ordine=102, apri_nuova_tab=False, is_active=True, is_sistema=False,
    )


def indietro(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=ROTTA).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0182_subnav_mansioni_in_sicurezza"),
    ]

    operations = [
        migrations.RunPython(voce_menu, indietro),
    ]
