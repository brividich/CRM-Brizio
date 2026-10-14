"""Data migration: la voce di menu del modulo diventa «Contatori IT».

Rinomina solo se l'etichetta e' ancora quella di serie («Contatori MFC»): un
nome personalizzato dal NavBuilder resta com'e'.
"""
from django.db import migrations

VECCHIA = "Contatori MFC"
NUOVA = "Contatori IT"


def forwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="contatori", label=VECCHIA).update(label=NUOVA)


def backwards(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.filter(code="contatori", label=NUOVA).update(label=VECCHIA)


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0037_kyocera_contatori_stampa_copia"),
        ("core", "0067_soc_it_cn_category"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=backwards),
    ]
