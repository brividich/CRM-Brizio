from __future__ import annotations

import json
import logging
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.db import connection
from django.db.utils import ProgrammingError
from django.http import HttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.audit import log_action
from core.csrf_cookie_middleware import EnsureCSRFCookieMiddleware
from core.impersonation import IMPERSONATION_SESSION_KEY
from core.legacy_models import UtenteLegacy
from core.logging_handlers import SafeTimedRotatingFileHandler
from core.middleware import AdaptiveSecureCookieMiddleware
from core.legacy_utils import sync_django_user_from_legacy
from core.models import AuditLog, Profile
from core.session_middleware import SessionIdleTimeoutMiddleware
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


class DashboardRoutingTests(TestCase):
    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_dashboard_and_dashboard_home_routes_work(self):
        user = get_user_model().objects.create_user(username="route-user", password="pass12345")
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
        self.assertEqual(self.client.get(dashboard_url).status_code, 200)
        self.assertEqual(self.client.get(dashboard_home_url).status_code, 200)

    @override_settings(
        LEGACY_AUTH_ENABLED=False,
        APP_VERSION="9.9.9-test",
        MODULE_VERSIONS={"dashboard": "9.9.9-test", "assets": "1.2.3-assets"},
    )
    def test_dashboard_home_shows_version_footer(self):
        user = get_user_model().objects.create_user(username="route-user-version", password="pass12345")
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard_home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Versione portale")
        self.assertContains(response, "9.9.9-test")
        self.assertContains(response, "Moduli versionati")

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
        self.assertIn("Versioning e Release Notes", response.content.decode("utf-8"))
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
        self.assertContains(response, "Portale Applicativo")
        self.assertContains(response, "Example Organization")


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
