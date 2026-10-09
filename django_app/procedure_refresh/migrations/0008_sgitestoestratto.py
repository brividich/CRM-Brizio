from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('procedure_refresh', '0007_sgisynclog'),
    ]

    operations = [
        migrations.CreateModel(
            name='SgiTestoEstratto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_hash', models.CharField(db_index=True, max_length=128, verbose_name='Hash file estratto')),
                ('formato', models.CharField(max_length=10, verbose_name='Formato')),
                ('metodo', models.CharField(max_length=30, verbose_name='Metodo')),
                ('testo', models.TextField(blank=True, default='', verbose_name='Testo')),
                ('n_pagine', models.PositiveIntegerField(blank=True, null=True, verbose_name='Pagine')),
                ('n_caratteri', models.PositiveIntegerField(default=0, verbose_name='Caratteri')),
                ('n_sezioni', models.PositiveIntegerField(default=0, verbose_name='Sezioni §')),
                ('ha_testo_nativo', models.BooleanField(default=True, verbose_name='Testo nativo')),
                ('ocr_usato', models.BooleanField(default=False, verbose_name='OCR usato')),
                ('avvisi', models.TextField(blank=True, default='', verbose_name='Avvisi')),
                ('estratto_il', models.DateTimeField(auto_now=True, verbose_name='Estratto il')),
                ('revision', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='testo_estratto', to='procedure_refresh.procedurerevision', verbose_name='Revisione')),
            ],
            options={
                'verbose_name': 'Testo estratto SGI',
                'verbose_name_plural': 'Testi estratti SGI',
            },
        ),
    ]
