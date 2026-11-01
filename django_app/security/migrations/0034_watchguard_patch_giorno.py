# Fotografia giornaliera delle patch WatchGuard mancanti (services/patch_sla.py).

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0033_pacchetto_iso'),
    ]

    operations = [
        migrations.CreateModel(
            name='WatchGuardPatchGiorno',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('giorno', models.DateField(unique=True)),
                ('mancanti', models.PositiveIntegerField(default=0)),
                ('pc', models.PositiveIntegerField(default=0)),
                ('critiche', models.PositiveIntegerField(default=0)),
                ('kev', models.PositiveIntegerField(default=0)),
                ('oltre_termine', models.PositiveIntegerField(default=0)),
                ('letto_il', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'ordering': ['-giorno'],
            },
        ),
    ]
