"""Librerie Python del portale contro OSV (services/dipendenze_portale.py). Dati sintetici, rete simulata."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from security.models import SecurityAlert, SecurityLetturaLog, SecurityVulnerabilityFinding
from security.services import dipendenze_portale as dp
from security.services import iso27001, letture, soc_settings
from security.services.rule_engine import evaluate_security_rules

# acme-lib 1.0: lo stesso problema con due codici (PYSEC + GHSA che si citano), più un secondo problema senza gravità
BOLLETTINI = {
    "PYSEC-2099-1": {"id": "PYSEC-2099-1", "aliases": ["GHSA-aaaa-bbbb-cccc", "CVE-2099-0901"], "summary": "Lettura fuori limite",
                     "affected": [{"package": {"ecosystem": "PyPI", "name": "Acme_Lib"},
                                   "ranges": [{"events": [{"introduced": "0"}, {"fixed": "1.2.0"}]}]}]},
    "GHSA-aaaa-bbbb-cccc": {"id": "GHSA-aaaa-bbbb-cccc", "aliases": ["CVE-2099-0901"], "database_specific": {"severity": "HIGH"},
                            "affected": [{"package": {"ecosystem": "PyPI", "name": "acme-lib"},
                                          "ranges": [{"events": [{"fixed": "1.2.0"}]}]}]},
    "PYSEC-2099-2": {"id": "PYSEC-2099-2", "aliases": [], "details": "Negazione del servizio",
                     "affected": [{"package": {"ecosystem": "PyPI", "name": "acme-lib"},
                                   "ranges": [{"events": [{"fixed": "1.1.5"}]}]}]},
}


class _Osv:
    """Risponde come api.osv.dev: ``vulnerabili`` = {nome: {versione: [id]}}."""

    def __init__(self, vulnerabili, fallisce=False):
        self.vulnerabili, self.fallisce = vulnerabili, fallisce

    def __call__(self, metodo, url, **kw):
        if self.fallisce:
            raise dp.OsvError("OSV non raggiungibile (ConnectionError)")
        if url == dp.OSV_BATCH_URL:
            res = []
            for q in kw["json"]["queries"]:
                ids = self.vulnerabili.get(q["package"]["name"], {}).get(q["version"], [])
                res.append({"vulns": [{"id": i} for i in ids]} if ids else {})
            return {"results": res}
        return BOLLETTINI[url.rsplit("/", 1)[1]]


VULNERABILE = {"acme-lib": {"1.0": ["PYSEC-2099-1", "GHSA-aaaa-bbbb-cccc", "PYSEC-2099-2"]}}


class DipendenzePortaleTests(TestCase):
    def _giro(self, pacchetti, osv):
        with mock.patch.object(dp, "_http", osv):
            return dp.run(pacchetti)

    def test_raggruppa_gravita_e_versione_minima(self):
        r = self._giro({"acme-lib": "1.0", "sano": "2.0"}, _Osv(VULNERABILE))
        self.assertEqual((r["pacchetti"], r["vulnerabili"], r["vulnerabilita"], r["nuove"]), (2, 1, 2, 2))
        voci = {f.cve: f for f in SecurityVulnerabilityFinding.objects.filter(source=dp.source())}
        self.assertEqual(set(voci), {"CVE-2099-0901", "PYSEC-2099-2"})
        self.assertEqual(voci["CVE-2099-0901"].severity, "high")
        self.assertTrue(voci["CVE-2099-0901"].payload["classificata"])
        self.assertEqual(voci["PYSEC-2099-2"].severity, "medium")
        self.assertFalse(voci["PYSEC-2099-2"].payload["classificata"])
        g = dp.per_pacchetto()[0]
        self.assertEqual((g["pacchetto"], g["versione"], g["gravita"], g["aggiorna_a"]), ("acme-lib", "1.0", "high", "1.2.0"))

    def test_aggiornamento_risolve_e_chiude_alert(self):
        self._giro({"acme-lib": "1.0"}, _Osv(VULNERABILE))
        self.assertEqual(self._giro({"acme-lib": "1.0"}, _Osv(VULNERABILE))["nuove"], 0)
        evaluate_security_rules()
        alert = SecurityAlert.objects.get(event__event_type=dp.EVENT)
        self.assertIn("acme-lib 1.0", alert.title)
        self.assertIn("aggiornare a 1.2.0", alert.title)
        self.assertEqual(alert.severity, "high")
        r = self._giro({"acme-lib": "1.2.0"}, _Osv(VULNERABILE))
        self.assertEqual((r["risolte"], r["alert_chiusi"], r["vulnerabilita"]), (2, 1, 0))
        alert.refresh_from_db()
        self.assertNotIn(alert.status, ("new", "open", "in_progress"))
        risolte = dp.risolte_recenti()
        self.assertEqual(len(risolte), 2)
        self.assertEqual(risolte[0].payload["versione_dopo"], "1.2.0")

    def test_aggiornata_prima_della_valutazione_niente_alert(self):
        self._giro({"acme-lib": "1.0"}, _Osv(VULNERABILE))
        self._giro({"acme-lib": "1.2.0"}, _Osv(VULNERABILE))
        evaluate_security_rules()
        self.assertFalse(SecurityAlert.objects.filter(event__event_type=dp.EVENT).exists())

    def test_alert_spento(self):
        soc_settings.save({"dipendenze.alert.attivo": False}, None)
        r = self._giro({"acme-lib": "1.0"}, _Osv(VULNERABILE))
        self.assertEqual((r["vulnerabilita"], r["eventi"]), (2, 0))

    def test_osv_irraggiungibile_e_errore_non_pulito(self):
        self._giro({"acme-lib": "1.0"}, _Osv(VULNERABILE))
        with mock.patch.object(dp, "_http", _Osv({}, fallisce=True)):
            r = letture.esegui("dipendenze_portale")
        self.assertIn("OSV non raggiungibile", r["errore"])
        self.assertEqual(SecurityLetturaLog.objects.get(codice="dipendenze_portale").stato, SecurityLetturaLog.ERRORE)
        self.assertEqual(dp.aperte().count(), 2)  # le vulnerabilità di prima restano aperte

    def test_controllo_spento(self):
        soc_settings.save({"dipendenze.controllo.attivo": False}, None)
        self.assertIn("skipped", dp.run({"acme-lib": "1.0"}))

    def test_pacchetti_installati_normalizzati(self):
        installati = dp.pacchetti_installati()
        self.assertIn("django", installati)
        self.assertTrue(all(n == dp.nome_normale(n) for n in installati))

    def test_pagina_iso_e_accesso(self):
        with mock.patch.object(dp, "_http", _Osv(VULNERABILE)), mock.patch.object(dp, "pacchetti_installati", return_value={"acme-lib": "1.0"}):
            letture.esegui("dipendenze_portale")
        url = reverse("security:dipendenze_portale")
        self.client.force_login(get_user_model().objects.create(username="dip_no"))
        self.assertNotEqual(self.client.get(url).status_code, 200)
        self.client.force_login(get_user_model().objects.create(username="dip_admin", is_staff=True, is_superuser=True))
        page = self.client.get(url)
        self.assertContains(page, "acme-lib")
        self.assertContains(page, "1.2.0")
        self.assertContains(page, "CVE-2099-0901")
        e = {"stato": iso27001.OK, "frase": "Ok.", "numeri": {}, "evidenze": [], "azioni": []}
        iso27001._v_8_8_librerie(e)
        self.assertEqual(e["stato"], iso27001.ATTENZIONE)
        self.assertEqual(e["numeri"]["librerie_portale_gravi"], 1)
        self.assertIn("acme-lib 1.0 → 1.2.0", e["azioni"][0])
