"""audit_archive (BUILD_SPEC R0.3/R0.4) su dati sintetici misti."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import tempfile
from datetime import date, datetime
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from core import audit_archive as svc
from core.models import AuditLog


def _mk(azione, modulo, dettaglio):
    return AuditLog.objects.create(azione=azione, modulo=modulo, dettaglio=dettaglio)


def _checksum(qs) -> str:
    h = hashlib.sha256()
    for row in qs.order_by("id").values_list("id", "azione", "modulo", "dettaglio"):
        h.update(json.dumps(row, sort_keys=True, default=str).encode())
    return h.hexdigest()


class AuditArchiveTests(TestCase):
    def setUp(self):
        AuditLog.objects.all().delete()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # classe A: azione esplicita e auto_* di un modello di business
        self.a_ids = [
            _mk("modifica_ticket", "tickets", {"ticket": 1}).id,
            _mk("auto_insert", "core", {"model": "SiteConfig", "pk": "1", "valori": {"valore": "x"}}).id,
            _mk("auto_update", "automazioni", {"model": "AutomationRule", "pk": "2",
                                               "modifiche": {"name": {"old": "a", "new": "b"},
                                                             "last_run_at": {"old": None, "new": "t"}}}).id,
            _mk("login_fallito", "core", {"username": "u"}).id,
        ]
        # classe B
        self.b_ids = [
            _mk("auto_insert", "automazioni", {"model": "AutomationRunLog", "pk": str(i), "valori": {"x": i}}).id
            for i in range(5)
        ]
        # classe C con valori
        self.c_id = _mk("auto_insert", "security", {
            "model": "SecuritySourceFile", "pk": "9", "oggetto": "file.pdf",
            "valori": {"content": "CONTENUTO-PRIVATO", "filename": "file.pdf", "vuoto": ""},
        }).id
        # classe D a modifica nulla
        self.d_null_id = _mk("auto_update", "automazioni", {
            "model": "AutomationRule", "pk": "3",
            "modifiche": {"last_run_at": {"old": None, "new": "t"}, "updated_at": {"old": "a", "new": "b"}},
        }).id
        self.d_empty_id = _mk("auto_update", "core", {"model": "Notifica", "pk": "4"}).id

    def tearDown(self):
        self.tmp.cleanup()

    def _a_qs(self):
        return AuditLog.objects.filter(id__in=self.a_ids)

    def test_classify_row(self):
        cats = {r.id: svc.classify_row({"azione": r.azione, "modulo": r.modulo, "dettaglio": r.dettaglio})
                for r in AuditLog.objects.all()}
        for i in self.a_ids:
            self.assertEqual(cats[i], "keep")
        for i in self.b_ids:
            self.assertEqual(cats[i], "tecnico")
        self.assertEqual(cats[self.c_id], "contenuti")
        self.assertEqual(cats[self.d_null_id], "update_nullo")
        self.assertEqual(cats[self.d_empty_id], "update_nullo")

    def test_plan_non_modifica_nulla(self):
        prima = _checksum(AuditLog.objects.all())
        out = io.StringIO()
        call_command("audit_archive", "--plan", "--json", stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["righe_interessate"], 5 + 1 + 2)
        self.assertEqual(_checksum(AuditLog.objects.all()), prima)
        self.assertFalse(any(self.dir.iterdir()))

    def test_default_e_plan(self):
        out = io.StringIO()
        call_command("audit_archive", stdout=out)
        self.assertIn("dry-run", out.getvalue())

    def test_run_classe_a_intatta_b_archiviata_c_ridotta(self):
        a_prima = _checksum(self._a_qs())
        res = svc.run(self.dir, batch=3)
        self.assertTrue(res.completato)
        self.assertEqual(_checksum(self._a_qs()), a_prima)
        self.assertEqual(self._a_qs().count(), len(self.a_ids))
        self.assertFalse(AuditLog.objects.filter(id__in=self.b_ids + [self.d_null_id, self.d_empty_id]).exists())
        c = AuditLog.objects.get(id=self.c_id)
        self.assertNotIn("valori", c.dettaglio)
        self.assertEqual(c.dettaglio["campi_valorizzati"], ["content", "filename"])
        self.assertEqual(c.dettaglio["oggetto"], "file.pdf")
        self.assertNotIn("CONTENUTO-PRIVATO", json.dumps(c.dettaglio))
        # archivio: manifest verificato, righe B complete, C senza valori
        month_dirs = list((self.dir / "auditlog").iterdir())
        self.assertEqual(len(month_dirs), 1)
        ok, errori = svc.verify_month(month_dirs[0])
        self.assertTrue(ok, errori)
        records = []
        for part in sorted(month_dirs[0].glob("part-*.jsonl.gz")):
            with gzip.open(part, "rt", encoding="utf-8") as gz:
                records += [json.loads(line) for line in gz]
        self.assertEqual(sorted(r["id"] for r in records),
                         sorted(self.b_ids + [self.c_id, self.d_null_id, self.d_empty_id]))
        self.assertNotIn("CONTENUTO-PRIVATO", json.dumps(records))
        b0 = next(r for r in records if r["id"] == self.b_ids[0])
        self.assertEqual(b0["dettaglio"]["valori"], {"x": 0})

    def test_db_toccato_solo_dopo_archivio_e_ripresa(self):
        def boom():
            raise RuntimeError("interruzione simulata")

        with self.assertRaises(RuntimeError):
            svc.run(self.dir, batch=4, _after_archive_hook=boom)
        # archivio scritto ma DB intatto: nessuna cancellazione prima della fine del lotto
        self.assertEqual(AuditLog.objects.filter(id__in=self.b_ids).count(), 5)
        res = svc.run(self.dir, batch=4)
        self.assertTrue(res.completato)
        self.assertFalse(AuditLog.objects.filter(id__in=self.b_ids).exists())
        # la ripresa riparte dallo stato salvato
        state = json.loads((self.dir / svc.STATE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(state["runs"]["policy:-"]["last_id"], res.last_id)
        self.assertIn("completed_at", state["runs"]["policy:-"])

    def test_max_minutes_interrompe_e_riprende(self):
        res = svc.run(self.dir, batch=2, max_minutes=0.0000001)
        self.assertTrue(res.interrotto_per_tempo)
        res2 = svc.run(self.dir, batch=2)
        self.assertTrue(res2.completato)
        self.assertGreater(res2.last_id, res.last_id)
        self.assertFalse(AuditLog.objects.filter(id__in=self.b_ids).exists())

    def test_lotti_oltre_mille_id(self):
        AuditLog.objects.bulk_create([
            AuditLog(azione="auto_delete", modulo="security", dettaglio={"model": "SecurityCveImpact", "pk": str(i)})
            for i in range(2500)
        ])
        res = svc.run(self.dir, batch=5000)
        self.assertTrue(res.completato)
        self.assertEqual(AuditLog.objects.filter(dettaglio__model="SecurityCveImpact").count(), 0)
        self.assertEqual(res.cancellate, 2500 + 5 + 2)

    def test_restore_in_tabella_separata(self):
        svc.run(self.dir)
        manifest = next((self.dir / "auditlog").iterdir()) / "manifest.json"
        n = svc.restore(manifest, "core_auditlog_restored_t")
        self.assertEqual(n, 5 + 1 + 2)
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM core_auditlog_restored_t")
            self.assertEqual(cur.fetchone()[0], n)
        with self.assertRaises(svc.ArchiveError):
            svc.restore(manifest, "core_auditlog")
        with self.assertRaises(svc.ArchiveError):
            svc.restore(manifest, "x; DROP TABLE y")

    def test_restore_rifiuta_archivio_manomesso(self):
        svc.run(self.dir)
        month = next((self.dir / "auditlog").iterdir())
        part = next(month.glob("part-*.jsonl.gz"))
        part.write_bytes(part.read_bytes() + b"x")
        with self.assertRaises(svc.ArchiveError):
            svc.restore(month / "manifest.json", "core_auditlog_restored_t2")

    def test_business_minimo_60_mesi(self):
        with self.assertRaises(svc.ArchiveError):
            svc.business_cutoff(12)
        with self.assertRaises(CommandError):
            call_command("audit_archive", "--category", "business", "--older-than-months", "24", stdout=io.StringIO())
        self.assertEqual(svc.business_cutoff(60, today=date(2026, 10, 16)).date(), date(2021, 10, 1))

    def test_business_archivia_solo_classe_a_vecchia(self):
        vecchio = timezone.make_aware(datetime(2019, 1, 15))
        AuditLog.objects.filter(id=self.a_ids[0]).update(created_at=vecchio)
        res = svc.run(self.dir, category="business", before=svc.business_cutoff(60))
        self.assertEqual(res.archiviate, 1)
        self.assertFalse(AuditLog.objects.filter(id=self.a_ids[0]).exists())
        self.assertTrue(AuditLog.objects.filter(id__in=self.a_ids[1:]).count() == 3)
        self.assertEqual(AuditLog.objects.filter(id__in=self.b_ids).count(), 5)  # non è compito di business
        self.assertTrue((self.dir / "auditlog" / "2019-01" / "manifest.json").exists())

    def test_prune_archivi_120_mesi(self):
        root = self.dir / "auditlog"
        for m in ("2014-01", "2015-02", "2026-09"):
            svc.write_part(self.dir, m, [{"id": 1, "_categoria": "tecnico"}])
        # 2015-02 manomesso: non va eliminato
        p = next((root / "2015-02").glob("part-*.jsonl.gz"))
        p.write_bytes(b"manomesso")
        with self.assertRaises(svc.ArchiveError):
            svc.prune_archives(self.dir, keep_months=24)
        dry = svc.prune_archives(self.dir, today=date(2026, 10, 16))
        self.assertEqual({e["mese"] for e in dry}, {"2014-01", "2015-02"})
        self.assertTrue((root / "2014-01").exists())
        svc.prune_archives(self.dir, apply=True, today=date(2026, 10, 16))
        self.assertFalse((root / "2014-01").exists())
        self.assertTrue((root / "2015-02").exists())
        self.assertTrue((root / "2026-09").exists())

    def test_comando_run_richiede_archive_dir(self):
        with self.assertRaises(CommandError):
            call_command("audit_archive", "--run", stdout=io.StringIO())
