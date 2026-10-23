"""Indirizzi IP da DHCP/DNS di Windows Server (``/assets/rete/indirizzi/``): tabelle, binding ACL v2, menu.

La pagina si legge con lo stesso permesso del Catalogo software (chi segue l'IT):
si riusa il permesso del binding gia' esistente per ``/assets/software/`` (poi
``/assets/licenze/``, poi il dettaglio asset). La voce di menu nasce solo se manca,
accanto a «Catalogo software».
"""
import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q

NOTE = "[ASSET_RETE] Indirizzi IP (DHCP e DNS)"
PATH = "/assets/rete/"
FALLBACK_CODE = "legacy.assets.assets_view"
BUTTON_CODE = "rete_indirizzi"


def forwards(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias

    vicino = (
        Binding.objects.using(db)
        .filter(Q(path_pattern__startswith="/assets/software") | Q(path_pattern__startswith="/assets/licenze"), is_active=True)
        .order_by("-priority", "path_pattern", "id")
        .first()
    )
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
            "priority": 100,
            "is_active": True,
            "note": NOTE,
        },
    )

    if Button.objects.using(db).filter(code=BUTTON_CODE).exists():
        return
    sibling = Button.objects.using(db).filter(code="catalogo_software").first() or Button.objects.using(db).filter(code="licenze").first()
    Button.objects.using(db).create(
        code=BUTTON_CODE,
        section=sibling.section if sibling else "OPERATIONS",
        parent=sibling.parent if sibling else None,
        label="Indirizzi IP",
        target_url="django:assets:rete_indirizzi",
        active_match=PATH,
        is_subitem=bool(sibling and sibling.parent_id),
        sort_order=(sibling.sort_order + 3) if sibling else 78,
        is_visible=True,
    )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "RoutePermissionBinding").objects.using(db).filter(note=NOTE).delete()
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0146_intune_hardware'),
        ('core', '0034_permissiondefinition_rolepermissiongrant_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='AmbitoDhcp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('server', models.CharField(max_length=120)),
                ('scope_id', models.CharField(max_length=45)),
                ('nome', models.CharField(blank=True, default='', max_length=200)),
                ('maschera', models.CharField(blank=True, default='', max_length=45)),
                ('inizio', models.CharField(blank=True, default='', max_length=45)),
                ('fine', models.CharField(blank=True, default='', max_length=45)),
                ('stato', models.CharField(blank=True, default='', max_length=30)),
                ('durata_lease_ore', models.FloatField(blank=True, null=True)),
                ('in_uso', models.PositiveIntegerField(default=0)),
                ('liberi', models.PositiveIntegerField(default=0)),
                ('percentuale_uso', models.FloatField(blank=True, null=True)),
                ('presente', models.BooleanField(default=True)),
                ('letto_il', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name': 'Ambito DHCP',
                'verbose_name_plural': 'Ambiti DHCP',
                'ordering': ['server', 'scope_id'],
                'constraints': [models.UniqueConstraint(fields=('server', 'scope_id'), name='uniq_ambito_dhcp')],
            },
        ),
        migrations.CreateModel(
            name='IndirizzoRete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip', models.CharField(max_length=45, unique=True)),
                ('mac', models.CharField(blank=True, db_index=True, default='', max_length=17)),
                ('tipo', models.CharField(choices=[('lease', 'Indirizzo dinamico (DHCP)'), ('prenotazione', 'Prenotazione DHCP'), ('dns', 'Solo nel DNS')], default='lease', max_length=20)),
                ('nome_dhcp', models.CharField(blank=True, default='', max_length=255)),
                ('stato_dhcp', models.CharField(blank=True, default='', max_length=40)),
                ('scadenza_lease', models.DateTimeField(blank=True, null=True)),
                ('server_dhcp', models.CharField(blank=True, default='', max_length=120)),
                ('nel_dhcp', models.BooleanField(default=False)),
                ('nomi_dns', models.JSONField(blank=True, default=list)),
                ('dns_statico', models.BooleanField(default=False)),
                ('dns_aggiornato_il', models.DateTimeField(blank=True, null=True)),
                ('nel_dns', models.BooleanField(default=False)),
                ('prima_vista', models.DateTimeField(blank=True, null=True)),
                ('ultima_vista', models.DateTimeField(blank=True, null=True)),
                ('motivo_proposta', models.CharField(blank=True, default='', max_length=60)),
                ('aggiornato_il', models.DateTimeField(auto_now=True)),
                ('ambito', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='indirizzi', to='assets.ambitodhcp')),
                ('asset', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='indirizzi_rete', to='assets.asset')),
                ('asset_proposto', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='assets.asset')),
            ],
            options={
                'verbose_name': 'Indirizzo di rete',
                'verbose_name_plural': 'Indirizzi di rete',
                'ordering': ['ip'],
            },
        ),
        migrations.RunPython(forwards, backwards),
    ]
