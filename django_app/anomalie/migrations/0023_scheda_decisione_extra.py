from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anomalie", "0022_controllo_passaggi"),
    ]

    operations = [
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="dove_pezzi",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnala_terzista",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="segnala_car",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="car_segnalati",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="anomaliaschedaqualita",
            name="car_segnalati_il",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
