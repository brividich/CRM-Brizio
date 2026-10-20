from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assenze', '0006_assenza_capo_scelto'),
    ]

    operations = [
        migrations.CreateModel(
            name='AssenzaInseritaDa',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assenza_id', models.IntegerField(unique=True)),
                ('gruppo', models.CharField(blank=True, default='', max_length=20)),
                ('inserito_da', models.CharField(blank=True, default='', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Autore richiesta assenza',
                'verbose_name_plural': 'Autori richieste assenza',
            },
        ),
    ]
