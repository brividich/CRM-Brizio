from __future__ import annotations

import os
from unittest.mock import patch

from django.test import SimpleTestCase

from config.settings.base import build_sqlserver_database


def _timeout(**env: str) -> int:
    keys = ("HUB_PROCESS_ROLE", "DB_QUERY_TIMEOUT")
    clean = {k: v for k, v in os.environ.items() if k not in keys}
    with patch.dict(os.environ, {**clean, **env}, clear=True):
        return build_sqlserver_database()["OPTIONS"]["query_timeout"]


class DbQueryTimeoutTests(SimpleTestCase):
    def test_processo_web_ha_default_200(self):
        self.assertEqual(_timeout(HUB_PROCESS_ROLE="web"), 200)

    def test_comandi_e_qcluster_restano_senza_limite(self):
        self.assertEqual(_timeout(), 0)

    def test_valore_esplicito_vince_sul_default_del_web(self):
        self.assertEqual(_timeout(HUB_PROCESS_ROLE="web", DB_QUERY_TIMEOUT="60"), 60)
        self.assertEqual(_timeout(HUB_PROCESS_ROLE="web", DB_QUERY_TIMEOUT="0"), 0)

    def test_valore_non_numerico_torna_a_zero(self):
        self.assertEqual(_timeout(HUB_PROCESS_ROLE="web", DB_QUERY_TIMEOUT="abc"), 0)
