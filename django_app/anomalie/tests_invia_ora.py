"""Riepilogo delle decisioni: attesa configurabile e «Invia ora» da Gestione anomalie. Dati sintetici."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import mail_action_service as mas
from anomalie.mail_action_models import AnomaliaPendingNotification

User = get_user_model()
OP = "OP/2026/0099"


def _coda(op=OP, minuti_fa=1, righe=2):
    return AnomaliaPendingNotification.objects.create(
        op_id=op, op_nominativo=op, last_modified_at=timezone.now() - timedelta(minutes=minuti_fa),
        last_modified_by="Mario Rossi",
        updates_snapshot=[{"id": i, "seriale": f"LCN0000{i}", "avanzamento": "Accetto lo stato"} for i in range(1, righe + 1)],
    )


class CodaDecisioniTests(TestCase):
    def setUp(self):
        self._patches = [
            patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True),
            patch("anomalie.automazioni_service.prepara_decisioni_operatore", return_value=[]),
            patch("anomalie.automazioni_service.invia_decisioni_operatore", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_coda_e_partenza_prevista(self):
        self.assertIsNone(mas.decisioni_in_coda(OP))
        p = _coda()
        coda = mas.decisioni_in_coda(OP)
        self.assertEqual(coda["n"], 2)
        self.assertEqual(coda["partenza"], p.last_modified_at + timedelta(minutes=5))
        from core.models import SiteConfig

        from anomalie.escalation_config import KEY_RIEPILOGO_MINUTI
        SiteConfig.set(KEY_RIEPILOGO_MINUTI, "15", "test")
        self.assertEqual(mas.decisioni_in_coda(OP)["partenza"], p.last_modified_at + timedelta(minutes=15))

    def test_invia_ora_solo_quell_op(self):
        _coda(minuti_fa=0)
        altro = _coda(op="OP/2026/0100", minuti_fa=30)
        esito = mas.flush_pending_update_notifications(op_id=OP)
        self.assertEqual(esito["sent"], 1)
        self.assertIsNone(mas.decisioni_in_coda(OP))
        altro.refresh_from_db()
        self.assertFalse(altro.notified)  # gli altri OP seguono la loro attesa

    def test_task_usa_l_attesa_configurata(self):
        from core.models import SiteConfig

        from anomalie import tasks
        from anomalie.escalation_config import KEY_RIEPILOGO_MINUTI
        SiteConfig.set(KEY_RIEPILOGO_MINUTI, "12", "test")
        with patch("anomalie.mail_action_service.flush_pending_update_notifications", return_value={}) as flush:
            tasks.run_anomalie_pending_notifications(threshold_minutes=5)
        self.assertEqual(flush.call_args.kwargs["threshold_minutes"], 12)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class CodaDecisioniApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="coda-dec", password="pass12345", email="cd@example.local")
        self.client.force_login(self.user)
        self.puo = True
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", side_effect=lambda *a: self.puo),
            patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True),
            patch("anomalie.automazioni_service.prepara_decisioni_operatore", return_value=[]),
            patch("anomalie.automazioni_service.invia_decisioni_operatore", return_value=0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_get_e_invia_ora(self):
        url = reverse("api_anomalie_decisioni_coda")
        self.assertIsNone(self.client.get(url, {"op_id": OP}).json()["coda"])
        _coda(righe=3)
        self.assertEqual(self.client.get(url, {"op_id": OP}).json()["coda"]["n"], 3)
        r = self.client.post(url, json.dumps({"op_id": OP}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["inviate"], 3)
        self.assertIsNone(self.client.get(url, {"op_id": OP}).json()["coda"])

    def test_solo_chi_modifica_l_op(self):
        self.puo = False
        r = self.client.post(reverse("api_anomalie_decisioni_coda"), json.dumps({"op_id": OP}), content_type="application/json")
        self.assertEqual(r.status_code, 403)
