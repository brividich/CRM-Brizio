"""Regressioni: età delle anomalie per l'escalation e match univoco utenti legacy."""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

from django.test import TestCase

from anomalie import mail_action_service as svc
from core.legacy_models import UtenteLegacy


class EscalationEtaAnomalieTests(TestCase):
    def _fetch(self, age_ts, soglia=24):
        cur = MagicMock()
        cur.description = [("op_id",), ("id",), ("seriale",), ("age_ts",)]
        cur.fetchall.return_value = [("OP/2026/TEST", 1, "SN1", age_ts)]
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        with (
            patch("core.legacy_utils.legacy_table_columns", return_value={"created_datetime"}),
            patch("django.db.connections", {"default": conn}),
            patch.object(svc, "_fetch_pn_for_ops", return_value={}),
        ):
            return svc._fetch_op_da_controllare(soglia)

    def test_datetime_naive_utc_conta_le_ore(self):
        """pyodbc restituisce DATETIME2 naive: prima l'età risultava sempre 0h."""
        naive = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=48)
        rows = self._fetch(naive)
        self.assertEqual(len(rows), 1)
        self.assertGreaterEqual(rows[0]["ore_max"], 47.9)
        self.assertTrue(rows[0]["over_threshold"])

    def test_sotto_soglia_non_scatta(self):
        naive = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(hours=2)
        rows = self._fetch(naive)
        self.assertFalse(rows[0]["over_threshold"])


class FindLegacyUserByNameTests(TestCase):
    def setUp(self):
        self.mario = UtenteLegacy.objects.create(nome="Mario Rossi", password="x")
        UtenteLegacy.objects.create(nome="Giulia Rossini", password="x")
        UtenteLegacy.objects.create(nome="Anna Bianchi", password="x")
        UtenteLegacy.objects.create(nome="Paolo Bianchi", password="x")

    def test_nome_completo_esatto(self):
        self.assertEqual(svc.find_legacy_user_by_name("mario rossi"), self.mario)

    def test_ordine_cognome_nome(self):
        self.assertEqual(svc.find_legacy_user_by_name("ROSSI MARIO"), self.mario)

    def test_solo_cognome_univoco(self):
        # "Rossi" non deve agganciare "Rossini" (vecchio nome__icontains).
        self.assertEqual(svc.find_legacy_user_by_name("Rossi"), self.mario)

    def test_cognome_ambiguo_nessun_match(self):
        self.assertIsNone(svc.find_legacy_user_by_name("Bianchi"))

    def test_parziale_non_aggancia(self):
        self.assertIsNone(svc.find_legacy_user_by_name("Ross"))
        self.assertIsNone(svc.find_legacy_user_by_name(""))
