# Generated for NOVICROM HUB 1.1.1 — Reparti / caporeparto

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0031_onboardingoffboardingcampo'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='areaaziendale',
            options={
                'ordering': ['nome'],
                'verbose_name': 'Reparto',
                'verbose_name_plural': 'Reparti',
            },
        ),
        migrations.AddField(
            model_name='areaaziendale',
            name='caporeparto_legacy_id',
            field=models.IntegerField(
                blank=True,
                db_index=True,
                help_text='ID legacy del dipendente assegnato come caporeparto.',
                null=True,
                verbose_name='Caporeparto',
            ),
        ),
    ]
