"""Test F8 — validatore e import storico (fixture sintetiche conformi al template)."""
from __future__ import annotations

import csv
import os
import tempfile
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from gestione_specifiche import constants as C
from gestione_specifiche.import_storico import (
    EXPECTED_COLUMNS, importa_riga, importa_righe, valida_riga,
)
from gestione_specifiche.models import EventoSpecifica, Specifica


def _row(**kw):
    base = {
        "codice": "SPEC-001", "revisione": "1", "titolo": "T",
        "tipo": C.TIPO_SPECIFICA, "fonte": C.FONTE_CLIENTE, "cliente": "ACME",
        "tag": "", "data_inserimento": "", "data_verifica": "", "note": "",
        "stato": C.STATO_IN_VALIDITA, "master_codice": "",
    }
    base.update(kw)
    return base


class ValidatoreTests(TestCase):
    def test_riga_valida(self):
        self.assertEqual(valida_riga(_row()), [])

    def test_campi_obbligatori(self):
        err = valida_riga(_row(codice="", titolo=""))
        self.assertTrue(any("codice" in e for e in err))
        self.assertTrue(any("titolo" in e for e in err))

    def test_tipo_e_fonte_non_validi(self):
        err = valida_riga(_row(tipo="xxx", fonte="yyy"))
        self.assertTrue(any("tipo non valido" in e for e in err))
        self.assertTrue(any("fonte non valida" in e for e in err))

    def test_solo_in_validita(self):
        err = valida_riga(_row(stato=C.STATO_BOZZA))
        self.assertTrue(any("in_validita" in e for e in err))

    def test_data_malformata(self):
        err = valida_riga(_row(data_inserimento="14/03/2023"))
        self.assertTrue(any("data non valida" in e for e in err))


class ImportRigaTests(TestCase):
    def test_dry_run_non_crea(self):
        esito = importa_riga(_row(), apply=False)
        self.assertEqual(esito, "valido (dry-run)")
        self.assertFalse(Specifica.objects.exists())

    def test_apply_crea_in_validita(self):
        esito = importa_riga(_row(codice="SPEC-APP", data_inserimento="2020-01-15",
                                  data_verifica="2026-01-15"), apply=True)
        self.assertEqual(esito, "creato")
        spec = Specifica.objects.get(codice="SPEC-APP")
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)
        self.assertEqual(spec.data_inserimento.date().isoformat(), "2020-01-15")
        self.assertEqual(spec.data_verifica.isoformat(), "2026-01-15")
        self.assertTrue(EventoSpecifica.objects.filter(
            specifica=spec, trigger="import_storico").exists())

    def test_idempotenza(self):
        importa_riga(_row(codice="SPEC-IDEM"), apply=True)
        esito2 = importa_riga(_row(codice="SPEC-IDEM"), apply=True)
        self.assertEqual(esito2, "duplicato")
        self.assertEqual(Specifica.objects.filter(codice="SPEC-IDEM").count(), 1)

    def test_riga_scartata(self):
        esito = importa_riga(_row(tipo="xxx"), apply=True)
        self.assertTrue(esito.startswith("scartato"))
        self.assertFalse(Specifica.objects.exists())


class ImportRigheTests(TestCase):
    def test_conteggi(self):
        rows = [
            _row(codice="A"),
            _row(codice="B", tipo="xxx"),     # scartata
            _row(codice="A"),                  # duplicato (dopo A creata)
        ]
        res = importa_righe(rows, apply=True)
        c = res["counters"]
        self.assertEqual(c["creato"], 1)
        self.assertEqual(c["scartato"], 1)
        self.assertEqual(c["duplicato"], 1)
        self.assertEqual(len(res["scarti"]), 1)


class CommandTests(TestCase):
    def _scrivi_csv(self, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=EXPECTED_COLUMNS, delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow(r)
        self.addCleanup(os.remove, path)
        return path

    def test_dry_run_command(self):
        path = self._scrivi_csv([_row(codice="C1"), _row(codice="C2")])
        out = StringIO()
        call_command("import_specifiche_storico", path, stdout=out)
        self.assertFalse(Specifica.objects.exists())  # dry-run: nessuna scrittura
        self.assertIn("DRY-RUN", out.getvalue())

    def test_apply_command(self):
        path = self._scrivi_csv([
            _row(codice="C1"), _row(codice="C2"), _row(codice="C3", tipo="xxx"),
        ])
        out = StringIO()
        call_command("import_specifiche_storico", path, "--apply", stdout=out)
        self.assertEqual(Specifica.objects.count(), 2)
        self.assertIn("creati: 2", out.getvalue())
        self.assertIn("scartati: 1", out.getvalue())

    def test_genera_template(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        self.addCleanup(os.remove, path)
        xlsx = os.path.splitext(path)[0] + ".xlsx"
        self.addCleanup(lambda: os.path.exists(xlsx) and os.remove(xlsx))
        out = StringIO()
        call_command("import_specifiche_storico", "--genera-template", path, stdout=out)
        self.assertTrue(os.path.exists(path))
        with open(path, encoding="utf-8-sig") as fh:
            header = fh.readline()
        for col in ("codice", "tipo", "fonte", "stato"):
            self.assertIn(col, header)
