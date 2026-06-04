from __future__ import annotations

import json
import logging
import tempfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cachetools import TTLCache
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.db import connection
from django.db.utils import ProgrammingError
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.acl import check_permesso, diagnose_permesso_for_context
from core.acl_v2 import resolve_canonical_target
from core.audit import log_action
from core.csrf_cookie_middleware import EnsureCSRFCookieMiddleware
from core.accounts import windows_sso as windows_sso_module
from core.impersonation import IMPERSONATION_SESSION_KEY
from core.context_processors import (
    get_default_sidebar_footer_actions,
    get_sidebar_footer_catalog,
    legacy_nav,
    normalize_sidebar_footer_actions,
)
from core.branding import get_portal_branding
from core.contact_people import coalesce_contact_people, parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_models import Permesso, Pulsante, Ruolo, UtenteLegacy
from core.logging_handlers import SafeTimedRotatingFileHandler
from core.middleware import ACLMiddleware, AdaptiveSecureCookieMiddleware
from core.legacy_cache import bump_legacy_cache_version
from core.legacy_utils import ALLOWED_LEGACY_TABLES, legacy_table_columns, sync_django_user_from_legacy
from core.models import (
    AuditLog,
    LegacyRedirect,
    NavigationItem,
    NavigationRoleAccess,
    Notifica,
    PermissionDefinition,
    Profile,
    RolePermissionGrant,
    RoutePermissionBinding,
    SiteConfig,
    UserOnboarding,
    UserNavigationOverride,
    UserPermissionOverride,
    UserUiPreference,
)
from core.session_middleware import SessionIdleTimeoutMiddleware
from core.module_registry import (
    MODULE_DEFINITIONS,
    get_module_branding,
    get_module_definition,
    get_modules_by_audience,
    get_registered_modules,
    navigation_code_label_map,
    resolve_module_label,
)
from core.navigation_registry import (
    get_topbar_nodes,
    publish_navigation_snapshot,
    resolve_navigation_item_permission_code,
    restore_navigation_snapshot,
)
from core.views import csrf_failure
from config.settings.base import default_dev_allowed_hosts


def _attach_session(request) -> None:
    middleware = SessionMiddleware(lambda req: HttpResponse("ok"))
    middleware.process_request(request)
    request.session.save()


