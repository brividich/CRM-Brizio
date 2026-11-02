"""KPI della Hub Preview: numeri dell'ambito di chi guarda, solo per i moduli che può aprire."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from dashboard import views


class HubPreviewKpiAmbitoTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/hub-preview/")
        self.request.user = get_user_model().objects.create_user(username="kpi-hub", password="x")
        self.request.legacy_user = None
        self.tile = {
            "ticket": [{"value": 4, "unit": "attivi", "tone": "warning"}],
            "asset": [{"value": 2, "unit": "assegnati", "tone": "info"}, {"value": 1, "unit": "in uso", "tone": "info"}],
        }

    def _cards(self, visibili):
        with (
            patch("dashboard.views_home_portale._tile_kpi_counts", return_value=self.tile),
            patch("dashboard.views_home_portale.moduli_visibili", return_value=visibili),
        ):
            return {c["kpi_key"]: c for c in views._hub_kpi_cards({}, self.request)}

    def test_senza_moduli_visibili_niente_numeri_aziendali(self):
        cards = self._cards(set())
        for chiave in ("ticket", "asset", "anomalie", "incidenti", "diario", "dpi", "scadenze"):
            self.assertNotIn(chiave, cards)

    def test_numeri_presi_dalle_tessere_della_home(self):
        cards = self._cards({"ticket", "asset"})
        self.assertEqual(cards["ticket"]["value"], 4)
        self.assertEqual(cards["asset"]["value"], 2)
        self.assertEqual(cards["asset"]["sub"], "assegnati · 1 in uso")

    def test_pannelli_aziendali_nascosti_a_chi_non_vede_tutto(self):
        with (
            patch("dashboard.views_home_portale.moduli_visibili", return_value={"asset", "incidenti"}),
            patch("dashboard.views_home_portale._ambito_kpi", return_value={1, 2}),
            patch("dashboard.views._hub_kpi_cards", return_value=[]),
            patch("rilevazione_incidenti.services.get_safety_kpis") as safety,
            patch("assets.services.dashboard_kpi.get_maintenance_status_by_family") as manut,
            patch("dashboard.views.render") as render,
        ):
            views.dashboard_hub_preview.__wrapped__(self.request)
        safety.assert_not_called()
        manut.assert_not_called()
        ctx = render.call_args.args[2]
        self.assertEqual(ctx["safety_kpis"], {})
        self.assertEqual(ctx["maintenance_by_family"], [])
