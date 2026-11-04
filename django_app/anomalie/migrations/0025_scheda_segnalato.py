from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0024_scheda_dettaglio_controllo"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnalato_cliente_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnalato_cliente_da",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnalato_terzista_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnalato_terzista_da",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
    ]
