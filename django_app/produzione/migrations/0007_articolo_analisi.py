from django.db import migrations, models


class Migration(migrations.Migration):
    """Analisi delle quote precalcolata per P/N: Quote CMM legge questi numeri invece di ricalcolarli."""

    dependencies = [("produzione", "0006_report_lettore")]

    operations = [
        migrations.AddField(model_name="articolopn", name="quote_deriva",
                            field=models.PositiveIntegerField(default=0, help_text="Quote in deriva verso un limite.")),
        migrations.AddField(model_name="articolopn", name="quote_fuori_ultimo",
                            field=models.PositiveIntegerField(default=0, help_text="Quote fuori nell'ultimo report di ogni programma.")),
        migrations.AddField(model_name="articolopn", name="analisi_il",
                            field=models.DateTimeField(blank=True, null=True, help_text="Quando Cpk, deriva e fuori sono stati calcolati.")),
    ]
