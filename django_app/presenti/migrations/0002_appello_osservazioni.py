from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("presenti", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="appello",
            name="osservazioni",
            field=models.TextField(
                blank=True, default="",
                help_text="Osservazioni per il verbale: criticità, tempi, azioni di miglioramento.",
            ),
        ),
    ]
