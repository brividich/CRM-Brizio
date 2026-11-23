"""Voce di menu «P11TF12 – Foratura critica» accanto a «Processi qualificati».

Stessa categoria e stesso gruppo della voce del cruscotto MOD.128 (dove l'utente l'ha
lasciata), subito dopo. Idempotente per ``url_value``; una voce già presente non si tocca.
"""
from django.db import migrations

URL = "anagrafica:mpq_p11tf12"
ETICHETTA = "P11TF12 – Foratura critica"


def aggiungi(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    if Link.objects.filter(url_value=URL).exists():
        return
    vicino = Link.objects.filter(url_value="anagrafica:mpq_cruscotto").order_by("-is_active", "id").first()
    if vicino is not None:
        categoria, gruppo, ordine = vicino.categoria, vicino.gruppo, (vicino.ordine or 0) + 1
    else:
        categoria = Cat.objects.filter(nome="Competenze").order_by("id").first()
        gruppo, ordine = "Qualifiche", 259
    if categoria is None:
        return
    Link.objects.create(
        url_value=URL, url_type="named", etichetta=ETICHETTA, icona="", gruppo=gruppo,
        categoria=categoria, ordine=ordine, active_view_names=URL, is_active=True, is_sistema=False,
    )


def togli(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0231_elearning_link_aperto"),
    ]

    operations = [
        migrations.RunPython(aggiungi, togli),
    ]
