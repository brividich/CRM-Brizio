"""Alert di Microsoft Defender nel SOC (security.services.defender_alerts). Graph sempre simulato."""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from security.models import SecurityAlert, SecurityEventRecord, Status
from security.services import defender_alerts as svc
from security.services.configuration import set_setting
from security.services.rule_engine import evaluate_security_rules


def _alert(aid="da-001", severity="high", status="new", updated="2026-10-18T08:00:00Z", **extra):
    base = {
        "id": aid, "title": "Attività sospetta di PowerShell", "severity": severity, "status": status,
        "category": "Execution", "serviceSource": "microsoftDefenderForEndpoint",
        "lastUpdateDateTime": updated, "createdDateTime": "2026-10-18T07:55:00Z",
        "alertWebUrl": "https://security.microsoft.com/alerts/da-001",
        "description": "Descrizione lunga con dettagli che non devono essere copiati",
        "evidence": [
            {"@odata.type": "#microsoft.graph.security.deviceEvidence", "deviceDnsName": "pc-sintetico-01"},
            {"@odata.type": "#microsoft.graph.security.userEvidence",
             "userAccount": {"userPrincipalName": "mario.sintetico@example.com"}},
        ],
    }
    base.update(extra)
    return base


class _Resp:
    def __init__(self, status, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class NormalizzazioneTests(TestCase):
    def test_payload_minimo_senza_utenti_ne_descrizione(self):
        p = svc.normalize(_alert())
        self.assertEqual(p["devices"], ["pc-sintetico-01"])
        self.assertEqual(p["users_count"], 1)
        testo = str(p)
        self.assertNotIn("mario.sintetico", testo)
        self.assertNotIn("Descrizione lunga", testo)

    def test_link_non_https_scartato(self):
        self.assertEqual(svc.normalize(_alert(alertWebUrl="javascript:alert(1)"))["web_url"], "")


class EventiERegoleTests(TestCase):
    def setUp(self):
        set_setting("defender.alert.attivo", True)

    def test_stesso_alert_non_duplica_e_cambio_stato_si(self):
        self.assertEqual(len(svc.record_events([_alert()])), 1)
        self.assertEqual(len(svc.record_events([_alert(updated="2026-10-18T08:10:00Z")])), 0)
        self.assertEqual(len(svc.record_events([_alert(status="inProgress")])), 1)

    def test_alert_sopra_soglia_apre_alert_soc_una_volta(self):
        svc.record_events([_alert()])
        evaluate_security_rules()
        alert = SecurityAlert.objects.get()
        self.assertTrue(alert.title.startswith("Defender: Attività sospetta"))
        self.assertIn("pc-sintetico-01", alert.title)
        self.assertEqual(alert.severity, "high")
        svc.record_events([_alert(status="inProgress")])
        evaluate_security_rules()
        self.assertEqual(SecurityAlert.objects.count(), 1)

    def test_risolto_in_defender_chiude_alert_soc(self):
        svc.record_events([_alert()])
        evaluate_security_rules()
        svc.record_events([_alert(status="resolved")])
        evaluate_security_rules()
        alert = SecurityAlert.objects.get()
        self.assertEqual(alert.status, Status.RESOLVED)
        self.assertIn("Defender", alert.status_reason)

    def test_sotto_soglia_resta_evento(self):
        svc.record_events([_alert(severity="low")])
        evaluate_security_rules()
        self.assertFalse(SecurityAlert.objects.exists())
        self.assertEqual(SecurityEventRecord.objects.get().decision_trace["decision"], "kpi_only")
        set_setting("defender.severita_minima", "low")
        svc.record_events([_alert(aid="da-002", severity="low")])
        evaluate_security_rules()
        self.assertEqual(SecurityAlert.objects.count(), 1)


class GiroTests(TestCase):
    def test_spento_non_chiama_graph(self):
        with patch.object(svc, "fetch_alerts") as fetch:
            self.assertEqual(svc.run(), {"attivo": False})
        fetch.assert_not_called()

    def test_giro_salva_cursore_ed_esito(self):
        set_setting("defender.alert.attivo", True)
        with patch.object(svc, "fetch_alerts", return_value=[_alert()]) as fetch:
            esito = svc.run()
        self.assertTrue(esito["ok"])
        self.assertEqual(esito["eventi"], 1)
        self.assertEqual(SecurityAlert.objects.count(), 1)  # regole valutate subito
        self.assertTrue(svc.last_run()["ok"])
        # Secondo giro: parte dal cursore salvato (meno un minuto), non dai 7 giorni.
        with patch.object(svc, "fetch_alerts", return_value=[]) as fetch:
            svc.run()
        since = fetch.call_args.args[0]
        self.assertLess((timezone.now() - since).total_seconds(), 600)

    def test_permesso_mancante_registrato_senza_eccezione(self):
        set_setting("defender.alert.attivo", True)
        with patch.object(svc, "_token", return_value="t"), \
             patch.object(svc, "_graph_credentials", return_value=("t", "c", "s")), \
             patch("requests.get", return_value=_Resp(403)):
            esito = svc.run()
        self.assertFalse(esito["ok"])
        self.assertIn("SecurityAlert.Read.All", esito["errore"])

    def test_paginazione_e_link_estranei(self):
        pagine = [
            _Resp(200, {"value": [_alert("a1")], "@odata.nextLink": "https://graph.microsoft.com/v1.0/security/alerts_v2?$skiptoken=x"}),
            _Resp(200, {"value": [_alert("a2")]}),
        ]
        with patch("requests.get", side_effect=pagine):
            alerts = svc.fetch_alerts(timezone.now(), token="t")
        self.assertEqual([a["id"] for a in alerts], ["a1", "a2"])
        with patch("requests.get", return_value=_Resp(200, {"value": [], "@odata.nextLink": "https://evil.example/x"})):
            with self.assertRaises(svc.DefenderError):
                svc.fetch_alerts(timezone.now(), token="t")
