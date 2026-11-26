from django.db import migrations, models


class Migration(migrations.Migration):
    """Capacità per quota (confronto fra P/N, rischio del prossimo pezzo) e rischio/salute del P/N."""

    dependencies = [("produzione", "0009_misure_cluster_compressione")]

    operations = [
        migrations.AddField(model_name="articolopn", name="rischio_max",
                            field=models.FloatField(blank=True, null=True, help_text="Rischio più alto che il prossimo pezzo esca (0-1).")),
        migrations.AddField(model_name="articolopn", name="salute",
                            field=models.PositiveSmallIntegerField(blank=True, null=True, help_text="Salute CMM 0-100 (articoli.salute).")),
        migrations.CreateModel(
            name="QuotaCapacita",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pn", models.CharField(db_index=True, max_length=100, verbose_name="P/N")),
                ("prog", models.CharField(blank=True, default="", max_length=200, verbose_name="Programma")),
                ("quota_id", models.CharField(max_length=260)),
                ("nome", models.CharField(max_length=200)),
                ("caratteristica", models.CharField(db_index=True, max_length=120,
                                                    help_text="Nome senza numerazione, maiuscolo (es. «Ø40 H7»): unisce i P/N.")),
                ("nominale", models.FloatField()),
                ("lsl", models.FloatField(blank=True, null=True)),
                ("usl", models.FloatField(blank=True, null=True)),
                ("n", models.PositiveIntegerField(default=0)),
                ("cpk", models.FloatField(blank=True, null=True)),
                ("ppk", models.FloatField(blank=True, null=True)),
                ("indice", models.FloatField(blank=True, null=True, help_text="Il peggiore fra Cpk e Ppk.")),
                ("cpk_basso", models.FloatField(blank=True, null=True)),
                ("verdetto", models.CharField(blank=True, default="", max_length=20)),
                ("metodo", models.CharField(blank=True, default="", max_length=12)),
                ("rischio", models.FloatField(blank=True, null=True)),
                ("deriva", models.BooleanField(default=False)),
                ("fuori_ultimo", models.BooleanField(default=False)),
                ("famiglia", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("aggiornato_il", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Capacità di una quota", "verbose_name_plural": "Capacità delle quote",
                     "constraints": [models.UniqueConstraint(fields=("pn", "prog", "quota_id"), name="prod_qcap_unica")]},
        ),
    ]
