"""Mansionario fase 6 (3/3): via il vecchio catalogo ``MansioneRischio``.

I dati sono già sul catalogo ``Mansione`` (0175). Override e adempimenti tengono
la stessa colonna, ora collegata al catalogo ``Mansione``.
"""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0175_mansioni_rischio_unificate_dati"),
    ]

    operations = [
        # Override individuali
        migrations.AlterField(
            model_name="dipendentemansionerischiooverride",
            name="mansione_rischio",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="override_dipendenti",
                to="anagrafica.mansione", verbose_name="Mansione di rischio",
            ),
        ),
        migrations.AddConstraint(
            model_name="dipendentemansionerischiooverride",
            constraint=models.UniqueConstraint(
                condition=Q(attivo=True), fields=("legacy_anagrafica_id", "mansione_rischio"),
                name="uniq_override_mansrischio_attivo",
            ),
        ),
        # Adempimenti di cambio mansione
        migrations.AlterField(
            model_name="adempimentocambiomansione",
            name="origine_mansione_rischio",
            field=models.ForeignKey(
                null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="+", to="anagrafica.mansione",
            ),
        ),
        # Regole formative: il bersaglio «mansione di rischio» è la mansione stessa
        migrations.RemoveIndex(
            model_name="trainingrequirementrule", name="anagrafica__mansion_9ad23f_idx",
        ),
        migrations.RemoveField(model_name="trainingrequirementrule", name="mansione_rischio"),
        # Vecchio catalogo e collegamento
        migrations.RemoveField(model_name="mansione", name="mansioni_rischio"),
        migrations.DeleteModel(name="MansioneLavorativaRischio"),
        migrations.DeleteModel(name="MansioneRischio"),
    ]
