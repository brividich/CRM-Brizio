from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0023_scheda_decisione_extra"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="dettaglio_controllo",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
