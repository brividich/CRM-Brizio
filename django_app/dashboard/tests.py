from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dashboard import views as dashboard_views


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DashboardAnomalieAccessTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="dashboard-anomalie-user",
            password="pass12345",
        )
        self.client.force_login(self.user)

    def test_anomalie_menu_hides_forbidden_actions(self):
        with (
            patch("dashboard.views.user_can_modulo_action", return_value=False),
            patch("dashboard.views.get_legacy_user", return_value=None),
        ):
            response = self.client.get(reverse("anomalie_menu"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "non ha accesso alle funzioni operative del modulo anomalie")
        self.assertNotContains(response, reverse("apertura_segnalazione"))
        self.assertNotContains(response, reverse("gestione_anomalie_page"))

    def test_anomalie_menu_shows_only_allowed_actions(self):
        def fake_can(request, modulo: str, azione: str) -> bool:
            return modulo == "anomalie" and azione == "anomalie_aperte"

        with (
            patch("dashboard.views.user_can_modulo_action", side_effect=fake_can),
            patch("dashboard.views.get_legacy_user", return_value=None),
        ):
            response = self.client.get(reverse("anomalie_menu"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("gestione_anomalie_page"))
        self.assertNotContains(response, reverse("apertura_segnalazione"))
        self.assertNotContains(response, "non ha accesso alle funzioni operative del modulo anomalie")

    def test_board_widget_order_respects_anomalie_acl_visibility(self):
        legacy_user = SimpleNamespace(ruolo="amministrazione")

        widgets = dashboard_views._board_ordered_widgets(
            ["anomalie_gestione", "notifiche"],
            legacy_user,
            False,
            widget_visibility={"anomalie_gestione": False},
        )

        self.assertNotIn("anomalie_gestione", [w["id"] for w in widgets])

    def test_employee_board_data_returns_403_for_hidden_anomalie_widget(self):
        with (
            patch("dashboard.views.user_can_modulo_action", return_value=False),
            patch(
                "dashboard.views.get_legacy_user",
                return_value=SimpleNamespace(id=10, ruolo="amministrazione", ruolo_id=5),
            ),
        ):
            response = self.client.get(
                reverse("api_employee_board_data"),
                {"widget_id": "anomalie_gestione"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {"ok": False, "error": "forbidden"})
