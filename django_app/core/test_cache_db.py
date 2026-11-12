"""core.cache_db.DatabaseCacheLeggera: stessa cache su tabella, senza COUNT(*) a ogni scrittura."""
from django.core.cache import caches
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings

from core import cache_db

CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
         "tabella": {"BACKEND": "core.cache_db.DatabaseCacheLeggera", "LOCATION": "test_cache_leggera",
                     "OPTIONS": {"MAX_ENTRIES": 1000}}}


@override_settings(CACHES=CACHE)
class DatabaseCacheLeggeraTests(TestCase):
    def setUp(self):
        call_command("createcachetable", "--database", "default", verbosity=0)
        self.cache = caches["tabella"]

    def test_scrive_legge_e_conta_una_volta_ogni_cento(self):
        # Il registro delle query di Django scrive l'SQL prima della sostituzione: qui conta quello
        # che SQLite esegue davvero.
        connection.ensure_connection()
        eseguite = []
        connection.connection.set_trace_callback(eseguite.append)
        try:
            for i in range(cache_db.CONTA_OGNI):
                self.cache.set(f"k{i}", {"n": i}, 60)
        finally:
            connection.connection.set_trace_callback(None)
        conteggi = [s for s in eseguite if s.upper().startswith("SELECT COUNT(*)")]
        self.assertEqual(len(conteggi), 1)
        self.assertEqual(self.cache.get("k7"), {"n": 7})
        self.assertTrue(self.cache.add("nuova", 1))
        self.assertFalse(self.cache.add("nuova", 2))
        self.assertEqual(self.cache.get("nuova"), 1)
