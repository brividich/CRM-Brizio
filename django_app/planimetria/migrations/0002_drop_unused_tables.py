"""Rimuove i modelli Planimetria/Reparto/Macchina creati nella 0001
e mai usati in produzione. La gestione planimetria avviene tramite
assets.PlantLayout / PlantLayoutArea / PlantLayoutMarker."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("planimetria", "0001_initial"),
    ]

    operations = [
        migrations.DeleteModel(name="Macchina"),
        migrations.DeleteModel(name="Reparto"),
        migrations.DeleteModel(name="Planimetria"),
    ]
