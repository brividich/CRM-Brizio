"""DPI: per categoria chi consegna (magazzino o no, es. scarpe) e consegna diretta al
banco senza richiesta approvata (consumabili)."""

from django.db import migrations, models

# Stesso accorgimento della 0014: su SQLite le viste bi_* bloccano la ricostruzione
# della tabella; si tolgono e si rimettono. SQL Server fa ALTER TABLE ADD.
_VISTE_SQLITE: list[str] = []

_ICONE_CALZATURE = {"boots", "👢", "🥾", "👞"}


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


def _calzature_fuori_dal_magazzino(apps, schema_editor):
    """Le scarpe non le distribuisce il magazzino: categorie con l'icona calzature
    (o «scarp»/«calzat» nel nome) partono senza la spunta. Si cambia da Impostazioni."""
    CategoriaDPI = apps.get_model("dpi", "CategoriaDPI")
    for cat in CategoriaDPI.objects.all():
        nome = (cat.nome or "").casefold()
        if (cat.icona_emoji or "").strip() in _ICONE_CALZATURE or "scarp" in nome or "calzat" in nome:
            cat.consegna_magazzino = False
            cat.save(update_fields=["consegna_magazzino"])


class Migration(migrations.Migration):

    dependencies = [
        ('dpi', '0014_ciclo_ritiro_avvisi'),
    ]

    operations = [
        migrations.RunPython(_togli_viste_sqlite, _rimetti_viste_sqlite),
        migrations.AddField(
            model_name='categoriadpi',
            name='consegna_magazzino',
            field=models.BooleanField(default=True, help_text="La consegna la fa il magazzino: compare nel «Banco consegne» e la mail «Da consegnare» va al Magazzino. Senza spunta (es. scarpe) la mail va ai referenti DPI."),
        ),
        migrations.AddField(
            model_name='categoriadpi',
            name='consegna_diretta',
            field=models.BooleanField(default=False, help_text="Il magazzino la può consegnare al banco senza una richiesta approvata (consumabili: guanti, tappi, mascherine…). Il report di consegna va comunque al responsabile."),
        ),
        migrations.RunPython(_rimetti_viste_sqlite, _togli_viste_sqlite),
        migrations.RunPython(_calzature_fuori_dal_magazzino, migrations.RunPython.noop),
    ]
