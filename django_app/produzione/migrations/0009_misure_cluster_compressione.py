"""Misure CMM ordinate per report e compresse (solo SQL Server).

Le misure si leggono sempre a blocchi di un report (``report_id IN (...)``): con l'indice cluster su (report_id, id)
le righe di un report stanno vicine e non serve un accesso alla tabella per ogni misura. La compressione PAGE
(disponibile anche in Standard) riduce la tabella, che a regime supera i 2 GB. La chiave primaria resta su ``id``,
non cluster. Poi statistiche ricalcolate per intero (erano ferme a 30.000 righe su 2,4 milioni).

Non atomica: la ricostruzione è un'unica istruzione per tabella e, fuori transazione, il log resta piccolo.
Sugli altri database non fa nulla."""
from django.db import migrations

TABELLA = "produzione_misuracmm"


def _pk(cur):
    cur.execute("SELECT name, type_desc FROM sys.indexes WHERE object_id = OBJECT_ID(%s) AND is_primary_key = 1", [TABELLA])
    return cur.fetchone()


def avanti(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cur:
        pk = _pk(cur)
        if pk and pk[1] == "CLUSTERED":
            cur.execute(f"ALTER TABLE [{TABELLA}] DROP CONSTRAINT [{pk[0]}]")
        cur.execute("SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID(%s) AND name = 'prod_mcmm_report_cl'", [TABELLA])
        if not cur.fetchone():
            cur.execute(f"CREATE CLUSTERED INDEX [prod_mcmm_report_cl] ON [{TABELLA}] ([report_id], [id]) "
                        "WITH (DATA_COMPRESSION = PAGE, SORT_IN_TEMPDB = ON)")
        if not _pk(cur):
            cur.execute(f"ALTER TABLE [{TABELLA}] ADD CONSTRAINT [PK_{TABELLA}] PRIMARY KEY NONCLUSTERED ([id]) "
                        "WITH (DATA_COMPRESSION = PAGE)")
        cur.execute(f"UPDATE STATISTICS [{TABELLA}] WITH FULLSCAN")
        cur.execute("UPDATE STATISTICS [produzione_reportcmm] WITH FULLSCAN")


def indietro(apps, schema_editor):
    if schema_editor.connection.vendor != "microsoft":
        return
    with schema_editor.connection.cursor() as cur:
        pk = _pk(cur)
        if pk and pk[1] != "CLUSTERED":
            cur.execute(f"ALTER TABLE [{TABELLA}] DROP CONSTRAINT [{pk[0]}]")
        cur.execute("IF EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID(%s) AND name = 'prod_mcmm_report_cl') "
                    f"DROP INDEX [prod_mcmm_report_cl] ON [{TABELLA}]", [TABELLA])
        if not _pk(cur):
            cur.execute(f"ALTER TABLE [{TABELLA}] ADD CONSTRAINT [PK_{TABELLA}] PRIMARY KEY CLUSTERED ([id])")


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("produzione", "0008_indici_letture")]
    operations = [migrations.RunPython(avanti, indietro)]
