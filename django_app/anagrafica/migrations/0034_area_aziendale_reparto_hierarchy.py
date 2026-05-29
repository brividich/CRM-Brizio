# NOVICROM HUB 1.1.1 — Introduce AreaAziendale (livello padre) e Reparto (ex AreaAziendale)
# La tabella DB mantiene il nome storico `anagrafica_areaaziendale` per i reparti.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0033_reparto_label_sync"),
    ]

    operations = [
        # ── 1. Rinomina il modello Python AreaAziendale → Reparto
        #       La tabella DB rimane `anagrafica_areaaziendale` (nessun ALTER TABLE).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameModel("AreaAziendale", "Reparto"),
                # Necessario: senza questo Django usa la tabella default `anagrafica_reparto`
                # per tutte le operazioni successive in questa migrazione.
                migrations.AlterModelTable("Reparto", "anagrafica_areaaziendale"),
            ],
            database_operations=[],
        ),

        # ── 2. Crea il nuovo modello AreaAziendale (livello padre)
        migrations.CreateModel(
            name="AreaAziendale",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome", models.CharField(max_length=100, unique=True)),
                ("descrizione", models.TextField(blank=True, default="")),
                ("colore", models.CharField(default="#64748b", help_text="Colore esadecimale es. #1d4ed8", max_length=7)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Area aziendale",
                "verbose_name_plural": "Aree aziendali",
                "ordering": ["nome"],
                "db_table": "anagrafica_area_aziendale",
            },
        ),

        # ── 3. Aggiungi FK area_aziendale a Reparto (tabella `anagrafica_areaaziendale`)
        migrations.AddField(
            model_name="reparto",
            name="area_aziendale",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reparti",
                to="anagrafica.areaaziendale",
                verbose_name="Area aziendale",
            ),
        ),

        # ── 4. Aggiungi campi cache su DipendenteAnagraficaAziendale
        migrations.AddField(
            model_name="dipendenteanagraficaaziendale",
            name="area_aziendale_nome",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Compilato automaticamente dall'area aziendale del reparto assegnato.",
                max_length=100,
                verbose_name="Area aziendale",
            ),
        ),
        migrations.AddField(
            model_name="dipendenteanagraficaaziendale",
            name="caporeparto_legacy_id",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                help_text="ID legacy del caporeparto, compilato automaticamente dal reparto assegnato.",
                null=True,
                verbose_name="Caporeparto",
            ),
        ),
    ]
