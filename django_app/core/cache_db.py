"""Cache su tabella SQL che non conta la tabella a ogni scrittura.

``DatabaseCache`` di Django esegue ``SELECT COUNT(*) FROM django_cache`` prima di ogni ``set`` per
decidere se sfoltire. In produzione era la query con più CPU di tutto SQL Server (251.000 volte in
16 ore, ~1.000 pagine lette ciascuna) con la tabella lontana dal limite (meno di 30.000 righe su
``MAX_ENTRIES`` 50.000). Qui il conteggio vero si fa una scrittura ogni ``CONTA_OGNI`` per processo;
nelle altre la query diventa ``SELECT 0`` (nessuno sfoltimento). Il resto è il backend di Django.
"""

from __future__ import annotations

import threading

from django.core.cache.backends.base import DEFAULT_TIMEOUT
from django.core.cache.backends.db import DatabaseCache
from django.db import connections, router

CONTA_OGNI = 100


class DatabaseCacheLeggera(DatabaseCache):
    def __init__(self, table, params):
        super().__init__(table, params)
        self._contatore = 0
        self._lock = threading.Lock()

    def _base_set(self, mode, key, value, timeout=DEFAULT_TIMEOUT):
        with self._lock:
            self._contatore += 1
            conta = self._contatore % CONTA_OGNI == 1
        if conta:
            return super()._base_set(mode, key, value, timeout)
        db = router.db_for_write(self.cache_model_class)
        connection = connections[db]
        conteggio = "SELECT COUNT(*) FROM %s" % connection.ops.quote_name(self._table)

        def senza_conteggio(execute, sql, params, many, context):
            if sql == conteggio:
                return execute("SELECT 0", None, many, context)
            return execute(sql, params, many, context)

        with connection.execute_wrapper(senza_conteggio):
            return super()._base_set(mode, key, value, timeout)
