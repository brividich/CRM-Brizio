from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import EmployeeBoardConfig, EmployeeBoardTemplate
from dashboard import views as dashboard_views
from tickets.models import PrioritaTicket, StatoTicket, Ticket


@override_settings(STATIC_URL="/static/", MEDIA_URL="/media/")
class DashboardModuleIconDefaultsTests(TestCase):
    def test_default_card_icon_maps_user_module_labels(self):
        self.assertEqual(
            dashboard_views._card_image_public_url(
                dashboard_views._default_module_card_image("Diario Preposto")
            ),
            "/static/core/img/module-icons/diario-preposto.svg",
        )
        self.assertEqual(
            dashboard_views._card_image_public_url(
                dashboard_views._default_module_card_image("VRF Kickoff")
            ),
            "/static/core/img/module-icons/vrf-kickoff.svg",
        )

    def test_module_cards_keep_configured_card_image_priority(self):
        pulsanti = [
            SimpleNamespace(id=1, codice="tickets", label="Tickets", modulo="tickets", url="/tickets/"),
            SimpleNamespace(id=2, codice="assets", label="Assets", modulo="assets", url="/assets/"),
        ]

        cards = dashboard_views._module_cards(
            pulsanti,
            {
                1: {"enabled": True, "is_padre": True, "card_image": "custom/tickets.png"},
                2: {"enabled": True, "is_padre": True, "card_image": ""},
            },
        )

        by_id = {card["pulsante_id"]: card for card in cards}
        self.assertEqual(by_id[1]["image_url"], "/media/custom/tickets.png")
        self.assertEqual(by_id[2]["image_url"], "/static/core/img/module-icons/assets.svg")

    def test_module_card_image_lookup_uses_uploaded_module_logo(self):
        pulsanti = [
            SimpleNamespace(id=1, codice="tickets", label="Tickets", nome_visibile="Ticket", modulo="tickets", url="/tickets/"),
        ]

        lookup = dashboard_views._module_card_image_lookup(
            {1: {"card_image": "dashboard/modules/tickets/logo.png"}},
            pulsanti,
        )

        self.assertEqual(lookup["tickets"], "/media/dashboard/modules/tickets/logo.png")

    def test_employee_widgets_use_uploaded_module_logo(self):
        widgets = [{"id": "tickets_miei", "title": "Ticket Personali", "icon": "fallback"}]

        decorated = dashboard_views._decorate_board_widgets_with_module_images(
            widgets,
            {"tickets": "/media/dashboard/modules/tickets/logo.png"},
        )

        self.assertEqual(decorated[0]["icon"], "/media/dashboard/modules/tickets/logo.png")
        self.assertEqual(widgets[0]["icon"], "fallback")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DashboardAnomalieAccessTests(TestCase):
    def setUp(self):
        super().setUp()
        from django.utils import timezone

        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(
            username="dashboard-anomalie-user",
            password="pass12345",
        )
        # Completa l'onboarding: senza, l'OnboardingMiddleware redirige a /onboarding/
        # (302) prima del rendering, impedendo di verificare la pagina.
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now()
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
        from django.utils import timezone

        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(
            username="dashboard-route-compat-user",
            password="pass12345",
        )
        # Senza onboarding completato l'OnboardingMiddleware redirige a /onboarding/
        # prima della view, mascherando le redirect di compatibilità attese.
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now()
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
        from django.utils import timezone

        from core.models import UserOnboarding

        User = get_user_model()
        self.user = User.objects.create_user(
            username="employee-board-user",
            password="pass12345",
            email="employee.board@example.com",
        )
        # Senza onboarding completato l'OnboardingMiddleware risponde 403 sugli
        # endpoint JSON (reason "onboarding_required"), facendo fallire i test API.
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now()
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


