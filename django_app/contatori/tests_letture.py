"""Letture guidate e lettura SNMP che non sovrascrive. Dati sintetici."""
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from . import services
from .models import LetturaContatori, Macchina
from .tests import _AuthedClientMixin

VALORI = {"a4_bn": 1000, "a3_bn": 100, "a4_col": 500, "a3_col": 50}


class LetturaFormTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.m = Macchina.objects.create(reparto="Ufficio", matricola="SYN-1", host="192.0.2.20")
        LetturaContatori.objects.create(macchina=self.m, trimestre="2026-Q1", data=date(2026, 4, 2), **VALORI)

    def _post(self, url=None, **over):
        dati = {"macchina": self.m.pk, "trimestre": "2026-Q2", "data": "2026-07-02",
                "fonte": "MANUALE", **VALORI, **over}
        return self.client.post(url or reverse("contatori:importa_lettura"), dati)

    def test_salva_e_torna_alla_macchina(self):
        r = self._post(a4_bn=1200)
        self.assertRedirects(r, reverse("contatori:macchina", args=[self.m.pk]))
        self.assertEqual(LetturaContatori.objects.get(trimestre="2026-Q2").a4_bn, 1200)

    def test_calo_bloccato_poi_confermabile(self):
        r = self._post(a4_bn=900)
        self.assertEqual(r.status_code, 200)
        self.assertIn("a4_bn", r.context["form"].errors)
        self.assertContains(r, 'type="checkbox" name="conferma_calo"')
        r = self._post(a4_bn=900, conferma_calo="on")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(LetturaContatori.objects.get(trimestre="2026-Q2").a4_bn, 900)

    def test_conferma_nascosta_senza_calo(self):
        r = self.client.get(reverse("contatori:importa_lettura"))
        self.assertContains(r, 'type="hidden" name="conferma_calo"')

    def test_doppia_lettura_messaggio_chiaro(self):
        r = self._post(trimestre="2026-Q1")
        self.assertIn("Esiste già una lettura", r.context["form"].errors["trimestre"][0])

    def test_correggi_ed_elimina(self):
        lettura = LetturaContatori.objects.get()
        r = self._post(url=reverse("contatori:lettura_edit", args=[lettura.pk]), trimestre="2026-Q1", a4_bn=1001)
        self.assertEqual(r.status_code, 302)
        lettura.refresh_from_db()
        self.assertEqual(lettura.a4_bn, 1001)
        r = self.client.post(reverse("contatori:lettura_elimina", args=[lettura.pk]))
        self.assertRedirects(r, reverse("contatori:macchina", args=[self.m.pk]))
        self.assertFalse(LetturaContatori.objects.exists())

    def test_trimestre_solo_da_elenco(self):
        r = self._post(trimestre="2026-Q9")
        self.assertIn("trimestre", r.context["form"].errors)


class LeggiSnmpTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.trim = services.trimestre_corrente()
        self.manuale = Macchina.objects.create(reparto="Manuale", matricola="SYN-M", host="192.0.2.31")
        self.calo = Macchina.objects.create(reparto="Calo", matricola="SYN-C", host="192.0.2.32")
        self.ok = Macchina.objects.create(reparto="Ok", matricola="SYN-O", host="192.0.2.33")
        LetturaContatori.objects.create(macchina=self.manuale, trimestre=self.trim, data=date.today(),
                                        fonte="MANUALE", **VALORI)
        LetturaContatori.objects.create(macchina=self.calo, trimestre="2000-Q1", data=date(2000, 3, 1),
                                        a4_bn=999999, a3_bn=0, a4_col=0, a3_col=0)

    def test_non_sovrascrive_manuali_ne_salva_cali(self):
        with mock.patch.object(services, "interroga_macchina", return_value=dict(VALORI)) as interroga:
            r = self.client.post(reverse("contatori:leggi_snmp"), follow=True)
        self.assertEqual(interroga.call_count, 2)  # la manuale non viene neppure interrogata
        self.assertEqual(LetturaContatori.objects.get(macchina=self.manuale, trimestre=self.trim).fonte, "MANUALE")
        self.assertFalse(LetturaContatori.objects.filter(macchina=self.calo, trimestre=self.trim).exists())
        self.assertTrue(LetturaContatori.objects.filter(macchina=self.ok, trimestre=self.trim, fonte="SNMP").exists())
        testi = [str(m) for m in r.context["messages"]]
        self.assertTrue(any("Manuale" in t and "Non sovrascritte" in t for t in testi), testi)
        self.assertTrue(any("Calo" in t and "più bassi" in t for t in testi), testi)
