"""Tessere della riconciliazione cliccabili: ogni numero apre la vista del confronto con lo stesso insieme."""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import Fattura, LetturaContatori, Macchina, RigaFattura
from .tests import _AuthedClientMixin


class RiconciliazioneKpiLinkTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        a = Macchina.objects.create(reparto="Uff A", matricola="SYN-KA", contratto="C-OK")
        b = Macchina.objects.create(reparto="Uff B", matricola="SYN-KB", contratto="C-KO")
        Macchina.objects.create(reparto="Uff C", matricola="SYN-KC", contratto="C-MANCA")
        f = Fattura.objects.create(numero="F-K", data=date(2026, 7, 1), trimestre="2026-Q2",
                                   periodo_al=date(2026, 6, 30))
        RigaFattura.objects.create(fattura=f, contratto="C-OK", a4_bn=10)
        RigaFattura.objects.create(fattura=f, contratto="C-KO", a4_bn=500)
        RigaFattura.objects.create(fattura=f, contratto="C-MANCA", a4_bn=10)
        LetturaContatori.objects.create(macchina=a, trimestre="2026-Q2", data=date(2026, 7, 3), a4_bn=20)
        LetturaContatori.objects.create(macchina=b, trimestre="2026-Q2", data=date(2026, 7, 3), a4_bn=100)
        self.url = reverse("contatori:riconciliazione_trim", args=["2026-Q2"])

    def test_tessere_portano_alle_viste_con_lo_stesso_numero(self):
        _righe, riepilogo = services.riconcilia("2026-Q2")
        html = self.client.get(self.url).content.decode()
        attese = {
            "": riepilogo["contratti"],
            "allineati": riepilogo["contratti_ok"],
            "da-controllare": riepilogo["contratti_danger"],
            "letture-mancanti": None,
        }
        for vista, numero in attese.items():
            href = f"{self.url}{'?vista=' + vista if vista else ''}#confronto"
            self.assertIn(f'href="{href}"', html, vista)
            r = self.client.get(self.url, {"vista": vista} if vista else {})
            if numero is not None:
                self.assertEqual(len(r.context["gruppi"]), numero, vista)
        # Letture mancanti: la vista mostra i contratti con MFC senza lettura, cioè quelle contate.
        r = self.client.get(self.url, {"vista": "letture-mancanti"})
        mfc = {m.pk for gr in r.context["gruppi"] for m in gr["mancanti"]}
        self.assertEqual(len(mfc), riepilogo["letture_mancanti"])
        self.assertEqual(riepilogo["contratti_ok"], 1)
        self.assertEqual(riepilogo["contratti_danger"], 1)
        self.assertEqual(riepilogo["letture_mancanti"], 1)

    def test_vista_sconosciuta_mostra_tutto(self):
        r = self.client.get(self.url, {"vista": "boh"})
        self.assertEqual(r.context["vista"], "")
        self.assertEqual(len(r.context["gruppi"]), 3)
