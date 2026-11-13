from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0044_indici_lentezza_prod"),
    ]

    operations = [
        migrations.CreateModel(
            name="WatchGuardAggiornamento",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("host", models.CharField(db_index=True, help_text="Nome normalizzato (minuscolo, senza dominio).", max_length=255)),
                ("nome", models.CharField(max_length=500)),
                ("versione", models.CharField(blank=True, default="", max_length=120)),
                ("produttore", models.CharField(blank=True, default="", max_length=255)),
                ("installato_il", models.DateField(blank=True, null=True)),
                ("letto_il", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["host", "-installato_il", "nome"]},
        ),
        migrations.CreateModel(
            name="PosturaGiorno",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("giorno", models.DateField(db_index=True)),
                ("pc", models.CharField(help_text="Nome normalizzato (minuscolo, senza dominio).", max_length=255)),
                ("nome", models.CharField(blank=True, default="", max_length=255)),
                ("punteggio", models.PositiveSmallIntegerField()),
            ],
            options={
                "ordering": ["pc", "giorno"],
                "constraints": [models.UniqueConstraint(fields=("giorno", "pc"), name="sec_postura_giorno_pc")],
                "indexes": [models.Index(fields=["pc", "giorno"], name="sec_postura_pc_giorno_idx")],
            },
        ),
        migrations.AlterField(
            model_name="securitypropostaai",
            name="tipo",
            field=models.CharField(choices=[("cpe", "Collegamento CPE"), ("esito", "Esito CVE su un PC"),
                                            ("doppione", "Stesso programma da due fonti")], db_index=True, max_length=8),
        ),
    ]
