"""Comando ripara_legacy_id_import: remap del legacy_anagrafica_id dei moduli
importati DEV->PROD, agganciando le persone per CODICE FISCALE.

Usa ContinuitaOperativa (skill matrix) come modello target di prova: richiede solo un
ProcessoCriticoContinuita (nome). I test simulano lo scarto di id creando "prod" con un
legacy_id diverso ma stesso codice fiscale.
"""
from __future__ import annotations

import json
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from .models import DipendenteAnagraficaCivile as AC
from .models_skillmatrix import ContinuitaOperativa, ProcessoCriticoContinuita
from .tests import _ensure_anagrafica_table


def _mk_dipendente_legacy(legacy_id: int, nome: str, cognome: str) -> None:
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO anagrafica_dipendenti (id, nome, cognome, attivo) VALUES (%s, %s, %s, 1)",
            [legacy_id, nome, cognome],
        )


class RiparaLegacyIdImportTest(TestCase):
    CF = "RSSMRA80A01H501Z"

    def setUp(self):
        _ensure_anagrafica_table()
        self.processo = ProcessoCriticoContinuita.objects.create(nome="Saldatura TIG")

    def _run(self, *args):
        out = StringIO()
        call_command("ripara_legacy_id_import", *args, stdout=out, stderr=out)
        return out.getvalue()

    def _export_dev(self, dev_id: int, cf: str):
        """Crea lo stato 'dev' (civile con CF) ed esporta la mappa, poi lo azzera."""
        _mk_dipendente_legacy(dev_id, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=dev_id, codice_fiscale=cf)
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self._run("--export", path)
        # azzera lo stato dev per simulare prod
        AC.objects.filter(legacy_anagrafica_id=dev_id).delete()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti WHERE id = %s", [dev_id])
        return path

    def test_export_mappa_numero_cf(self):
        _mk_dipendente_legacy(1, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=1, codice_fiscale="rssmra80a01h501z")
        AC.objects.create(legacy_anagrafica_id=2, codice_fiscale="")  # senza CF -> escluso
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self._run("--export", path)
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(len(payload["map"]), 1)
        self.assertEqual(payload["map"][0]["cf"], "RSSMRA80A01H501Z")  # normalizzato

    def test_remap_orfano_via_cf_con_id_diverso(self):
        path = self._export_dev(100, self.CF)  # dev: persona #100, CF
        # prod: stessa persona come #500 (id diverso), record orfano ancora a #100
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF.lower())
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=100, processo=self.processo)

        # dry-run non scrive
        self._run("--import", path)
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 100)

        # apply: aggancia per CF -> id di prod 500
        out = self._run("--import", path, "--apply")
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 500)
        self.assertIn("FATTO: 1", out)

        # idempotente: un secondo giro non trova piu' orfani
        out2 = self._run("--import", path, "--apply")
        self.assertIn("FATTO: 0", out2)

    def test_non_orfano_non_toccato(self):
        path = self._export_dev(100, self.CF)
        # prod: la persona esiste come #500 e il record e' GIA' a #500 (valido)
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=500, processo=self.processo)
        self._run("--import", path, "--apply")
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 500)  # invariato

    def test_cf_non_in_prod_saltato(self):
        path = self._export_dev(100, self.CF)
        # prod NON ha quel codice fiscale
        _mk_dipendente_legacy(500, "ALTRO", "TIZIO")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale="XXXYYY00A00A000A")
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=100, processo=self.processo)
        out = self._run("--import", path, "--apply")
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 100)  # non rimappato
        self.assertIn("FATTO: 0", out)

    def test_collisione_saltata(self):
        path = self._export_dev(100, self.CF)
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        # in prod esiste gia' la coppia (500, processo): rimappare 100->500 collide
        ContinuitaOperativa.objects.create(legacy_anagrafica_id=500, processo=self.processo)
        orfano = ContinuitaOperativa.objects.create(legacy_anagrafica_id=100, processo=self.processo)
        out = self._run("--import", path, "--apply")
        orfano.refresh_from_db()
        self.assertEqual(orfano.legacy_anagrafica_id, 100)  # saltato
        self.assertIn("collisioni 1", out)
        self.assertIn("FATTO: 0", out)

    def test_esterno_id_zero_saltato(self):
        path = self._export_dev(100, self.CF)
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=0, processo=self.processo)
        self._run("--import", path, "--apply")
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 0)  # esterno, non toccato