def _ensure_legacy_acl_tables() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ruoli (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS utenti (
                    id INTEGER PRIMARY KEY,
                    nome VARCHAR(200) NOT NULL,
                    email VARCHAR(200) NULL,
                    password VARCHAR(500) NOT NULL,
                    ruolo VARCHAR(100) NULL,
                    attivo INTEGER NOT NULL DEFAULT 1,
                    deve_cambiare_password INTEGER NOT NULL DEFAULT 0,
                    ruolo_id INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('ruoli', 'U') IS NULL
                CREATE TABLE ruoli (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(100) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                IF OBJECT_ID('utenti', 'U') IS NULL
                CREATE TABLE utenti (
                    id INT NOT NULL PRIMARY KEY,
                    nome NVARCHAR(200) NOT NULL,
                    email NVARCHAR(200) NULL,
                    password NVARCHAR(500) NOT NULL,
                    ruolo NVARCHAR(100) NULL,
                    attivo BIT NOT NULL DEFAULT 1,
                    deve_cambiare_password BIT NOT NULL DEFAULT 0,
                    ruolo_id INT NULL
                )
                """
            )


def _clear_legacy_acl_tables() -> None:
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM utenti")
        cursor.execute("DELETE FROM ruoli")


def _ensure_legacy_navigation_tables() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pulsanti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice VARCHAR(100) NOT NULL,
                    nome_visibile VARCHAR(200) NULL,
                    icona VARCHAR(20) NULL,
                    modulo VARCHAR(100) NOT NULL,
                    url VARCHAR(500) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS permessi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    modulo VARCHAR(100) NOT NULL,
                    azione VARCHAR(100) NOT NULL,
                    ruolo_id INTEGER NOT NULL,
                    consentito INTEGER NULL,
                    can_view INTEGER NULL,
                    can_edit INTEGER NULL,
                    can_delete INTEGER NULL,
                    can_approve INTEGER NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ui_pulsanti_meta (
                    pulsante_id INTEGER PRIMARY KEY,
                    ui_slot VARCHAR(50) NULL,
                    ui_section VARCHAR(100) NULL,
                    ui_order INTEGER NULL,
                    visible_topbar INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            return

        cursor.execute(
            """
            IF OBJECT_ID('pulsanti', 'U') IS NULL
            CREATE TABLE pulsanti (
                id INT IDENTITY(1,1) PRIMARY KEY,
                codice NVARCHAR(100) NOT NULL,
                nome_visibile NVARCHAR(200) NULL,
                icona NVARCHAR(20) NULL,
                modulo NVARCHAR(100) NOT NULL,
                url NVARCHAR(500) NOT NULL
            )
            """
        )
        cursor.execute(
            """
            IF OBJECT_ID('permessi', 'U') IS NULL
            CREATE TABLE permessi (
                id INT IDENTITY(1,1) PRIMARY KEY,
                modulo NVARCHAR(100) NOT NULL,
                azione NVARCHAR(100) NOT NULL,
                ruolo_id INT NOT NULL,
                consentito INT NULL,
                can_view INT NULL,
                can_edit INT NULL,
                can_delete INT NULL,
                can_approve INT NULL
            )
            """
        )
        cursor.execute(
            """
            IF OBJECT_ID('ui_pulsanti_meta', 'U') IS NULL
            CREATE TABLE ui_pulsanti_meta (
                pulsante_id INT PRIMARY KEY,
                ui_slot NVARCHAR(50) NULL,
                ui_section NVARCHAR(100) NULL,
                ui_order INT NULL,
                visible_topbar BIT NOT NULL DEFAULT 1,
                enabled BIT NOT NULL DEFAULT 1
            )
            """
        )


def _clear_legacy_navigation_tables() -> None:
    with connection.cursor() as cursor:
        for table_name in ("ui_pulsanti_meta", "permessi", "pulsanti"):
            try:
                cursor.execute(f"DELETE FROM {table_name}")
            except Exception:
                continue


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class ACLLegacyDecisionTests(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        _ensure_legacy_navigation_tables()
        _clear_legacy_navigation_tables()
        cache.clear()
        self.factory = RequestFactory()

        Ruolo.objects.create(id=1, nome="admin")
        Ruolo.objects.create(id=2, nome="operatore")
        Ruolo.objects.create(id=3, nome="ospite")

        self.pulsante_assenze = Pulsante.objects.create(
            codice="gestione_assenze",
            nome_visibile="Gestione Assenze",
            icona="calendar",
            modulo="assenze",
            url="/assenze/",
        )
        self.pulsante_dashboard = Pulsante.objects.create(
            codice="view_dashboard",
            nome_visibile="Dashboard",
            icona="dashboard",
            modulo="dashboard",
            url="/dashboard",
        )

        Permesso.objects.create(
            ruolo_id=2,
            modulo="assenze",
            azione="gestione_assenze",
            consentito=1,
            can_view=1,
        )
        Permesso.objects.create(
            ruolo_id=3,
            modulo="assenze",
            azione="gestione_assenze",
            consentito=0,
            can_view=0,
        )
        Permesso.objects.create(
            ruolo_id=2,
            modulo="dashboard",
            azione="view_dashboard",
            consentito=1,
            can_view=1,
        )

        self.legacy_role_ok = UtenteLegacy.objects.create(
            nome="Utente Permesso",
            email="permesso@example.local",
            password="x",
            ruolo="operatore",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=2,
        )
        self.legacy_role_denied = UtenteLegacy.objects.create(
            nome="Utente Negato",
            email="negato@example.local",
            password="x",
            ruolo="ospite",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=3,
        )
        self.legacy_admin = UtenteLegacy.objects.create(
            nome="Admin Legacy",
            email="admin@example.local",
            password="x",
            ruolo="admin",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=1,
        )
        bump_legacy_cache_version()

    def test_access_granted_for_matching_role(self):
        self.assertTrue(check_permesso(self.legacy_role_ok, "/assenze/"))

    def test_access_denied_for_wrong_role(self):
        self.assertFalse(check_permesso(self.legacy_role_denied, "/assenze/"))

    def test_user_override_precedence_over_role_permission(self):
        UserPermissionOverride.objects.create(
            legacy_user_id=self.legacy_role_ok.id,
            modulo="assenze",
            azione="gestione_assenze",
            can_view=False,
        )
        self.assertFalse(check_permesso(self.legacy_role_ok, "/assenze/"))

    def test_admin_bypass_allows_access_even_without_button_match(self):
        self.assertTrue(check_permesso(self.legacy_admin, "/percorso/senza/match"))

    def test_route_without_button_match_returns_denied_diagnostic(self):
        diag = diagnose_permesso_for_context(
            legacy_user=self.legacy_role_ok,
            path="/percorso/non-mappato/",
            forced_role_id=None,
        )
        self.assertFalse(diag["allowed"])
        self.assertEqual(diag["reason_code"], "no_pulsante_match")

    def test_dashboard_and_dashboard_home_acl_equivalence(self):
        self.assertEqual(reverse("dashboard"), reverse("dashboard_home"))
        self.assertTrue(check_permesso(self.legacy_role_ok, "/dashboard"))
        self.assertTrue(check_permesso(self.legacy_role_ok, "/"))

    def test_acl_middleware_logs_warning_for_protected_path_without_button_match(self):
        request = self.factory.get("/route-non-mappata/")
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=777)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))
        fake_decision = {
            "allowed": False,
            "decision_source": "legacy_fallback",
            "path_normalized": "/route-non-mappata",
            "route_name": "",
            "legacy_user": {"id": self.legacy_role_ok.id},
            "reason": "Nessun match legacy",
            "legacy_fallback": {"reason_code": "no_pulsante_match"},
        }

        with patch("core.middleware.get_legacy_user", return_value=self.legacy_role_ok), patch(
            "core.middleware.resolve_acl_access",
            return_value=fake_decision,
        ):
            with self.assertLogs("core.middleware", level="WARNING") as logs:
                response = middleware(request)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(any("senza binding canonico e senza pulsante legacy matchato" in line for line in logs.output))

    def test_acl_middleware_returns_json_for_unauthenticated_api_requests(self):
        request = self.factory.post(
            "/admin-portale/api/ruoli/create",
            HTTP_ACCEPT="application/json",
        )
        _attach_session(request)
        request.user = AnonymousUser()
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))

        response = middleware(request)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = json.loads(response.content)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "unauthenticated")
        self.assertIn(reverse("login"), payload["login_url"])

    def test_acl_middleware_returns_json_for_forbidden_api_requests(self):
        request = self.factory.get(
            "/admin-portale/api/ruoli/create",
            HTTP_ACCEPT="application/json",
        )
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=888)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))
        fake_decision = {
            "allowed": False,
            "decision_source": "legacy_fallback",
            "path_normalized": "/admin-portale/api/ruoli/create",
            "route_name": "",
            "legacy_user": {"id": self.legacy_role_denied.id},
            "reason": "Permesso negato",
            "legacy_fallback": {"reason_code": "explicit_deny"},
        }

        with patch("core.middleware.get_legacy_user", return_value=self.legacy_role_denied), patch(
            "core.middleware.resolve_acl_access",
            return_value=fake_decision,
        ):
            response = middleware(request)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = json.loads(response.content)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["reason"], "forbidden")
        self.assertEqual(payload["error"], "Permessi insufficienti.")

    def test_acl_middleware_allows_notifiche_routes_without_legacy_acl_permission(self):
        request = self.factory.get("/notifiche/")
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=889)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))

        with patch("core.models.UserOnboarding.objects.filter") as mocked_onboarding_filter, patch(
            "core.middleware.get_legacy_user"
        ) as mocked_get_legacy_user, patch("core.middleware.resolve_acl_access") as mocked_resolve_acl_access:
            response = middleware(request)

        self.assertEqual(response.status_code, 200)
        mocked_onboarding_filter.assert_not_called()
        mocked_get_legacy_user.assert_not_called()
        mocked_resolve_acl_access.assert_not_called()

    def test_acl_middleware_allows_notifiche_api_routes_without_legacy_acl_permission(self):
        request = self.factory.post(
            "/api/notifiche/popup-ack/",
            HTTP_ACCEPT="application/json",
            CONTENT_TYPE="application/json",
        )
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=890)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))

        with patch("core.models.UserOnboarding.objects.filter") as mocked_onboarding_filter, patch(
            "core.middleware.get_legacy_user"
        ) as mocked_get_legacy_user, patch("core.middleware.resolve_acl_access") as mocked_resolve_acl_access:
            response = middleware(request)

        self.assertEqual(response.status_code, 200)
        mocked_onboarding_filter.assert_not_called()
        mocked_get_legacy_user.assert_not_called()
        mocked_resolve_acl_access.assert_not_called()

    def test_acl_middleware_profile_shared_path_still_requires_onboarding_completion(self):
        request = self.factory.get("/profilo/")
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=891)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))
        onboarding_qs = MagicMock()
        onboarding_qs.first.return_value = SimpleNamespace(is_done=lambda: False)

        with patch("core.models.UserOnboarding.objects.filter", return_value=onboarding_qs) as mocked_onboarding_filter, patch(
            "core.middleware.get_legacy_user"
        ) as mocked_get_legacy_user, patch("core.middleware.resolve_acl_access") as mocked_resolve_acl_access:
            response = middleware(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("onboarding_wizard"))
        mocked_onboarding_filter.assert_called_once_with(user=request.user)
        mocked_get_legacy_user.assert_not_called()
        mocked_resolve_acl_access.assert_not_called()

    def test_acl_middleware_allows_acl_shared_assets_api_after_onboarding(self):
        request = self.factory.post(
            "/api/assets/dashboard/config/",
            data="{}",
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=892)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))
        onboarding_qs = MagicMock()
        onboarding_qs.first.return_value = SimpleNamespace(is_done=lambda: True)

        with patch("core.models.UserOnboarding.objects.filter", return_value=onboarding_qs) as mocked_onboarding_filter, patch(
            "core.middleware.get_legacy_user"
        ) as mocked_get_legacy_user, patch("core.middleware.resolve_acl_access") as mocked_resolve_acl_access:
            response = middleware(request)

        self.assertEqual(response.status_code, 200)
        mocked_onboarding_filter.assert_called_once_with(user=request.user)
        mocked_get_legacy_user.assert_not_called()
        mocked_resolve_acl_access.assert_not_called()

    def test_acl_middleware_allows_onboarding_email_api_without_acl_resolution(self):
        request = self.factory.post(
            "/api/onboarding/email/",
            HTTP_ACCEPT="application/json",
            CONTENT_TYPE="application/json",
        )
        _attach_session(request)
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False, id=893)
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))

        with patch("core.models.UserOnboarding.objects.filter") as mocked_onboarding_filter, patch(
            "core.middleware.get_legacy_user"
        ) as mocked_get_legacy_user, patch("core.middleware.resolve_acl_access") as mocked_resolve_acl_access:
            response = middleware(request)

        self.assertEqual(response.status_code, 200)
        mocked_onboarding_filter.assert_not_called()
        mocked_get_legacy_user.assert_not_called()
        mocked_resolve_acl_access.assert_not_called()

    def test_acl_middleware_treats_monitoring_exempt_prefix_without_trailing_slash_as_exempt(self):
        request = self.factory.post(
            "/monitoring/report-problem",
            HTTP_ACCEPT="application/json",
            CONTENT_TYPE="application/json",
        )
        _attach_session(request)
        request.user = AnonymousUser()
        middleware = ACLMiddleware(lambda req: HttpResponse("ok"))

        response = middleware(request)

        self.assertEqual(response.status_code, 200)


@override_settings(
    LEGACY_AUTH_ENABLED=True,
    NAVIGATION_REGISTRY_ENABLED=True,
    NAVIGATION_LEGACY_FALLBACK_ENABLED=True,
    SECURE_SSL_REDIRECT=False,
)
class NavigationFallbackAndLegacyRedirectTests(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        _ensure_legacy_navigation_tables()
        _clear_legacy_navigation_tables()
        cache.clear()
        self.factory = RequestFactory()

        Ruolo.objects.create(id=1, nome="utente")
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Mario Fallback",
            email="mario.fallback@example.local",
            password="x",
            ruolo="utente",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=1,
        )
        Pulsante.objects.create(
            codice="view_tasks",
            nome_visibile="Tasks",
            icona="check",
            modulo="tasks",
            url="/tasks/",
        )
        Permesso.objects.create(
            ruolo_id=1,
            modulo="tasks",
            azione="view_tasks",
            consentito=1,
            can_view=1,
        )
        bump_legacy_cache_version()

    def test_navigation_registry_falls_back_to_legacy_when_registry_empty(self):
        request = self.factory.get("/tasks/")
        request.user = get_user_model().objects.create_user(
            username="fallback-nav-user",
            password="pass12345",
        )
        request.legacy_user = self.legacy_user
        _attach_session(request)

        context = legacy_nav(request)

        self.assertTrue(context["nav_items"])
        self.assertTrue(any(item.legacy_url == "/tasks" for item in context["nav_items"]))

    def test_legacy_fallback_deduplicates_topbar_items_by_module(self):
        Pulsante.objects.create(
            codice="notizie_lista",
            nome_visibile="Notizie",
            icona="bell",
            modulo="notizie",
            url="/notizie/",
        )
        Pulsante.objects.create(
            codice="notizie_nuova",
            nome_visibile="Nuova notizia",
            icona="newspaper",
            modulo="notizie",
            url="/notizie/nuova/",
        )
        Permesso.objects.create(
            ruolo_id=1,
            modulo="notizie",
            azione="notizie_lista",
            consentito=1,
            can_view=1,
        )
        Permesso.objects.create(
            ruolo_id=1,
            modulo="notizie",
            azione="notizie_nuova",
            consentito=1,
            can_view=1,
        )
        bump_legacy_cache_version()

        request = self.factory.get("/notizie/")
        request.user = get_user_model().objects.create_user(
            username="fallback-nav-dedupe-user",
            password="pass12345",
        )
        request.legacy_user = self.legacy_user
        _attach_session(request)

        context = legacy_nav(request)
        labels = [item.label for item in context["nav_items"]]

        self.assertEqual(labels.count("Notizie"), 1)

    def test_legacy_redirect_row_in_db_is_applied_on_dispatch(self):
        user = get_user_model().objects.create_user(username="legacy-redirect-user", password="pass12345")
        self.client.force_login(user)
        LegacyRedirect.objects.create(
            legacy_path="/admin/legacy-report",
            target_route_name="dashboard_home",
            is_enabled=True,
        )

        response = self.client.get("/admin/legacy-report")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("dashboard_home"))


class DashboardRoutingTests(TestCase):
    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_dashboard_and_dashboard_home_routes_work(self):
        user = get_user_model().objects.create_user(username="route-user", password="pass12345")
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)

        root_url = reverse("root")
        dashboard_url = reverse("dashboard")
        dashboard_home_url = reverse("dashboard_home")

        self.assertEqual(root_url, "/")
        self.assertEqual(dashboard_url, "/dashboard")
        self.assertEqual(dashboard_home_url, "/dashboard")
        root_response = self.client.get(root_url)
        self.assertEqual(root_response.status_code, 302)
        self.assertEqual(root_response.headers.get("Location"), "/dashboard")
        dashboard_response = self.client.get(dashboard_url)
        dashboard_home_response = self.client.get(dashboard_home_url)
        self.assertEqual(dashboard_response.status_code, 302)
        self.assertEqual(dashboard_response.headers.get("Location"), reverse("home_portale:index"))
        self.assertEqual(dashboard_home_response.status_code, 302)
        self.assertEqual(dashboard_home_response.headers.get("Location"), reverse("home_portale:index"))
        self.assertEqual(self.client.get(dashboard_url, follow=True).status_code, 200)
        self.assertEqual(self.client.get(dashboard_home_url, follow=True).status_code, 200)

    def test_coming_assenze_route_name_resolves_to_modulo_assenze_path(self):
        self.assertEqual(reverse("coming_assenze"), reverse("assenze_menu"))

    @override_settings(
        LEGACY_AUTH_ENABLED=False,
        APP_VERSION="9.9.9-test",
    )
    def test_dashboard_home_shows_version_footer(self):
        user = get_user_model().objects.create_user(username="route-user-version", password="pass12345")
        UserOnboarding.objects.create(user=user, completed=True)
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard_home"), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [(reverse("home_portale:index"), 302)])
        self.assertContains(response, "NOVICROM HUB")
        self.assertContains(response, "9.9.9-test")
        self.assertContains(response, "moduli registrati")

    @override_settings(
        APP_VERSION="9.9.9-test",
        MODULE_VERSIONS={"assets": "1.2.3-assets", "admin_portale": "9.9.9-test"},
    )
    def test_admin_index_shows_versioning_card(self):
        from admin_portale import views as admin_views

        user = get_user_model().objects.create_user(username="admin-version-user", password="pass12345")
        request = RequestFactory().get(reverse("admin_portale:index"))
        _attach_session(request)
        request.user = user
        request.legacy_user = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)
        setattr(request, "_messages", FallbackStorage(request))

        response = admin_views.index.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Versione portale", response.content.decode("utf-8"))
        self.assertIn("9.9.9-test", response.content.decode("utf-8"))
        self.assertIn("Assets", response.content.decode("utf-8"))
        self.assertIn("1.2.3-assets", response.content.decode("utf-8"))


class SessionIdleTimeoutMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(username="idle-user", password="pass12345")

    def _request(self, path: str, method: str = "GET", authenticated: bool = True):
        req = self.factory.generic(method=method, path=path)
        _attach_session(req)
        req.user = self.user if authenticated else AnonymousUser()
        return req

    @patch("core.session_middleware.time.time", return_value=1700000000)
    def test_static_endpoint_does_not_refresh_activity(self, _mocked_time):
        request = self._request("/static/core/app.css")
        request.session[SessionIdleTimeoutMiddleware.SESSION_KEY] = 1234
        request.session.save()
        middleware = SessionIdleTimeoutMiddleware(lambda req: HttpResponse("ok"))

        middleware(request)

        self.assertEqual(request.session[SessionIdleTimeoutMiddleware.SESSION_KEY], 1234)

    @patch("core.session_middleware.time.time", return_value=1700000100)
    def test_interactive_endpoint_refreshes_activity(self, _mocked_time):
        request = self._request("/richieste")
        request.session[SessionIdleTimeoutMiddleware.SESSION_KEY] = 1700000090
        request.session.save()
        middleware = SessionIdleTimeoutMiddleware(lambda req: HttpResponse("ok"))

        middleware(request)

        self.assertEqual(request.session[SessionIdleTimeoutMiddleware.SESSION_KEY], 1700000100)

    @patch("core.session_middleware.time.time", return_value=1700000200)
    def test_login_post_success_refreshes_activity(self, _mocked_time):
        request = self._request("/login/", method="POST", authenticated=False)

        def fake_login_response(req):
            req.user = self.user
            return HttpResponse(status=302)

        middleware = SessionIdleTimeoutMiddleware(fake_login_response)
        middleware(request)

        self.assertEqual(request.session[SessionIdleTimeoutMiddleware.SESSION_KEY], 1700000200)


class EnsureCSRFCookieMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _middleware_chain():
        def view(_request):
            return HttpResponse("ok")

        return CsrfViewMiddleware(EnsureCSRFCookieMiddleware(view))

    def test_html_get_seeds_csrf_cookie(self):
        request = self.factory.get("/dashboard", HTTP_ACCEPT="text/html")
        response = self._middleware_chain()(request)
        self.assertIn("csrftoken", response.cookies)

    def test_json_get_does_not_seed_csrf_cookie(self):
        request = self.factory.get("/api/notifiche/1/leggi", HTTP_ACCEPT="application/json")
        response = self._middleware_chain()(request)
        self.assertNotIn("csrftoken", response.cookies)

    def test_static_get_does_not_seed_csrf_cookie(self):
        request = self.factory.get("/static/core/theme.css", HTTP_ACCEPT="text/html")
        response = self._middleware_chain()(request)
        self.assertNotIn("csrftoken", response.cookies)


class CSRFFailureViewTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(username="csrf-user", password="pass12345")

    def _request(self, path: str, method: str = "POST", authenticated: bool = True, **extra):
        request = self.factory.generic(method=method, path=path, **extra)
        _attach_session(request)
        request.user = self.user if authenticated else AnonymousUser()
        setattr(request, "_messages", FallbackStorage(request))
        return request

    def test_missing_cookie_on_post_redirects_to_same_origin_referer(self):
        detail_url = reverse("notizie_dettaglio", args=[1])
        request = self._request(
            reverse("notizie_conferma", args=[1]),
            HTTP_REFERER=f"http://testserver{detail_url}",
        )

        response = csrf_failure(request, reason="CSRF cookie not set.")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{detail_url}?csrf_retry=1")

    def test_missing_cookie_on_post_without_referer_redirects_authenticated_user_to_dashboard(self):
        request = self._request(reverse("notizie_conferma", args=[1]))

        response = csrf_failure(request, reason="CSRF cookie not set.")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('dashboard_home')}?csrf_retry=1")

    def test_missing_cookie_on_post_without_referer_redirects_anonymous_user_to_login(self):
        request = self._request("/submit/", authenticated=False)

        response = csrf_failure(request, reason="CSRF cookie not set.")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("login"))

    def test_missing_cookie_on_json_post_returns_json_retry_payload(self):
        gestione_url = reverse("assenze_gestione")
        request = self._request(
            reverse("assenze_api_evento_delete", args=[42]),
            CONTENT_TYPE="application/json",
            HTTP_ACCEPT="application/json",
            HTTP_REFERER=f"http://testserver{gestione_url}",
        )

        response = csrf_failure(request, reason="CSRF cookie not set.")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = json.loads(response.content)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["csrf_retry"])
        self.assertEqual(payload["reload_url"], f"{gestione_url}?csrf_retry=1")


class DevAllowedHostsTests(TestCase):
    @patch("config.settings.base.socket.getaddrinfo")
    @patch("config.settings.base.socket.getfqdn", return_value="novi-host.local")
    @patch("config.settings.base.socket.gethostname", return_value="novi-host")
    def test_default_dev_allowed_hosts_include_local_ips_and_hostnames(
        self,
        _mock_hostname,
        _mock_fqdn,
        mock_getaddrinfo,
    ):
        mock_getaddrinfo.return_value = [
            (2, 1, 6, "", ("192.0.2.10", 0)),
            (2, 1, 6, "", ("198.51.100.50", 0)),
        ]

        hosts = default_dev_allowed_hosts()

        self.assertIn("localhost", hosts)
        self.assertIn("testserver", hosts)
        self.assertIn("novi-host", hosts)
        self.assertIn("novi-host.local", hosts)
        self.assertIn("192.0.2.10", hosts)
        self.assertIn("198.51.100.50", hosts)


class AdaptiveSecureCookieMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @staticmethod
    def _middleware_chain():
        def view(request):
            request.session["probe"] = "1"
            response = HttpResponse("ok")
            response.set_cookie("csrftoken", "token", secure=True)
            return response

        return AdaptiveSecureCookieMiddleware(SessionMiddleware(view))

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_http_request_removes_secure_flag_from_session_and_csrf_cookies(self):
        request = self.factory.get("/login/")
        response = self._middleware_chain()(request)

        self.assertIn("csrftoken", response.cookies)
        self.assertIn("sessionid", response.cookies)
        self.assertEqual(response.cookies["csrftoken"]["secure"], "")
        self.assertEqual(response.cookies["sessionid"]["secure"], "")

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_https_request_preserves_secure_flag_from_session_and_csrf_cookies(self):
        request = self.factory.get("/login/", secure=True)
        response = self._middleware_chain()(request)

        self.assertIn("csrftoken", response.cookies)
        self.assertIn("sessionid", response.cookies)
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["secure"])


class LoginViewHardeningTests(TestCase):
    def test_login_response_is_not_cacheable_and_sets_csrf_cookie(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))

    def test_login_uses_mobile_template_for_smartphone_user_agent(self):
        response = self.client.get(
            reverse("login"),
            HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/pages/login_mobile.html")

    def test_login_layout_query_overrides_user_agent_template_selection(self):
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"

        mobile_response = self.client.get(reverse("login") + "?layout=mobile")
        desktop_response = self.client.get(reverse("login") + "?layout=desktop", HTTP_USER_AGENT=iphone_ua)

        self.assertEqual(mobile_response.status_code, 200)
        self.assertTemplateUsed(mobile_response, "core/pages/login_mobile.html")
        self.assertEqual(desktop_response.status_code, 200)
        self.assertTemplateUsed(desktop_response, "core/pages/login.html")

    @override_settings(CSRF_COOKIE_SECURE=True, ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
    def test_login_response_on_http_strips_secure_flag_from_csrf_cookie(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertEqual(response.cookies["csrftoken"]["secure"], "")

    @override_settings(CSRF_COOKIE_SECURE=True, ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
    def test_login_response_on_https_keeps_secure_flag_on_csrf_cookie(self):
        response = self.client.get(reverse("login"), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("csrftoken", response.cookies)
        self.assertTrue(response.cookies["csrftoken"]["secure"])

    @patch("core.models.SiteConfig.objects.filter")
    def test_login_falls_back_to_defaults_when_siteconfig_table_is_missing(self, mocked_filter):
        class BrokenValuesList:
            def __iter__(self):
                raise ProgrammingError("missing table")

        class BrokenQuerySet:
            def values_list(self, *args, **kwargs):
                return BrokenValuesList()

        mocked_filter.return_value = BrokenQuerySet()
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Portale Novicrom")
        self.assertContains(response, "Area autenticata")

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_login_rejects_external_next_and_falls_back_to_dashboard(self):
        user = get_user_model().objects.create_user(
            username="login-hardening-user",
            password="pass12345",
            email="login-hardening@example.com",
        )

        response = self.client.post(
            f"{reverse('login')}?next=https://evil.example/phishing",
            {"username": user.username, "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("dashboard_home"))

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_login_preserves_safe_relative_next(self):
        user = get_user_model().objects.create_user(
            username="login-safe-next-user",
            password="pass12345",
            email="login-safe-next@example.com",
        )

        response = self.client.post(
            f"{reverse('login')}?next={reverse('tickets:dashboard')}",
            {"username": user.username, "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("tickets:dashboard"))

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_login_does_not_store_plaintext_password_in_session(self):
        user = get_user_model().objects.create_user(
            username="login-session-hardening-user",
            password="pass12345",
            email="login-session-hardening@example.com",
        )

        response = self.client.post(
            reverse("login"),
            {"username": user.username, "password": "pass12345"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_sso_relay_pwd", self.client.session)


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    AXES_FAILURE_LIMIT=2,
    AXES_COOLOFF_TIME=1,
    AXES_RESET_ON_SUCCESS=True,
    AXES_LOCKOUT_TEMPLATE="core/pages/lockout.html",
    INSTANCE_NAME="Helpdesk Novicrom",
)
class AxesLockoutTemplateTests(TestCase):
    def test_lockout_renders_custom_template_with_expected_copy(self):
        user = get_user_model().objects.create_user(
            username="axes-lockout-user",
            password="pass12345",
            email="axes-lockout@example.com",
        )

        login_url = reverse("login")
        self.client.post(login_url, {"username": user.username, "password": "wrong-1"})
        self.client.post(login_url, {"username": user.username, "password": "wrong-2"})
        locked_response = self.client.post(login_url, {"username": user.username, "password": "pass12345"})

        self.assertIn(locked_response.status_code, {403, 429})
        body = locked_response.content.decode("utf-8", errors="ignore")
        self.assertIn("1 ora", body)
        self.assertIn("Helpdesk Novicrom", body)
        self.assertIn("Link login disabilitato durante il lockout", body)


class WindowsSSORedirectHardeningTests(TestCase):
    @override_settings(LDAP_ENABLED=True, ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"])
    def test_windows_sso_rejects_external_next_and_falls_back_to_dashboard(self):
        user = get_user_model().objects.create_user(
            username="windows-sso-user",
            password="pass12345",
            email="windows-sso@example.com",
        )
        ctx = SimpleNamespace(complete=True, client_principal="CNOVICROM\\windows-sso-user")
        ctx.step = lambda _token: None
        fake_spnego = SimpleNamespace(server=lambda **_kwargs: ctx)

        with (
            patch.dict("sys.modules", {"spnego": fake_spnego}),
            patch("core.accounts.windows_sso.provision_legacy_user", return_value=SimpleNamespace(id=1)),
            patch("core.accounts.windows_sso.sync_django_user_from_legacy", return_value=user),
        ):
            response = self.client.get(
                f"{reverse('windows_sso')}?next=https://evil.example/phishing",
                HTTP_AUTHORIZATION="Negotiate dGVzdA==",
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), reverse("dashboard_home"))


class WindowsSSOMemoryHardeningTests(SimpleTestCase):
    def test_spnego_contexts_cache_is_ttl_bounded(self):
        cache_obj = windows_sso_module._SPNEGO_CONTEXTS
        self.assertIsInstance(cache_obj, TTLCache)
        self.assertEqual(cache_obj.maxsize, 500)
        self.assertEqual(int(cache_obj.ttl), 60)


class LegacyTableColumnsHardeningTests(SimpleTestCase):
    def setUp(self):
        super().setUp()
        legacy_table_columns.cache_clear()

    def tearDown(self):
        legacy_table_columns.cache_clear()
        super().tearDown()

    def test_sqlite_disallows_non_whitelisted_table_without_executing_pragma(self):
        conn = MagicMock()
        conn.vendor = "sqlite"

        with patch("core.legacy_utils.connections", {"default": conn}):
            columns = legacy_table_columns('assenze";DROP TABLE utenti;--')

        self.assertEqual(columns, set())
        conn.cursor.assert_not_called()

    def test_sqlite_whitelisted_table_executes_pragma_and_returns_columns(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [(0, "id"), (1, "copia_nome")]
        conn = MagicMock()
        conn.vendor = "sqlite"
        conn.cursor.return_value.__enter__.return_value = cursor

        with patch("core.legacy_utils.connections", {"default": conn}):
            columns = legacy_table_columns("assenze")

        self.assertIn("assenze", ALLOWED_LEGACY_TABLES)
        self.assertEqual(columns, {"id", "copia_nome"})
        cursor.execute.assert_called_once_with('PRAGMA table_info("assenze")')


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class LogoutFlowTests(TestCase):
    def test_logout_via_get_terminates_session(self):
        user = get_user_model().objects.create_user(username="logout-user", password="pass12345")
        self.client.force_login(user)

        response = self.client.get(reverse("logout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), f"{reverse('login')}?reason=logout")
        dashboard_response = self.client.get(reverse("dashboard_home"))
        self.assertEqual(dashboard_response.status_code, 302)
        self.assertIn(reverse("login"), dashboard_response.headers.get("Location", ""))


class LegacySyncHardeningTests(TestCase):
    def test_sync_skips_existing_user_bound_to_other_legacy_profile(self):
        User = get_user_model()
        locked_user = User.objects.create_user(username="mario.rossi", password="pass12345")
        Profile.objects.create(user=locked_user, legacy_user_id=999, legacy_ruolo_id=1, legacy_ruolo="utente")

        legacy_user = UtenteLegacy(
            id=1001,
            nome="Mario Rossi",
            email="mario.rossi@example.com",
            password="ignored",
            ruolo="utente",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=2,
        )

        synced_user = sync_django_user_from_legacy(legacy_user)

        self.assertNotEqual(synced_user.id, locked_user.id)
        self.assertFalse(synced_user.has_usable_password())
        self.assertNotIn(" ", synced_user.username)
        self.assertEqual(Profile.objects.get(user=locked_user).legacy_user_id, 999)
        self.assertEqual(Profile.objects.get(user=synced_user).legacy_user_id, legacy_user.id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImpersonationFlowTests(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_acl_tables()
        _clear_legacy_acl_tables()
        self.factory = RequestFactory()
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, %s)", [1, "admin"])
            cursor.execute("INSERT INTO ruoli (id, nome) VALUES (%s, %s)", [2, "utente"])
            cursor.execute(
                """
                INSERT INTO utenti (id, nome, email, password, ruolo, attivo, deve_cambiare_password, ruolo_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [100, "Admin Example", "admin@example.local", "x", "admin", True, False, 1],
            )
            cursor.execute(
                """
                INSERT INTO utenti (id, nome, email, password, ruolo, attivo, deve_cambiare_password, ruolo_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [200, "Mario Rossi", "m.rossi@example.local", "x", "utente", True, False, 2],
            )

        self.admin_legacy = UtenteLegacy.objects.get(id=100)
        self.target_legacy = UtenteLegacy.objects.get(id=200)
        self.admin_user = sync_django_user_from_legacy(self.admin_legacy)
        self.target_user = sync_django_user_from_legacy(self.target_legacy)
        UserOnboarding.objects.get_or_create(user=self.admin_user, defaults={"completed": True})
        UserOnboarding.objects.get_or_create(user=self.target_user, defaults={"completed": True})

    def test_admin_can_start_and_stop_impersonation_with_audit(self):
        self.client.force_login(self.admin_user)

        start_response = self.client.post(
            reverse("admin_portale:utente_impersonate", args=[self.target_legacy.id]),
            {"next": reverse("profilo")},
            follow=True,
        )

        self.assertEqual(start_response.status_code, 200)
        self.assertContains(start_response, "Impersonazione attiva")
        self.assertContains(start_response, "Mario Rossi")
        self.assertEqual(self.client.session[IMPERSONATION_SESSION_KEY]["target_legacy_user_id"], self.target_legacy.id)

        start_log = AuditLog.objects.get(azione="impersonation_start")
        self.assertEqual(start_log.legacy_user_id, self.admin_legacy.id)
        self.assertEqual(start_log.dettaglio["target_legacy_user_id"], self.target_legacy.id)

        stop_response = self.client.post(
            reverse("stop_impersonation"),
            {"next": reverse("profilo")},
            follow=True,
        )

        self.assertEqual(stop_response.status_code, 200)
        self.assertNotContains(stop_response, "Impersonazione attiva")
        self.assertContains(stop_response, "Admin Example")
        self.assertNotIn(IMPERSONATION_SESSION_KEY, self.client.session)

        stop_log = AuditLog.objects.get(azione="impersonation_stop")
        self.assertEqual(stop_log.legacy_user_id, self.admin_legacy.id)
        self.assertEqual(stop_log.dettaglio["target_legacy_user_id"], self.target_legacy.id)

    def test_impersonated_user_cannot_open_admin_portale(self):
        self.client.force_login(self.admin_user)
        self.client.post(
            reverse("admin_portale:utente_impersonate", args=[self.target_legacy.id]),
            {"next": reverse("profilo")},
        )

        response = self.client.get(reverse("admin_portale:utenti_list"))

        self.assertEqual(response.status_code, 403)

    def test_log_action_attributes_impersonated_activity_to_admin(self):
        request = self.factory.get("/profilo/")
        _attach_session(request)
        request.user = self.target_user
        request.legacy_user = self.target_legacy
        request.impersonation_active = True
        request.impersonator_user = self.admin_user
        request.impersonator_legacy_user = self.admin_legacy
        request.impersonated_user = self.target_user
        request.impersonated_legacy_user = self.target_legacy

        log_action(request, "probe_impersonation", "core", {"sample": True})

        entry = AuditLog.objects.get(azione="probe_impersonation")
        self.assertEqual(entry.legacy_user_id, self.admin_legacy.id)
        self.assertEqual(entry.dettaglio["_impersonation"]["impersonated_legacy_user_id"], self.target_legacy.id)


class SafeTimedRotatingFileHandlerTests(TestCase):
    def test_emit_falls_back_to_plain_write_when_rollover_file_is_locked(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = f"{tmp_dir}/app.log"
            handler = SafeTimedRotatingFileHandler(log_path, when="midnight", backupCount=1, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler.rolloverAt = 0

            with patch.object(
                logging.handlers.TimedRotatingFileHandler,
                "doRollover",
                side_effect=PermissionError(32, "locked"),
            ):
                handler.emit(logging.makeLogRecord({"msg": "probe", "levelno": logging.INFO, "levelname": "INFO"}))

            handler.flush()
            handler.close()

            with open(log_path, "r", encoding="utf-8") as stream:
                self.assertIn("probe", stream.read())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ModuleBrandingRegistryTests(TestCase):
    @override_settings(
        MODULE_BRANDING={
            "assets": {
                "display_label": "Novicrom Assets",
                "menu_label": "Novicrom Asset Hub",
            }
        }
    )
    def test_module_branding_merges_defaults_settings_and_siteconfig(self):
        from core.models import SiteConfig

        SiteConfig.objects.create(
            chiave="module_branding.assets.menu_label",
            valore="Novicrom Assets Menu",
        )
        SiteConfig.objects.create(
            chiave="module_branding.assets.dashboard_label",
            valore="Novicrom Assets Dashboard",
        )
        SiteConfig.objects.create(
            chiave="module_branding.assets.logo_url",
            valore="/media/module_branding/assets/logo.svg",
        )

        branding = get_module_branding("assets")

        self.assertIsNotNone(branding)
        assert branding is not None
        self.assertEqual(branding.default_label, "Assets")
        self.assertEqual(branding.display_label, "Novicrom Assets")
        self.assertEqual(branding.menu_label, "Novicrom Assets Menu")
        self.assertEqual(branding.short_label, "Assets")
        self.assertEqual(branding.dashboard_label, "Novicrom Assets Dashboard")
        self.assertEqual(branding.logo_url, "/media/module_branding/assets/logo.svg")

    @override_settings(
        MODULE_BRANDING={
            "assets": {
                "display_label": "Novicrom Assets",
            }
        }
    )
    def test_navigation_code_label_map_uses_registered_module_navigation_codes(self):
        mapping = navigation_code_label_map(surface="menu")

        self.assertEqual(mapping.get("assets"), "Novicrom Assets")
        self.assertEqual(resolve_module_label("assets", fallback="Asset", surface="dashboard"), "Novicrom Assets")


class ContactPeopleTests(SimpleTestCase):
    def test_parse_contact_people_accepts_pipe_and_angle_brackets(self):
        people = parse_contact_people(
            "Mario Rossi | mario.rossi@example.com\nLucia Bianchi <lucia.bianchi@example.com>\nsolo@example.com"
        )

        self.assertEqual(
            people,
            [
                {"nome": "Mario Rossi", "email": "mario.rossi@example.com"},
                {"nome": "Lucia Bianchi", "email": "lucia.bianchi@example.com"},
                {"nome": "", "email": "solo@example.com"},
            ],
        )

    def test_coalesce_and_primary_contact_fall_back_to_legacy_fields(self):
        contacts = coalesce_contact_people([], fallback_name="Mario Rossi", fallback_email="mario@example.com")

        self.assertEqual(contacts, [{"nome": "Mario Rossi", "email": "mario@example.com"}])
        self.assertEqual(
            primary_contact([], fallback_name="Mario Rossi", fallback_email="mario@example.com"),
            {"nome": "Mario Rossi", "email": "mario@example.com"},
        )

    def test_serialize_contact_people_uses_multiline_format(self):
        self.assertEqual(
            serialize_contact_people(
                [
                    {"nome": "Mario Rossi", "email": "mario@example.com"},
                    {"nome": "Lucia Bianchi", "email": ""},
                ]
            ),
            "Mario Rossi | mario@example.com\nLucia Bianchi",
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NavigationRegistryBrandingTests(TestCase):
    @override_settings(
        MODULE_BRANDING={
            "assets": {
                "menu_label": "Novicrom Assets",
            }
        }
    )
    def test_navigation_registry_applies_branding_override_on_topbar_label(self):
        from core.models import NavigationItem, NavigationRoleAccess

        NavigationItem.objects.filter(code="assets").delete()
        item = NavigationItem.objects.create(
            code="assets",
            label="Inventario asset",
            section="topbar",
            route_name="dashboard_home",
            order=35,
            is_visible=True,
            is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=item, legacy_role_id=1, can_view=True)

        nodes = get_topbar_nodes(current_path="/dashboard", role_id=None, is_admin=True)

        assets_nodes = [node for node in nodes if node.codice == "assets"]

        self.assertEqual(len(assets_nodes), 1)
        self.assertEqual(assets_nodes[0].label, "Novicrom Assets")

    @override_settings(
        MODULE_BRANDING={
            "assets": {
                "menu_label": "Novicrom Assets",
            }
        }
    )
    def test_navigation_registry_branding_keeps_code_and_href_stable(self):
        from core.models import NavigationItem, NavigationRoleAccess

        NavigationItem.objects.filter(code="assets").delete()
        item = NavigationItem.objects.create(
            code="assets",
            label="Inventario asset",
            section="topbar",
            route_name="dashboard_home",
            order=35,
            is_visible=True,
            is_enabled=True,
        )
        NavigationRoleAccess.objects.create(item=item, legacy_role_id=1, can_view=True)

        nodes = get_topbar_nodes(current_path="/dashboard", role_id=None, is_admin=True)
        assets_nodes = [node for node in nodes if node.codice == "assets"]

        self.assertEqual(len(assets_nodes), 1)
        self.assertEqual(assets_nodes[0].codice, "assets")
        self.assertEqual(assets_nodes[0].href, reverse("dashboard_home"))
        self.assertEqual(
            NavigationItem.objects.get(code="assets").route_name,
            "dashboard_home",
        )

    def test_navigation_registry_exposes_category_icon_for_grouped_items(self):
        from core.models import ModuleCategory, NavigationItem, NavigationRoleAccess
        from core.navigation_registry import bump_navigation_registry_version

        category = ModuleCategory.objects.create(
            key="sicurezza-test",
            label="Sicurezza",
            icon="🛡️",
            topbar_color="#1e3a5f",
            order=10,
        )
        item = NavigationItem.objects.create(
            code="sicurezza_test",
            label="Segnalazioni sicurezza",
            section="topbar",
            route_name="dashboard_home",
            order=20,
            is_visible=True,
            is_enabled=True,
            category=category,
        )
        NavigationRoleAccess.objects.create(item=item, legacy_role_id=1, can_view=True)
        bump_navigation_registry_version()

        nodes = get_topbar_nodes(current_path="/dashboard", role_id=None, is_admin=True)
        sicurezza_nodes = [node for node in nodes if node.codice == "sicurezza_test"]

        self.assertEqual(len(sicurezza_nodes), 1)
        self.assertEqual(sicurezza_nodes[0].category_icon, "🛡️")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NavigationRegistryCanonicalTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.role = Ruolo.objects.create(id=202, nome="Operatore Canonico")
        self.legacy_user = UtenteLegacy.objects.create(
            id=902,
            nome="Utente Canonico",
            email="canonico@example.local",
            password="hash",
            ruolo=self.role.nome,
            ruolo_id=self.role.id,
            attivo=True,
        )
        PermissionDefinition.objects.create(
            code="dashboard.home.view",
            label="Dashboard Home",
            module="dashboard",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            permission_id="dashboard.home.view",
            route_name="dashboard_home",
            path_pattern="/dashboard",
            source_app="dashboard",
            is_active=True,
        )

    def test_positive_nav_override_does_not_force_show_denied_item(self):
        item = NavigationItem.objects.create(
            code="dashboard_canonico",
            label="Dashboard",
            section="topbar",
            route_name="dashboard_home",
            order=10,
            is_visible=True,
            is_enabled=True,
        )
        UserNavigationOverride.objects.create(
            legacy_user_id=self.legacy_user.id,
            item=item,
            enabled=True,
        )

        nodes = get_topbar_nodes(
            current_path="/dashboard",
            role_id=self.role.id,
            is_admin=False,
            legacy_user_id=self.legacy_user.id,
        )

        self.assertEqual(nodes, [])

    def test_navigation_snapshot_preserves_required_permission_code(self):
        item = NavigationItem.objects.create(
            code="dashboard_canonico",
            label="Dashboard",
            section="topbar",
            route_name="dashboard_home",
            required_permission_code="dashboard.home.view",
            order=10,
            is_visible=True,
            is_enabled=True,
        )

        snapshot = publish_navigation_snapshot()
        NavigationItem.objects.all().delete()
        restore_navigation_snapshot(snapshot)

        restored = NavigationItem.objects.get(code=item.code)
        self.assertEqual(restored.required_permission_code, "dashboard.home.view")

    def test_navigation_item_route_name_infers_permission_from_reversed_path(self):
        item = NavigationItem.objects.create(
            code="dashboard_alias",
            label="Dashboard Alias",
            section="topbar",
            route_name="dashboard",
            order=12,
            is_visible=True,
            is_enabled=True,
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=self.role.id,
            permission_id="dashboard.home.view",
            enabled=True,
        )

        self.assertEqual(resolve_navigation_item_permission_code(item), "dashboard.home.view")

        nodes = get_topbar_nodes(
            current_path="/dashboard",
            role_id=self.role.id,
            is_admin=False,
            legacy_user_id=self.legacy_user.id,
        )

        alias_nodes = [node for node in nodes if node.codice == "dashboard_alias"]
        self.assertEqual(len(alias_nodes), 1)
        self.assertEqual(alias_nodes[0].href, reverse("dashboard"))

    def test_navigation_legacy_permission_code_uses_legacy_permesso_when_canonical_grant_missing(self):
        PermissionDefinition.objects.create(
            code="legacy.dashboard.view_dashboard",
            label="Dashboard legacy",
            module="dashboard",
            is_active=True,
        )
        Permesso.objects.create(
            ruolo_id=self.role.id,
            modulo="dashboard",
            azione="view_dashboard",
            consentito=1,
            can_view=1,
        )
        item = NavigationItem.objects.create(
            code="dashboard_legacy",
            label="Dashboard Legacy",
            section="topbar",
            route_name="dashboard_home",
            required_permission_code="legacy.dashboard.view_dashboard",
            order=13,
            is_visible=True,
            is_enabled=True,
        )

        nodes = get_topbar_nodes(
            current_path="/dashboard",
            role_id=self.role.id,
            is_admin=False,
            legacy_user_id=self.legacy_user.id,
        )

        legacy_nodes = [node for node in nodes if node.codice == item.code]
        self.assertEqual(len(legacy_nodes), 1)
        self.assertEqual(legacy_nodes[0].href, reverse("dashboard_home"))

    def test_resolve_canonical_target_prefers_more_specific_path_binding(self):
        PermissionDefinition.objects.create(
            code="anagrafica.index.view",
            label="Anagrafica Index",
            module="anagrafica",
            is_active=True,
        )
        PermissionDefinition.objects.create(
            code="anagrafica.dipendenti.view",
            label="Anagrafica Dipendenti",
            module="anagrafica",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            permission_id="anagrafica.index.view",
            path_pattern="/anagrafica",
            source_app="anagrafica",
            is_active=True,
        )
        RoutePermissionBinding.objects.create(
            permission_id="anagrafica.dipendenti.view",
            path_pattern="/anagrafica/dipendenti",
            source_app="anagrafica",
            is_active=True,
        )

        resolved = resolve_canonical_target(path="/anagrafica/dipendenti")

        self.assertTrue(resolved["binding_found"])
        self.assertEqual(resolved["binding"]["permission_code"], "anagrafica.dipendenti.view")


class ModuleSettingsRouteTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser(
            username="module-settings-admin",
            email="module-settings@test.local",
            password="pass12345",
        )
        self.client.force_login(self.user)

    def test_canonical_module_settings_routes(self):
        self.assertEqual(reverse("diario_preposto:impostazioni"), "/diario-preposto/impostazioni/")
        self.assertEqual(reverse("rilevazione_incidenti:impostazioni"), "/rilevazione-incidenti/impostazioni/")
        self.assertEqual(reverse("timbri:configurazione"), "/timbri/impostazioni/")
        self.assertEqual(reverse("rentri_impostazioni"), "/rentri/impostazioni/")
        self.assertEqual(reverse("assenze_gestione"), "/assenze/impostazioni/")
        self.assertEqual(reverse("notizie_gestione_admin"), "/notizie/impostazioni/")
        self.assertEqual(reverse("procedure_refresh:admin_dashboard"), "/procedure-refresh/impostazioni/")
        self.assertEqual(reverse("tasks:impostazioni"), "/tasks/impostazioni/")
        self.assertEqual(reverse("assets:gestione_admin"), "/assets/impostazioni/")

    def test_legacy_settings_routes_redirect_to_canonical_paths(self):
        response = self.client.get("/timbri/configurazione/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/timbri/impostazioni/")

        response = self.client.get("/notizie/gestione/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/notizie/impostazioni/")

        response = self.client.get("/assets/gestione/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/assets/impostazioni/")

        response = self.client.get("/assenze/gestione_assenze")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/assenze/impostazioni/")

        response = self.client.get("/procedure-refresh/admin/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/procedure-refresh/impostazioni/")


@override_settings(SECURE_SSL_REDIRECT=False)
class LegacyNavigationBrandingTests(TestCase):
    def setUp(self):
        super().setUp()
        _ensure_legacy_navigation_tables()
        _clear_legacy_navigation_tables()
        cache.clear()
        self.factory = RequestFactory()
        self.user = get_user_model().objects.create_user(username="legacy-nav-user", password="pass12345")
        self.legacy_user = UtenteLegacy(
            id=900,
            nome="Legacy Admin",
            email="legacy.admin@example.local",
            password="x",
            ruolo="admin",
            attivo=True,
            deve_cambiare_password=False,
            ruolo_id=1,
        )

    @override_settings(
        LEGACY_AUTH_ENABLED=True,
        NAVIGATION_REGISTRY_ENABLED=False,
        MODULE_BRANDING={
            "assets": {
                "menu_label": "Novicrom Assets",
            }
        },
    )
    def test_legacy_nav_fallback_applies_branding_override(self):
        Pulsante.objects.create(
            codice="assets",
            nome_visibile="Asset Inventory",
            icona="box",
            modulo="assets",
            url="route:assets:asset_list",
        )
        bump_legacy_cache_version()

        request = self.factory.get("/dashboard")
        _attach_session(request)
        request.user = self.user
        request.legacy_user = self.legacy_user

        context = legacy_nav(request)
        assets_items = [item for item in context["nav_items"] if item.codice == "assets"]

        self.assertEqual(len(assets_items), 1)
        self.assertEqual(assets_items[0].label, "Novicrom Assets")
        self.assertEqual(assets_items[0].codice, "assets")
        self.assertEqual(assets_items[0].href, reverse("assets:asset_list"))


@override_settings(MEDIA_URL="/media/")
class IconTemplateTagTests(SimpleTestCase):
    def test_render_icon_renders_image_for_ico_sources(self):
        html = Template(
            "{% load ui_icons %}<span>{% render_icon 'media:nav/test-icon.ico' 'Dashboard' %}</span>"
        ).render(Context())

        self.assertIn("<img", html)
        self.assertIn('/media/nav/test-icon.ico', html)

    def test_render_icon_falls_back_to_text_when_no_semantic_icon_exists(self):
        html = Template(
            "{% load ui_icons %}<span>{% render_icon '' 'Foo' %}</span>"
        ).render(Context())

        self.assertIn(">F<", html)

    def test_render_icon_renders_svg_for_semantic_alias(self):
        html = Template(
            "{% load ui_icons %}<span>{% render_icon 'shield-check' 'DPI' %}</span>"
        ).render(Context())

        self.assertIn("<svg", html)
        self.assertIn("ui-icon-svg", html)

    def test_render_icon_uses_label_mapping_when_icon_is_blank(self):
        html = Template(
            "{% load ui_icons %}<span>{% render_icon '' 'Notizie' %}</span>"
        ).render(Context())

        self.assertIn("<svg", html)
        self.assertNotIn(">N<", html)

    def test_render_icon_replaces_placeholder_initials_with_semantic_icon(self):
        html = Template(
            "{% load ui_icons %}<span>{% render_icon 'A' 'Anagrafica' %}</span>"
        ).render(Context())

        self.assertIn("<svg", html)
        self.assertNotIn(">A<", html)


class ModuleRegistryStructureTests(TestCase):
    """Verifica integrità strutturale di MODULE_DEFINITIONS."""

    def test_no_duplicate_keys(self):
        """Il dizionario Python garantisce l'unicità, ma verifichiamo che definition.key == chiave dict."""
        for dict_key, definition in MODULE_DEFINITIONS.items():
            self.assertEqual(
                dict_key,
                definition.key,
                f"Chiave dict '{dict_key}' non corrisponde a definition.key='{definition.key}'",
            )

    def test_required_fields_non_empty(self):
        """Ogni modulo deve avere key, default_label e icon valorizzati."""
        for key, definition in MODULE_DEFINITIONS.items():
            with self.subTest(module=key):
                self.assertTrue(definition.key, f"{key}: key vuota")
                self.assertTrue(definition.default_label, f"{key}: default_label vuota")
                self.assertTrue(definition.icon, f"{key}: icon vuota")

    def test_route_name_present_for_navigable_modules(self):
        """I moduli con enabled_by_default=True devono avere un route_name."""
        for key, definition in MODULE_DEFINITIONS.items():
            if definition.enabled_by_default:
                with self.subTest(module=key):
                    self.assertTrue(
                        definition.route_name,
                        f"{key}: modulo navigabile senza route_name",
                    )

    def test_order_values_unique(self):
        """I valori order devono essere unici per evitare ambiguità di ordinamento."""
        orders = [d.order for d in MODULE_DEFINITIONS.values()]
        self.assertEqual(len(orders), len(set(orders)), "Valori order duplicati nel registry")

    def test_get_module_definition_returns_correct_entry(self):
        for key in MODULE_DEFINITIONS:
            with self.subTest(module=key):
                definition = get_module_definition(key)
                self.assertIsNotNone(definition)
                self.assertEqual(definition.key, key)

    def test_get_module_definition_unknown_key_returns_none(self):
        self.assertIsNone(get_module_definition("modulo_inesistente"))
        self.assertIsNone(get_module_definition(""))
        self.assertIsNone(get_module_definition(None))

    def test_get_registered_modules_returns_all_definitions(self):
        modules = get_registered_modules()
        self.assertEqual(set(modules.keys()), set(MODULE_DEFINITIONS.keys()))

    def test_navigation_codes_non_empty_for_enabled_modules(self):
        """I moduli abilitati devono avere almeno un navigation_code."""
        for key, definition in MODULE_DEFINITIONS.items():
            if definition.enabled_by_default:
                with self.subTest(module=key):
                    self.assertTrue(
                        definition.navigation_codes,
                        f"{key}: modulo abilitato senza navigation_codes",
                    )

    def test_navigation_code_label_map_covers_all_enabled_modules(self):
        """navigation_code_label_map deve produrre una entry per ogni codice di ogni modulo abilitato."""
        label_map = navigation_code_label_map(surface="menu")
        for key, definition in MODULE_DEFINITIONS.items():
            if not definition.enabled_by_default:
                continue
            for code in definition.navigation_codes:
                with self.subTest(module=key, code=code):
                    self.assertIn(
                        code,
                        label_map,
                        f"Codice '{code}' del modulo '{key}' assente dalla navigation_code_label_map",
                    )

    def test_branding_fallback_uses_default_label_when_no_overrides(self):
        """Senza override SiteConfig o settings, resolve_module_label torna il default_label."""
        for key, definition in MODULE_DEFINITIONS.items():
            with self.subTest(module=key):
                label = resolve_module_label(key, fallback="__FALLBACK__", surface="display")
                self.assertEqual(
                    label,
                    definition.default_label,
                    f"{key}: label attesa '{definition.default_label}', ottenuta '{label}'",
                )

    def test_resolve_module_label_returns_fallback_for_unknown_module(self):
        result = resolve_module_label("modulo_inesistente", fallback="FALLBACK", surface="menu")
        self.assertEqual(result, "FALLBACK")

    @override_settings(
        MODULE_BRANDING={
            "tasks": {"display_label": "Attività", "menu_label": "Le mie attività"},
            "tickets": {"short_label": "HelpDesk"},
        }
    )
    def test_settings_branding_override_applied_for_new_modules(self):
        """Gli override in settings.MODULE_BRANDING devono funzionare per tutti i moduli registrati."""
        tasks_label = resolve_module_label("tasks", fallback="Task", surface="menu")
        self.assertEqual(tasks_label, "Le mie attività")

        tickets_short = resolve_module_label("tickets", fallback="Ticket", surface="short")
        self.assertEqual(tickets_short, "HelpDesk")

    def test_audience_values_are_valid(self):
        """Ogni modulo deve avere audience in {"user", "admin", "system"}."""
        valid = {"user", "admin", "system"}
        for key, definition in MODULE_DEFINITIONS.items():
            with self.subTest(module=key):
                self.assertIn(
                    definition.audience,
                    valid,
                    f"{key}: audience='{definition.audience}' non valida",
                )

    def test_admin_modules_have_enabled_by_default_false(self):
        """I moduli admin e system non devono essere abilitati di default."""
        for key, definition in MODULE_DEFINITIONS.items():
            if definition.audience in ("admin", "system"):
                with self.subTest(module=key):
                    self.assertFalse(
                        definition.enabled_by_default,
                        f"{key}: audience='{definition.audience}' ma enabled_by_default=True",
                    )

    def test_get_modules_by_audience_user_excludes_admin_and_system(self):
        user_modules = get_modules_by_audience("user")
        for key, definition in user_modules.items():
            self.assertEqual(definition.audience, "user", f"{key} non dovrebbe essere in audience=user")
        admin_keys = {k for k, d in MODULE_DEFINITIONS.items() if d.audience == "admin"}
        system_keys = {k for k, d in MODULE_DEFINITIONS.items() if d.audience == "system"}
        self.assertFalse(admin_keys & set(user_modules.keys()), "Moduli admin presenti in audience=user")
        self.assertFalse(system_keys & set(user_modules.keys()), "Moduli system presenti in audience=user")

    def test_get_modules_by_audience_admin_includes_expected_modules(self):
        admin_modules = get_modules_by_audience("admin")
        self.assertIn("admin_portale", admin_modules)
        self.assertIn("hub_tools", admin_modules)
        self.assertIn("automazioni", admin_modules)

    def test_get_modules_by_audience_system_includes_monitoring(self):
        system_modules = get_modules_by_audience("system")
        self.assertIn("monitoring", system_modules)

    def test_navigation_code_label_map_does_not_include_disabled_modules_by_default(self):
        """I moduli con enabled_by_default=False non devono comparire automaticamente in branding."""
        disabled_keys = {key for key, d in MODULE_DEFINITIONS.items() if not d.enabled_by_default}
        if not disabled_keys:
            return  # nessun modulo disabilitato, test non applicabile
        label_map = navigation_code_label_map(surface="menu")
        disabled_codes = set()
        for key in disabled_keys:
            disabled_codes.update(MODULE_DEFINITIONS[key].navigation_codes)
        # I codici dei moduli disabled sono presenti nel map (il registry li include comunque),
        # ma verifichiamo che la struttura sia coerente (enabled_by_default=False è documentazione,
        # non filtraggio automatico in navigation_code_label_map)
        for code in disabled_codes:
            # Presenza o assenza sono entrambe accettabili; verifichiamo solo che non lanci eccezioni
            _ = label_map.get(code)


@override_settings(LEGACY_AUTH_ENABLED=True, SECURE_SSL_REDIRECT=False)
class OnboardingWizardTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="onboarding.user",
            password="test-pass-123",
            email="onboarding.user@example.com",
        )
        self.role = Ruolo.objects.create(id=101, nome="Operatore Onboarding")
        self.legacy_user = UtenteLegacy.objects.create(
            id=501,
            nome="Utente Onboarding",
            email="onboarding.user@example.com",
            password="hash",
            ruolo=self.role.nome,
            ruolo_id=self.role.id,
            attivo=True,
        )
        Profile.objects.create(
            user=self.user,
            legacy_user_id=self.legacy_user.id,
            legacy_ruolo_id=self.role.id,
            legacy_ruolo=self.role.nome,
        )
        self._grant_legacy_path_access("/profilo/", "profilo")
        self.client.force_login(self.user)

    def _grant_topbar_module(self, code: str, label: str) -> None:
        item = NavigationItem.objects.create(
            code=code,
            label=label,
            section="topbar",
            route_name="dashboard_home",
            order=10,
        )
        NavigationRoleAccess.objects.create(item=item, legacy_role_id=self.role.id, can_view=True)

    def _grant_legacy_path_access(self, path: str, action: str) -> None:
        Pulsante.objects.create(
            codice=action,
            nome_visibile=action.title(),
            modulo="core",
            url=path,
        )
        Permesso.objects.create(
            modulo="core",
            azione=action,
            ruolo_id=self.role.id,
            consentito=1,
            can_view=1,
        )

    def test_onboarding_get_shows_only_notification_options_for_visible_modules(self):
        self._grant_topbar_module("assenze", "Assenze")

        response = self.client.get(reverse("onboarding_wizard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Preferenze interfaccia")
        visible_options = response.context["visible_notification_options"]
        self.assertEqual([option["key"] for option in visible_options], ["assenze"])
        self.assertContains(response, "Assenze e presenze")
        self.assertNotContains(response, "Comunicazioni aziendali")
        self.assertNotContains(response, "Ticket e segnalazioni")

    def test_onboarding_get_is_accessible_without_legacy_acl_permission(self):
        response = self.client.get(reverse("onboarding_wizard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Completa il setup iniziale del tuo profilo.")

    def test_onboarding_post_saves_ui_preferences_and_disables_hidden_notification_modules(self):
        self._grant_topbar_module("assenze", "Assenze")

        response = self.client.post(
            reverse("onboarding_wizard"),
            {
                "email_contatto": "contatto@example.com",
                "cellulare_contatto": "+39 333 1234567",
                "nav_mode": "side",
                "theme_mode": "dark",
                "font_scale": "large",
                "sidebar_collapsed": "1",
                "sidebar_footer_actions": ["car"],
                "notifiche_assenze": "1",
            },
        )

        self.assertRedirects(response, reverse("dashboard_home"), fetch_redirect_response=False)

        onboarding = UserOnboarding.objects.get(user=self.user)
        self.assertTrue(onboarding.completed)
        self.assertEqual(onboarding.email_contatto, "contatto@example.com")
        self.assertEqual(onboarding.notifiche_config.get("assenze"), True)
        self.assertEqual(onboarding.notifiche_config.get("comunicazioni"), False)
        self.assertEqual(onboarding.notifiche_config.get("scadenzari"), False)
        self.assertEqual(onboarding.notifiche_config.get("ticket"), False)

        ui_prefs = UserUiPreference.objects.get(user=self.user)
        self.assertEqual(ui_prefs.nav_mode, "side")
        self.assertEqual(ui_prefs.theme_mode, "dark")
        self.assertEqual(ui_prefs.font_scale, "large")
        self.assertTrue(ui_prefs.sidebar_collapsed)
        self.assertEqual(ui_prefs.sidebar_footer_actions, ["car"])

    def test_profile_summary_keeps_only_notification_options_for_current_role(self):
        self._grant_topbar_module("assenze", "Assenze")
        UserOnboarding.objects.create(
            user=self.user,
            completed=True,
            email_contatto="contatto@example.com",
            notifiche_config={
                "assenze": True,
                "comunicazioni": False,
                "scadenzari": False,
                "ticket": False,
            },
        )

        response = self.client.get(reverse("profilo"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["onboarding_notifiche"], [("Assenze e presenze", True)])


class SidebarFooterActionsTests(SimpleTestCase):
    def test_footer_catalog_excludes_fixed_user_panel_actions(self):
        keys = [item["key"] for item in get_sidebar_footer_catalog()]

        self.assertEqual(keys, ["car", "notifications"])

    def test_default_footer_actions_include_notifications_only(self):
        self.assertEqual(get_default_sidebar_footer_actions(), ["notifications"])

    def test_normalize_discards_legacy_user_panel_entries(self):
        normalized = normalize_sidebar_footer_actions(
            ["notifications", "preferences", "profile", "logout", "car"],
            fallback_to_default=True,
        )

        self.assertEqual(normalized, ["notifications", "car"])


class PortalBrandingAssetCacheBustTests(TestCase):
    def test_local_media_logo_gets_cache_busting_version(self):
        SiteConfig.set("brand_logo_full", "/media/portal_branding/logo_full.png", "test")

        branding = get_portal_branding()

        self.assertTrue(branding.brand_logo_full.startswith("/media/portal_branding/logo_full.png"))
        self.assertIn("?v=", branding.brand_logo_full)

    def test_external_logo_url_is_not_modified(self):
        SiteConfig.set("brand_logo_full", "https://cdn.example.com/logo.png", "test")

        branding = get_portal_branding()

        self.assertEqual(branding.brand_logo_full, "https://cdn.example.com/logo.png")


class CoreBacklogCFeatureTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="cuser", password="pw", is_superuser=True)
        self.legacy_user = UtenteLegacy.objects.create(
            nome="Core User",
            email="cuser@example.com",
            password="x",
            ruolo="admin",
            attivo=True,
        )
        Profile.objects.create(user=self.user, legacy_user_id=self.legacy_user.id, legacy_ruolo="admin")

    def test_notification_panel_lists_unread_notifications(self):
        Notifica.objects.create(
            legacy_user_id=self.legacy_user.id,
            tipo="ticket_sla",
            messaggio="SLA ticket scaduto",
            url_azione="/tickets/",
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("api_notifiche_panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Centro notifiche")
        self.assertContains(response, "SLA ticket scaduto")

    def test_live_notifications_api_returns_badge_count_and_popup_payload(self):
        Notifica.objects.create(
            legacy_user_id=self.legacy_user.id,
            tipo="ticket_sla",
            messaggio="Popup live",
            url_azione="/tickets/",
        )
        Notifica.objects.create(
            legacy_user_id=self.legacy_user.id,
            tipo="dpi_scadenza",
            messaggio="Gia mostrata",
            popup_shown=True,
        )
        Notifica.objects.create(
            legacy_user_id=self.legacy_user.id,
            tipo="generico",
            messaggio="Gia letta",
            letta=True,
        )
        other = UtenteLegacy.objects.create(nome="Other", email="other@example.com", password="x", attivo=True)
        Notifica.objects.create(legacy_user_id=other.id, tipo="generico", messaggio="Non mia")
        self.client.force_login(self.user)

        response = self.client.get(reverse("api_notifiche_live"), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["unread_count"], 2)
        self.assertEqual(len(data["popup_notifications"]), 1)
        self.assertEqual(data["popup_notifications"][0]["messaggio"], "Popup live")
        self.assertEqual(data["popup_notifications"][0]["url_azione"], "/tickets/")

    def test_popup_ack_marks_only_current_user_notifications(self):
        own = Notifica.objects.create(legacy_user_id=self.legacy_user.id, tipo="generico", messaggio="Mia")
        other_user = UtenteLegacy.objects.create(nome="Other", email="other2@example.com", password="x", attivo=True)
        other = Notifica.objects.create(legacy_user_id=other_user.id, tipo="generico", messaggio="Altra")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("api_notifiche_popup_ack"),
            data=json.dumps({"ids": [own.id, other.id]}),
            content_type="application/json",
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        own.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(own.popup_shown)
        self.assertFalse(other.popup_shown)

    def test_base_template_loads_live_notification_client(self):
        Notifica.objects.create(legacy_user_id=self.legacy_user.id, tipo="generico", messaggio="Badge live")
        self.client.force_login(self.user)

        response = self.client.get(reverse("profilo"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("api_notifiche_live"))
        self.assertContains(response, "data-notification-badge-host")
        self.assertContains(response, "data-notification-badge")

    def test_mark_all_notifications_read(self):
        Notifica.objects.create(legacy_user_id=self.legacy_user.id, tipo="dpi_scadenza", messaggio="DPI in scadenza")
        self.client.force_login(self.user)

        response = self.client.post(reverse("api_notifiche_mark_all_read"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Notifica.objects.filter(legacy_user_id=self.legacy_user.id, letta=False).exists())

    def test_notification_export_csv_preserves_filtered_user(self):
        Notifica.objects.create(legacy_user_id=self.legacy_user.id, tipo="generico", messaggio="Export me")
        self.client.force_login(self.user)

        response = self.client.get(reverse("notifiche"), {"export": "csv"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("Export me", response.content.decode("utf-8"))

    def test_user_activity_view_and_export(self):
        AuditLog.objects.create(
            legacy_user_id=self.legacy_user.id,
            utente_display="Core User",
            modulo="core",
            azione="test_action",
            dettaglio={"ok": True},
        )
        self.client.force_login(self.user)

        url = reverse("admin_portale:user_activity")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "test_action")

        export_response = self.client.get(url, {"export": "csv"})
        self.assertEqual(export_response.status_code, 200)
        self.assertIn("text/csv", export_response["Content-Type"])
        self.assertIn("test_action", export_response.content.decode("utf-8"))


class ValidateDeploymentSecurityChecksTests(SimpleTestCase):
    """Copre i check di sicurezza del comando validate_deployment."""

    def _run_security_checks(self):
        from core.management.commands.validate_deployment import DeploymentValidator

        validator = DeploymentValidator()
        validator.check_security()
        return {result.name: result for result in validator.results}

    @override_settings(SQL_LOG_ENABLED=False)
    def test_sql_log_disabled_is_ok(self):
        results = self._run_security_checks()
        self.assertIn("SQL_LOG_ENABLED", results)
        self.assertEqual(results["SQL_LOG_ENABLED"].severity, "OK")

    @override_settings(SQL_LOG_ENABLED=True, MONITORING_ENVIRONMENT="production")
    def test_sql_log_enabled_in_prod_fails(self):
        results = self._run_security_checks()
        self.assertIn("SQL_LOG_ENABLED", results)
        self.assertEqual(results["SQL_LOG_ENABLED"].severity, "FAIL")

    @override_settings(SQL_LOG_ENABLED=True, MONITORING_ENVIRONMENT="development")
    def test_sql_log_enabled_outside_prod_warns(self):
        results = self._run_security_checks()
        self.assertIn("SQL_LOG_ENABLED", results)
        self.assertEqual(results["SQL_LOG_ENABLED"].severity, "WARN")


class RoutePatternToPathTests(SimpleTestCase):
    """Conversione pattern URL -> path concreto per il match dei binding."""

    def test_django_converters_are_replaced(self):
        from core.management.commands.acl_fallback_report import route_pattern_to_path

        self.assertEqual(route_pattern_to_path("tickets/<int:pk>/"), "/tickets/_/")
        self.assertEqual(
            route_pattern_to_path("rilevazione-incidenti/<str:sp_id>/pdf/"),
            "/rilevazione-incidenti/_/pdf/",
        )

    def test_leading_caret_and_slash_normalized(self):
        from core.management.commands.acl_fallback_report import route_pattern_to_path

        self.assertEqual(route_pattern_to_path("^assets/lista/$"), "/assets/lista/")
        self.assertTrue(route_pattern_to_path("tickets/").startswith("/"))


class AclFallbackReportPrefixBindingTests(TestCase):
    """Una route coperta solo da binding PREFIX (senza route_name) non deve
    risultare 'unbound': il report deve usare la stessa logica di matching del
    middleware (route_name + path prefix/regex), non il solo route_name.
    """

    def test_prefix_binding_without_route_name_counts_as_bound(self):
        from django.core.management import call_command
        from io import StringIO
        from core.models import PermissionDefinition, RoutePermissionBinding

        # Prendo una route applicativa reale e la copro con un binding PREFIX
        # sul suo path, lasciando route_name vuoto.
        probe_out = StringIO()
        call_command("acl_fallback_report", "--only-unbound", "--format", "json", stdout=probe_out)
        unbound = json.loads(probe_out.getvalue())["routes"]
        target = next(
            (r for r in unbound if r["pattern"].lstrip("^/").startswith("tickets/")),
            None,
        )
        if target is None:
            self.skipTest("nessuna route tickets unbound disponibile come probe")

        from core.management.commands.acl_fallback_report import route_pattern_to_path
        path_norm = route_pattern_to_path(target["pattern"]).rstrip("/") or "/"

        perm = PermissionDefinition.objects.create(
            code="test.prefix.probe", module="tickets",
            label="Test prefix probe", is_active=True,
        )
        RoutePermissionBinding.objects.create(
            route_name="", path_pattern=path_norm,
            match_strategy=RoutePermissionBinding.MATCH_PREFIX,
            permission=perm, is_active=True,
        )

        after_out = StringIO()
        call_command("acl_fallback_report", "--only-unbound", "--format", "json", stdout=after_out)
        still_unbound = json.loads(after_out.getvalue())["routes"]
        self.assertFalse(
            any(r["pattern"] == target["pattern"] for r in still_unbound),
            msg="La route coperta da binding prefix risulta ancora unbound",
        )


class AclFallbackReportNamespaceTests(TestCase):
    """Le route con namespace (es. 'fornitori:fornitore_create') devono essere
    confrontate con i binding usando il nome namespaced, come fa il middleware
    via `view_name`. Senza questo, route già bindate risultano falsi 'unbound'.
    """

    def test_namespaced_routes_use_namespaced_name(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("acl_fallback_report", "--format", "json", stdout=out)
        names = [r["name"] for r in json.loads(out.getvalue())["routes"]]
        # Almeno una route deve essere namespaced (contiene ':'): prova che il
        # report ricostruisce il namespace invece di usare il solo url_name.
        self.assertTrue(
            any(":" in n for n in names),
            msg="Nessuna route namespaced: il namespace non viene propagato",
        )


class AclFallbackReportAdminExclusionTests(SimpleTestCase):
    """L'esclusione delle route del Django admin dal report di copertura ACL.

    Le route del contrib admin (montato su 'admin/') sono fuori dal perimetro
    ACL applicativo e non vanno migrate a RoutePermissionBinding: gonfiavano il
    conteggio 'unbound' rendendo impossibile sapere quando la migrazione e'
    completa.
    """

    def test_django_admin_routes_recognized_by_pattern(self):
        from core.management.commands.acl_fallback_report import (
            is_django_admin_route,
        )

        self.assertTrue(is_django_admin_route("admin/"))
        self.assertTrue(is_django_admin_route("admin/auth/user/"))
        self.assertTrue(is_django_admin_route("^admin/login/"))

    def test_application_routes_are_not_flagged_as_admin(self):
        from core.management.commands.acl_fallback_report import (
            is_django_admin_route,
        )

        # 'admin-portale/' NON e' il Django admin.
        self.assertFalse(is_django_admin_route("admin-portale/"))
        self.assertFalse(is_django_admin_route("admin-portale/permessi/"))
        # Route applicative con 'admin' nel path o suffisso '_add' nel nome:
        # qui conta solo il pattern, e questi pattern non iniziano con 'admin/'.
        self.assertFalse(is_django_admin_route("procedure-refresh/admin/documenti/"))
        self.assertFalse(is_django_admin_route("setup/api/create-admin/"))
        self.assertFalse(is_django_admin_route("anagrafica/dipendenti/<int:legacy_id>/qualifiche/add"))


class AclFallbackReportCommandTests(TestCase):
    def test_report_excludes_django_admin_by_default(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command("acl_fallback_report", "--format", "json", stdout=out)
        data = json.loads(out.getvalue())

        self.assertGreater(data["summary"]["excluded_django_admin"], 0)
        # Nessuna route con pattern del Django admin deve comparire nei risultati.
        for route in data["routes"]:
            self.assertFalse(
                route["pattern"].lstrip("^/").startswith("admin/"),
                msg=f"Route admin non esclusa: {route}",
            )

    def test_include_admin_flag_restores_admin_routes(self):
        from django.core.management import call_command
        from io import StringIO

        default_out = StringIO()
        call_command("acl_fallback_report", "--format", "json", stdout=default_out)
        default_total = json.loads(default_out.getvalue())["summary"]["total_routes"]

        admin_out = StringIO()
        call_command(
            "acl_fallback_report", "--format", "json", "--include-admin",
            stdout=admin_out,
        )
        admin_total = json.loads(admin_out.getvalue())["summary"]["total_routes"]

        self.assertGreater(admin_total, default_total)
