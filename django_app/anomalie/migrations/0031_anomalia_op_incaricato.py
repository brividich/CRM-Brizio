from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anomalie', '0030_anomalia_action_nota'),
    ]

    operations = [
        migrations.CreateModel(
            name='AnomaliaOpIncaricato',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('op_key', models.CharField(db_index=True, max_length=200)),
                ('op_id', models.CharField(blank=True, default='', max_length=200)),
                ('ruolo', models.CharField(max_length=16)),
                ('legacy_user_id', models.IntegerField(db_index=True)),
                ('nome', models.CharField(blank=True, default='', max_length=200)),
                ('assegnato_da', models.CharField(blank=True, default='', max_length=200)),
                ('assegnato_il', models.DateTimeField(auto_now=True)),
                ('nota', models.CharField(blank=True, default='', max_length=500)),
            ],
            options={
                'verbose_name': "Incaricato dell'OP",
                'verbose_name_plural': 'Incaricati degli OP',
                'constraints': [models.UniqueConstraint(fields=('op_key', 'ruolo'), name='anomalia_op_incaricato_ruolo_unico')],
            },
        ),
    ]
