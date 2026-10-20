"""Connessioni persistenti a SQL Server (DB_CONN_MAX_AGE)."""
import os
from unittest import mock

from django.test import SimpleTestCase

from config.settings import base


class ConnMaxAgeTests(SimpleTestCase):
    def _db(self, **env):
        with mock.patch.dict(os.environ, {"DB_NAME": "x", "DB_HOST": "h", **env}, clear=False):
            if "DB_CONN_MAX_AGE" not in env:
                os.environ.pop("DB_CONN_MAX_AGE", None)
            return base.build_sqlserver_database()

    def test_default_connessioni_persistenti_con_health_check(self):
        db = self._db()
        self.assertEqual(db["CONN_MAX_AGE"], 60)
        self.assertTrue(db["CONN_HEALTH_CHECKS"])

    def test_zero_ripristina_il_comportamento_precedente(self):
        db = self._db(DB_CONN_MAX_AGE="0")
        self.assertEqual(db["CONN_MAX_AGE"], 0)
        self.assertFalse(db["CONN_HEALTH_CHECKS"])

    def test_valore_non_valido_ricade_sul_default(self):
        self.assertEqual(self._db(DB_CONN_MAX_AGE="abc")["CONN_MAX_AGE"], 60)
