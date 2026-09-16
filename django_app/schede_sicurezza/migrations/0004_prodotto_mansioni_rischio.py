from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0122_referti_requisiti_oculistica"),
        ("schede_sicurezza", "0003_prodottochimico_visite_qr"),
    ]

    operations = [
        migrations.AlterField(
            model_name="prodottochimico",
            name="reparto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="prodotti_chimici",
                to="anagrafica.reparto",
                verbose_name="Reparto storico (non operativo)",
            ),
        ),
        migrations.AddField(
            model_name="prodottochimico",
            name="mansioni",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "Mansioni i cui dipendenti devono consultare e confermare "
                    "la presa visione della SDS corrente."
                ),
                related_name="prodotti_chimici",
                to="anagrafica.mansione",
                verbose_name="Mansioni di rischio",
            ),
        ),
    ]
