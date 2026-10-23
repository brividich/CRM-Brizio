"""Approvazione via mail: stato coerente e invio a SharePoint (#9656, #9727)."""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from automazioni.services import _execute_update_trigger_record

from .views import _helpers


class AllineaDopoAutomazioneTests(TestCase):
    @patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"ok": True, "queued": True})
    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._has_assenze_column", return_value=True)
    @patch("assenze.views._helpers._get_assenza",
           return_value={"id": 9, "moderation_status": 0, "consenso": "In attesa", "approvazione_datetime": None})
    def test_approvata_via_mail_consenso_e_coda(self, _get, _col, upd, enq):
        _helpers.allinea_dopo_automazione(9, ["moderation_status"])
        updates = upd.call_args.args[1]
        self.assertEqual(updates["consenso"], "Approvato")
        self.assertIn("approvazione_datetime", updates)
        enq.assert_called_once_with(9)

    @patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"ok": True})
    @patch("assenze.views._helpers._update_assenza")
    @patch("assenze.views._helpers._get_assenza",
           return_value={"id": 9, "moderation_status": 1, "consenso": "Rifiutato"})
    def test_gia_coerente_solo_coda(self, _get, upd, enq):
        _helpers.allinea_dopo_automazione(9, ["moderation_status"])
        upd.assert_not_called()
        enq.assert_called_once_with(9)


class UpdateTriggerRecordAssenzeTests(TestCase):
    def setUp(self):
        with connection.cursor() as c:
            c.execute("CREATE TABLE IF NOT EXISTS assenze (id INTEGER PRIMARY KEY, moderation_status INTEGER, "
                      "consenso TEXT)")
            c.execute("DELETE FROM assenze")
            c.execute("INSERT INTO assenze (id, moderation_status, consenso) VALUES (7, 2, 'In attesa')")

    @patch("assenze.views._helpers.allinea_dopo_automazione")
    def test_aggancio_dopo_update(self, allinea):
        out = _execute_update_trigger_record(
            source_code="assenze", payload_context={"id": 7}, queue_event=None,
            update_fields={"moderation_status": "0"},
        )
        self.assertEqual(out["rowcount"], 1)
        allinea.assert_called_once()
        self.assertEqual(str(allinea.call_args.args[0]), "7")
        self.assertIn("moderation_status", allinea.call_args.args[1])

    @patch("assenze.views._helpers.allinea_dopo_automazione", side_effect=RuntimeError("giù"))
    def test_errore_di_allineamento_non_annulla_update(self, _allinea):
        out = _execute_update_trigger_record(
            source_code="assenze", payload_context={"id": 7}, queue_event=None,
            update_fields={"moderation_status": "0"},
        )
        self.assertEqual(out["rowcount"], 1)
        with connection.cursor() as c:
            c.execute("SELECT moderation_status FROM assenze WHERE id = 7")
            self.assertEqual(c.fetchone()[0], 0)


class RiallineaComandoTests(TestCase):
    def _approval(self, pk, status):
        from automazioni.models import AutomationApproval, AutomationRule, AutomationRunLog

        rule = AutomationRule.objects.create(code=f"r{pk}{status}", name="r", source_code="assenze", operation_type="insert")
        rl = AutomationRunLog.objects.create(rule=rule, source_code="assenze", operation_type="insert")
        return AutomationApproval.objects.create(run_log=rl, subject="s", status=status, resume_payload={"id": pk},
                                                 decided_by_email="capo@example.com")

    @patch("assenze.views._helpers.allinea_dopo_automazione")
    @patch("assenze.views._helpers._update_assenza", return_value=True)
    @patch("assenze.views._helpers._get_assenza")
    def test_anteprima_e_applica(self, get, upd, allinea):
        self._approval(9727, "approved")
        self._approval(9000, "approved")
        get.side_effect = lambda pk: {"id": pk, "moderation_status": 2 if pk == 9727 else 0}
        out = StringIO()
        call_command("riallinea_assenze_decise_da_mail", stdout=out)
        self.assertIn("#9727: In attesa -> Approvato", out.getvalue())
        self.assertNotIn("#9000", out.getvalue())
        upd.assert_not_called()
        call_command("riallinea_assenze_decise_da_mail", "--applica", stdout=StringIO())
        upd.assert_called_once_with(9727, {"moderation_status": 0})
        allinea.assert_called_once_with(9727, ["moderation_status"])
