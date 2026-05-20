# Generated manually 2026-05-20 — Sprint 2a + Sprint 3 manual entry

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('anagrafica', '0010_tipologia_contratto'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DipendenteCambiamentoOrganizzativo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('legacy_anagrafica_id', models.IntegerField(db_index=True)),
                ('tipo', models.CharField(choices=[
                    ('MANSIONE', 'Mansione'),
                    ('REPARTO', 'Reparto'),
                    ('AREA', 'Area aziendale'),
                    ('RUOLO_AZIENDALE', 'Ruolo aziendale'),
                ], db_index=True, max_length=30)),
                ('valore_precedente', models.CharField(blank=True, default='', max_length=300)),
                ('valore_nuovo', models.CharField(blank=True, default='', max_length=300)),
                ('data_effetto', models.DateField(help_text='Data da cui vale il nuovo valore (default: oggi)')),
                ('note', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name='cambiamenti_organizzativi_registrati',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Cambiamento organizzativo',
                'verbose_name_plural': 'Storico cambiamenti organizzativi',
                'ordering': ['-data_effetto', '-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='dipendentecambiamentoorganizzativo',
            index=models.Index(
                fields=['legacy_anagrafica_id', 'tipo', '-data_effetto'],
                name='anag_cambio_lid_tipo_dt_idx',
            ),
        ),
        migrations.AddField(
            model_name='importazioneretributiva',
            name='origine',
            field=models.CharField(
                choices=[('CSV', 'Import CSV studio paghe'), ('MANUALE', 'Inserimento manuale HR')],
                db_index=True, default='CSV', max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='voceretributiva',
            name='manuale',
            field=models.BooleanField(
                db_index=True, default=False,
                help_text='True se voce inserita manualmente da utente HR (override delle voci CSV con stesso pay_item_key)',
            ),
        ),
        migrations.AddField(
            model_name='voceretributiva',
            name='note',
            field=models.CharField(blank=True, default='', max_length=300),
        ),
        migrations.AddField(
            model_name='voceretributiva',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddField(
            model_name='voceretributiva',
            name='updated_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=models.deletion.SET_NULL,
                related_name='voci_retributive_modificate',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