@override_settings(STATIC_URL="/static/", MEDIA_URL="/media/")
class PriorityKpisTests(TestCase):
    """#3 — i KPI hero della home riusano i conteggi reali di _tile_kpi_counts."""

    def test_priority_kpis_use_tile_counts(self):
        from dashboard import views_home_portale as hp

        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, is_authenticated=True,
                                 get_username=lambda: "u", get_full_name=lambda: "U"),
            legacy_user=None,
        )
        tile_kpis = {
            "anomalie": [{"value": 7, "unit": "aperte", "tone": "danger"}],
            "ticket": [{"value": 3, "unit": "attivi", "tone": "warning"}],
            "task": [{"value": 5, "unit": "in corso"}, {"value": 2, "unit": "scaduti"}],
            "assenze": [{"value": 4, "unit": "in approvazione", "tone": "warning"}],
        }
        with patch("dashboard.views_home_portale.get_legacy_user", return_value=None):
            kpis = hp._priority_kpis(request, tile_kpis)

        by_label = {k["label"]: k for k in kpis}
        self.assertEqual(by_label["Anomalie aperte"]["value"], 7)
        self.assertEqual(by_label["Ticket attivi"]["value"], 3)
        self.assertEqual(by_label["Task in corso"]["value"], 5)
        self.assertEqual(by_label["Task in corso"]["sub"], "2 scaduti")
        self.assertEqual(by_label["Approvazioni"]["value"], 4)

    def test_priority_kpis_default_zero_without_tile_data(self):
        from dashboard import views_home_portale as hp

        request = SimpleNamespace(
            user=SimpleNamespace(is_superuser=False, is_authenticated=True,
                                 get_username=lambda: "u", get_full_name=lambda: "U"),
            legacy_user=None,
        )
        with patch("dashboard.views_home_portale.get_legacy_user", return_value=None):
            kpis = hp._priority_kpis(request, None)
        self.assertTrue(all(k["value"] == 0 for k in kpis))


@override_settings(STATIC_URL="/static/", MEDIA_URL="/media/")
class HomePortaleModuleVisibilityTests(TestCase):
    """La home mostra solo i moduli realmente visibili dal ruolo utente."""

    def test_module_groups_include_only_accessible_modules(self):
        from dashboard import views_home_portale as hp

        with (
            patch("dashboard.views_home_portale._safe_url", return_value="#"),
            patch("dashboard.views_home_portale._module_image_url_for", return_value=""),
        ):
            groups = hp._module_groups(
                SimpleNamespace(),
                accessible_set={"anomalie"},
                is_admin=False,
                image_lookup={},
                kpi_counts={},
            )

        module_ids = [mod["id"] for grp in groups for mod in grp["modules"]]
        self.assertEqual(module_ids, ["anomalie"])
        self.assertEqual(groups[0]["accessible_count"], 1)
        self.assertEqual(groups[0]["total"], 1)

    def test_home_context_ignores_stale_locked_modules_session(self):
        from dashboard import views_home_portale as hp

        request = SimpleNamespace(
            user=SimpleNamespace(
                is_superuser=False,
                is_authenticated=True,
                first_name="Mario",
                get_username=lambda: "mario",
            ),
            legacy_user=None,
            session={"hp_show_locked": True},
        )

        with (
            patch("dashboard.views_home_portale.get_legacy_user", return_value=None),
            patch("dashboard.views_home_portale._module_card_image_lookup", return_value={}),
            patch("dashboard.views_home_portale._build_accessible_set", return_value={"anomalie"}),
            patch("dashboard.views_home_portale._my_tasks", return_value=[]),
            patch("dashboard.views_home_portale._pending_approvals", return_value=[]),
            patch("dashboard.views_home_portale._tile_kpi_counts", return_value={}),
            patch("dashboard.views_home_portale._module_groups", return_value=[]),
            patch("dashboard.views_home_portale._header_actions", return_value=[]),
            patch("dashboard.views_home_portale._priority_kpis", return_value=[]),
            patch("dashboard.views_home_portale._active_unit", return_value=None),
            patch("dashboard.views_home_portale._calendar_week", return_value=[]),
            patch("dashboard.views_home_portale._news_items", return_value=[]),
            patch("dashboard.views_home_portale._activity_items", return_value=[]),
            patch("dashboard.views_home_portale._safety_kpis", return_value=[]),
            patch("dashboard.views_home_portale._system_status", return_value=[]),
            patch(
                "dashboard.views_mie_attivita.build_cose_da_gestire",
                return_value={"sections": [], "total": 0},
            ),
            patch("dashboard.views_home_portale.render") as render_mock,
        ):
            hp.home_portale(request)

        context = render_mock.call_args.args[2]
        self.assertNotIn("show_locked_modules", context)


