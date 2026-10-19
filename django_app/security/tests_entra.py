"""Segnali di Microsoft Entra ID nel SOC (security.services.entra_signals). Graph sempre simulato."""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from django.test import TestCase

from security.models import SecurityAlert, SecurityEventRecord, Severity
from security.services import entra_signals as svc
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.configuration import set_setting

ORA = datetime(2026, 10, 19, 10, 0, tzinfo=dt_timezone.utc)


def _audit(aid="aud-1", attivita="Add member to role", quando="2026-10-19T09:30:00Z"):
    return {
        "id": aid, "activityDisplayName": attivita, "category": "RoleManagement", "result": "success",
        "activityDateTime": quando,
        "initiatedBy": {"user": {"userPrincipalName": "admin.sintetico@example.com"}},
        "targetResources": [{"userPrincipalName": "utente.sintetico@example.com"}, {"displayName": "Global Administrator"}],
    }


def _riconciliazione(*righe):
    return {"letto_alle": ORA.isoformat(), "con_accessi": True, "inattivo_giorni": 90,
            "conteggi": {}, "righe": list(righe)}


def _riga(entra_id="u-1", esito="cessato_attivo"):
    return {"entra_id": entra_id, "nome_account": "Rossi Sintetico", "upn": "r.sintetico@example.com",
            "abilitato": True, "licenze": 1, "ultimo_accesso": "", "esito": esito, "persona": "ROSSI SINTETICO",
            "persona_id": 7, "cessato_il": "2026-09-30", "giorni_senza_accesso": 19, "note": []}


class ClassificazioneTests(TestCase):
    def test_attivita_sorvegliate(self):
        self.assertEqual(svc.classifica("Add member to role")[1], Severity.HIGH)
        self.assertEqual(svc.classifica("Set domain authentication")[1], Severity.CRITICAL)
        self.assertEqual(svc.classifica("Update conditional access policy")[1], Severity.HIGH)
        self.assertEqual(svc.classifica("User registered security info")[1], Severity.MEDIUM)
        self.assertIsNone(svc.classifica("Update user"))

    def test_riga_non_sorvegliata_scartata(self):
        self.assertIsNone(svc.normalizza_audit(_audit(attivita="Update user")))
        p = svc.normalizza_audit(_audit())
        self.assertEqual(p["autore"], "admin.sintetico@example.com")
        self.assertEqual(p["target"][0], "utente.sintetico@example.com")


class AuditTests(TestCase):
    def setUp(self):
        set_setting("entra.audit.attivo", True)

    def test_giro_crea_alert_solo_per_attivita_sorvegliate_senza_doppioni(self):
        righe = [_audit(), _audit("aud-2", "Update user")]
        with patch("core.m365_graph.get_all", return_value=righe):
            esito = svc.run(now=ORA)
            svc.run(now=ORA + timedelta(minutes=15))
        self.assertEqual(esito["audit"]["eventi"], 1)
        self.assertEqual(SecurityEventRecord.objects.filter(event_type=svc.EVENT_AUDIT).count(), 1)
        alert = SecurityAlert.objects.get()
        self.assertIn("Ruolo di amministratore assegnato", alert.title)
        self.assertEqual(alert.severity, Severity.HIGH)

    def test_errore_graph_non_ferma_il_giro(self):
        from core.m365_graph import GraphError

        with patch("core.m365_graph.get_all", side_effect=GraphError("403", 403)):
            esito = svc.run(now=ORA)
        self.assertIn("errore", esito["audit"])
        self.assertTrue(svc.last_run()["attivo"])


