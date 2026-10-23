from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0152_collector_dal_portale'),
    ]

    operations = [
        migrations.CreateModel(
            name='MacRete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mac', models.CharField(max_length=17, unique=True)),
                ('prima_vista', models.DateTimeField()),
                ('ultima_vista', models.DateTimeField()),
                ('ultimo_ip', models.CharField(blank=True, default='', max_length=45)),
                ('ultimo_nome', models.CharField(blank=True, default='', max_length=255)),
                ('segnalato_il', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'MAC visto in rete',
                'verbose_name_plural': 'MAC visti in rete',
                'ordering': ['-prima_vista'],
            },
        ),
    ]
