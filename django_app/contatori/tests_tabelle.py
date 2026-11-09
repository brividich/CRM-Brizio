"""Tabelle del modulo in stile SOC: pannello di anteprima, selezione multipla, CSV ordine. Dati sintetici."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog

from .models import AvvisoStampante, DispositivoSNMP, LetturaConsumabile, LetturaContatori, Macchina
from .tests import _AuthedClientMixin

V = {"a4_bn": 1000, "a3_bn": 100, "a4_col": 500, "a3_col": 50}


def _sola_lettura(test):
    for target in ("contatori.permessi.puo_gestire", "contatori.templatetags.contatori_acl._puo_gestire"):
        p = mock.patch(target, return_value=False)
        p.start()
        test.addCleanup(p.stop)


class AnteprimaTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Reparto Sintetico", matricola="SYN-T1", host="192.0.2.81",
                                         modello="Demo MX")
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q2", data=date(2026, 7, 2), **V)
        ora = timezone.now()  # stessa lettura: stesso istante
        LetturaConsumabile.objects.create(macchina=self.m, nome="Toner nero", pct=9, rilevata_il=ora)
        LetturaConsumabile.objects.create(macchina=self.m, nome="Tamburo", pct=60, rilevata_il=ora)
        AvvisoStampante.objects.create(macchina=self.m, chiave="k1", testo="Carta inceppata vassoio 2", critico=True)
        AvvisoStampante.objects.create(macchina=self.m, chiave="k2", testo="Pronta", informativo=True)
        self.d = DispositivoSNMP.objects.create(nome="Switch demo", host="192.0.2.82")

    def test_anteprima_mfc(self):
        r = self.client.get(reverse("contatori:anteprima", args=["mfc", self.m.pk]),
                            HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        for testo in ("pv-head", "pv-facts", "pv-foot", "Reparto Sintetico", "Toner nero", "9%", "2026-Q2",
                      "Carta inceppata vassoio 2", "Apri la scheda MFC", "non collegato"):
            self.assertContains(r, testo)
        self.assertNotContains(r, "Pronta")  # gli eventi informativi non sono avvisi aperti
        self.assertContains(r, reverse("contatori:macchina", args=[self.m.pk]))
        self.assertNotContains(r, "<html")  # frammento, non pagina

    def test_anteprima_dispositivo_e_tipo_sconosciuto(self):
        r = self.client.get(reverse("contatori:anteprima", args=["snmp", self.d.pk]))
        self.assertContains(r, "Switch demo")
        self.assertContains(r, "Apri la scheda del dispositivo")
        self.assertContains(r, "nessuna interrogazione")
        self.assertEqual(self.client.get(reverse("contatori:anteprima", args=["xyz", 1])).status_code, 404)
        self.assertEqual(self.client.get(reverse("contatori:anteprima", args=["mfc", 999999])).status_code, 404)

    def test_righe_marcate_per_il_pannello(self):
        url_m = reverse("contatori:anteprima", args=["mfc", self.m.pk])
        url_d = reverse("contatori:anteprima", args=["snmp", self.d.pk])
        for pagina in ("contatori:macchine", "contatori:consumabili", "contatori:dashboard"):
            self.assertContains(self.client.get(reverse(pagina)), f'data-preview="{url_m}"', msg_prefix=pagina)
        r = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertContains(r, f'data-preview="{url_m}"')
        self.assertContains(r, f'data-preview="{url_d}"')

    def test_modulo_raggruppabile_e_ospite_del_pannello(self):
        r = self.client.get(reverse("contatori:macchine"))
        self.assertContains(r, 'class="contatori-module" data-fm-groupable="1" data-drawer-host')
        self.assertContains(r, "core/js/hub-bulk-pannello.js")

    def test_anteprima_in_sola_lettura(self):
        _sola_lettura(self)
        r = self.client.get(reverse("contatori:anteprima", args=["mfc", self.m.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "proposto")


class ConsumabiliAzioniTests(_AuthedClientMixin, TestCase):
    URL = reverse("contatori:consumabili_azioni")

    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-C1", host="192.0.2.91", modello="Demo A")
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-C2", host="192.0.2.92", modello="=cmd()")
        self.c = Macchina.objects.create(reparto="Gamma", matricola="SYN-C3", host="192.0.2.93")
        prima = timezone.now() - timedelta(days=10)
        LetturaConsumabile.objects.create(macchina=self.a, nome="Toner nero", pct=40, rilevata_il=prima)
        ora = timezone.now()  # stessa lettura: stesso istante
        LetturaConsumabile.objects.create(macchina=self.a, nome="Toner nero", pct=8, rilevata_il=ora)
        LetturaConsumabile.objects.create(macchina=self.a, nome="Tamburo", pct=70, rilevata_il=ora)
        LetturaConsumabile.objects.create(macchina=self.b, nome="Toner ciano", pct=55)

    def test_pagina_con_selezione_non_spuntata(self):
        r = self.client.get(reverse("contatori:consumabili"))
        self.assertContains(r, 'id="cons-bulk" data-bulk')
        self.assertContains(r, "Leggi ora le selezionate")
        self.assertContains(r, "Prepara richiesta ordine")
        self.assertContains(r, 'class="sec-bulk-item" name="macchina"', count=3)
        self.assertNotContains(r, 'form="cons-bulk" checked')

    def test_csv_ordine(self):
        r = self.client.post(self.URL, {"azione": "ordine", "macchina": [self.a.pk, self.b.pk, self.c.pk]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r["Content-Disposition"])
        testo = r.content.decode("utf-8-sig")
        righe = [x for x in testo.splitlines() if x]
        self.assertEqual(righe[0].split(";")[:6], ["Modello", "Matricola", "MFC", "Consumabile", "Livello %",
                                                    "Giorni stimati"])
        self.assertIn("Demo A;SYN-C1;Alfa;Toner nero;8;", testo)   # solo il critico, non il tamburo al 70%
        self.assertNotIn("Tamburo", testo)
        self.assertIn("SYN-C2;Beta;Toner ciano;55;", testo)          # nessun critico: il più basso
        self.assertIn("SYN-C3;Gamma;nessuna lettura salvata", testo)
        self.assertNotIn(";=cmd()", testo)                          # protezione formule
        self.assertIn("'=cmd()", testo)

    def test_leggi_ora_le_selezionate(self):
        with mock.patch("contatori.lettura_ora.accoda") as accoda:
            r = self.client.post(self.URL, {"azione": "leggi", "macchina": [self.a.pk, self.b.pk]})
        self.assertRedirects(r, reverse("contatori:consumabili"), fetch_redirect_response=False)
        self.assertEqual(sorted(c.args[0].pk for c in accoda.call_args_list), sorted([self.a.pk, self.b.pk]))
        self.assertTrue(AuditLog.objects.filter(azione="contatori_consumabili_leggi_ora").exists())

    def test_leggi_ora_serve_la_gestione_ma_il_csv_no(self):
        _sola_lettura(self)
        with mock.patch("contatori.lettura_ora.accoda") as accoda:
            r = self.client.post(self.URL, {"azione": "leggi", "macchina": [self.a.pk]},
                                 HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r["Content-Type"], "application/json")
        accoda.assert_not_called()
        r = self.client.post(self.URL, {"azione": "ordine", "macchina": [self.a.pk]})
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse("contatori:consumabili"))
        self.assertNotContains(r, "Leggi ora le selezionate")
        self.assertContains(r, "Prepara richiesta ordine")

    def test_solo_post(self):
        self.assertEqual(self.client.get(self.URL).status_code, 405)


class CollegaAssetMultiploTests(_AuthedClientMixin, TestCase):
    URL = reverse("contatori:macchine_collega_asset")

    def setUp(self):
        super().setUp()
        from assets.models import Asset

        self.asset = Asset.objects.create(asset_tag="DEMO-MFC-71", name="MFC demo 71", serial_number="SYNMFC071")
        self.con = Macchina.objects.create(reparto="Con proposta", matricola="SYNMFC071")
        self.senza = Macchina.objects.create(reparto="Senza proposta", matricola="SYNMFC072")

    def test_anteprima_poi_conferma(self):
        r = self.client.get(reverse("contatori:macchine"))
        self.assertContains(r, "Collega gli asset proposti")
        self.assertContains(r, f'name="macchina" value="{self.con.pk}" form="mac-bulk"')
        r = self.client.post(self.URL, {"macchina": [self.con.pk, self.senza.pk]})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "DEMO-MFC-71")
        self.assertContains(r, "nessuna proposta")
        self.assertContains(r, f'value="{self.con.pk}:{self.asset.pk}"')
        self.con.refresh_from_db()
        self.assertIsNone(self.con.asset_id)  # l'anteprima non collega niente
        r = self.client.post(self.URL, {"conferma": "1", "abbina": [f"{self.con.pk}:{self.asset.pk}"]})
        self.assertRedirects(r, reverse("contatori:macchine"), fetch_redirect_response=False)
        self.con.refresh_from_db()
        self.assertEqual(self.con.asset_id, self.asset.pk)
        log = AuditLog.objects.get(azione="apparato_collegato_asset")
        self.assertEqual(log.dettaglio["apparato_id"], self.con.pk)

    def test_proposta_cambiata_non_collega(self):
        self.client.post(self.URL, {"conferma": "1", "abbina": [f"{self.con.pk}:999999"]})
        self.con.refresh_from_db()
        self.assertIsNone(self.con.asset_id)

    def test_serve_la_gestione(self):
        _sola_lettura(self)
        r = self.client.post(self.URL, {"conferma": "1", "abbina": [f"{self.con.pk}:{self.asset.pk}"]})
        self.assertRedirects(r, reverse("contatori:dashboard"), fetch_redirect_response=False)
        self.con.refresh_from_db()
        self.assertIsNone(self.con.asset_id)
        self.assertNotContains(self.client.get(reverse("contatori:macchine")), "Collega gli asset proposti")


class DiscoveryCorreggiIpTests(_AuthedClientMixin, TestCase):
    URL = reverse("contatori:discovery_correggi_ip")

    def test_correzione_multipla(self):
        a = Macchina.objects.create(reparto="Alfa", matricola="SYN-D1", host="192.0.2.101")
        b = Macchina.objects.create(reparto="Beta", matricola="SYN-D2", host="192.0.2.102")
        r = self.client.post(self.URL, {"correggi": [f"{a.pk}|192.0.2.111", f"{b.pk}|non-un-ip"]})
        self.assertRedirects(r, reverse("contatori:discovery"), fetch_redirect_response=False)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(str(a.host), "192.0.2.111")
        self.assertEqual(str(b.host), "192.0.2.102")
        self.assertTrue(AuditLog.objects.filter(azione="discovery_ip_corretti").exists())

    def test_serve_la_gestione(self):
        _sola_lettura(self)
        a = Macchina.objects.create(reparto="Alfa", matricola="SYN-D3", host="192.0.2.103")
        self.client.post(self.URL, {"correggi": [f"{a.pk}|192.0.2.113"]})
        a.refresh_from_db()
        self.assertEqual(str(a.host), "192.0.2.103")


class LettureSelezioneTests(_AuthedClientMixin, TestCase):
    def test_gestisci_letture_a_pagine_con_barra_standard(self):
        m = Macchina.objects.create(reparto="Alfa", matricola="SYN-L1")
        LetturaContatori.objects.bulk_create([
            LetturaContatori(macchina=m, trimestre=f"{2000 + i // 4}-Q{i % 4 + 1}", data=date(2000 + i // 4, 1, 1), **V)
            for i in range(105)])
        r = self.client.get(reverse("contatori:letture_gestisci"))
        self.assertEqual(len(r.context["righe"].object_list), 100)
        self.assertContains(r, "105 letture")
        self.assertContains(r, 'data-fm-last-page="2"')
        self.assertContains(r, "sec-bulk-bar")
        self.assertContains(r, "data-bulk-go disabled")
        self.assertNotContains(r, "data-fm-table-skip")
        self.assertNotContains(r, "lg-tutte")
        r = self.client.get(reverse("contatori:letture_gestisci") + "?page=2")
        self.assertEqual(len(r.context["righe"].object_list), 5)
