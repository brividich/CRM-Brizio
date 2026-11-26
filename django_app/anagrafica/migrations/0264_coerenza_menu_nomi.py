"""Nomi del menu Formazione coerenti: «Formazione su mansioni» diventa «Richieste di formazione».

Accanto c'è «Sessioni» (le edizioni dei corsi): il vecchio nome si confondeva. Tocca solo la voce
in Competenze › Formazione e solo se ha ancora il nome dato dalla 0245. Idempotente.
"""
from django.db import migrations

VECCHIO = "Formazione su mansioni"
NUOVO = "Richieste di formazione"


def rinomina(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value="anagrafica:sessioni", etichetta=VECCHIO).update(etichetta=NUOVO)


def indietro(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value="anagrafica:sessioni", etichetta=NUOVO).update(etichetta=VECCHIO)


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0261_efficacia_senza_tipo_permessi"),
    ]

    operations = [
        migrations.RunPython(rinomina, indietro),
    ]
