"""Defender for Endpoint: software dei PC, incidenti, Secure Score (Graph/Defender simulati)."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from security.models import SecurityAlert, SecurityEventRecord, SoftwareInstallation, SoftwareInventoryImport, SoftwareSourceKind
from security.services import defender_alerts, defender_software, secure_score
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.configuration import set_setting
from security.services.rule_engine import evaluate_security_rules

ORA = datetime(2026, 10, 19, 10, 0, tzinfo=dt_timezone.utc)


def _sw(host="PC-SINT-01", nome="microsoft_365_apps", versione="16.0.1", vendor="microsoft"):
    return {"deviceName": host, "softwareName": nome, "softwareVersion": versione, "softwareVendor": vendor}


class SoftwareTests(TestCase):
    def test_import_come_fonte_defender(self):
        with patch("security.services.defender_software._dopo_import") as dopo:
            esito = defender_software.sincronizza(righe=[_sw(), _sw(nome="chrome", vendor="google", versione="120.0"),
                                                         _sw(versione=""), _sw()])
        self.assertEqual((esito["importate"], esito["pc"]), (2, 1))
        dopo.assert_called_once()
        imp = SoftwareInventoryImport.objects.get()
        self.assertEqual(imp.source_kind, SoftwareSourceKind.DEFENDER)
        self.assertEqual(imp.rows_skipped, 1)
        self.assertTrue(SoftwareInstallation.objects.filter(source_kind=SoftwareSourceKind.DEFENDER, product_raw="microsoft 365 apps").exists())

    def test_software_sparito_non_piu_rilevato(self):
        with patch("security.services.defender_software._dopo_import"):
            defender_software.sincronizza(righe=[_sw(), _sw(nome="chrome", vendor="google", versione="120.0")])
            esito = defender_software.sincronizza(righe=[_sw()])
        self.assertEqual(esito["non_piu_rilevate"], 1)

    def test_spento_non_legge(self):
        with patch("security.services.defender_software.leggi") as leggi:
            self.assertEqual(defender_software.run(), {"attivo": False})
        leggi.assert_not_called()

    def test_permesso_mancante_non_fa_fallire(self):
        from core.m365_graph import GraphError

        set_setting("defender.software.attivo", True)
        with patch("core.m365_graph.configurato", return_value=True), \
             patch("security.services.defender_software.leggi", side_effect=GraphError("403", 403)):
            self.assertFalse(defender_software.run()["ok"])


def _incidente(iid="inc-1", status="active", severity="high", updated="2026-10-19T09:00:00Z"):
    return {"id": iid, "displayName": "Attività sospetta su più dispositivi", "status": status, "severity": severity,
            "lastUpdateDateTime": updated, "incidentWebUrl": "https://security.microsoft.com/incidents/inc-1"}


def _alert(aid, incident="inc-1"):
    return {"id": aid, "title": "PowerShell sospetto", "severity": "high", "status": "new", "incidentId": incident,
            "lastUpdateDateTime": "2026-10-19T09:00:00Z", "evidence": []}


class IncidentiTests(TestCase):
    def setUp(self):
        set_setting("defender.alert.attivo", True)
        set_setting("defender.incidenti.attivo", True)

    def test_un_alert_per_incidente_e_chiusura(self):
        with patch("security.services.defender_alerts.fetch_alerts", return_value=[_alert("a1"), _alert("a2")]), \
             patch("security.services.defender_alerts.fetch_incidents", return_value=[_incidente()]):
            esito = defender_alerts.run(now=ORA)
        self.assertEqual(esito["eventi_incidenti"], 1)
        alert = SecurityAlert.objects.get()
        self.assertIn("incidente", alert.title)
        # Gli alert singoli restano eventi.
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=defender_alerts.EVENT_TYPE).count(), 2)

        with patch("security.services.defender_alerts.fetch_alerts", return_value=[]), \
             patch("security.services.defender_alerts.fetch_incidents",
                   return_value=[_incidente(status="resolved", updated="2026-10-19T11:00:00Z")]):
            defender_alerts.run(now=ORA + timedelta(minutes=15))
        alert.refresh_from_db()
        self.assertNotIn(alert.status, ACTIVE_ALERT_STATUSES)

    def test_senza_raggruppamento_un_alert_per_alert(self):
        set_setting("defender.incidenti.attivo", False)
        with patch("security.services.defender_alerts.fetch_alerts", return_value=[_alert("a1"), _alert("a2")]), \
             patch("security.services.defender_alerts.fetch_incidents") as inc:
            defender_alerts.run(now=ORA)
        inc.assert_not_called()
        evaluate_security_rules()
        self.assertEqual(SecurityAlert.objects.count(), 2)


def _score(giorno, attuale, controlli=None):
    return {"createdDateTime": f"2026-10-{giorno:02d}T00:00:00Z", "currentScore": attuale, "maxScore": 200,
            "controlScores": controlli or []}


class SecureScoreTests(TestCase):
    profili = [
        {"id": "MFARegistrationV2", "title": "Registra tutti gli utenti per l'MFA", "maxScore": 9, "actionUrl": "https://security.microsoft.com/x"},
        {"id": "BlockLegacyAuth", "title": "Blocca l'autenticazione legacy", "maxScore": 8, "actionUrl": "javascript:alert(1)"},
        {"id": "Fatto", "title": "Già fatto", "maxScore": 5},
        {"id": "Vecchio", "title": "Deprecato", "maxScore": 10, "deprecated": True},
    ]

    def test_calcolo(self):
        controlli = [{"controlName": "MFARegistrationV2", "score": 3}, {"controlName": "BlockLegacyAuth", "score": 0},
                     {"controlName": "Fatto", "score": 5}, {"controlName": "Vecchio", "score": 0}]
        r = secure_score.calcola([_score(19, 120, controlli), _score(1, 100)], self.profili)
        self.assertEqual(r["percentuale"], 60.0)
        self.assertEqual(r["variazione_30gg"], 10.0)
        self.assertEqual([a["titolo"] for a in r["azioni"]], ["Blocca l'autenticazione legacy", "Registra tutti gli utenti per l'MFA"])
        self.assertEqual(r["azioni"][0]["url"], "")  # link non https scartato

    def test_aggiorna_ogni_12_ore_e_panoramica(self):
        set_setting("defender.secure_score.attivo", True)
        with patch("core.m365_graph.get_all", side_effect=[[_score(19, 120)], []]) as get_all:
            secure_score.aggiorna(now=ORA)
            secure_score.aggiorna(now=ORA + timedelta(hours=1))
        self.assertEqual(get_all.call_count, 2)  # una lettura sola (punteggi + profili)
        self.assertEqual(secure_score.per_panoramica()["percentuale"], 60.0)

    def test_spento(self):
        self.assertEqual(secure_score.aggiorna(now=ORA), {"attivo": False})
        self.assertIsNone(secure_score.per_panoramica())


class TokenDefenderTests(TestCase):
    def test_url_defender_ammesso_altri_no(self):
        from core import m365_graph

        with self.assertRaises(m365_graph.GraphError):
            m365_graph.get("https://esempio.it/api", permesso="x", tok="t")
        with patch("requests.get") as get:
            get.return_value.status_code = 200
            get.return_value.json.return_value = {"value": []}
            m365_graph.get(defender_software.URL, permesso="x", tok="t")
        self.assertTrue(get.called)
