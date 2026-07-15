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

    def test_report_conflitti_errore_silenzioso(self):
        # DEV: la persona SARA ha dev_id 398, CF noto.
        cf_sara = "GNTSRA80A41H501W"
        _mk_dipendente_legacy(398, "SARA", "GENTILE")
        AC.objects.create(legacy_anagrafica_id=398, codice_fiscale=cf_sara)
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        self._run("--export", path)
        AC.objects.filter(legacy_anagrafica_id=398).delete()
        with connection.cursor() as cur:
            cur.execute("DELETE FROM anagrafica_dipendenti WHERE id = %s", [398])

        # PROD: SARA ha id 200; #398 in prod e' MARIO (un'ALTRA persona reale).
        _mk_dipendente_legacy(200, "SARA", "GENTILE")
        _mk_dipendente_legacy(398, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=200, codice_fiscale=cf_sara)
        # record importato da dev sotto #398 (non orfano: 398 esiste in prod come MARIO)
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=398, processo=self.processo)

        out = self._run("--report", path)
        self.assertIn("#398", out)
        self.assertIn("#200", out)
        self.assertIn("persona sbagliata", out)
        # sola lettura: non tocca niente
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 398)

    def test_report_nessun_conflitto(self):
        path = self._export_dev(100, self.CF)
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        ContinuitaOperativa.objects.create(legacy_anagrafica_id=500, processo=self.processo)
        out = self._run("--report", path)
        self.assertIn("Nessun conflitto", out)

    def test_remap_visita_medica_orfana(self):
        from datetime import date

        from .models import TipoVisitaMedica, VisitaMedica

        path = self._export_dev(100, self.CF)  # dev: persona #100, CF
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")  # in prod la persona e' #500
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        tipo = TipoVisitaMedica.objects.create(nome="Visita periodica")
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=100, tipo=tipo, data_svolgimento=date(2024, 1, 10))

        self._run("--import", path, "--apply")
        v.refresh_from_db()
        self.assertEqual(v.legacy_anagrafica_id, 500)  # riagganciata alla persona di prod

    def test_rifai_scadenze_elimina_orfane(self):
        from datetime import timedelta

        from django.utils import timezone

        from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan

        piano = TrainingPlan.objects.create(codice="P1", nome="Piano test")
        corso = TrainingCourse.objects.create(piano=piano, codice="C1", titolo="Sicurezza",
                                              durata_ore_teorica=4)
        # prod: esiste il dipendente 500; NON esiste il 398 (scadenza orfana = "#398")
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        TrainingDeadline.objects.create(
            corso=corso, legacy_anagrafica_id=398,
            data_scadenza=timezone.localdate() + timedelta(days=10),
            stato_scadenza="IN_SCADENZA_30", giorni_alla_scadenza=10, is_required=True)

        out = self._run("--rifai-scadenze")  # dry-run
        self.assertIn("orfane (mostrano #ID): 1", out)
        self.assertEqual(TrainingDeadline.objects.count(), 1)  # dry-run non tocca

        out2 = self._run("--rifai-scadenze", "--apply")
        # senza record sorgente la rigenerazione non ricrea nulla -> la cache resta pulita
        self.assertEqual(TrainingDeadline.objects.filter(legacy_anagrafica_id=398).count(), 0)
        self.assertIn("cache ricostruita", out2)

    def test_scan_conta_orfani(self):
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")  # unico dipendente di prod
        ContinuitaOperativa.objects.create(legacy_anagrafica_id=999, processo=self.processo)  # orfano
        ContinuitaOperativa.objects.create(legacy_anagrafica_id=500, processo=ProcessoCriticoContinuita.objects.create(nome="Altro"))  # valido
        out = self._run("--scan")
        self.assertIn("SCAN ORFANI", out)
        self.assertIn("ContinuitaOperativa", out)
        self.assertIn("ORFANI", out)  # almeno un modello con orfani

    def test_esterno_id_zero_saltato(self):
        path = self._export_dev(100, self.CF)
        _mk_dipendente_legacy(500, "MARIO", "ROSSI")
        AC.objects.create(legacy_anagrafica_id=500, codice_fiscale=self.CF)
        rec = ContinuitaOperativa.objects.create(legacy_anagrafica_id=0, processo=self.processo)
        self._run("--import", path, "--apply")
        rec.refresh_from_db()
        self.assertEqual(rec.legacy_anagrafica_id, 0)  # esterno, non toccato
