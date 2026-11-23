"""Riscaldamento del processo web all'avvio (core/avvio.py)."""
from __future__ import annotations

import os
from unittest import mock

from django.test import SimpleTestCase

from core.avvio import riscalda


class RiscaldaTests(SimpleTestCase):
    def test_prepara_rotte_e_template(self):
        esito = riscalda()
        self.assertTrue(esito.get("rotte"))
        self.assertGreaterEqual(esito.get("template", 0), 1)
        self.assertIn("ms", esito)

    def test_spento_con_variabile(self):
        with mock.patch.dict(os.environ, {"HUB_WARMUP": "0"}):
            self.assertEqual(riscalda(), {"skipped": True})

    def test_un_passo_che_fallisce_non_ferma_gli_altri(self):
        with mock.patch("core.avvio._riscalda_cancelli_sottomenu", side_effect=RuntimeError("giù")):
            esito = riscalda()
        self.assertTrue(esito.get("rotte"))
        self.assertNotIn("cancelli_anagrafica", esito)
        self.assertGreaterEqual(esito.get("template", 0), 1)
