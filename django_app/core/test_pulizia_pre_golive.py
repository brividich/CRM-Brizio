"""``pulizia_pre_golive``: svuota i log operativi, mai l'audit trail.

Il patto da fissare: il dry-run non cancella nulla, l'esecuzione cancella solo
le voci di log operativo (o quelle scelte con ``--solo``), l'AuditLog resta e
riceve una riga con i conteggi.
"""
from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from anomalie.mail_action_models import AnomaliaPendingNotification
from anomalie.mail_log_models import AnomalieEmailLog
from automazioni.models import AutomationRunLog
from core.models import AuditLog, Notifica
from django.utils import timezone


def _run(*args) -> str:
    out = StringIO()
    call_command("pulizia_pre_golive", *args, stdout=out)
    return out.getvalue()


class PuliziaPreGoliveCommandTest(TestCase):
    def setUp(self):
        Notifica.objects.create(legacy_user_id=1, messaggio="prova")
        Notifica.objects.create(legacy_user_id=2, messaggio="prova 2")
        AnomalieEmailLog.objects.create(subject="test")
        AutomationRunLog.objects.create(source_code="test", operation_type="insert", status="success")
        AnomaliaPendingNotification.objects.create(op_id="OP1", last_modified_at=timezone.now(), notified=True)
        AnomaliaPendingNotification.objects.create(op_id="OP2", last_modified_at=timezone.now(), notified=False)
        AuditLog.objects.create(azione="login", modulo="core")

    def test_dry_run_non_cancella(self):
        audit_prima = AuditLog.objects.count()
        out = _run()
        self.assertIn("DRY-RUN", out)
        self.assertEqual(Notifica.objects.count(), 2)
        self.assertEqual(AnomalieEmailLog.objects.count(), 1)
        self.assertEqual(AutomationRunLog.objects.count(), 1)
        self.assertEqual(AuditLog.objects.count(), audit_prima)

    def test_esegui_svuota_log_operativi_e_registra_audit(self):
        _run("--esegui")
        self.assertEqual(Notifica.objects.count(), 0)
        self.assertEqual(AnomalieEmailLog.objects.count(), 0)
        self.assertEqual(AutomationRunLog.objects.count(), 0)
        # La notifica ancora da inviare resta in coda.
        self.assertEqual(list(AnomaliaPendingNotification.objects.values_list("op_id", flat=True)), ["OP2"])
        # L'audit trail resta e riceve il riepilogo della pulizia.
        self.assertTrue(AuditLog.objects.filter(azione="login").exists())
        riga = AuditLog.objects.get(azione="pulizia_pre_golive")
        self.assertEqual(riga.dettaglio["righe_cancellate"]["notifiche"], 2)

    def test_solo_limita_le_voci(self):
        _run("--solo", "notifiche", "--esegui")
        self.assertEqual(Notifica.objects.count(), 0)
        self.assertEqual(AnomalieEmailLog.objects.count(), 1)
        self.assertEqual(AutomationRunLog.objects.count(), 1)

    def test_codice_sconosciuto_errore(self):
        with self.assertRaises(CommandError):
            _run("--solo", "audit_log")
