"""Modelli di report predefiniti + voce di subnav «Reportistica» nel pilastro Persone.

I quattro modelli (personale per cliente, organico, ISO 45001, UNI/PdR 125)
nascono una sola volta e restano modificabili; la voce di menu sta subito dopo
«Report dipendenti» (ordine 141 contro 140). Link NON di sistema: riordinabile
o nascondibile da Impostazioni → Navigazione.
"""
from django.db import migrations

URL_VALUE = "anagrafica:reportistica_index"
CATEGORIA = "Persone"
ETICHETTA = "Reportistica"
ORDINE = 141

ACTIVE_VIEWS = ",".join([
    "anagrafica:reportistica_index",
    "anagrafica:reportistica_genera",
    "anagrafica:reportistica_modello_create",
    "anagrafica:reportistica_modello_edit",
])


def apply(apps, schema_editor):
    from anagrafica.reportistica.predefiniti import crea_predefiniti

    crea_predefiniti(apps.get_model("anagrafica", "ReportModello"), apps.get_model("anagrafica", "ReportBlocco"))

    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()
    if not Link.objects.filter(url_value=URL_VALUE).exists():
        Link.objects.create(
            url_value=URL_VALUE, url_type="named", etichetta=ETICHETTA,
            icona="", gruppo="", categoria=cat, ordine=ORDINE,
            active_view_names=ACTIVE_VIEWS, is_active=True, is_sistema=False,
        )


def revert(apps, schema_editor):
    apps.get_model("anagrafica", "SubnavLinkAnagrafica").objects.filter(url_value=URL_VALUE).delete()
    apps.get_model("anagrafica", "ReportModello").objects.exclude(codice_sistema="").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0128_reportistica_modelli"),
    ]

    operations = [
        migrations.RunPython(apply, revert),
    ]
