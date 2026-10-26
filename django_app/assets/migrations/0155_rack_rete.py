"""Rack di rete: tabella, rack e membro dello stack sugli switch, voce di menu «Rack e switch».

La pagina ``/assets/rete/rack/`` ricade nel binding ACL v2 di ``/assets/rete/`` (0147,
stesso permesso di «Indirizzi IP»): nessun binding nuovo. La voce di menu nasce solo
se manca, subito dopo «Indirizzi IP».
"""
import django.db.models.deletion
from django.db import migrations, models

BUTTON_CODE = "rete_rack"

# Solo SQLite (test/sviluppo): aggiungere un campo con default ricostruisce assets_asset e
# SQLite rifiuta il rename finché esistono viste che la leggono (le bi_* di dati_bi).
# Si tolgono prima e si ricreano dopo con il loro stesso SQL. SQL Server fa ALTER TABLE ADD.
_VISTE_SQLITE: list[str] = []


def _togli_viste_sqlite(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type = 'view'")
        righe = [(nome, sql) for nome, sql in cursor.fetchall() if nome.startswith("bi_")]
        _VISTE_SQLITE[:] = [sql for _nome, sql in righe if sql]
        for nome, _sql in righe:
            cursor.execute(f'DROP VIEW IF EXISTS "{nome}"')


def _rimetti_viste_sqlite(apps, schema_editor):
    if schema_editor.connection.vendor != "sqlite":
        return
    with schema_editor.connection.cursor() as cursor:
        for sql in _VISTE_SQLITE:
            cursor.execute(sql)
    _VISTE_SQLITE.clear()


def forwards(apps, schema_editor):
    Button = apps.get_model("assets", "AssetSidebarButton")
    db = schema_editor.connection.alias
    if Button.objects.using(db).filter(code=BUTTON_CODE).exists():
        return
    sibling = (Button.objects.using(db).filter(code="rete_indirizzi").first()
               or Button.objects.using(db).filter(code="catalogo_software").first())
    Button.objects.using(db).create(
        code=BUTTON_CODE,
        section=sibling.section if sibling else "OPERATIONS",
        parent=sibling.parent if sibling else None,
        label="Rack e switch",
        target_url="django:assets:rete_rack",
        active_match="/assets/rete/rack/",
        is_subitem=bool(sibling and sibling.parent_id),
        sort_order=sibling.sort_order if sibling else 78,
        is_visible=True,
    )


def backwards(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("assets", "AssetSidebarButton").objects.using(db).filter(code=BUTTON_CODE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0154_collector_cnc_ore_e_avvisi'),
    ]

    operations = [
        migrations.RunPython(_togli_viste_sqlite, _rimetti_viste_sqlite),
        migrations.CreateModel(
            name='RackRete',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('codice', models.CharField(max_length=20, unique=True, verbose_name='Codice')),
                ('nome', models.CharField(max_length=120, verbose_name='Nome')),
                ('ubicazione', models.CharField(blank=True, default='', max_length=200, verbose_name='Ubicazione')),
                ('prefisso_porte', models.CharField(blank=True, db_index=True, default='', max_length=20, verbose_name='Prefisso porte switch')),
                ('prefisso_patch', models.CharField(blank=True, default='', max_length=20, verbose_name='Prefisso patch panel')),
                ('note', models.TextField(blank=True, default='')),
                ('aggiornato_il', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Rack di rete',
                'verbose_name_plural': 'Rack di rete',
                'ordering': ['codice'],
            },
        ),
        migrations.AddField(
            model_name='asset',
            name='switch_membro',
            field=models.CharField(blank=True, default='', max_length=10, verbose_name='Membro dello stack'),
        ),
        migrations.AddField(
            model_name='asset',
            name='rack',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='switch', to='assets.rackrete', verbose_name='Rack'),
        ),
        migrations.RunPython(_rimetti_viste_sqlite, _togli_viste_sqlite),
        migrations.RunPython(forwards, backwards),
    ]
