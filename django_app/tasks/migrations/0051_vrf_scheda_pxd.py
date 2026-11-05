from django.db import migrations, models


class Migration(migrations.Migration):
    """Scheda VRF sul nuovo MOD.073 (P x D): Totale Rischio, fascia e CEO al posto
    dei totali per fase del modulo a 3 fasi, mai usato con dati reali."""

    dependencies = [
        ("tasks", "0050_kickoffmeeting_convocazione_dati"),
    ]

    operations = [
        migrations.RemoveField(model_name="vrfriskassessment", name="total_p"),
        migrations.RemoveField(model_name="vrfriskassessment", name="total_i"),
        migrations.RemoveField(model_name="vrfriskassessment", name="total_c"),
        migrations.RemoveField(model_name="vrfriskassessment", name="dig_triggered"),
        migrations.AddField(
            model_name="vrfriskassessment",
            name="total_tr",
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name="vrfriskassessment",
            name="livello",
            field=models.CharField(blank=True, default="", max_length=10),
        ),
        migrations.AddField(
            model_name="vrfriskassessment",
            name="ceo_required",
            field=models.BooleanField(default=False),
        ),
    ]
