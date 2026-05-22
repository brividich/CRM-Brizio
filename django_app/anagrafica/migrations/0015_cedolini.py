from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0014_alter_dipendenteanagraficacivile_provincia_nascita"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportazioneCedolini",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("data_importazione", models.DateTimeField(auto_now_add=True)),
                ("data_competenza", models.DateField(help_text="Ultimo giorno del mese di competenza (es. 2026-05-31)")),
                ("origine", models.CharField(choices=[("XLSX", "Import XLSX cedolini"), ("SQL", "Import diretto SQL")], db_index=True, default="XLSX", max_length=10)),
                ("file_nome", models.CharField(blank=True, default="", max_length=255)),
                ("righe_totali", models.IntegerField(default=0)),
                ("righe_ok", models.IntegerField(default=0)),
                ("righe_errore", models.IntegerField(default=0)),
                ("righe_non_trovate", models.IntegerField(default=0)),
                ("note", models.TextField(blank=True, default="")),
                ("importato_da", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="importazioni_cedolini", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Importazione cedolini",
                "verbose_name_plural": "Importazioni cedolini",
                "ordering": ["-data_competenza", "-data_importazione"],
            },
        ),
        migrations.CreateModel(
            name="SaldoCedolino",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tax_code", models.CharField(db_index=True, max_length=16, verbose_name="Codice fiscale")),
                ("legacy_anagrafica_id", models.IntegerField(blank=True, db_index=True, help_text="Risolto al momento dell'import da DipendenteAnagraficaCivile.codice_fiscale", null=True)),
                ("data_competenza", models.DateField(db_index=True, help_text="Ultimo giorno del mese di competenza (es. 2026-05-31)")),
                ("anzianita_anni", models.SmallIntegerField(blank=True, null=True, verbose_name="Anzianità (anni)")),
                ("anzianita_mesi", models.SmallIntegerField(blank=True, null=True, verbose_name="Anzianità (mesi aggiuntivi)")),
                ("ferie_anni_prec", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ferie anni prec.")),
                ("ferie_maturati", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ferie maturate")),
                ("ferie_goduti", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ferie godute")),
                ("ferie_residui", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ferie residue")),
                ("rol_anni_prec", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="ROL anni prec.")),
                ("rol_maturati", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="ROL maturati")),
                ("rol_goduti", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="ROL goduti")),
                ("rol_residui", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="ROL residui")),
                ("ex_fest_anni_prec", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ex-fest. anni prec.")),
                ("ex_fest_maturati", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ex-fest. maturate")),
                ("ex_fest_goduti", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ex-fest. godute")),
                ("ex_fest_residui", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Ex-fest. residue")),
                ("permessi_anni_prec", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Permessi anni prec.")),
                ("permessi_maturati", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Permessi maturati")),
                ("permessi_goduti", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Permessi goduti")),
                ("permessi_residui", models.DecimalField(decimal_places=2, default=0, max_digits=8, verbose_name="Permessi residui")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("importazione", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="saldi", to="anagrafica.importazionecedolini")),
            ],
            options={
                "verbose_name": "Saldo cedolino",
                "verbose_name_plural": "Saldi cedolini",
                "ordering": ["-data_competenza", "tax_code"],
            },
        ),
        migrations.AddConstraint(
            model_name="saldocedolino",
            constraint=models.UniqueConstraint(
                fields=["tax_code", "data_competenza"],
                name="anagrafica_saldo_cedolino_tax_competenza_uniq",
            ),
        ),
        migrations.AddIndex(
            model_name="saldocedolino",
            index=models.Index(fields=["legacy_anagrafica_id", "-data_competenza"], name="anagrafica_saldo_lid_comp_idx"),
        ),
        migrations.AddIndex(
            model_name="saldocedolino",
            index=models.Index(fields=["data_competenza"], name="anagrafica_saldo_comp_idx"),
        ),
    ]
