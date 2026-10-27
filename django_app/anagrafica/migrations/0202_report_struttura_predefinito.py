"""Modello di report pronto «Struttura: ruoli, mansioni e capi» (27/10/2026).

Crea solo i predefiniti mancanti (per ``codice_sistema``): i modelli esistenti
e le modifiche fatte dagli utenti non vengono toccati.
"""
from django.db import migrations


def apply(apps, schema_editor):
    from anagrafica.reportistica.predefiniti import crea_predefiniti

    crea_predefiniti(apps.get_model("anagrafica", "ReportModello"), apps.get_model("anagrafica", "ReportBlocco"))


def revert(apps, schema_editor):
    apps.get_model("anagrafica", "ReportModello").objects.filter(codice_sistema="struttura_ruoli_capi").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0201_assegnazioni_capi_acl"),
    ]

    operations = [
        migrations.RunPython(apply, revert),
    ]
