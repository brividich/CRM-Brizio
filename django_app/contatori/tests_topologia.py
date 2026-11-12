"""Topologia, porte degli apparati e disegni delle schede (contatori/topologia.py). Dati sintetici."""
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import topologia
from .models import DispositivoSNMP, Macchina, PortaApparato, StatoSNMP
from .tests import _AuthedClientMixin


class _Rete(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.fw = DispositivoSNMP.objects.create(nome="FW-01", host="192.0.2.1", categoria="FIREWALL", snmp_stato=StatoSNMP.OK, porte_totali=6)
        self.sw = DispositivoSNMP.objects.create(nome="SW-01", host="192.0.2.2", categoria="RETE", snmp_stato=StatoSNMP.OK)
        self.cam = DispositivoSNMP.objects.create(nome="CAM-01", host="192.0.2.3", categoria="TVCC_CAMERA", snmp_stato=StatoSNMP.ERROR)
        self.sciolto = DispositivoSNMP.objects.create(nome="UPS-01", host="192.0.2.4", categoria="UPS")
        self.mfc = Macchina.objects.create(reparto="Ufficio", matricola="T-1", host="192.0.2.10", snmp_stato=StatoSNMP.OK)
        PortaApparato.objects.create(dispositivo=self.fw, numero=1, tipo="WAN", nome="WAN1", collegato_testo="Internet")
        PortaApparato.objects.create(dispositivo=self.fw, numero=2, nome="Uplink", collegato_dispositivo=self.sw)
        PortaApparato.objects.create(dispositivo=self.sw, numero=5, collegato_macchina=self.mfc, vlan="10")
        PortaApparato.objects.create(dispositivo=self.sw, numero=6, collegato_dispositivo=self.cam)
        PortaApparato.objects.create(dispositivo=self.sw, numero=24, collegato_dispositivo=self.fw)  # ciclo: ignorato


class AlberoTests(_Rete):
    def test_internet_sopra_il_firewall_e_rami_dalle_porte(self):
        t = topologia.albero()
        self.assertEqual(len(t["radici"]), 1)
        internet = t["radici"][0]
        self.assertEqual(internet["nome"], "Internet")
        fw = internet["figli"][0]["nodo"]
        self.assertEqual((fw["nome"], internet["figli"][0]["porta"]), ("FW-01", "porta 1 · WAN1"))
        sw = fw["figli"][0]["nodo"]
        self.assertEqual(sw["nome"], "SW-01")
        self.assertEqual([c["nodo"]["nome"] for c in sw["figli"]], ["Ufficio", "CAM-01"])
        self.assertEqual(sw["figli"][0]["porta"], "porta 5 · VLAN 10")
        self.assertEqual(sw["figli"][1]["nodo"]["tono"], "danger")
        self.assertEqual([n["nome"] for n in t["scollegati"]], ["UPS-01"])

    def test_due_wan_verso_internet_il_firewall_compare_una_volta(self):
        PortaApparato.objects.create(dispositivo=self.fw, numero=3, tipo="WAN", nome="WAN2", collegato_testo="internet")
        internet = topologia.albero()["radici"][0]
        self.assertEqual(len(internet["figli"]), 1)
        self.assertEqual(internet["figli"][0]["porta"], "porta 1 · WAN1 + porta 3 · WAN2")

    def test_query_costanti_al_crescere_della_rete(self):
        def conta():
            with CaptureQueriesContext(connection) as q:
                topologia.albero()
            return len(q)

        prima = conta()
        for i in range(6):
            d = DispositivoSNMP.objects.create(nome=f"CAM-{i + 10}", host=f"192.0.2.{50 + i}", categoria="TVCC_CAMERA")
            PortaApparato.objects.create(dispositivo=self.sw, numero=10 + i, collegato_dispositivo=d)
        self.assertEqual(conta(), prima)

    def test_pannello_e_numero_porta(self):
        porte = topologia.porte_pannello(self.fw)
        self.assertEqual(len(porte), 6)
        self.assertEqual([p["tono"] for p in porte[:3]], ["wan", "on", "off"])
        self.assertEqual(len(topologia.porte_pannello(self.sw)), 24)  # predefinite per uno switch
        self.assertEqual((topologia.numero_porta("Gi1/0/12"), topologia.numero_porta("port 3"), topologia.numero_porta("x")), (12, 3, None))


class PagineTests(_Rete):
    def test_pagina_topologia(self):
        html = self.client.get(reverse("contatori:topologia")).content.decode()
        for testo in ("Internet", 'id="nodo-d%d"' % self.fw.pk, "SW-01", "porta 5 · VLAN 10", "Non ancora collegati", "UPS-01"):
            self.assertIn(testo, html)
        self.assertIn(f'href="{reverse("contatori:topologia")}"', html)  # voce nella barra del modulo

    def test_scheda_firewall_con_pannello_delle_porte(self):
        html = self.client.get(reverse("contatori:snmp_dispositivo", args=[self.fw.pk])).content.decode()
        self.assertIn('class="cc-face cc-face-firewall', html)
        self.assertIn('class="cc-port is-wan"', html)
        self.assertIn(reverse("contatori:dispositivo_porte", args=[self.fw.pk]), html)
        self.assertIn(reverse("contatori:snmp_dispositivo", args=[self.sw.pk]), html)  # la porta 2 porta allo switch

    def test_editor_porte_salva_e_toglie(self):
        url = reverse("contatori:dispositivo_porte", args=[self.fw.pk])
        self.assertContains(self.client.get(url), 'name="coll_2"')
        r = self.client.post(url, {"porte_totali": "4", "nome_1": "WAN1", "tipo_1": "WAN", "testo_1": "Fibra",
                                   "coll_3": f"m:{self.mfc.pk}", "tipo_3": "LAN", "coll_4": "d:99999"})
        self.assertEqual(r.status_code, 302)
        porte = {p.numero: p for p in PortaApparato.objects.filter(dispositivo=self.fw)}
        self.assertEqual(sorted(porte), [1, 3])  # la 2 svuotata, la 4 con un apparato inesistente scartata
        self.assertEqual(porte[1].collegato_testo, "Fibra")
        self.assertEqual(porte[3].collegato_macchina_id, self.mfc.pk)
        self.fw.refresh_from_db()
        self.assertEqual(self.fw.porte_totali, 4)

    def test_editor_porte_solo_con_la_gestione(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            r = self.client.post(reverse("contatori:dispositivo_porte", args=[self.fw.pk]), {"porte_totali": "2"})
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(PortaApparato.objects.filter(dispositivo=self.fw).count(), 2)

    def test_scheda_mfc_con_la_stampante_disegnata(self):
        self.mfc.dati_stampante = {"consumabili": [{"nome": "Toner nero", "colore": "nero", "pct": 8}, {"nome": "Toner ciano", "colore": "ciano", "pct": 70}],
                                   "cassetti": [{"nome": "Cassetto 1", "pct": 50}], "stato": {"display": ["Pronta"]}}
        self.mfc.save(update_fields=["dati_stampante"])
        html = self.client.get(reverse("contatori:macchina", args=[self.mfc.pk])).content.decode()
        for testo in ("cc-draw-mfc", "Toner nero: 8%", "#111827", "#06b6d4", "Pronta", "Cassetto 1"):
            self.assertIn(testo, html)
        self.assertIn("cc-svg-toner is-basso", html)
