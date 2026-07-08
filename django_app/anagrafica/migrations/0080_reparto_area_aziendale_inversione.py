from django.db import migrations, models
import django.db.models.deletion


def cancella_dati_vecchia_gerarchia(apps, schema_editor):
    """Taglio netto: i dati esistenti sono nella forma vecchia (sbagliata,
    confermato dall'utente in sessione 2026-07-08) e vengono ricreati da UI
    con la nuova gerarchia dopo il deploy."""
    Reparto = apps.get_model("anagrafica", "Reparto")
    AreaAziendale = apps.get_model("anagrafica", "AreaAziendale")
    Reparto.objects.all().delete()
    AreaAziendale.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0079_processoqualificato_corsi_richiesti_and_more"),
    ]

    operations = [
        migrations.RunPython(cancella_dati_vecchia_gerarchia, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="reparto",
            name="area_aziendale",
        ),
        migrations.AddField(
            model_name="reparto",
            name="colore",
            field=models.CharField(default="#64748b", help_text="Colore esadecimale es. #1d4ed8", max_length=7),
        ),
        migrations.RemoveField(
            model_name="areaaziendale",
            name="colore",
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="reparto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="aree_aziendali",
                to="anagrafica.reparto",
                verbose_name="Reparto",
            ),
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="responsabile_legacy_id",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                help_text="ID legacy del dipendente responsabile di quest'area (opzionale, es. dirigente qualità/produzione).",
                null=True,
                verbose_name="Responsabile",
            ),
        ),
    ]
