"""Letture trimestrali proposte dalle mensili SNMP. Dati sintetici."""
from datetime import date, datetime, timezone as dt_tz

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import LetturaContatori, LetturaMensileContatori, Macchina
from .tests import _AuthedClientMixin


def _mensile(m, mese, giorno_ora, base):
    return LetturaMensileContatori.objects.create(
        macchina=m, mese=mese, rilevata_il=giorno_ora, a4_bn=base, a3_bn=10, a4_col=base // 10, a3_col=1)


class ProposteTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-L1", host="192.0.2.81")
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-L2", host="192.0.2.82")
        self.c = Macchina.objects.create(reparto="Gamma", matricola="SYN-L3", host="192.0.2.83")
        # Alfa: la mensile del 1 luglio e' la piu' vicina alla chiusura del Q2
        _mensile(self.a, date(2026, 6, 1), datetime(2026, 6, 1, 8, tzinfo=dt_tz.utc), 900)
        _mensile(self.a, date(2026, 7, 1), datetime(2026, 7, 1, 8, tzinfo=dt_tz.utc), 1000)
        # Beta: mensile piu' bassa della lettura Q1 -> incoerente
        LetturaContatori.objects.create(macchina=self.b, trimestre="2026-Q1", data=date(2026, 4, 2),
                                        a4_bn=5000, a3_bn=0, a4_col=0, a3_col=0)
        _mensile(self.b, date(2026, 7, 1), datetime(2026, 7, 1, 8, tzinfo=dt_tz.utc), 100)
        # Gamma: ha gia' la lettura Q2 -> nessuna proposta
        LetturaContatori.objects.create(macchina=self.c, trimestre="2026-Q2", data=date(2026, 7, 2))
        _mensile(self.c, date(2026, 7, 1), datetime(2026, 7, 1, 8, tzinfo=dt_tz.utc), 300)

    def test_proposte(self):
        proposte = {p["macchina"].reparto: p for p in services.proposte_letture_trimestrali("2026-Q2")}
        self.assertEqual(set(proposte), {"Alfa", "Beta"})
        self.assertEqual(proposte["Alfa"]["mensile"].a4_bn, 1000)
        self.assertFalse(proposte["Alfa"]["incoerente"])
        self.assertTrue(proposte["Beta"]["incoerente"])

    def test_conferma_crea_solo_le_coerenti(self):
        r = self.client.post(reverse("contatori:letture_proposte"),
                             {"trimestre": "2026-Q2", "macchina": [self.a.pk, self.b.pk]})
        self.assertEqual(r.status_code, 302)
        lettura = LetturaContatori.objects.get(macchina=self.a, trimestre="2026-Q2")
        self.assertEqual((lettura.a4_bn, lettura.fonte, lettura.data), (1000, "SNMP", date(2026, 7, 1)))
        self.assertIn("07/2026", lettura.note)
        self.assertFalse(LetturaContatori.objects.filter(macchina=self.b, trimestre="2026-Q2").exists())
        # Riconferma: idempotente
        self.client.post(reverse("contatori:letture_proposte"), {"trimestre": "2026-Q2", "macchina": [self.a.pk]})
        self.assertEqual(LetturaContatori.objects.filter(macchina=self.a, trimestre="2026-Q2").count(), 1)

    def test_pagina_e_voce_in_centrale(self):
        r = self.client.get(reverse("contatori:letture_proposte") + "?trimestre=2026-Q2")
        self.assertContains(r, "Più bassa del 2026-Q1")
        self.assertContains(r, 'name="macchina" value="%d"' % self.a.pk)
        self.assertNotContains(r, 'name="macchina" value="%d"' % self.b.pk)
        oggi = date(2026, 7, 10)
        titoli = [t["titolo"] for t in services.cruscotto_operativo(oggi=oggi)["da_fare"]]
        self.assertIn("1 lettura 2026-Q2 pronta dalle mensili", titoli)
