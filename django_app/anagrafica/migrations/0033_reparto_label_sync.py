# Generated for NOVICROM HUB 1.1.1 — sync label "Reparto"

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0032_areaaziendale_caporeparto'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dipendenteanagraficaaziendale',
            name='area',
            field=models.CharField(
                blank=True,
                default='',
                max_length=100,
                verbose_name='Reparto',
            ),
        ),
        migrations.AlterField(
            model_name='dipendentecambiamentoorganizzativo',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('MANSIONE', 'Mansione'),
                    ('REPARTO', 'Reparto (legacy)'),
                    ('AREA', 'Reparto'),
                    ('RUOLO_AZIENDALE', 'Ruolo aziendale'),
                ],
                db_index=True,
                max_length=30,
            ),
        ),
    ]
