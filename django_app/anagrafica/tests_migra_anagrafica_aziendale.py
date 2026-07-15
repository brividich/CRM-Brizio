"""Comando migra_anagrafica_aziendale: allineamento DEV->PROD dei campi data
(data_prima_assunzione, data_consenso_privacy) con match per CODICE FISCALE.

Il codice fiscale e' l'unica identita' stabile: legacy_anagrafica_id differisce tra
dev e prod. I test simulano lo scarto di id creando "prod" con un legacy_id diverso
ma stesso codice fiscale.

Verifica: export keyed per codice fiscale (solo righe con date e con CF); import
fill-only che riempie i NULL, non sovrascrive, non crea righe, aggancia per CF anche
con legacy_id diverso, allinea il flag solo quando valorizza la data di consenso.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from .models import DipendenteAnagraficaAziendale as AA
from .models import DipendenteAnagraficaCivile as AC
from .tests import _ensure_anagrafica_table


def _mk_dipendente_legacy(legacy_id: int, nome: str, cognome: str) -> None:
    """Riga minima nella tabella legacy anagrafica_dipendenti (per il nome nel report)."""
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO anagrafica_dipendenti (id, nome, cognome, attivo) VALUES (%s, %s, %s, 1)",
            [legacy_id, nome, cognome],
        )


class MigraAnagraficaAziendaleTest(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()

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

    def test_export_keyed_per_codice_fiscale_solo_righe_con_date(self):
        _mk_dipendente_legacy(1, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=1, codice_fiscale="rssmra80a01h501z")
        AA.objects.create(legacy_anagrafica_id=1,
                          data_prima_assunzione=date(2020, 1, 15),
                          data_consenso_privacy=date(2021, 6, 1),
                          consenso_privacy=True)
        # Riga con date ma SENZA codice fiscale -> esclusa.
        AA.objects.create(legacy_anagrafica_id=2, data_prima_assunzione=date(2019, 1, 1))
        # Riga senza date -> esclusa.
        AC.objects.create(legacy_anagrafica_id=3, codice_fiscale="AAABBB00A00A000A")
        AA.objects.create(legacy_anagrafica_id=3)

        _, payload = self._export_to_tmp()
        self.assertEqual(len(payload["righe"]), 1)
        r = payload["righe"][0]
        self.assertEqual(r["codice_fiscale"], "RSSMRA80A01H501Z")  # normalizzato maiuscolo
        self.assertEqual(r["data_prima_assunzione"], "2020-01-15")
        self.assertIn("ROSSI", r["nome"])

    def test_bridge_per_cf_con_legacy_id_diverso_fill_only(self):
        # "DEV": persona con legacy_id 100, date valorizzate.
        _mk_dipendente_legacy(100, "LUCA", "BOVA")
        AC.objects.create(legacy_anagrafica_id=100, codice_fiscale="BVOLCU90A01H501K")
        AA.objects.create(legacy_anagrafica_id=100,
                          data_prima_assunzione=date(2015, 3, 1),
                          data_consenso_privacy=date(2022, 2, 2),
                          consenso_privacy=True)
        path, _ = self._export_to_tmp()

        # Passa a "PROD": stessa persona (stesso CF) ma legacy_id 555, scheda con
        # prima_assunzione gia' presente (diversa) e consenso a NULL, flag False.
        AA.objects.filter(legacy_anagrafica_id=100).delete()
        AC.objects.filter(legacy_anagrafica_id=100).delete()
        AC.objects.create(legacy_anagrafica_id=555, codice_fiscale="bvolcu90a01h501k")  # minuscolo
        AA.objects.create(legacy_anagrafica_id=555,
                          data_prima_assunzione=date(2000, 1, 1),
                          data_consenso_privacy=None,
                          consenso_privacy=False)

        # dry-run non scrive
        self._run("--import", path)
        r = AA.objects.get(legacy_anagrafica_id=555)
        self.assertIsNone(r.data_consenso_privacy)

        # apply: aggancia per CF la scheda 555, riempie SOLO il NULL, non sovrascrive
        out = self._run("--import", path, "--apply")
        r = AA.objects.get(legacy_anagrafica_id=555)
        self.assertEqual(r.data_prima_assunzione, date(2000, 1, 1))   # NON sovrascritto
        self.assertEqual(r.data_consenso_privacy, date(2022, 2, 2))   # riempito via CF
        self.assertTrue(r.consenso_privacy)                           # flag coerente
        self.assertIn("FATTO: 1", out)

    def test_cf_non_trovato_in_prod_viene_saltato(self):
        _mk_dipendente_legacy(10, "ANNA", "VERDI")
        AC.objects.create(legacy_anagrafica_id=10, codice_fiscale="VRDNNA85A41H501Q")
        AA.objects.create(legacy_anagrafica_id=10, data_prima_assunzione=date(2018, 5, 5))
        path, _ = self._export_to_tmp()

        # "PROD" non ha quel codice fiscale.
        AA.objects.all().delete()
        AC.objects.all().delete()

        out = self._run("--import", path, "--apply")
        self.assertIn("NON trovati in prod", out)
        self.assertIn("FATTO: 0", out)

    def test_cf_trovato_ma_senza_scheda_aziendale(self):
        _mk_dipendente_legacy(20, "PAOLO", "NERI")
        AC.objects.create(legacy_anagrafica_id=20, codice_fiscale="NREPLA70A01H501B")
        AA.objects.create(legacy_anagrafica_id=20, data_consenso_privacy=date(2023, 1, 1))
        path, _ = self._export_to_tmp()

        # "PROD": la persona (CF) esiste ma la scheda aziendale no.
        AA.objects.all().delete()
        AC.objects.all().delete()
        AC.objects.create(legacy_anagrafica_id=77, codice_fiscale="NREPLA70A01H501B")

        out = self._run("--import", path, "--apply")
        self.assertIn("SENZA scheda aziendale", out)
        self.assertIn("FATTO: 0", out)

    def test_non_sovrascrive_flag_se_data_gia_presente(self):
        _mk_dipendente_legacy(30, "GIA", "BIANCHI")
        AC.objects.create(legacy_anagrafica_id=30, codice_fiscale="BNCGIA80A01H501C")
        AA.objects.create(legacy_anagrafica_id=30,
                          data_consenso_privacy=date(2023, 1, 1),
                          consenso_privacy=True)
        path, _ = self._export_to_tmp()
        # prod ha gia' la data ma flag False: data non NULL -> niente da fare, flag intatto.
        AA.objects.filter(legacy_anagrafica_id=30).update(consenso_privacy=False)
        self._run("--import", path, "--apply")
        r = AA.objects.get(legacy_anagrafica_id=30)
        self.assertFalse(r.consenso_privacy)
