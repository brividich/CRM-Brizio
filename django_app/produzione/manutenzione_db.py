"""Manutenzione notturna delle tabelle di Controllo dimensionale (solo SQL Server).

Sull'istanza non c'è l'Agent né un piano di manutenzione: la lettura dei report scrive migliaia di misure ogni ora
e le statistiche restavano ferme (30.000 righe contate su 2,4 milioni), con piani di esecuzione sbagliati. Ogni
notte: statistiche ricalcolate dove è cambiato più del 10% delle righe; indici riorganizzati oltre il 10% di
frammentazione e ricostruiti oltre il 30% (la ricostruzione tiene la compressione già impostata)."""
from __future__ import annotations

import logging
import time

from django.db import connection

logger = logging.getLogger(__name__)

TABELLE = ("produzione_reportcmm", "produzione_misuracmm", "produzione_articolopn", "produzione_cartellareportcmm")
SOGLIA_STATISTICHE = 0.10
MIN_MODIFICHE = 5000
PAGINE_MIN = 1000


def manutenzione() -> dict:
    if connection.vendor != "microsoft":
        return {"saltata": "solo SQL Server"}
    inizio = time.monotonic()
    esito = {"statistiche": [], "riorganizzati": [], "ricostruiti": []}
    elenco = ", ".join("'" + t + "'" for t in TABELLE)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT OBJECT_NAME(s.object_id), s.name, sp.rows, sp.modification_counter FROM sys.stats s "
            "CROSS APPLY sys.dm_db_stats_properties(s.object_id, s.stats_id) sp "
            f"WHERE OBJECT_NAME(s.object_id) IN ({elenco})")
        for tab, nome, righe, modifiche in cur.fetchall():
            if modifiche and modifiche >= MIN_MODIFICHE and modifiche > (righe or 0) * SOGLIA_STATISTICHE:
                esito["statistiche"].append(f"{tab}.{nome}")
        for voce in sorted(set(esito["statistiche"])):
            tab, nome = voce.split(".", 1)
            cur.execute(f"UPDATE STATISTICS [{tab}] ([{nome}])")
        cur.execute(
            "SELECT OBJECT_NAME(ps.object_id), i.name, ps.avg_fragmentation_in_percent FROM "
            "sys.dm_db_index_physical_stats(DB_ID(), NULL, NULL, NULL, 'LIMITED') ps "
            "JOIN sys.indexes i ON i.object_id = ps.object_id AND i.index_id = ps.index_id "
            f"WHERE OBJECT_NAME(ps.object_id) IN ({elenco}) AND i.name IS NOT NULL AND ps.page_count >= %s "
            "AND ps.avg_fragmentation_in_percent > 10", [PAGINE_MIN])
        for tab, nome, fram in cur.fetchall():
            if fram > 30:
                cur.execute(f"ALTER INDEX [{nome}] ON [{tab}] REBUILD WITH (SORT_IN_TEMPDB = ON)")
                esito["ricostruiti"].append(f"{tab}.{nome} ({fram:.0f}%)")
            else:
                cur.execute(f"ALTER INDEX [{nome}] ON [{tab}] REORGANIZE")
                esito["riorganizzati"].append(f"{tab}.{nome} ({fram:.0f}%)")
    esito["secondi"] = round(time.monotonic() - inizio, 1)
    logger.info("manutenzione db produzione: %s", esito)
    return esito
