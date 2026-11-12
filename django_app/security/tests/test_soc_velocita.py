"""Velocità del SOC: impostazioni lette una volta, CVE KEV senza IN enormi, niente query per riga."""
from datetime import timedelta

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from security.models import SecurityAlert, SecurityCveRecord, SecurityRemediationTicket, SecuritySource, SourceType
from security.services import configuration, soc_settings, triage_tempi
from security.services.kev import kev_tra


class ImpostazioniInMemoriaTests(TestCase):
    def setUp(self):
        configuration.invalida_impostazioni()

    def tearDown(self):
        configuration.invalida_impostazioni()

    @override_settings(SECURITY_SETTINGS_CACHE_SECONDS=30)
    def test_una_query_per_tutte_le_letture_e_salvataggio_svuota(self):
        soc_settings.save({"watchguard.api.patch": True}, None)
        with CaptureQueriesContext(connection) as c:
            for _ in range(50):
                self.assertTrue(soc_settings.value("watchguard.api.patch"))
                soc_settings.value("watchguard.api.software")
        self.assertEqual(len(c), 1)
        soc_settings.save({"watchguard.api.patch": False}, None)  # post_save svuota la copia
        self.assertFalse(soc_settings.value("watchguard.api.patch"))

    @override_settings(SECURITY_SETTINGS_CACHE_SECONDS=30)
    def test_copia_non_condivisa_con_chi_modifica(self):
        configuration.set_setting("prova.elenco", [1, 2], value_type="json")
        configuration.get_setting("prova.elenco").append(3)
        self.assertEqual(configuration.get_setting("prova.elenco"), [1, 2])


class KevTests(TestCase):
    def test_kev_tra_senza_in_e_con_maiuscole(self):
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0001", kev=True)
        SecurityCveRecord.objects.create(cve_id="CVE-2099-0002", kev=False)
        molte = [f"CVE-2099-{i:05d}" for i in range(3000)] + ["cve-2099-0001", "CVE-2099-0002"]
        with CaptureQueriesContext(connection) as c:
            self.assertEqual(kev_tra(molte), {"cve-2099-0001"})
        self.assertEqual(len(c), 1)
        self.assertEqual(kev_tra([]), set())


class QueryPerRigaTests(TestCase):
    def setUp(self):
        self.source = SecuritySource.objects.create(name="Fonte velocità", vendor="Demo", source_type=SourceType.EMAIL)
        self.alerts = [SecurityAlert.objects.create(source=self.source, title=f"A{i}", severity="high", dedup_hash=f"v{i}")
                       for i in range(6)]

    @override_settings(SECURITY_SETTINGS_CACHE_SECONDS=30)
    def test_riepilogo_triage_non_legge_il_log_per_alert(self):
        configuration.invalida_impostazioni()
        self.addCleanup(configuration.invalida_impostazioni)
        oggi = timezone.localdate()
        with CaptureQueriesContext(connection) as c:
            out = triage_tempi.riepilogo(oggi - timedelta(days=1), oggi)
        self.assertEqual(out["non_presi"], 6)
        self.assertLess(len(c), 6)

    def test_ticket_della_pagina_alert_in_poche_query(self):
        from security.views import _alert_case, _alert_cases

        t1 = SecurityRemediationTicket.objects.create(source=self.source, alert=self.alerts[0], title="T1", dedup_hash="t1")
        t2 = SecurityRemediationTicket.objects.create(source=self.source, title="T2", dedup_hash="t2")
        t2.linked_alerts.add(self.alerts[0], self.alerts[1])
        with CaptureQueriesContext(connection) as c:
            mappa = _alert_cases(self.alerts)
        self.assertLessEqual(len(c), 3)
        for a in self.alerts:
            self.assertEqual(mappa.get(a.pk), _alert_case(a))
        self.assertIn(mappa[self.alerts[0].pk], (t1, t2))
