from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0028_decisione_qualita'),
    ]

    operations = [
        migrations.CreateModel(
            name='AnomaliaIncaricato',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('anomalia_id', models.IntegerField(db_index=True)),
                ('ruolo', models.CharField(max_length=16)),
                ('legacy_user_id', models.IntegerField(db_index=True)),
                ('nome', models.CharField(blank=True, default='', max_length=200)),
                ('assegnato_da', models.CharField(blank=True, default='', max_length=200)),
                ('assegnato_il', models.DateTimeField(auto_now=True)),
                ('nota', models.CharField(blank=True, default='', max_length=500)),
            ],
            options={
                'verbose_name': "Incaricato dell'anomalia",
                'verbose_name_plural': 'Incaricati delle anomalie',
                'constraints': [models.UniqueConstraint(fields=('anomalia_id', 'ruolo'), name='anomalia_incaricato_ruolo_unico')],
            },
        ),
    ]
