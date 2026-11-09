"""Correzioni di novembre 2026: permessi su «Interroga», stato flotta coerente, consumabili
senza finestra, cali mensili e «calo spiegato», filtri e link della Centrale. Dati sintetici."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    DispositivoSNMP,
    LetturaConsumabile,
    LetturaContatori,
    LetturaMensileContatori,
    Macchina,
    RilevazioneSNMP,
    StatoSNMP,
)
from .tests import _AuthedClientMixin


def _sola_lettura(test):
    for bersaglio in ("contatori.permessi.puo_gestire", "contatori.templatetags.contatori_acl._puo_gestire"):
        patch = mock.patch(bersaglio, return_value=False)
        patch.start()
        test.addCleanup(patch.stop)


def _mensile(macchina, mese, totale_a4):
    return LetturaMensileContatori.objects.create(macchina=macchina, mese=mese, a4_bn=totale_a4, a3_bn=0,
                                                  a4_col=0, a3_col=0)


class InterrogaPermessiTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.disp = DispositivoSNMP.objects.create(nome="SYN-SW", host="192.0.2.110")

    @mock.patch("contatori.tasks._enqueue", return_value=True)
    @mock.patch("contatori.services.interroga_dispositivo")
    def test_sola_lettura_non_interroga(self, interroga, accoda):
        _sola_lettura(self)
        r = self.client.post(reverse("contatori:snmp_dispositivo_interroga", args=[self.disp.pk]))
        self.assertRedirects(r, reverse("contatori:dashboard"), fetch_redirect_response=False)
        r = self.client.post(reverse("contatori:snmp_interroga_tutti"))
        self.assertRedirects(r, reverse("contatori:dashboard"), fetch_redirect_response=False)
        interroga.assert_not_called()
        accoda.assert_not_called()
        pagina = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertNotContains(pagina, "Interroga tutti ora")
        scheda = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.disp.pk]))
        self.assertNotContains(scheda, "Interroga ora")

    @mock.patch("contatori.tasks._enqueue", return_value=True)
    def test_interroga_tutti_salta_i_doppioni_mfc(self, accoda):
        Macchina.objects.create(reparto="Alfa", matricola="SYN-C1", host="192.0.2.111")
        DispositivoSNMP.objects.create(nome="Stessa MFC", host="192.0.2.111")
        r = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertEqual(r.context["da_interrogare"], 1)
        self.client.post(reverse("contatori:snmp_interroga_tutti"))
        accoda.assert_called_once_with("contatori.tasks.poll_dispositivo", self.disp.pk)


class StatoFlottaCoerenteTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        ora = timezone.now()
        self.errore = DispositivoSNMP.objects.create(nome="SYN-E", host="192.0.2.120", snmp_stato=StatoSNMP.ERROR,
                                                     snmp_ultimo_controllo=ora)
        # In attenzione ma non interrogato da giorni: per la flotta è «non interrogato».
        DispositivoSNMP.objects.create(nome="SYN-V", host="192.0.2.121", snmp_stato=StatoSNMP.WARNING,
                                       snmp_ultimo_controllo=ora - timedelta(days=10))
        DispositivoSNMP.objects.create(nome="SYN-OK", host="192.0.2.122", snmp_stato=StatoSNMP.OK,
                                       snmp_ultimo_controllo=ora)

    def test_voce_da_fare_usa_lo_stato_flotta(self):
        voce = next(v for v in services.cruscotto_operativo()["da_fare"] if "dispositivi SNMP" in v["titolo"])
        self.assertTrue(voce["titolo"].startswith("1 dispositivi"))
        self.assertIn("0 in attenzione", voce["dettaglio"])
        self.assertTrue(voce["url"].endswith("?flotta=errore"))
        flotta = services.stato_flotta()
        self.assertEqual((flotta["errore"], flotta["attenzione"], flotta["non_interrogati"]), (1, 0, 1))

    def test_monitor_filtro_flotta_e_vecchi_link(self):
        for url in ("?flotta=errore", "?stato=ERROR"):
            r = self.client.get(reverse("contatori:snmp_centrale") + url)
            self.assertEqual([d.pk for d in r.context["dispositivi"]], [self.errore.pk], url)
        r = self.client.get(reverse("contatori:snmp_centrale"))
        self.assertContains(r, '<option value="non_interrogati"')
        self.assertContains(r, 'href="?flotta=attenzione"')
        self.assertContains(r, "Apparati")
        self.assertNotContains(r, "Endpoint")


class ConsumabiliSenzaFinestraTests(_AuthedClientMixin, TestCase):
    def test_ultima_lettura_vecchia_resta_e_conta(self):
        vecchia = Macchina.objects.create(reparto="Alfa", matricola="SYN-K1", host="192.0.2.130")
        nuova = Macchina.objects.create(reparto="Beta", matricola="SYN-K2", host="192.0.2.131")
        Macchina.objects.create(reparto="Gamma", matricola="SYN-K3", host="192.0.2.132")  # mai letta
        ora = timezone.now()
        LetturaConsumabile.objects.create(macchina=vecchia, nome="Toner nero", pct=8,
                                          rilevata_il=ora - timedelta(days=90))
        LetturaConsumabile.objects.create(macchina=nuova, nome="Toner nero", pct=60, rilevata_il=ora)
        stati = services.stato_consumabili([vecchia, nuova])
        self.assertTrue(stati[vecchia.pk]["critici"])
        self.assertFalse(stati[vecchia.pk]["recente"])
        self.assertIsNone(stati[vecchia.pk]["voci"][0]["giorni"])  # una sola lettura: nessuna stima
        self.assertTrue(stati[nuova.pk]["recente"])
        r = self.client.get(reverse("contatori:consumabili"))
        self.assertEqual((r.context["critici"], r.context["non_recenti"]), (1, 2))
        self.assertContains(r, "Senza lettura recente")
        r = self.client.get(reverse("contatori:consumabili") + "?filtro=non_recenti")
        self.assertEqual({x["macchina"].pk for x in r.context["righe"]}, {vecchia.pk} | {
            m.pk for m in Macchina.objects.filter(matricola="SYN-K3")})
        self.assertEqual(services.cruscotto_operativo()["consumabili_critici"], 1)


class CaliTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Alfa", matricola="SYN-L1")
        _mensile(self.m, date(2026, 8, 1), 1000)
        self.calo = _mensile(self.m, date(2026, 9, 1), 10)

    def test_calo_mensile_in_da_fare_e_nella_centrale(self):
        cali = services.controllo_monotonia("mensile")
        self.assertEqual(len(cali), 1)
        self.assertEqual((cali[0]["lettura_id"], cali[0]["a_trim"]), (self.calo.pk, "09/2026"))
        titoli = [v["titolo"] for v in services.cruscotto_operativo()["da_fare"]]
        self.assertIn("1 lettura mensile con un calo", titoli)
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertContains(r, f"?tipo=mensili&amp;macchina={self.m.pk}&amp;cali=1")
        self.assertContains(r, reverse("contatori:lettura_calo_spiegato", args=["mensile", self.calo.pk]))

    def test_segna_calo_spiegato(self):
        url = reverse("contatori:lettura_calo_spiegato", args=["mensile", self.calo.pk])
        self.client.post(url, {"motivo": "  "})
        self.calo.refresh_from_db()
        self.assertIsNone(self.calo.calo_spiegato_il)
        self.client.post(url, {"motivo": "Contatore azzerato dal tecnico"})
        self.calo.refresh_from_db()
        self.assertIsNotNone(self.calo.calo_spiegato_il)
        self.assertEqual(self.calo.calo_spiegato_da, "contatori_test_admin")
        self.assertEqual(self.calo.calo_spiegato_motivo, "Contatore azzerato dal tecnico")
        self.assertEqual(services.controllo_monotonia("mensile"), [])
        # Il mese dopo si confronta con il valore azzerato: nessun nuovo calo.
        _mensile(self.m, date(2026, 10, 1), 50)
        self.assertEqual(services.controllo_monotonia("mensile"), [])
        # Contatori corretti a mano: la spiegazione non vale più.
        self.client.post(reverse("contatori:lettura_mensile_edit", args=[self.calo.pk]),
                         {"a4_bn": 20, "a3_bn": 0, "a4_col": 0, "a3_col": 0, "conferma_calo": "on"})
        self.calo.refresh_from_db()
        self.assertIsNone(self.calo.calo_spiegato_il)

    def test_calo_spiegato_trimestrale_e_permessi(self):
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q1", data=date(2026, 3, 31), a4_bn=500)
        calo = LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q2", data=date(2026, 6, 30), a4_bn=5)
        self.assertEqual(len(services.controllo_monotonia()), 1)
        _sola_lettura(self)
        self.client.post(reverse("contatori:lettura_calo_spiegato", args=["trimestrale", calo.pk]),
                         {"motivo": "Sostituita"})
        calo.refresh_from_db()
        self.assertIsNone(calo.calo_spiegato_il)


class LinkFiltratiTests(_AuthedClientMixin, TestCase):
    def test_mensile_mancante_e_voci_filtrate(self):
        letta = Macchina.objects.create(reparto="Alfa", matricola="SYN-M1", host="192.0.2.140")
        mancante = Macchina.objects.create(reparto="Beta", matricola="SYN-M2", host="192.0.2.141",
                                           snmp_stato=StatoSNMP.ERROR)
        Macchina.objects.create(reparto="Gamma", matricola="SYN-M3")  # senza IP: non si legge
        oggi = timezone.localdate()
        _mensile(letta, oggi.replace(day=1), 100)
        r = self.client.get(reverse("contatori:macchine") + "?lettura=mensile_mancante")
        self.assertEqual([m.pk for m in r.context["macchine"]], [mancante.pk])
        voci = {v["titolo"]: v["url"] for v in services.cruscotto_operativo(oggi.replace(day=9))["da_fare"]}
        self.assertTrue(voci["1 MFC non raggiungibili"].endswith("?stato=ERROR"))
        self.assertTrue(voci["1 letture mensili saltate"].endswith("?lettura=mensile_mancante"))

    def test_elenchi_della_centrale_con_totale(self):
        for i in range(10):
            DispositivoSNMP.objects.create(nome=f"SYN-D{i}", host=f"192.0.2.{150 + i}",
                                           snmp_stato=StatoSNMP.ERROR, snmp_ultimo_controllo=timezone.now())
        r = self.client.get(reverse("contatori:dashboard"))
        self.assertEqual((r.context["dispositivi_altri"], r.context["errori_altri"]), (2, 4))
        self.assertContains(r, "e altri 4 →")


class GuidaEStoricoTests(_AuthedClientMixin, TestCase):
    def test_guida_al_nuovo_indirizzo(self):
        self.assertEqual(reverse("contatori:guida"), "/contatori/guida/")
        r = self.client.get(reverse("contatori:guida"))
        self.assertContains(r, "Consumabili della flotta")
        vecchia = self.client.get("/contatori/riconciliazione/guida/")
        self.assertRedirects(vecchia, "/contatori/guida/", status_code=301)

    def test_storico_interrogazioni_paginato_e_filtrato(self):
        disp = DispositivoSNMP.objects.create(nome="SYN-P", host="192.0.2.170")
        for i in range(60):
            RilevazioneSNMP.objects.create(dispositivo=disp, stato=StatoSNMP.ERROR if i % 10 == 0 else StatoSNMP.OK)
        url = reverse("contatori:snmp_dispositivo", args=[disp.pk])
        r = self.client.get(url)
        self.assertEqual(len(r.context["rilevazioni"]), 50)
        self.assertContains(r, "60 righe in totale")
        r = self.client.get(url + "?page=2")
        self.assertEqual(len(r.context["rilevazioni"]), 10)
        r = self.client.get(url + "?stato=ERROR")
        self.assertEqual(len(r.context["rilevazioni"]), 6)
