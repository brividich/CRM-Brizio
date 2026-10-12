from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rilevazione_incidenti", "0006_rilevazioneincidente_planimetria_area_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rilevazioneincidente",
            name="segnalato_da_legacy_id",
            field=models.IntegerField(blank=True, db_index=True, null=True),
        ),
    ]
