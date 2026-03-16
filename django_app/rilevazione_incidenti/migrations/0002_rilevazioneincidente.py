from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rilevazione_incidenti", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RilevazioneIncidente",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nominativo", models.CharField(max_length=255)),
                ("tipologia_scheda", models.CharField(max_length=50)),
                ("reparto", models.CharField(blank=True, max_length=150)),
                ("data_segnalazione", models.DateTimeField(blank=True, null=True)),
                ("descrizione_attivita", models.TextField(blank=True)),
                ("descrizione_avvenimento", models.TextField(blank=True)),
                ("usa_macchina", models.BooleanField(default=False)),
                ("nome_macchina", models.CharField(blank=True, max_length=300)),
                ("buono_stato_macchina", models.BooleanField(default=False)),
                ("utilizzo_dpi", models.BooleanField(default=False)),
                ("prima_volta", models.BooleanField(default=False)),
                ("persone_coinvolte", models.CharField(blank=True, max_length=100)),
                ("causa_evento", models.CharField(blank=True, max_length=200)),
                ("altre_cause", models.TextField(blank=True)),
                ("misure_tecniche", models.BooleanField(default=False)),
                ("quali_misure", models.TextField(blank=True)),
                ("approvazione_rls", models.CharField(blank=True, max_length=50)),
                ("note_preposto", models.TextField(blank=True)),
                ("note_rspp", models.TextField(blank=True)),
                ("data_approvazione_rls", models.DateField(blank=True, null=True)),
                ("chiusura_rspp", models.BooleanField(default=False)),
                ("data_chiusura_rspp", models.DateField(blank=True, null=True)),
                ("why_1", models.TextField(blank=True)),
                ("why_2", models.TextField(blank=True)),
                ("why_3", models.TextField(blank=True)),
                ("why_4", models.TextField(blank=True)),
                ("why_5", models.TextField(blank=True)),
                ("partecipanti", models.TextField(blank=True)),
                ("contatore", models.IntegerField(default=0)),
                ("id_originale", models.IntegerField(
                    blank=True,
                    help_text="ID originale da CSV/SharePoint",
                    null=True,
                )),
            ],
            options={
                "verbose_name": "Rilevazione Incidente",
                "verbose_name_plural": "Rilevazioni Incidenti",
                "ordering": ["-data_segnalazione"],
            },
        ),
    ]
