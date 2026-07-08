from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0081_subnav_reparti_persone"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dipendenteanagraficaaziendale",
            name="area_aziendale_nome",
        ),
        migrations.AddField(
            model_name="dipendenteanagraficaaziendale",
            name="area_aziendale",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="dipendenti_assegnati",
                to="anagrafica.areaaziendale",
                verbose_name="Area aziendale",
            ),
        ),
    ]
