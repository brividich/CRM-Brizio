"""DPI: passo «Pronto per il ritiro», avviso all'Amministrazione per categoria,
opzione avviso di ritiro subito all'approvazione."""

from django.db import migrations, models

# Solo SQLite (test/sviluppo): aggiungere un campo con default ricostruisce le tabelle e
# SQLite rifiuta il rename finché esistono viste che le leggono (le bi_* di dati_bi).
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


class Migration(migrations.Migration):

    dependencies = [
        ('dpi', '0013_icona_vie_respiratorie'),
    ]

    operations = [
        migrations.RunPython(_togli_viste_sqlite, _rimetti_viste_sqlite),
        migrations.AddField(
            model_name='categoriadpi',
            name='avvisa_amministrazione_consegna',
            field=models.BooleanField(default=True, help_text="Alla consegna manda il report con il PDF anche all'Amministrazione"),
        ),
        migrations.AddField(
            model_name='dpiimpostazioni',
            name='avviso_ritiro_all_approvazione',
            field=models.BooleanField(default=False, help_text="Avvisa il dipendente di ritirare il DPI subito all'approvazione, senza aspettare «Pronto per il ritiro» del magazzino"),
        ),
        migrations.AddField(
            model_name='richiestadpi',
            name='pronta_ritiro_da_nome',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='richiestadpi',
            name='pronta_ritiro_il',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='dpiimpostazioni',
            name='amministrazione_emails',
            field=models.TextField(blank=True, default='', help_text="Report di consegna (per le categorie con l'avviso all'Amministrazione), uno per riga"),
        ),
        migrations.RunPython(_rimetti_viste_sqlite, _togli_viste_sqlite),
    ]
