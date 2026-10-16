"""«Gestisci letture»: elenco, filtri, correzione ed eliminazione (anche in blocco). Dati sintetici."""
from datetime import date
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import LetturaContatori, LetturaMensileContatori, Macchina
from .tests import _AuthedClientMixin

V = {"a4_bn": 1000, "a3_bn": 100, "a4_col": 500, "a3_col": 50}
URL = reverse("contatori:letture_gestisci")


def _mensile(macchina, mese, **over):
    return LetturaMensileContatori.objects.create(
        macchina=macchina, mese=mese, rilevata_il=timezone.now(), **{**V, **over})


class GestisciLettureTests(_AuthedClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.a = Macchina.objects.create(reparto="Alfa", matricola="SYN-G1")
        self.b = Macchina.objects.create(reparto="Beta", matricola="SYN-G2")
        self.q1 = LetturaContatori.objects.create(macchina=self.a, trimestre="2026-Q1", data=date(2026, 4, 2), **V)
        # Q2 con A4 BN sceso: e' la lettura sbagliata da trovare.
        self.q2 = LetturaContatori.objects.create(macchina=self.a, trimestre="2026-Q2", data=date(2026, 7, 2),
                                                  **{**V, "a4_bn": 900})
        self.b25 = LetturaContatori.objects.create(macchina=self.b, trimestre="2025-Q4", data=date(2026, 1, 2), **V)
        self.m9 = _mensile(self.a, date(2026, 9, 1))
        self.m10 = _mensile(self.a, date(2026, 10, 1), a3_col=10)

    def test_elenco_trimestrali_con_cali_e_filtri(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["lettura"].pk for x in r.context["righe"]], [self.q2.pk, self.q1.pk, self.b25.pk])
        self.assertContains(r, "calo A4 BN")
        r = self.client.get(URL + "?cali=1")
        self.assertEqual([x["lettura"].pk for x in r.context["righe"]], [self.q2.pk])
        r = self.client.get(URL + f"?anno=2025&macchina={self.b.pk}")
        self.assertEqual([x["lettura"].pk for x in r.context["righe"]], [self.b25.pk])
        self.assertContains(r, "? Guida")

    def test_elenco_mensili(self):
        r = self.client.get(URL + "?tipo=mensili")
        self.assertEqual([x["periodo"] for x in r.context["righe"]], ["10/2026", "09/2026"])
        self.assertEqual(r.context["righe"][0]["cali"], ["A3 COL"])
        self.assertContains(r, reverse("contatori:lettura_mensile_edit", args=[self.m10.pk]))

    def test_elimina_in_blocco_solo_del_tipo_scelto(self):
        r = self.client.post(URL, {"tipo": "trimestrali", "lettura": [self.q1.pk, self.q2.pk, self.m9.pk],
                                   "next": URL + "?cali=1"})
        self.assertRedirects(r, URL + "?cali=1", fetch_redirect_response=False)
        self.assertEqual(list(LetturaContatori.objects.values_list("pk", flat=True)), [self.b25.pk])
        # L'id della mensile, passato tra le trimestrali, non tocca le mensili.
        self.assertEqual(LetturaMensileContatori.objects.count(), 2)
        self.client.post(URL, {"tipo": "mensili", "lettura": [self.m10.pk]})
        self.assertEqual(list(LetturaMensileContatori.objects.values_list("pk", flat=True)), [self.m9.pk])

    def test_next_esterno_ignorato(self):
        r = self.client.post(URL, {"tipo": "mensili", "lettura": [self.m10.pk], "next": "https://example.com/"})
        self.assertRedirects(r, URL + "?tipo=mensili", fetch_redirect_response=False)

    def test_correggi_mensile_con_calo_da_confermare_e_ritorno(self):
        url = reverse("contatori:lettura_mensile_edit", args=[self.m10.pk])
        ritorno = URL + "?tipo=mensili"
        r = self.client.post(url, {**V, "a3_col": 10, "next": ritorno})
        self.assertEqual(r.status_code, 200)
        self.assertIn("a3_col", r.context["form"].errors)
        r = self.client.post(url, {**V, "a3_col": 60, "next": ritorno})
        self.assertRedirects(r, ritorno, fetch_redirect_response=False)
        self.m10.refresh_from_db()
        self.assertEqual(self.m10.a3_col, 60)

    def test_elimina_mensile_singola(self):
        r = self.client.post(reverse("contatori:lettura_mensile_elimina", args=[self.m9.pk]))
        self.assertRedirects(r, reverse("contatori:macchina", args=[self.a.pk]), fetch_redirect_response=False)
        self.assertFalse(LetturaMensileContatori.objects.filter(pk=self.m9.pk).exists())

    def test_correggi_trimestrale_torna_all_elenco(self):
        ritorno = URL + "?cali=1"
        r = self.client.post(reverse("contatori:lettura_edit", args=[self.q2.pk]), {
            "macchina": self.a.pk, "trimestre": "2026-Q2", "data": "2026-07-02", "fonte": "MANUALE",
            **{**V, "a4_bn": 1100}, "next": ritorno})
        self.assertRedirects(r, ritorno, fetch_redirect_response=False)

    def test_senza_gestione_nessun_accesso(self):
        with mock.patch("contatori.permessi.puo_gestire", return_value=False):
            self.assertRedirects(self.client.get(URL), reverse("contatori:dashboard"),
                                 fetch_redirect_response=False)
            self.client.post(URL, {"tipo": "trimestrali", "lettura": [self.q1.pk]})
            self.client.post(reverse("contatori:lettura_mensile_elimina", args=[self.m9.pk]))
        self.assertTrue(LetturaContatori.objects.filter(pk=self.q1.pk).exists())
        self.assertTrue(LetturaMensileContatori.objects.filter(pk=self.m9.pk).exists())