class AccountCessatiTests(TestCase):
    def setUp(self):
        set_setting("entra.account_cessati.attivo", True)

    def test_alert_aperto_poi_chiuso_quando_l_account_viene_disattivato(self):
        with patch("core.account_m365.esegui", return_value=_riconciliazione(_riga(), _riga("u-2", "ok"))):
            esito = svc.run(now=ORA)
        self.assertEqual(esito["account"]["cessati_attivi"], 1)
        alert = SecurityAlert.objects.get()
        self.assertIn("ROSSI SINTETICO", alert.title)
        self.assertIn(alert.status, ACTIVE_ALERT_STATUSES)

        # Stesso stato dopo 6 ore: nessun nuovo alert.
        with patch("core.account_m365.esegui", return_value=_riconciliazione(_riga())):
            svc.run(now=ORA + timedelta(hours=7))
        self.assertEqual(SecurityAlert.objects.count(), 1)

        # Account disattivato: l'alert si chiude da solo.
        with patch("core.account_m365.esegui", return_value=_riconciliazione(_riga(esito="ok"))):
            esito = svc.run(now=ORA + timedelta(hours=14))
        self.assertEqual(esito["account"]["chiusi"], 1)
        alert.refresh_from_db()
        self.assertNotIn(alert.status, ACTIVE_ALERT_STATUSES)

    def test_controllo_al_massimo_ogni_6_ore(self):
        with patch("core.account_m365.esegui", return_value=_riconciliazione()) as esegui:
            svc.run(now=ORA)
            svc.run(now=ORA + timedelta(hours=1))
        self.assertEqual(esegui.call_count, 1)


class SpentoTests(TestCase):
    def test_interruttori_spenti_nessuna_chiamata(self):
        with patch("core.m365_graph.get_all") as get_all, patch("core.account_m365.esegui") as esegui:
            self.assertEqual(svc.run(now=ORA), {"attivo": False})
        get_all.assert_not_called()
        esegui.assert_not_called()



def _accesso(upn="mario.sintetico@example.com", codice=0, paese="IT", app="Browser", quando="2026-10-19T09:40:00Z",
             ip="203.0.113.10"):
    return {"userPrincipalName": upn, "status": {"errorCode": codice}, "location": {"countryOrRegion": paese, "city": "Città"},
            "clientAppUsed": app, "createdDateTime": quando, "ipAddress": ip, "appDisplayName": "Office 365 Exchange Online"}


class AccessiSospettiTests(TestCase):
    def test_anomalie(self):
        righe = [_accesso(codice=50126) for _ in range(10)] + [
            _accesso("anna.sintetica@example.com", paese="RU"),
            _accesso("anna.sintetica@example.com", paese="RU"),
            _accesso("luca.sintetico@example.com", app="IMAP4"),
            _accesso("ok.sintetico@example.com"),
            _accesso("pochi.falliti@example.com", codice=50126),
        ]
        anomalie = svc.anomalie_accessi(righe, soglia_falliti=10, paesi={"IT"})
        motivi = sorted((a["motivo"], a["upn"]) for a in anomalie)
        self.assertEqual(motivi, [("estero", "anna.sintetica@example.com"),
                                  ("falliti", "mario.sintetico@example.com"),
                                  ("protocollo", "luca.sintetico@example.com")])
        estero = next(a for a in anomalie if a["motivo"] == "estero")
        self.assertEqual(estero["severita"], Severity.HIGH)

    def test_paese_ammesso_non_segnalato(self):
        self.assertEqual(svc.anomalie_accessi([_accesso(paese="CH")], soglia_falliti=10, paesi={"IT", "CH"}), [])

    def test_giro_un_alert_al_giorno_per_account_e_motivo(self):
        set_setting("entra.accessi.attivo", True)
        righe = [_accesso("anna.sintetica@example.com", paese="RU")]
        with patch("core.m365_graph.get_all", return_value=righe):
            esito = svc.run(now=ORA)
            svc.run(now=ORA + timedelta(minutes=15))
        self.assertEqual(esito["accessi"]["eventi"], 1)
        alert = SecurityAlert.objects.get()
        self.assertIn("Paese non ammesso", alert.title)
        self.assertIn("anna.sintetica@example.com", alert.title)
        # Il giorno dopo, stessa anomalia: un nuovo evento.
        with patch("core.m365_graph.get_all", return_value=righe):
            esito = svc.run(now=ORA + timedelta(days=1))
        self.assertEqual(esito["accessi"]["eventi"], 1)

    def test_singoli_accessi_non_salvati(self):
        set_setting("entra.accessi.attivo", True)
        with patch("core.m365_graph.get_all", return_value=[_accesso() for _ in range(5)]):
            svc.run(now=ORA)
        self.assertEqual(SecurityEventRecord.objects.count(), 0)
