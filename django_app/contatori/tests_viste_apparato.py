"""Layout per tipologia di apparato (contatori/presentazione.py). Dati sintetici."""
from decimal import Decimal
from types import SimpleNamespace

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from . import presentazione
from .models import DispositivoSNMP, Macchina, RilevazioneSNMP, SondaSNMP, StatoSNMP, ValoreSNMP
from .tests import _AuthedClientMixin


def _sonda(pk, nome, numero=None, testo="", stato="OK", unita=""):
    valore = SimpleNamespace(valore_numero=Decimal(numero) if numero is not None else None, stato=stato,
                             valore_display=f"{numero} {unita}".strip() if numero is not None else testo)
    return SimpleNamespace(pk=pk, nome=nome, ultimo_valore=valore)


class VistaTests(TestCase):
    def test_ups_riconosce_carica_autonomia_e_stato(self):
        d = SimpleNamespace(categoria="UPS")
        sonde = [_sonda(1, "Carica residua", 87, unita="%"), _sonda(2, "Autonomia stimata", 42, unita="min"),
                 _sonda(3, "Stato batteria", testo="Normale"), _sonda(4, "Sonda strana", 5)]
        v = presentazione.vista(d, sonde)
        per_label = {i["label"]: i for i in v["indicatori"]}
        self.assertEqual(per_label["Carica batteria"]["pct"], 87)
        self.assertEqual(per_label["Autonomia"]["valore"], "42 min")
        self.assertEqual(per_label["Stato batteria"]["forma"], "testo")
        self.assertEqual((v["riconosciute"], v["sonde_totali"]), (3, 4))

    def test_una_sonda_vale_per_un_solo_indicatore_e_soglia_colora(self):
        d = SimpleNamespace(categoria="STORAGE")
        sonde = [_sonda(1, "Temperatura massima dischi", 61, stato="WARNING", unita="°C"), _sonda(2, "Temperatura sistema", 40, unita="°C")]
        per_label = {i["label"]: i for i in presentazione.vista(d, sonde)["indicatori"]}
        self.assertEqual(per_label["Temperatura dischi"]["sonda"], "Temperatura massima dischi")
        self.assertEqual(per_label["Temperatura dischi"]["tono"], "warn")
        self.assertEqual(per_label["Temperatura"]["sonda"], "Temperatura sistema")

    def test_stampante_ha_il_suo_pannello(self):
        self.assertIsNone(presentazione.vista(SimpleNamespace(categoria="STAMPANTE"), []))

    def test_firewall_porta_a_vpn_e_rete(self):
        v = presentazione.vista(SimpleNamespace(categoria="FIREWALL"), [])
        urls = [c["url"] for c in v["collegamenti"]]
        self.assertIn(reverse("security:vpn_history"), urls)
        self.assertIn(reverse("security:rete_indirizzi"), urls)


class SchedeTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.ups = DispositivoSNMP.objects.create(nome="UPS-CED", host="192.0.2.201", categoria="UPS", snmp_stato=StatoSNMP.OK)
        r = RilevazioneSNMP.objects.create(dispositivo=self.ups, stato=StatoSNMP.OK, tempo_risposta_ms=35, sys_uptime_seconds=90000)
        for nome, n, unita, oid in (("Carica residua", 91, "%", "1.3.6.1.2.1.33.1.2.4.0"), ("Autonomia stimata", 37, "min", "1.3.6.1.2.1.33.1.2.3.0")):
            s = SondaSNMP.objects.create(dispositivo=self.ups, nome=nome, oid=oid, unita=unita)
            ValoreSNMP.objects.create(rilevazione=r, sonda=s, valore_numero=Decimal(n), stato=StatoSNMP.OK)

    def test_scheda_ups_con_quadro_alimentazione(self):
        html = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.ups.pk])).content.decode()
        for testo in ("Alimentazione", "Carica batteria", "91%", "Autonomia", "37 min", "Risposta", "35 ms", "Acceso da", "1 g 1 h"):
            self.assertIn(testo, html)

    def test_il_quadro_non_aggiunge_query(self):
        url = reverse("contatori:snmp_dispositivo", args=[self.ups.pk])
        self.client.get(url)
        with CaptureQueriesContext(connection) as con:
            self.client.get(url)
        with CaptureQueriesContext(connection) as senza:
            from unittest import mock

            with mock.patch("contatori.presentazione.vista", return_value=None):
                self.client.get(url)
        self.assertEqual(len(con), len(senza))

    def test_scheda_mfc_con_barra_dei_collegamenti(self):
        m = Macchina.objects.create(reparto="Ufficio", matricola="V-1", host="192.0.2.210", snmp_ultimo_controllo=timezone.now())
        html = self.client.get(reverse("contatori:macchina", args=[m.pk])).content.decode()
        self.assertIn("cc-links-bar", html)
        self.assertIn(f"{reverse('contatori:letture_gestisci')}?macchina={m.pk}", html)


class FormatoTests(TestCase):
    def test_byte_leggibili(self):
        self.assertEqual(presentazione._byte(9123456789), "8,5 GB")
        self.assertEqual(presentazione._byte(512), "512 byte")
