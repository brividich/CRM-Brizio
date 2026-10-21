from __future__ import annotations

import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from anomalie.mail_log_models import AnomalieEmailLog
from anomalie.quality_models import (
    AnomaliaDescrizione,
    AnomaliaNC,
    AnomaliaNCEvento,
    AnomaliaSegnalazioneMeta,
    AnomaliaTipoDifetto,
)
from core.legacy_utils import legacy_table_columns


class SvuotaAnomalieTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT)")
            cur.execute("CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT)")
            cur.execute("INSERT INTO anomalie (ex_op_nominativo) VALUES ('OP-TEST-1'), ('OP-TEST-1')")
            cur.execute("INSERT INTO ordini_produzione (title) VALUES ('OP-TEST-1')")
        legacy_table_columns.cache_clear()

        nc = AnomaliaNC.objects.create(protocollo="NC-TEST-1", op_titolo="OP-TEST-1")
        AnomaliaNCEvento.objects.create(nc=nc, tipo="creata", testo="test")
        meta = AnomaliaSegnalazioneMeta.objects.create(anomalia_id=1, fase="Fase test", nc=nc)
        AnomaliaDescrizione.objects.create(segnalazione=meta, testo="Descrizione sintetica")
        AnomalieEmailLog.objects.create(subject="Mail di prova")
        self.tipo = AnomaliaTipoDifetto.objects.create(codice="graffio", nome="Graffio")

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "1").mkdir()
        (self.root / "1" / "file.pdf").write_bytes(b"x")
        (self.root / "nc" / str(nc.pk)).mkdir(parents=True)
        (self.root / "README.txt").write_text("non toccare")
        patcher = patch(
            "anomalie.management.commands.svuota_anomalie._anomalie_attachments_root", return_value=self.root
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")
            cur.execute("DROP TABLE ordini_produzione")
        legacy_table_columns.cache_clear()
        self.tmp.cleanup()

    def _conta(self, tabella):
        with connection.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {tabella}")
            return cur.fetchone()[0]

    def test_prova_a_secco_non_cancella(self):
        out = StringIO()
        call_command("svuota_anomalie", stdout=out)
        self.assertIn("Prova a secco", out.getvalue())
        self.assertIn("Tabella anomalie: 2", out.getvalue())
        self.assertEqual(self._conta("anomalie"), 2)
        self.assertEqual(AnomaliaNC.objects.count(), 1)
        self.assertTrue((self.root / "1").exists())

    def test_esegui_svuota_dati_e_lascia_configurazione(self):
        call_command("svuota_anomalie", "--esegui", stdout=StringIO())
        self.assertEqual(self._conta("anomalie"), 0)
        self.assertEqual(self._conta("ordini_produzione"), 0)
        self.assertEqual(AnomaliaNC.objects.count(), 0)
        self.assertEqual(AnomaliaNCEvento.objects.count(), 0)
        self.assertEqual(AnomaliaSegnalazioneMeta.objects.count(), 0)
        self.assertEqual(AnomaliaDescrizione.objects.count(), 0)
        self.assertEqual(AnomalieEmailLog.objects.count(), 0)
        self.assertTrue(AnomaliaTipoDifetto.objects.filter(pk=self.tipo.pk).exists())
        self.assertFalse((self.root / "1").exists())
        self.assertEqual(list((self.root / "nc").iterdir()), [])
        self.assertTrue((self.root / "README.txt").exists())

    def test_mantieni_op(self):
        call_command("svuota_anomalie", "--esegui", "--mantieni-op", stdout=StringIO())
        self.assertEqual(self._conta("anomalie"), 0)
        self.assertEqual(self._conta("ordini_produzione"), 1)
