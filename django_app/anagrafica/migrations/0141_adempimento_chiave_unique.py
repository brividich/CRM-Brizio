from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0140_adempimento_chiave_backfill"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="adempimentocambiomansione",
            constraint=models.UniqueConstraint(
                condition=models.Q(("attivo", True)), fields=("assegnazione", "chiave"),
                name="uniq_adempimento_cm_chiave_attivo",
            ),
        ),
    ]
