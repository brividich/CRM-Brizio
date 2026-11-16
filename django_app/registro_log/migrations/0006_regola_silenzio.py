import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registro_log', '0005_operazione_manutenzione'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegolaSilenzio',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('categoria', models.CharField(max_length=32)),
                ('account', models.CharField(blank=True, default='', max_length=150)),
                ('host', models.CharField(blank=True, default='', max_length=255)),
                ('testo', models.CharField(blank=True, default='', max_length=200)),
                ('motivo', models.CharField(max_length=500)),
                ('creata_da', models.CharField(blank=True, default='', max_length=150)),
                ('creata_il', models.DateTimeField(default=django.utils.timezone.now)),
                ('scade_il', models.DateTimeField(blank=True, null=True)),
                ('attiva', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Regola di silenzio',
                'verbose_name_plural': 'Regole di silenzio',
                'ordering': ['-creata_il', '-id'],
            },
        ),
    ]
