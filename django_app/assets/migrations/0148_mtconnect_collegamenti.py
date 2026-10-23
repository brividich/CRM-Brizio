"""Macchine collegate via MTConnect (``/assets/work-machines/mtconnect/``): tabelle, fonte contatori, ACL v2, menu.

La pagina si legge con lo stesso permesso della mappa officina (poi dell'elenco macchine,
poi del dettaglio asset); collegare una macchina richiede, nella vista, il permesso di
modificarla. La voce di menu nasce solo se manca, dopo «Indirizzi IP».
"""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

NOTE = "[ASSET_MTCONNECT] Macchine collegate (MTConnect)"
PATH = "/assets/work-machines/mtconnect/"
FALLBACK_CODE = "legacy.assets.assets_view"
BUTTON_CODE = "mtconnect_collegamenti"


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias

    vicino = None
    for filtro in (Q(path_pattern__startswith="/assets/work-machines/map"), Q(path_pattern="/assets/work-machines/"),
                   Q(path_pattern__startswith="/assets/work-machines")):
        vicino = Binding.objects.using(db).filter(filtro, is_active=True).exclude(note=NOTE).order_by("-priority", "id").first()
        if vicino:
            break
    code = vicino.permission_id if vicino else FALLBACK_CODE
    if not vicino:
        Permission.objects.using(db).get_or_create(
            code=FALLBACK_CODE, defaults={"module": "assets", "label": "Assets - Dettaglio asset", "is_active": True}
        )
    Binding.objects.using(db).get_or_create(
        route_name="",
        path_pattern=PATH,
        defaults={
            "permission_id": code,
            "match_strategy": "prefix",
            "source_app": "assets",
            "priority": 110,
            "is_active": True,
            "note": NOTE,
        },
    )

    if Button.objects.using(db).filter(code=BUTTON_CODE).exists():
        return
    sibling = (Button.objects.using(db).filter(code="rete_indirizzi").first()
               or Button.objects.using(db).filter(code="catalogo_software").first())
    Button.objects.using(db).create(
        code=BUTTON_CODE,
        section=sibling.section if sibling else "OPERATIONS",
        parent=sibling.parent if sibling else None,
        label="Macchine collegate",
        target_url="django:assets:mtconnect_collegamenti",
        active_match=PATH,
        is_subitem=bool(sibling and sibling.parent_id),
        sort_order=(sibling.sort_order + 1) if sibling else 79,
        is_visible=True,
    )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "RoutePermissionBinding").objects.using(db).filter(note=NOTE).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0147_rete_indirizzi_dhcp_dns'),
        ('core', '0034_permissiondefinition_rolepermissiongrant_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assetmeter',
            name='source',
            field=models.CharField(choices=[('MANUAL', 'Manuale'), ('OPCUA', 'OPC UA'), ('SNMP', 'SNMP'), ('IMPORT', 'Import'), ('MTCONNECT', 'MTConnect')], default='MANUAL', max_length=10),
        ),
        migrations.AlterField(
            model_name='assetmeterhistory',
            name='source',
            field=models.CharField(choices=[('MANUAL', 'Manuale'), ('OPCUA', 'OPC UA'), ('SNMP', 'SNMP'), ('IMPORT', 'Import'), ('MTCONNECT', 'MTConnect')], default='MANUAL', max_length=10),
        ),
        migrations.CreateModel(
            name='CollegamentoMTConnect',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('url_agent', models.CharField(help_text="Indirizzo dell'agent MTConnect, es. http://10.0.5.21:5000", max_length=300)),
                ('dispositivo', models.CharField(blank=True, default='', help_text="Nome del dispositivo nell'agent; vuoto = il primo.", max_length=120)),
                ('attivo', models.BooleanField(default=True)),
                ('stato', models.CharField(choices=[('in_lavoro', 'In lavoro'), ('pronta', 'Pronta, ferma senza programma'), ('ferma', 'Programma interrotto'), ('allarme', 'In allarme'), ('spenta', 'Spenta o non disponibile'), ('non_raggiungibile', 'Agent non raggiungibile'), ('mai', 'Mai letta')], default='mai', max_length=20)),
                ('stato_dal', models.DateTimeField(blank=True, null=True)),
                ('disponibilita', models.CharField(blank=True, default='', max_length=30)),
                ('esecuzione', models.CharField(blank=True, default='', max_length=30)),
                ('modalita', models.CharField(blank=True, default='', max_length=30)),
                ('emergenza', models.CharField(blank=True, default='', max_length=30)),
                ('programma', models.CharField(blank=True, default='', max_length=200)),
                ('pezzi_grezzo', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('ore_grezzo', models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ('sospesi', models.JSONField(blank=True, default=dict)),
                ('allarmi', models.JSONField(blank=True, default=list)),
                ('letto_il', models.DateTimeField(blank=True, null=True)),
                ('controllato_il', models.DateTimeField(blank=True, null=True)),
                ('errore', models.CharField(blank=True, default='', max_length=300)),
                ('creato_il', models.DateTimeField(auto_now_add=True)),
                ('aggiornato_il', models.DateTimeField(auto_now=True)),
                ('asset', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='mtconnect', to='assets.asset')),
                ('contatore_ore', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='assets.assetmeter')),
                ('contatore_pezzi', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='assets.assetmeter')),
            ],
            options={
                'verbose_name': 'Collegamento MTConnect',
                'verbose_name_plural': 'Collegamenti MTConnect',
                'ordering': ['asset__name'],
            },
        ),
        migrations.CreateModel(
            name='PeriodoStatoMacchina',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('stato', models.CharField(choices=[('in_lavoro', 'In lavoro'), ('pronta', 'Pronta, ferma senza programma'), ('ferma', 'Programma interrotto'), ('allarme', 'In allarme'), ('spenta', 'Spenta o non disponibile'), ('non_raggiungibile', 'Agent non raggiungibile'), ('mai', 'Mai letta')], max_length=20)),
                ('dal', models.DateTimeField(db_index=True)),
                ('al', models.DateTimeField(blank=True, null=True)),
                ('collegamento', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='periodi', to='assets.collegamentomtconnect')),
            ],
            options={
                'verbose_name': 'Periodo di stato della macchina',
                'verbose_name_plural': 'Periodi di stato delle macchine',
                'ordering': ['-dal'],
                'indexes': [models.Index(fields=['collegamento', 'dal'], name='assets_periodo_mtc_idx')],
            },
        ),
        migrations.RunPython(forwards, backwards),
    ]
