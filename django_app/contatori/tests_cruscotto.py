"""Centrale: KPI operativi ed elenco «da fare». Dati sintetici."""
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import Fattura, LetturaContatori, Macchina, RigaFattura, StatoSNMP
from .tests import _AuthedClientMixin

OGGI = date(2026, 8, 10)  # 2026-Q3, precedente 2026-Q2


def _lettura(m, trim, base, giorno=date(2026, 7, 2)):
    return LetturaContatori.objects.create(macchina=m, trimestre=trim, data=giorno,
                                           a4_bn=base, a3_bn=0, a4_col=0, a3_col=0)


class CruscottoTests(TestCase):
    def setUp(self):
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-1", contratto="K1",
                                         host="192.0.2.41", snmp_stato=StatoSNMP.OK)
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-2", contratto="K2",
                                         host="192.0.2.42", snmp_stato=StatoSNMP.ERROR)

    def _titoli(self):
        return [t["titolo"] for t in services.cruscotto_operativo(oggi=OGGI)["da_fare"]]

    def test_segnala_letture_mancanti_fattura_e_irraggiungibili(self):
        _lettura(self.a, "2026-Q2", 100)
        _lettura(self.a, "2026-Q3", 200)
        titoli = self._titoli()
        self.assertIn("1 MFC senza lettura 2026-Q3", titoli)
        self.assertIn("Fattura 2026-Q2 non caricata", titoli)
        self.assertIn("1 MFC non raggiungibili", titoli)
        self.assertIn("2 letture mensili non registrate", titoli)
        # Le criticita' rosse vengono prima
        da_fare = services.cruscotto_operativo(oggi=OGGI)["da_fare"]
        self.assertEqual(da_fare[0]["livello"], "danger")

    def test_riconciliazione_con_eccesso_fatturato(self):
        _lettura(self.a, "2026-Q2", 90)
        _lettura(self.b, "2026-Q2", 50)
        f = Fattura.objects.create(numero="F", data=date(2026, 7, 5), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="K1", a4_bn=100)
        c = services.cruscotto_operativo(oggi=OGGI)
        self.assertEqual(c["riconciliazione"]["anomalie"], 1)
        self.assertIn("Riconciliazione 2026-Q2 da verificare", [t["titolo"] for t in c["da_fare"]])
        self.assertNotIn("Fattura 2026-Q2 non caricata", [t["titolo"] for t in c["da_fare"]])

    def test_variazione_copie(self):
        _lettura(self.a, "2026-Q1", 0)
        _lettura(self.a, "2026-Q2", 100)
        _lettura(self.a, "2026-Q3", 250)
        c = services.cruscotto_operativo(oggi=OGGI)
        self.assertEqual(c["consumo_ultimo"]["totale"], 150)
        self.assertEqual(c["variazione"], 50)

    def test_mensili_non_segnalate_il_primo_del_mese(self):
        c = services.cruscotto_operativo(oggi=date(2026, 8, 1))
        self.assertFalse(any("mensili" in t["titolo"] for t in c["da_fare"]))


class DashboardTests(_AuthedClientMixin, TestCase):
    def test_nessuna_interrogazione_snmp_all_apertura(self):
        Macchina.objects.create(reparto="Alfa", matricola="SYN-9", host="192.0.2.49")
        with mock.patch.object(services, "interroga_macchina") as interroga, \
                mock.patch.object(services, "interroga_dispositivo") as dispositivo:
            r = self.client.get(reverse("contatori:dashboard"))
        self.assertEqual(r.status_code, 200)
        interroga.assert_not_called()
        dispositivo.assert_not_called()
        self.assertContains(r, "Da fare")
        self.assertContains(r, "+ Inserisci")


class NavigazioneTests(_AuthedClientMixin, TestCase):
    def _attive(self, url):
        import re
        html = self.client.get(url).content.decode()
        nav = html[html.index('<nav class="cnav"'):html.index("</nav>", html.index('<nav class="cnav"'))]
        return re.findall(r'class="[^"]*\bactive\b[^"]*">([^<]+)<', nav)

    def test_una_sola_voce_attiva(self):
        self.assertEqual(self._attive(reverse("contatori:snmp_profili")), ["Profili SNMP"])
        self.assertEqual(self._attive(reverse("contatori:snmp_centrale")), ["Monitor SNMP"])
        self.assertEqual(self._attive(reverse("contatori:importa_lettura")), ["Stampanti MFC"])
        self.assertEqual(self._attive(reverse("contatori:fattura_nuova")), ["Riconciliazione"])


class ConsumabiliTests(_AuthedClientMixin, TestCase):
    def test_riepilogo_mai_letta_marcata_per_ordinamento(self):
        from . import services
        m = Macchina.objects.create(reparto="Alfa", matricola="SYN-8", host="192.0.2.48")
        # Il riepilogo e' un GET: legge solo lo storico, mai la stampante.
        with mock.patch.object(services, "leggi_consumabili_macchina", side_effect=AssertionError("no SNMP")):
            r = self.client.get(reverse("contatori:consumabili_riepilogo", args=[m.pk]))
        self.assertContains(r, 'data-stato="errore"')
        self.assertContains(r, "Mai letta")
