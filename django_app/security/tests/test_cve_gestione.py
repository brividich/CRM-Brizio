"""Gestione delle CVE: elenco arricchito e registro delle correzioni. Dati sintetici."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from security.models import SecurityCveImpact, SecurityCveRecord, SecurityCveRisoluzione, SoftwareCpeMapping, SoftwareInstallation
from security.services import cve_gestione, cve_impact


class CveGestioneTests(TestCase):
    def setUp(self):
        SoftwareCpeMapping.objects.create(vendor="acme", product="viewer", cpe_vendor="acme", cpe_product="viewer", confirmed=True)
        self.record = SecurityCveRecord.objects.create(
            cve_id="CVE-2099-0201", description="Sintetica per la gestione.", cvss=9.1,
            configurations=[{"vendor": "acme", "product": "viewer", "end_excluding": "2.0"}],
        )
        self.vecchia = self._inst("pc-ges-01", "1.0")
        self._inst("pc-ges-02", "1.5")
        cve_impact.recompute(self.record)
        self.admin = get_user_model().objects.create(username="ges_admin", is_staff=True, is_superuser=True)

    def _inst(self, host, version):
        now = timezone.now()
        return SoftwareInstallation.objects.create(
            dedup_key=f"{host}|viewer|{version}", source_kind="watchguard", host=host, host_display=host.upper(),
            vendor="acme", vendor_raw="Acme", product="viewer", product_raw="Acme Viewer", version_raw=version,
            fonti=["watchguard"], still_detected=True, seen_at=now, last_seen_at=now, last_inventory_date=timezone.localdate(),
        )

    def _aggiorna_pc1(self):
        SoftwareInstallation.objects.filter(pk=self.vecchia.pk).update(still_detected=False)
        self._inst("pc-ges-01", "2.1")
        cve_impact.recompute(self.record)

    def test_elenco_con_programmi_classe_e_termine(self):
        riga = cve_gestione.elenco_cve()["righe"][0]
        self.assertEqual(riga["cve_id"], "CVE-2099-0201")
        self.assertEqual(riga["classe"], "critica")
        self.assertEqual(riga["impatta"], 2)
        self.assertIn("Acme Viewer 1.0", riga["programmi"])
        self.assertIsNotNone(riga["termine"])

    def test_filtri_dell_elenco(self):
        self.assertEqual(len(cve_gestione.elenco_cve(q="viewer")["righe"]), 1)
        self.assertEqual(len(cve_gestione.elenco_cve(q="pc-ges-02")["righe"]), 1)
        self.assertEqual(cve_gestione.elenco_cve(q="niente-del-genere")["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(classe="bassa")["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(solo_kev=True)["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve(termine="scaduta")["righe"], [])

    def test_correzione_da_aggiornamento_e_cve_ancora_aperta(self):
        self._aggiorna_pc1()
        d = cve_gestione.correzioni()
        self.assertEqual(d["kpi"]["corretti"], 1)
        self.assertEqual(d["kpi"]["aggiornati"], 1)
        x = d["righe"][0]
        self.assertEqual((x["r"].versione_prima, x["r"].versione_dopo), ("1.0", "2.1"))
        self.assertTrue(x["nel_termine"])
        g = d["gruppi"][0]
        self.assertEqual(g["stato"], "aperta")
        self.assertEqual(g["ancora"], 1)
        self.assertEqual(cve_gestione.elenco_cve()["righe"][0]["corretti_90"], 1)

    def test_cve_chiusa_su_tutti_i_pc(self):
        self._aggiorna_pc1()
        SoftwareInstallation.objects.filter(host="pc-ges-02").update(still_detected=False)
        self._inst("pc-ges-02", "3.0")
        cve_impact.recompute(self.record)
        self.assertFalse(SecurityCveImpact.objects.filter(cve=self.record, outcome=SecurityCveImpact.IMPACTS).exists())
        d = cve_gestione.correzioni()
        self.assertEqual(d["gruppi"][0]["stato"], "corretta")
        self.assertEqual(d["kpi"]["cve_corrette"], 1)

    def test_uscite_non_correttive_escluse_di_default(self):
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-ges-09", come=SecurityCveRisoluzione.PC_ASSENTE)
        self.assertEqual(cve_gestione.correzioni()["righe"], [])
        self.assertEqual(len(cve_gestione.correzioni(come="altro")["righe"]), 1)

    def test_pagine_e_csv(self):
        self._aggiorna_pc1()
        self.client.force_login(self.admin)
        page = self.client.get(reverse("security:vulnerabilities"), {"q": "viewer"})
        self.assertContains(page, "CVE-2099-0201")
        self.assertContains(page, "Acme Viewer 1.5")
        for vista in ("cve", "pc"):
            page = self.client.get(reverse("security:cve_correzioni"), {"vista": vista})
            self.assertContains(page, "CVE-2099-0201")
        page = self.client.get(reverse("security:cve_correzioni"), {"vista": "pc"})
        self.assertContains(page, "2.1")
        csv = self.client.get(reverse("security:cve_correzioni"), {"formato": "csv"})
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("PC-GES-01", csv.content.decode("utf-8"))

    def test_correzioni_negata_senza_permesso(self):
        utente = get_user_model().objects.create(username="ges_nessuno")
        self.client.force_login(utente)
        page = self.client.get(reverse("security:cve_correzioni"))
        self.assertNotEqual(page.status_code, 200)

    def test_pc_sparito_dall_inventario_non_rende_la_cve_corretta(self):
        self._aggiorna_pc1()
        SoftwareInstallation.objects.filter(host="pc-ges-02").delete()
        cve_impact.recompute(self.record)
        self.assertFalse(SecurityCveImpact.objects.filter(cve=self.record).exclude(
            outcome=SecurityCveImpact.NOT_IMPACTED).exists())
        d = cve_gestione.correzioni()
        self.assertEqual(d["gruppi"][0]["stato"], "nessuno_esposto")
        self.assertEqual(d["kpi"]["cve_corrette"], 0)
        self.assertEqual(d["kpi"]["cve_nessuno_esposto"], 1)

    def test_pc_di_nuovo_esposto_non_conta_come_corretto(self):
        self._aggiorna_pc1()
        # torna la versione vulnerabile sullo stesso PC
        SoftwareInstallation.objects.filter(host="pc-ges-01").update(still_detected=False)
        SoftwareInstallation.objects.filter(pk=self.vecchia.pk).update(still_detected=True)
        cve_impact.recompute(self.record)
        self.assertTrue(SecurityCveImpact.objects.filter(cve=self.record, host="pc-ges-01",
                                                         outcome=SecurityCveImpact.IMPACTS).exists())
        d = cve_gestione.correzioni()
        self.assertEqual(d["kpi"]["corretti"], 0)
        self.assertEqual(d["kpi"]["di_nuovo"], 1)
        self.assertEqual(d["righe"], [])
        self.assertEqual(cve_gestione.elenco_cve()["righe"][0]["corretti_90"], 0)
        altre = cve_gestione.correzioni(come="altro")["righe"]
        self.assertEqual(len(altre), 1)
        self.assertTrue(altre[0]["di_nuovo"])

    def test_filtro_come_sull_ultima_uscita(self):
        prima = timezone.now() - timezone.timedelta(days=5)
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-ges-08", come=SecurityCveRisoluzione.AGGIORNATO,
                                              versione_prima="1.0", versione_dopo="2.2", risolta_il=prima)
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-ges-08", come=SecurityCveRisoluzione.PC_ASSENTE)
        self.assertEqual(cve_gestione.correzioni()["righe"], [])
        self.assertEqual(cve_gestione.correzioni(come="aggiornato")["righe"], [])
        self.assertEqual(len(cve_gestione.correzioni(come="altro")["righe"]), 1)

    def test_csv_neutralizza_le_formule(self):
        SecurityCveRisoluzione.objects.create(cve=self.record, host="pc-ges-07", software="=HYPERLINK(\"x\")",
                                              versione_prima="1.0", versione_dopo="2.5", come=SecurityCveRisoluzione.AGGIORNATO)
        self.client.force_login(self.admin)
        testo = self.client.get(reverse("security:cve_correzioni"), {"formato": "csv"}).content.decode("utf-8")
        self.assertIn("'=HYPERLINK", testo)
        self.assertNotIn(";=HYPERLINK", testo)

    def test_totali_su_tutte_le_righe_anche_oltre_il_limite(self):
        for i in range(3):
            SecurityCveRisoluzione.objects.create(cve=self.record, host=f"pc-lim-{i}", versione_prima="1.0",
                                                  versione_dopo="2.0", come=SecurityCveRisoluzione.AGGIORNATO)
        with mock.patch.object(cve_gestione, "MAX_RIGHE_CORREZIONI", 1):
            d = cve_gestione.correzioni()
        self.assertTrue(d["troncato"])
        self.assertEqual(len(d["righe_mostrate"]), 1)
        self.assertEqual(d["kpi"]["corretti"], 3)

    def test_stesso_numero_in_tutte_le_pagine(self):
        """Pagina Correzioni, elenco CVE, riquadro «Dalla segnalazione alla correzione» e tempi di correzione."""
        from security.services import cve_chiusura, cve_sla

        self._aggiorna_pc1()
        # pc-ges-02: corretto e poi di nuovo esposto
        SoftwareInstallation.objects.filter(host="pc-ges-02").update(still_detected=False)
        nuova = self._inst("pc-ges-02", "3.0")
        cve_impact.recompute(self.record)
        SoftwareInstallation.objects.filter(pk=nuova.pk).update(still_detected=False)
        SoftwareInstallation.objects.filter(host="pc-ges-02", version_raw="1.5").update(still_detected=True)
        cve_impact.recompute(self.record)

        oggi = timezone.localdate()
        pagina = cve_gestione.correzioni()["kpi"]["corretti"]
        elenco = cve_gestione.elenco_cve()["righe"][0]["corretti_90"]
        riquadro = cve_chiusura.metriche()["correzioni"]
        termini = cve_sla.riepilogo(oggi - timezone.timedelta(days=90), oggi)["corrette"]
        self.assertEqual((pagina, elenco, riquadro, termini), (1, 1, 1, 1))

    def test_query_costanti_al_crescere_dei_pc(self):
        """Le pagine non devono fare una query per PC (in produzione erano 1.400-1.800 per pagina)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self._aggiorna_pc1()
        self.client.force_login(self.admin)

        def conta():
            out = {}
            for nome, url, params in (("lista", "security:vulnerabilities", {}),
                                      ("cve", "security:cve_correzioni", {}),
                                      ("pc", "security:cve_correzioni", {"vista": "pc"})):
                with CaptureQueriesContext(connection) as c:
                    self.assertEqual(self.client.get(reverse(url), params).status_code, 200)
                out[nome] = len(c)
            return out

        conta()  # giro a vuoto: la prima richiesta riempie le cache del portale (menu, permessi)
        prima = conta()
        for i in range(3, 9):
            self._inst(f"pc-ges-{i:02d}", "1.0")
        cve_impact.recompute(self.record)
        for i in range(3, 9):
            SoftwareInstallation.objects.filter(host=f"pc-ges-{i:02d}").update(still_detected=False)
            self._inst(f"pc-ges-{i:02d}", "2.3")
        cve_impact.recompute(self.record)
        self.assertEqual(conta(), prima)
