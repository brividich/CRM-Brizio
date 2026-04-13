from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0010_project_revisione_versione"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="vrf_status",
            field=models.CharField(
                choices=[("PENDING", "Da caricare"), ("UPLOADED", "Caricato"), ("NOT_REQUIRED", "Non richiesto")],
                default="PENDING",
                max_length=20,
                verbose_name="Stato documento VRF",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_file",
            field=models.FileField(blank=True, null=True, upload_to="tasks_vrf/%Y/%m/"),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_original_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_uploaded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_quote_number",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="Preventivo n°"),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_description",
            field=models.CharField(blank=True, default="", max_length=500, verbose_name="Descrizione VRF"),
        ),
        migrations.AddField(
            model_name="project",
            name="vrf_esp",
            field=models.CharField(blank=True, default="", max_length=120, verbose_name="Esp"),
        ),
        migrations.AddField(
            model_name="taskimpostazioni",
            name="vrf_reminder_days",
            field=models.PositiveSmallIntegerField(
                default=7,
                help_text="Mostra un avviso giallo dopo N giorni dalla creazione del progetto senza documento VRF caricato.",
                verbose_name="Giorni avviso VRF",
            ),
        ),
        migrations.AddField(
            model_name="taskimpostazioni",
            name="vrf_blocking_days",
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text="Blocca la creazione/modifica di VRF su quel progetto dopo N giorni senza documento VRF.",
                verbose_name="Giorni blocco VRF",
            ),
        ),
    ]
