# Pacchetto mensile di evidenze ISO/IEC 27001 del SOC (services/iso_pacchetto.py).

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import core.private_attachments
import security.models


class Migration(migrations.Migration):

    dependencies = [
        ('security', '0030_proposta_ai'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SecurityPacchettoIso',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('periodo_dal', models.DateField(db_index=True)),
                ('periodo_al', models.DateField()),
                ('file', models.FileField(max_length=500, storage=core.private_attachments.PrivateAttachmentStorage(download_hint='Scarica da SOC › Report › Conformità ISO 27001.'), upload_to=security.models._percorso_pacchetto_iso)),
                ('sha256', models.CharField(max_length=64)),
                ('generato_il', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('automatico', models.BooleanField(default=False)),
                ('riepilogo', models.JSONField(blank=True, default=dict)),
                ('copia_esito', models.CharField(blank=True, default='', max_length=500)),
                ('generato_da', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Pacchetto evidenze ISO 27001',
                'verbose_name_plural': 'Pacchetti evidenze ISO 27001',
                'ordering': ['-periodo_dal', '-generato_il'],
            },
        ),
    ]
