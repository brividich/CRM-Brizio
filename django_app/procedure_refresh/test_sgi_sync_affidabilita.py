"""Sync SGI dalla share: niente riscritture inutili, budget con ripresa, lock, drift senza SMB."""
from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from core.models import SiteConfig
from procedure_refresh.management.commands import import_sgi_da_share as cmd
from procedure_refresh.models import ProcedureDocument, ProcedureRevision, SourceType
from procedure_refresh import tasks


def _share(tmp: str, nomi: list[str]) -> None:
    for rel in nomi:
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4 sintetico " + rel.encode("utf-8"))


class UpsertInvariatoTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_file_invariato_non_si_riscrive_ne_si_rilegge(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_Nuovo.pdf"])
            candidates, _s, _c = cmd.scan_share_candidates(Path(tmp))
            info = candidates[0]
            self.assertEqual(cmd.upsert_candidate(info), ("created", True))

            rev = ProcedureRevision.objects.get(document__code="MT CN 07")
            prima = rev.updated_at if hasattr(rev, "updated_at") else None
            with mock.patch.object(cmd, "_sha256", wraps=cmd._sha256) as hash_letto, \
                    mock.patch.object(ProcedureRevision, "save") as salva:
                stato = cmd.upsert_candidate(info)
            self.assertEqual(stato, ("unchanged", False))
            hash_letto.assert_not_called()
            salva.assert_not_called()
            if prima is not None:
                rev.refresh_from_db()
                self.assertEqual(rev.updated_at, prima)

    def test_file_modificato_si_aggiorna(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_Nuovo.pdf"])
            info = cmd.scan_share_candidates(Path(tmp))[0][0]
            cmd.upsert_candidate(info)
            Path(info["path"]).write_bytes(b"%PDF-1.4 contenuto cambiato, piu' lungo")
            self.assertEqual(cmd.upsert_candidate(info), ("updated", False))
            rev = ProcedureRevision.objects.get(document__code="MT CN 07")
            self.assertEqual(rev.file_hash, cmd._sha256(Path(info["path"])))


@override_settings()
class AutoSyncAffidabilitaTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        SiteConfig.set("pr_sgi_auto_sync_attivo", "1", "test")

    def test_secondo_giro_conta_invariati_non_aggiornati(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf", "9100/MT CN 08 Rev.1_B.pdf"])
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                with mock.patch("django_q.tasks.async_task"):
                    primo = tasks.run_sgi_auto_sync(reindex=True)
                with mock.patch("django_q.tasks.async_task") as accoda:
                    secondo = tasks.run_sgi_auto_sync(reindex=True)
        self.assertEqual(primo["created"], 2)
        self.assertEqual((secondo["created"], secondo["updated"], secondo["unchanged"]), (0, 0, 2))
        accoda.assert_not_called()  # niente re-index completo per file invariati

    def test_lock_contro_sovrapposizione(self):
        cache.add(tasks._SGI_SYNC_LOCK, 1, 60)
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf"])
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                res = tasks.run_sgi_auto_sync(force=True)
        self.assertTrue(res["skipped"])
        self.assertIn("in corso", res["reason"])
        self.assertFalse(ProcedureDocument.objects.exists())

    def test_budget_tronca_e_riprende(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, [f"9100/MT CN {n:02d} Rev.1_Doc.pdf" for n in range(10, 14)])
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp):
                # Primo giro: tutti nuovi (prioritari), budget a zero -> nessuno scritto.
                with mock.patch.object(tasks, "SGI_SYNC_BUDGET_SECONDI", -1), \
                        mock.patch("django_q.tasks.async_task") as accoda:
                    res = tasks.run_sgi_auto_sync(force=True, reindex=True)
                self.assertTrue(res["troncato"])
                self.assertEqual(res["rimanenti"], 4)
                self.assertTrue(res.get("seguito_accodato"))
                kwargs = accoda.call_args[1]
                self.assertEqual(kwargs["catena"], 1)
                # Il seguito completa il lavoro e fa partire il re-index una volta sola.
                with mock.patch("django_q.tasks.async_task") as accoda2:
                    fine = tasks.run_sgi_auto_sync(force=True, reindex=True, catena=1)
        self.assertEqual(fine["created"], 4)
        self.assertFalse(fine.get("troncato"))
        accoda2.assert_called_once_with("ai_assistant.tasks.run_index_sgi_documents")
        self.assertEqual(SiteConfig.get(tasks._RIPRENDI_DA_KEY, ""), "")

    def test_catena_ha_un_tetto(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf"])
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp), \
                    mock.patch.object(tasks, "SGI_SYNC_BUDGET_SECONDI", -1), \
                    mock.patch("django_q.tasks.async_task") as accoda:
                res = tasks.run_sgi_auto_sync(force=True, catena=tasks.SGI_SYNC_MAX_CATENA)
        self.assertTrue(res["troncato"])
        accoda.assert_not_called()

    def test_ordine_prima_nuovi_e_revisioni_poi_ripresa(self):
        safe = [
            {"code": "A"}, {"code": "B"}, {"code": "C", "nuovo": True},
            {"code": "D"}, {"code": "E", "aggiornamento_revisione": True},
        ]
        ordine = [i["code"] for i in tasks._ordina_per_priorita(safe, "D")]
        self.assertEqual(ordine, ["C", "E", "D", "A", "B"])


class DriftSenzaSmbTests(TestCase):
    def _doc(self, code: str, path: str):
        doc = ProcedureDocument.objects.create(code=code, title="t", is_active=True)
        ProcedureRevision.objects.create(
            document=doc, revision_code="1", revision_date=date.today(), effective_date=date.today(),
            source_type=SourceType.FILESERVER, source_path=path, file_name=Path(path).name, is_current=True,
        )

    def test_spariti_dall_insieme_elencato_senza_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf"])
            presente = str(Path(tmp) / "9100" / "MT CN 07 Rev.3_A.pdf")
            self._doc("MT CN 07", presente.upper())  # maiuscole diverse: è lo stesso file
            self._doc("MT CN 99", str(Path(tmp) / "9100" / "MT CN 99 Rev.1_Via.pdf"))
            with mock.patch.object(Path, "exists", side_effect=AssertionError("niente exists per doc")):
                drift = cmd.detect_share_drift(Path(tmp))
        self.assertEqual({m["code"] for m in drift["missing"]}, {"MT CN 99"})
        self.assertFalse(drift["missing_saltati"])

    def test_elenco_crollato_non_calcola_gli_spariti(self):
        SiteConfig.set(cmd.DRIFT_ULTIMO_ELENCO_KEY, json.dumps({"file_elencati": 100}), "test")
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf"])
            self._doc("MT CN 99", str(Path(tmp) / "9100" / "MT CN 99 Rev.1_Via.pdf"))
            drift = cmd.detect_share_drift(Path(tmp))
        self.assertTrue(drift["missing_saltati"])
        self.assertEqual(drift["missing"], [])
        self.assertIn("parziale", drift["missing_motivo"])

    def test_watchdog_con_elenco_parziale_non_risolve_la_issue(self):
        from procedure_refresh.tasks import run_sgi_share_check

        SiteConfig.set(cmd.DRIFT_ULTIMO_ELENCO_KEY, json.dumps({"file_elencati": 100}), "test")
        with tempfile.TemporaryDirectory() as tmp:
            _share(tmp, ["9100/MT CN 07 Rev.3_A.pdf"])
            self._doc("MT CN 07", str(Path(tmp) / "9100" / "MT CN 07 Rev.3_A.pdf"))
            with override_settings(PROCEDURE_REFRESH_SGI_SHARE_ROOT=tmp), \
                    mock.patch("monitoring.services.resolve_health_check_issue") as risolvi:
                res = run_sgi_share_check()
        self.assertTrue(res.get("missing_saltati"))
        risolvi.assert_not_called()
