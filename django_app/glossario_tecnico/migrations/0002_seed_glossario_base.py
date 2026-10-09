"""Seed del glossario: ~85 termini in «bozza» (fonte=seed), da validare in Qualità.

Idempotente: un termine già presente (stesso termine e categoria) non viene
toccato; una variante la cui chiave esiste già viene saltata. Reverse: elimina
solo i termini seed ancora in bozza (quelli già validati o modificati restano).
"""

from django.db import migrations


def _chiave(testo):
    from glossario_tecnico.chiave import normalizza_chiave

    return normalizza_chiave(testo)


def chiave_binaria_sqlserver(apps, schema_editor):
    """Su SQL Server la chiave va confrontata byte per byte.

    È già normalizzata in Python (minuscolo, senza accenti): la collation del DB non
    deve aggiungere altro. Con le collation «vecchie» (es. Latin1_General_CI_AS) i
    simboli senza peso (⏤ rettilineità, ⏥ planarità, ⫽ parallelismo) risultano
    uguali tra loro e il vincolo UNIQUE fallisce. Altri DB: nulla da fare.
    """
    conn = schema_editor.connection
    if conn.vendor != "microsoft":
        return
    tabella = apps.get_model("glossario_tecnico", "Variante")._meta.db_table
    with conn.cursor() as c:
        c.execute(
            "SELECT i.name, i.is_unique_constraint, i.is_unique FROM sys.indexes i "
            "JOIN sys.index_columns ic ON ic.object_id = i.object_id AND ic.index_id = i.index_id "
            "JOIN sys.columns col ON col.object_id = ic.object_id AND col.column_id = ic.column_id "
            "WHERE i.object_id = OBJECT_ID(%s) AND col.name = 'chiave' AND i.is_primary_key = 0",
            [tabella],
        )
        indici = c.fetchall()
        for nome, vincolo, _unico in indici:
            if vincolo:
                c.execute(f"ALTER TABLE [{tabella}] DROP CONSTRAINT [{nome}]")
            else:
                c.execute(f"DROP INDEX [{nome}] ON [{tabella}]")
        c.execute(f"ALTER TABLE [{tabella}] ALTER COLUMN [chiave] nvarchar(150) COLLATE Latin1_General_100_BIN2 NOT NULL")
        for nome, vincolo, unico in indici:
            if vincolo:
                c.execute(f"ALTER TABLE [{tabella}] ADD CONSTRAINT [{nome}] UNIQUE ([chiave])")
            else:
                c.execute(f"CREATE {'UNIQUE ' if unico else ''}INDEX [{nome}] ON [{tabella}] ([chiave])")


def seed(apps, schema_editor):
    from glossario_tecnico.seed_data import TERMINI

    Termine = apps.get_model("glossario_tecnico", "Termine")
    Variante = apps.get_model("glossario_tecnico", "Variante")
    chiavi = set(Variante.objects.values_list("chiave", flat=True))
    for dati in TERMINI:
        termine, creato = Termine.objects.get_or_create(
            termine=dati["termine"], categoria=dati["categoria"],
            defaults={
                "termine_en": dati["termine_en"], "definizione": dati["definizione"],
                "simbolo": dati["simbolo"], "esempio_disegno": dati["esempio_disegno"],
                "norma_rif": dati["norma_rif"], "note_interne": dati["note_interne"],
                "stato": "bozza", "fonte": "seed",
            },
        )
        if not creato:
            continue
        for tipo, testo, lingua in dati["varianti"]:
            chiave = _chiave(testo)
            if not chiave or chiave in chiavi:
                continue
            Variante.objects.create(termine=termine, testo=testo, tipo=tipo, lingua=lingua or "", chiave=chiave)
            chiavi.add(chiave)


def unseed(apps, schema_editor):
    Termine = apps.get_model("glossario_tecnico", "Termine")
    Termine.objects.filter(fonte="seed", stato="bozza").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("glossario_tecnico", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(chiave_binaria_sqlserver, migrations.RunPython.noop),
        migrations.RunPython(seed, unseed),
    ]
