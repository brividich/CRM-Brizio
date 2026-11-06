from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assenze', '0013_avviso_certificato'),
    ]

    operations = [
        migrations.CreateModel(
            name='CambioCapoAbilitato',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legacy_anagrafica_id', models.IntegerField(db_index=True, unique=True)),
                ('nominativo', models.CharField(blank=True, default='', help_text="Copia del nominativo al momento dell'abilitazione, per leggibilità dello storico.", max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.CharField(blank=True, default='', max_length=200)),
            ],
            options={
                'verbose_name': 'Abilitato al cambio del capo reparto',
                'verbose_name_plural': 'Abilitati al cambio del capo reparto',
                'ordering': ['nominativo', 'legacy_anagrafica_id'],
            },
        ),
    ]