class MieAttivitaTests(TestCase):
    """#4 — cockpit personale 'Le mie attività'."""

    def setUp(self):
        from django.utils import timezone

        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(
            username="cockpit", password="x", email="cockpit@test.local"
        )
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now()
        )
        self.client.force_login(self.user)

    def test_page_renders_with_sections(self):
        with patch("dashboard.views_mie_attivita.get_legacy_user", return_value=None):
            response = self.client.get(reverse("mie_attivita"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Le mie attività")
        self.assertContains(response, "Anomalie aperte")
        self.assertContains(response, "Ticket aperti")
        self.assertContains(response, "Richieste DPI in corso")

    def test_my_tickets_lists_only_open_related(self):
        from dashboard import views_mie_attivita as ma

        legacy_user = SimpleNamespace(id=4242)
        open_t = Ticket.objects.create(
            titolo="Guasto mandrino", stato=StatoTicket.APERTA,
            priorita=PrioritaTicket.ALTA, richiedente_legacy_user_id=4242,
        )
        Ticket.objects.create(
            titolo="Vecchio chiuso", stato=StatoTicket.CHIUSO,
            richiedente_legacy_user_id=4242,
        )
        rows = ma._my_tickets(self.user, legacy_user, 4242)
        titles = [r["title"] for r in rows]
        self.assertIn("Guasto mandrino", titles)
        self.assertNotIn("Vecchio chiuso", titles)


class CoseDaGestireTests(TestCase):
    """#6 — sezione 'Cose da gestire': aggregatore cross-modulo per l'utente."""

    def setUp(self):
        from django.utils import timezone
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(
            username="cdg", password="x", email="cdg@test.local"
        )
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    def _req(self):
        request = SimpleNamespace(user=self.user, legacy_user=None)
        return request

    def test_build_returns_expected_sections(self):
        from dashboard import views_mie_attivita as ma

        with patch("dashboard.views_mie_attivita.get_legacy_user", return_value=None):
            data = ma.build_cose_da_gestire(self._req())

        keys = [s["key"] for s in data["sections"]]
        self.assertEqual(
            set(keys),
            {"approvazioni", "ticket", "anomalie", "procedure", "dpi", "elearning", "skm_refresh"},
        )
        self.assertIn("total", data)

    def test_total_counts_items_across_sections(self):
        from dashboard import views_mie_attivita as ma

        # Un ticket aperto correlato all'utente fa salire il totale.
        legacy_user = SimpleNamespace(id=555, ruolo="", ruolo_id=None, nome="", email="")
        Ticket.objects.create(
            titolo="Da gestire", stato=StatoTicket.APERTA,
            priorita=PrioritaTicket.ALTA, richiedente_legacy_user_id=555,
        )
        request = SimpleNamespace(user=self.user, legacy_user=legacy_user)
        with (
            patch("dashboard.views_mie_attivita.get_legacy_user", return_value=legacy_user),
            patch("dashboard.views_mie_attivita._my_approvals", return_value=[]),
        ):
            data = ma.build_cose_da_gestire(request)
        ticket_section = next(s for s in data["sections"] if s["key"] == "ticket")
        self.assertGreaterEqual(len(ticket_section["items"]), 1)
        self.assertGreaterEqual(data["total"], 1)

    def test_my_procedure_lists_only_unread(self):
        from datetime import date

        from dashboard import views_mie_attivita as ma
        from procedure_refresh.models import (
            AssignmentStatus, ProcedureAssignment, ProcedureCampaign,
            ProcedureDocument, ProcedureRevision, SourceType,
        )

        campaign = ProcedureCampaign.objects.create(
            name="Refresh sicurezza 2026", start_date=date(2026, 1, 1), due_date=date(2026, 12, 31),
        )
        doc = ProcedureDocument.objects.create(code="DOC-X", title="Procedura X")
        rev = ProcedureRevision.objects.create(
            document=doc, revision_code="01", revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 2), file_name="proc_x_v1.pdf",
            source_type=SourceType.FILESERVER, source_path="/srv/proc_x_v1.pdf",
        )
        ProcedureAssignment.objects.create(
            campaign=campaign, revision=rev, user=self.user, status=AssignmentStatus.ASSIGNED,
        )
        # Confermata: NON deve comparire.
        ProcedureAssignment.objects.create(
            campaign=campaign, revision=rev, user=self.user, status=AssignmentStatus.READ_CONFIRMED,
        )
        rows = ma._my_procedure(self.user)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Refresh sicurezza 2026")

    def test_my_procedure_empty_without_assignments(self):
        from dashboard import views_mie_attivita as ma

        self.assertEqual(ma._my_procedure(self.user), [])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ScadenzeGlobaliTests(TestCase):
    """Scadenzario globale unificato (/scadenze) — provider, gating, filtri."""

    def setUp(self):
        from django.utils import timezone

        from core.models import UserOnboarding

        self.admin = get_user_model().objects.create_superuser(
            username="sg-admin", email="sg-admin@test.local", password="x"
        )
        self.user = get_user_model().objects.create_user(
            username="sg-user", password="x"
        )
        for u in (self.admin, self.user):
            UserOnboarding.objects.create(user=u, completed=True, completed_at=timezone.now())

    def _make_asset_deadline(self, *, days, title="Revisione periodica"):
        from datetime import timedelta

        from django.utils import timezone
        from assets.models import Asset, AssetAdministrativeDeadline

        asset = Asset.objects.create(
            asset_tag=f"SG-{title[:4]}-{days}", name="Tornio CNC", reparto="OFFICINA"
        )
        return AssetAdministrativeDeadline.objects.create(
            asset=asset,
            title=title,
            due_date=timezone.localdate() + timedelta(days=days),
            is_active=True,
        )

    def test_page_renders_for_authenticated_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("scadenze_globali"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scadenzario globale")

    def test_asset_provider_collects_active_deadlines_in_window(self):
        from dashboard.scadenze_providers import ScadenzeContext, collect_asset, SOURCE_ASSET

        self._make_asset_deadline(days=20, title="Certificato CE")     # in finestra
        self._make_asset_deadline(days=400, title="Lontana")           # fuori finestra (60gg)
        request = SimpleNamespace(user=self.admin)
        ctx = ScadenzeContext.build(request)
        items = collect_asset(ctx)
        titoli = [i.titolo for i in items]
        self.assertIn("Certificato CE", titoli)
        self.assertNotIn("Lontana", titoli)
        self.assertTrue(all(i.source == SOURCE_ASSET for i in items))

    def test_asset_provider_gated_for_user_without_permission(self):
        from dashboard.scadenze_providers import ScadenzeContext, collect_asset

        self._make_asset_deadline(days=10)
        request = SimpleNamespace(user=self.user)  # non-superuser, nessun ACL assets
        with patch("core.acl.user_can_modulo_action", return_value=False):
            ctx = ScadenzeContext.build(request)
            items = collect_asset(ctx)
        self.assertEqual(items, [])

    def test_scaduta_flag_and_giorni(self):
        from datetime import timedelta

        from django.utils import timezone
        from dashboard.scadenze_providers import ScadenzaItem, SOURCE_ASSET

        past = ScadenzaItem(
            source=SOURCE_ASSET, kind="x", kind_label="X", titolo="t", soggetto="s",
            reparto="", data_scadenza=timezone.localdate() - timedelta(days=3), giorni=-3,
        )
        future = ScadenzaItem(
            source=SOURCE_ASSET, kind="x", kind_label="X", titolo="t", soggetto="s",
            reparto="", data_scadenza=timezone.localdate() + timedelta(days=5), giorni=5,
        )
        self.assertTrue(past.scaduta)
        self.assertFalse(future.scaduta)

    def test_filter_by_source_csv_export(self):
        self.client.force_login(self.admin)
        self._make_asset_deadline(days=15, title="Taratura strumenti")
        response = self.client.get(reverse("scadenze_globali") + "?sorgente=asset&format=csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        body = response.content.decode("utf-8-sig")
        self.assertEqual(body.count("﻿"), 0)  # BOM una volta sola, non per riga
        self.assertIn("Taratura strumenti", body)

    def test_collect_all_isolates_failing_provider(self):
        from dashboard import scadenze_providers as sp

        request = SimpleNamespace(user=self.admin)
        with patch.object(sp, "collect_asset", side_effect=RuntimeError("boom")):
            # Un provider che esplode non deve far cadere l'aggregatore.
            items = sp.collect_all(request, sources={sp.SOURCE_ASSET})
        self.assertEqual(items, [])

    def test_dpi_provider_collects_consegna_with_scadenza(self):
        from datetime import timedelta

        from django.utils import timezone
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI
        from dashboard.scadenze_providers import ScadenzeContext, collect_dpi, SOURCE_DPI

        categoria = CategoriaDPI.objects.create(nome="Guanti antitaglio")
        richiesta = RichiestaDPI.objects.create(
            categoria=categoria, richiedente_nome="Mario Rossi", richiedente_reparto="OFFICINA"
        )
        ConsegnaDPI.objects.create(
            richiesta=richiesta,
            data_consegna=timezone.localdate(),
            data_scadenza_stimata=timezone.localdate() + timedelta(days=25),
        )
        ctx = ScadenzeContext.build(SimpleNamespace(user=self.admin))
        items = collect_dpi(ctx)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].source, SOURCE_DPI)
        self.assertEqual(items[0].titolo, "Guanti antitaglio")
        self.assertEqual(items[0].soggetto, "Mario Rossi")


class CoseDaGestireSafetyTests(TestCase):
    """La sezione Salute e Sicurezza (scadenze qualifiche) entra in "cose da gestire"
    per chi ha il permesso formazione/HR."""

    @classmethod
    def setUpTestData(cls):
        from anagrafica.tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        cls.admin = get_user_model().objects.create_superuser(
            username="cdg_admin", email="cdg@x.local", password="x"
        )

    def test_safety_section_con_qualifica_scaduta(self):
        from datetime import timedelta
        from django.db import connection
        from django.test import RequestFactory
        from django.utils import timezone
        from anagrafica.models import TipoQualifica, DipendenteQualifica
        from dashboard.views_mie_attivita import build_cose_da_gestire

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, mansione, attivo) "
                "VALUES (9001, 'Aldo', 'Bianchi', '', 1)"
            )
        tipo = TipoQualifica.objects.create(
            nome="Carrellista Home", categoria=TipoQualifica.CAT_SICUREZZA
        )
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=9001, tipo=tipo,
            data_scadenza=timezone.localdate() - timedelta(days=3),
        )
        req = RequestFactory().get("/")
        req.user = self.admin
        data = build_cose_da_gestire(req)
        safety = next((s for s in data["sections"] if s["key"] == "safety"), None)
        self.assertIsNotNone(safety)
        self.assertIn("Carrellista Home", [i["title"] for i in safety["items"]])

    def test_run_idoneita_digest_failsafe(self):
        """Il task schedulato dell'idoneità è no-op (nessun errore) quando non ci
        sono destinatari/mansioni configurati."""
        from anagrafica.tasks import run_idoneita_digest
        res = run_idoneita_digest()
        self.assertTrue(res.get("ok"))
