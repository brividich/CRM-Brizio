from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rilevazione_incidenti", "0002_rilevazioneincidente"),
    ]

    operations = [
        migrations.AddField(
            model_name="sicurezzaimpostazioni",
            name="reparti_custom",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Lista reparti personalizzata (uno per riga). Vuota = usa lista predefinita.",
            ),
        ),
        migrations.AddField(
            model_name="sicurezzaimpostazioni",
            name="cause_evento_custom",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Lista cause evento personalizzata (una per riga). Vuota = usa lista predefinita.",
            ),
        ),
    ]
