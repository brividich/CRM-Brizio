import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0006_areaaziendale_ruoloaziendale"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportazioneRetributiva",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data_importazione", models.DateTimeField(auto_now_add=True)),
                ("data_competenza", models.DateField(help_text="Primo giorno del mese di competenza (es. 2026-04-01)")),
                ("file_nome", models.CharField(blank=True, default="", max_length=255)),
                ("righe_totali", models.IntegerField(default=0)),
                ("righe_ok", models.IntegerField(default=0)),
                ("righe_errore", models.IntegerField(default=0)),
                ("note", models.TextField(blank=True, default="")),
                (
                    "importato_da",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="importazioni_retributive",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Importazione retributiva",
                "verbose_name_plural": "Importazioni retributive",
                "ordering": ["-data_competenza", "-data_importazione"],
            },
        ),
        migrations.CreateModel(
            name="VoceRetributiva",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tax_code", models.CharField(db_index=True, max_length=16)),
                ("legacy_anagrafica_id", models.IntegerField(blank=True, db_index=True, null=True)),
                ("data_competenza", models.DateField()),
                ("pay_item", models.CharField(max_length=150)),
                ("pay_item_key", models.CharField(db_index=True, max_length=150)),
                (
                    "categoria",
                    models.CharField(
                        choices=[
                            ("fisso", "Elementi Fissi"),
                            ("variabile", "Elementi Variabili"),
                            ("totale", "Totali Elementi"),
                            ("altro", "Altro"),
                        ],
                        default="altro",
                        max_length=20,
                    ),
                ),
                ("importo", models.DecimalField(decimal_places=2, max_digits=12)),
                ("is_changed", models.BooleanField(default=False)),
                ("importo_precedente", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                (
                    "importazione",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="voci",
                        to="anagrafica.importazioneretributiva",
                    ),
                ),
            ],
            options={
                "verbose_name": "Voce retributiva",
                "verbose_name_plural": "Voci retributive",
                "ordering": ["-data_competenza", "tax_code", "categoria", "pay_item_key"],
            },
        ),
        migrations.AddIndex(
            model_name="voceretributiva",
            index=models.Index(
                fields=["tax_code", "pay_item_key", "-data_competenza"],
                name="anagrafica_taxcode_payitem_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="voceretributiva",
            index=models.Index(
                fields=["legacy_anagrafica_id", "-data_competenza"],
                name="anagrafica_legacyid_comp_idx",
            ),
        ),
    ]
