from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0066_assetmaintenancebudget"),
        ("rilevazione_incidenti", "0004_sicurezzaimpostazioni_singleton"),
    ]

    operations = [
        migrations.AddField(
            model_name="rilevazioneincidente",
            name="asset",
            field=models.ForeignKey(
                blank=True,
                help_text="Asset coinvolto nell'evento (opzionale)",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="rilevazioni_incidenti",
                to="assets.asset",
            ),
        ),
    ]
