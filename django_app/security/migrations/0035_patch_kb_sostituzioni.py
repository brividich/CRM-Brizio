# KB delle patch WatchGuard, link di download, e sostituzioni fra KB dal Security Update Guide di Microsoft
# (services/patch_kb.py).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0034_watchguard_patch_giorno'),
    ]

    operations = [
        migrations.AddField(
            model_name='watchguardpatch',
            name='kb',
            field=models.CharField(blank=True, db_index=True, default='', help_text='Articolo Microsoft (es. KB5134133) ricavato da nome o file: services/patch_kb.py.', max_length=12),
        ),
        migrations.AddField(
            model_name='watchguardpatch',
            name='download_url',
            field=models.CharField(blank=True, default='', max_length=1000),
        ),
        migrations.AddField(
            model_name='watchguardpatch',
            name='nome_file',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='watchguardpatch',
            name='riavvio_automatico',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='MicrosoftKbSostituzione',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kb', models.CharField(db_index=True, max_length=12)),
                ('sostituita', models.CharField(db_index=True, max_length=12)),
                ('mese', models.CharField(help_text='Documento CVRF da cui viene (es. 2026-Oct).', max_length=12)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('kb', 'sostituita'), name='sec_ms_kb_sost_uniq')],
            },
        ),
        migrations.CreateModel(
            name='MicrosoftCvrfMese',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mese', models.CharField(max_length=12, unique=True)),
                ('aggiornato_il', models.DateTimeField(blank=True, help_text='CurrentReleaseDate di Microsoft.', null=True)),
                ('letto_il', models.DateTimeField(blank=True, null=True)),
                ('sostituzioni', models.PositiveIntegerField(default=0)),
            ],
        ),
    ]
