"""Pulsante «N da approvare» della barra: somma tutte le fonti e porta alla pagina giusta."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse

from dashboard import da_approvare


class DaApprovareTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(username="syn.approva", email="capo@example.test")
        self.req = RequestFactory().get("/")
        self.req.user = self.user
        self.legacy = SimpleNamespace(id=77, nome="Capo Sintetico", email="capo@example.test")

    def _riepilogo(self, assenze=0, dpi=0):
        with patch("core.context_processors._count_car_pending", return_value=assenze), \
             patch("dpi.mie_attivita.da_approvare", return_value=[{}] * dpi):
            return da_approvare.riepilogo(self.req, self.legacy)

    def test_solo_assenze_porta_alle_assenze(self):
        r = self._riepilogo(assenze=2)
        self.assertEqual(r["totale"], 2)
        self.assertEqual(r["url"], reverse("assenze_car_dashboard"))
        self.assertIn("2 assenze", r["titolo"])

    def test_piu_fonti_portano_a_le_mie_attivita(self):
        r = self._riepilogo(assenze=1, dpi=1)
        self.assertEqual(r["totale"], 2)
        self.assertEqual(r["url"], reverse("mie_attivita"))
        self.assertIn("1 assenza", r["titolo"])
        self.assertIn("1 DPI", r["titolo"])

    def test_solo_dpi_porta_ai_dpi(self):
        r = self._riepilogo(dpi=3)
        self.assertTrue(r["url"].startswith(reverse("dpi:gestione_list")))

    def test_niente_da_decidere(self):
        self.assertEqual(self._riepilogo()["totale"], 0)
