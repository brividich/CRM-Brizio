"""Comando migra_anagrafica_aziendale: allineamento DEV->PROD dei campi data
(data_prima_assunzione, data_consenso_privacy) in modalita' FILL-ONLY.

Verifica: export solo delle righe con almeno una data; import che riempie i NULL,
NON sovrascrive valori esistenti, NON crea righe mancanti, e allinea il flag
consenso_privacy solo quando valorizza la data di consenso.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from .models import DipendenteAnagraficaAziendale as AA


class MigraAnagraficaAziendaleTest(TestCase):
    def _run(self, *args):
        out = StringIO()
        call_command("migra_anagrafica_aziendale", *args, stdout=out, stderr=out)
        return out.getvalue()

    def _export_to_tmp(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self._run("--export", path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return path, payload

    def test_export_include_solo_righe_con_date(self):
        AA.objects.create(legacy_anagrafica_id=1,
                          data_prima_assunzione=date(2020, 1, 15),
                          data_consenso_privacy=date(2021, 6, 1),
                          consenso_privacy=True)
        AA.objects.create(legacy_anagrafica_id=2)  # nessuna data -> escluso
        _, payload = self._export_to_tmp()
        ids = {r["legacy_anagrafica_id"] for r in payload["righe"]}
        self.assertEqual(ids, {1})
        self.assertEqual(payload["righe"][0]["data_prima_assunzione"], "2020-01-15")

    def test_fill_only_non_sovrascrive_e_setta_flag(self):
        # Sorgente "dev": due date valorizzate.
        AA.objects.create(legacy_anagrafica_id=10,
                          data_prima_assunzione=date(2019, 3, 1),
                          data_consenso_privacy=date(2022, 2, 2),
                          consenso_privacy=True)
        path, _ = self._export_to_tmp()

        # "prod": stessa riga ma con prima_assunzione gia' valorizzata (diversa) e
        # consenso a NULL con flag False.
        AA.objects.filter(legacy_anagrafica_id=10).update(
            data_prima_assunzione=date(2000, 1, 1),
            data_consenso_privacy=None,
            consenso_privacy=False,
        )

        # dry-run non scrive
        self._run("--import", path)
        r = AA.objects.get(legacy_anagrafica_id=10)
        self.assertEqual(r.data_prima_assunzione, date(2000, 1, 1))
        self.assertIsNone(r.data_consenso_privacy)

        # apply: riempie SOLO il NULL, non sovrascrive prima_assunzione, alza il flag
        self._run("--import", path, "--apply")
        r = AA.objects.get(legacy_anagrafica_id=10)
        self.assertEqual(r.data_prima_assunzione, date(2000, 1, 1))  # NON sovrascritto
        self.assertEqual(r.data_consenso_privacy, date(2022, 2, 2))  # riempito
        self.assertTrue(r.consenso_privacy)                          # flag coerente

    def test_riga_mancante_in_prod_viene_saltata(self):
        AA.objects.create(legacy_anagrafica_id=20,
                          data_prima_assunzione=date(2018, 5, 5))
        path, _ = self._export_to_tmp()
        AA.objects.filter(legacy_anagrafica_id=20).delete()  # "prod" non ce l'ha

        out = self._run("--import", path, "--apply")
        self.assertFalse(AA.objects.filter(legacy_anagrafica_id=20).exists())  # non creata
        self.assertIn("NON esistono in prod", out)

    def test_flag_non_toccato_se_data_consenso_gia_presente(self):
        AA.objects.create(legacy_anagrafica_id=30,
                          data_consenso_privacy=date(2023, 1, 1),
                          consenso_privacy=True)
        path, _ = self._export_to_tmp()
        # prod ha gia' la data ma flag False: non tocchiamo nulla (data non NULL).
        AA.objects.filter(legacy_anagrafica_id=30).update(consenso_privacy=False)
        self._run("--import", path, "--apply")
        r = AA.objects.get(legacy_anagrafica_id=30)
        self.assertFalse(r.consenso_privacy)  # data gia' presente -> flag non toccato
