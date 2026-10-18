"""Migration 0083 — Centro report: registro emissioni, profili e assegnazioni di layout.

Aggiunge anche la voce «Centro report» nel gruppo «sistema» dell'admin_subnav
(/admin-portale/centro-report/).
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

NAV_CODE = "admin-centro-report"
NAV_ITEM = dict(
    label="Centro report",
    section="admin_subnav",
    parent_code="admin-portale",
    group="sistema",
    order=174,  # dopo "Log notifiche" (172), prima di "Health Check" (180)
    route_name="admin_portale:centro_report",
    active_patterns="admin_portale:centro_report",
    description="Tutti i report del portale in un posto: catalogo, registro di chi ha scaricato cosa, profili di layout.",
    is_visible=True,
    is_enabled=True,
)


def add_nav(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")
    NavigationItem.objects.get_or_create(code=NAV_CODE, defaults=NAV_ITEM)


def remove_nav(apps, schema_editor):
    apps.get_model("core", "NavigationItem").objects.filter(code=NAV_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0082_appartenenza_scadenza'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReportProfiloLayout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100, unique=True)),
                ('descrizione', models.CharField(blank=True, default='', max_length=300)),
                ('logo_url', models.CharField(blank=True, default='', help_text='Percorso /media/… di un PNG o JPG; vuoto = logo del template globale.', max_length=300)),
                ('colore_primario', models.CharField(blank=True, default='', max_length=7, validators=[django.core.validators.RegexValidator('^(#[0-9A-Fa-f]{6})?$', 'Colore nel formato #RRGGBB.')])),
                ('colore_accento', models.CharField(blank=True, default='', max_length=7, validators=[django.core.validators.RegexValidator('^(#[0-9A-Fa-f]{6})?$', 'Colore nel formato #RRGGBB.')])),
                ('piede_pagina', models.CharField(blank=True, default='', max_length=200)),
                ('filigrana', models.CharField(blank=True, default='', help_text='Testo in diagonale su ogni pagina, es. BOZZA o COPIA NON CONTROLLATA.', max_length=40)),
                ('mostra_data_generazione', models.BooleanField(default=True)),
                ('mostra_numero_pagina', models.BooleanField(default=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Profilo layout report',
                'verbose_name_plural': 'Profili layout report',
                'ordering': ['nome'],
            },
        ),
        migrations.CreateModel(
            name='ReportEmissione',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('legacy_user_id', models.IntegerField(blank=True, db_index=True, null=True)),
                ('utente_display', models.CharField(blank=True, default='', max_length=200)),
                ('impersonato_display', models.CharField(blank=True, default='', help_text='Persona impersonata al momento dello scaricamento (chi agiva è utente_display).', max_length=200)),
                ('report_chiave', models.CharField(blank=True, db_index=True, default='', help_text='Chiave della voce di catalogo; vuota = route non ancora catalogata.', max_length=120)),
                ('modulo', models.CharField(blank=True, db_index=True, default='', max_length=80)),
                ('titolo', models.CharField(blank=True, default='', max_length=200)),
                ('route_name', models.CharField(blank=True, db_index=True, default='', max_length=160)),
                ('path', models.CharField(blank=True, default='', max_length=500)),
                ('formato', models.CharField(choices=[('pdf', 'PDF'), ('xlsx', 'Excel'), ('csv', 'CSV'), ('docx', 'Word'), ('zip', 'ZIP'), ('altro', 'Altro')], db_index=True, default='altro', max_length=10)),
                ('nome_file', models.CharField(blank=True, default='', max_length=255)),
                ('dimensione_byte', models.BigIntegerField(blank=True, null=True)),
                ('sha256', models.CharField(blank=True, db_index=True, default='', max_length=64)),
                ('parametri', models.JSONField(blank=True, default=dict)),
                ('dati_personali', models.BooleanField(db_index=True, default=False)),
                ('profilo_layout', models.CharField(blank=True, default='', max_length=100)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Emissione report',
                'verbose_name_plural': 'Emissioni report',
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['report_chiave', '-created_at'], name='core_reportem_chiave_recenti')],
            },
        ),
        migrations.CreateModel(
            name='ReportAssegnazioneLayout',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ambito', models.CharField(choices=[('modulo', 'Modulo'), ('voce', 'Singolo report')], max_length=10)),
                ('chiave', models.CharField(max_length=120)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('profilo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assegnazioni', to='core.reportprofilolayout')),
            ],
            options={
                'verbose_name': 'Assegnazione layout report',
                'verbose_name_plural': 'Assegnazioni layout report',
                'ordering': ['ambito', 'chiave'],
                'constraints': [models.UniqueConstraint(fields=('ambito', 'chiave'), name='uniq_report_layout_ambito_chiave')],
            },
        ),
        migrations.RunPython(add_nav, reverse_code=remove_nav),
    ]
