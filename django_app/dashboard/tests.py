from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import EmployeeBoardConfig, EmployeeBoardTemplate
from dashboard import views as dashboard_views
from tickets.models import PrioritaTicket, StatoTicket, Ticket


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

    def test_board_widget_order_keeps_only_selected_widgets(self):
        legacy_user = SimpleNamespace(ruolo="impiegato")

        widgets = dashboard_views._board_ordered_widgets(
            ["notifiche"],
            legacy_user,
            False,
        )

        self.assertEqual([w["id"] for w in widgets], ["notifiche"])

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DashboardRouteCompatibilityTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="dashboard-route-compat-user",
            password="pass12345",
        )
        self.client.force_login(self.user)

    def test_richieste_route_redirects_to_assenze_gestione(self):
        response = self.client.get(reverse("richieste"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("assenze_gestione"))

    def test_employee_board_route_redirects_to_dashboard_home(self):
        response = self.client.get(reverse("employee_board"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("dashboard_home"))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class EmployeeBoardTemplateTests(TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="employee-board-user",
            password="pass12345",
            email="employee.board@example.com",
        )
        self.admin_user = User.objects.create_superuser(
            username="employee-board-admin",
            password="pass12345",
            email="employee.board.admin@example.com",
        )

    def test_load_employee_board_config_uses_admin_template_for_new_user(self):
        EmployeeBoardTemplate.objects.create(
            key="default",
            name="Template officina",
            layout=["profilo", "tickets_miei", "procedure_da_leggere"],
            widget_configs={"tickets_miei": {"max_items": 3, "show_closed": False}},
        )

        cfg = dashboard_views._load_employee_board_config(legacy_user_id=77)

        self.assertEqual(cfg["layout"], ["profilo", "tickets_miei", "procedure_da_leggere"])
        self.assertFalse(cfg["has_user_config"])
        self.assertEqual(cfg["template_name"], "Template officina")
        self.assertEqual(cfg["widget_configs"]["tickets_miei"]["max_items"], 3)

    def test_load_employee_board_config_merges_template_and_user_config(self):
        EmployeeBoardTemplate.objects.create(
            key="default",
            layout=["profilo", "tickets_miei"],
            widget_configs={"tickets_miei": {"max_items": 4, "show_closed": False}},
        )
        EmployeeBoardConfig.objects.create(
            legacy_user_id=88,
            layout=["tickets_miei"],
            widget_configs={"tickets_miei": {"max_items": 2, "show_closed": True}},
        )

        cfg = dashboard_views._load_employee_board_config(legacy_user_id=88)

        self.assertTrue(cfg["has_user_config"])
        self.assertEqual(cfg["layout"], ["tickets_miei"])
        self.assertEqual(cfg["widget_configs"]["tickets_miei"]["max_items"], 2)
        self.assertTrue(cfg["widget_configs"]["tickets_miei"]["show_closed"])

    def test_reset_endpoint_clears_user_config_and_restores_template(self):
        EmployeeBoardTemplate.objects.create(
            key="default",
            name="Template reparto",
            layout=["profilo", "panoramica_moduli"],
        )
        EmployeeBoardConfig.objects.create(
            legacy_user_id=101,
            layout=["notifiche"],
            widget_configs={"notifiche": {"max_items": 2, "solo_non_lette": True}},
        )
        self.client.force_login(self.user)

        with patch(
            "dashboard.views.get_legacy_user",
            return_value=SimpleNamespace(id=101, ruolo="impiegato", ruolo_id=2),
        ):
            response = self.client.post(
                reverse("api_employee_board_reset"),
                data="{}",
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmployeeBoardConfig.objects.filter(legacy_user_id=101).exists())
        self.assertJSONEqual(
            response.content,
            {"ok": True, "layout": ["profilo", "panoramica_moduli"], "template_name": "Template reparto"},
        )

    def test_admin_can_save_global_employee_board_template(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse("api_employee_board_admin_template"),
            data='{"name":"Template iniziale produzione","layout":["profilo","tickets_miei","profilo","unknown"],"widget_configs":{"tickets_miei":{"max_items":3,"show_closed":true}}}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        template = EmployeeBoardTemplate.objects.get(key="default")
        self.assertEqual(template.name, "Template iniziale produzione")
        self.assertEqual(template.layout, ["profilo", "tickets_miei"])
        self.assertEqual(template.widget_configs["tickets_miei"]["max_items"], 3)
        self.assertTrue(template.widget_configs["tickets_miei"]["show_closed"])

    def test_ticket_widget_collects_related_ticket_kpis(self):
        legacy_user = SimpleNamespace(id=222, nome="Mario Rossi", email=self.user.email)
        Ticket.objects.create(
            tipo="IT",
            titolo="VPN non raggiungibile",
            descrizione="Test widget ticket",
            categoria="RETE",
            priorita=PrioritaTicket.URGENTE,
            stato=StatoTicket.APERTA,
            richiedente_nome="Mario Rossi",
            richiedente_email=self.user.email,
            richiedente_legacy_user_id=222,
        )
        Ticket.objects.create(
            tipo="MAN",
            titolo="Compressore in verifica",
            descrizione="Test widget assegnato",
            categoria="GENERICA",
            priorita=PrioritaTicket.MEDIA,
            stato=StatoTicket.IN_CARICO,
            richiedente_nome="Altro Utente",
            richiedente_email="altro@example.com",
            assegnato_email=self.user.email,
            assegnato_a="Mario Rossi",
        )

        data = dashboard_views._board_data_tickets(
            self.user,
            legacy_user,
            legacy_user_id=222,
            params={"max_items": 10, "show_closed": False},
        )

        self.assertEqual(data["stats"]["open"], 1)
        self.assertEqual(data["stats"]["in_charge"], 1)
        self.assertEqual(data["stats"]["urgent"], 1)
        self.assertEqual(len(data["items"]), 2)
