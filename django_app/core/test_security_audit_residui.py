"""Regressioni audit 09/10: finding fuori dalle fasi della roadmap (M5, M9, B1-B8, S8)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.db import IntegrityError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings


class CaporepartoAssignmentTests(SimpleTestCase):
    """M5: un caporeparto non sposta nel suo reparto dipendenti di altri reparti."""

    def _call(self, target_reparto: str):
        from core import views

        request = RequestFactory().post(
            "/gestione-reparto/1/assegna/", data=json.dumps({}), content_type="application/json"
        )
        request.user = SimpleNamespace(is_authenticated=True)
        manager = SimpleNamespace(id=10, nome="Capo", email="capo@example.local")
        target = SimpleNamespace(id=20, nome="Dipendente", email="dip@example.local")

        def reparto_of(legacy_id):
            return "Officina" if legacy_id == 10 else target_reparto

        with patch.object(views, "get_legacy_user", return_value=manager), \
             patch.object(views, "_can_manage_team_assignments", return_value=True), \
             patch.object(views, "is_legacy_admin", return_value=False), \
             patch.object(views, "_resolve_effective_reparto", side_effect=reparto_of), \
             patch.object(views, "_resolve_team_manager_value", return_value="Capo"), \
             patch.object(views, "_load_option_values", return_value=["Capo"]), \
             patch.object(views.UtenteLegacy.objects, "filter") as legacy_filter, \
             patch.object(views.UserExtraInfo.objects, "get_or_create") as get_or_create:
            legacy_filter.return_value.first.return_value = target
            get_or_create.return_value = (SimpleNamespace(save=lambda: None), True)
            return views.api_gestione_reparto_assegna.__wrapped__.__wrapped__(request, user_id=20)

    def test_other_department_is_refused(self):
        response = self._call("Montaggio")
        self.assertEqual(response.status_code, 403)

    def test_unassigned_or_same_department_is_allowed(self):
        self.assertEqual(self._call("").status_code, 200)
        self.assertEqual(self._call("officina").status_code, 200)


class SetupWizardProdTests(SimpleTestCase):
    """M9: con settings di produzione il wizard web resta chiuso."""

    def test_prod_settings_close_the_wizard(self):
        from setup_wizard import state

        with patch.object(state, "_running_with_prod_settings", return_value=True), \
             patch.object(state, "iter_runtime_env_paths", return_value=[]):
            self.assertFalse(state.setup_needed())

    def test_prod_detection(self):
        from setup_wizard import state

        with override_settings(SETTINGS_MODULE="config.settings.prod"):
            self.assertTrue(state._running_with_prod_settings())
        with override_settings(SETTINGS_MODULE="config.settings.test"):
            self.assertFalse(state._running_with_prod_settings())


class IdleTimeoutPrefixTests(SimpleTestCase):
    """B1: "/check" non esenta "/checklist-operativa/" dal timeout di sessione."""

    def test_segment_match(self):
        from core.middleware import _path_matches_prefixes

        self.assertTrue(_path_matches_prefixes("/check", ("/check",)))
        self.assertFalse(_path_matches_prefixes("/checklist-operativa/", ("/check",)))


class LoginLogoutHardeningTests(SimpleTestCase):
    """B2: logout cross-site bloccato, cambio password obbligatorio non aggirabile."""

    def test_cross_site_get_logout_is_ignored(self):
        from core.accounts.views import logout_view

        request = RequestFactory().get("/logout/", HTTP_SEC_FETCH_SITE="cross-site")
        request.user = SimpleNamespace(is_authenticated=True)
        with patch("core.accounts.views.logout") as fake_logout:
            response = logout_view(request)
        fake_logout.assert_not_called()
        self.assertEqual(response.status_code, 302)

    def test_forced_password_change_redirects_navigation(self):
        from core.session_middleware import FORCED_PASSWORD_CHANGE_SESSION_KEY, ForcedPasswordChangeMiddleware

        middleware = ForcedPasswordChangeMiddleware(lambda r: HttpResponse("ok"))
        request = RequestFactory().get("/dashboard/")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {FORCED_PASSWORD_CHANGE_SESSION_KEY: True}
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("cambia-password", response["Location"])

        allowed = RequestFactory().get("/cambia-password/")
        allowed.user = request.user
        allowed.session = request.session
        self.assertEqual(middleware(allowed).status_code, 200)

    def test_short_or_common_password_rejected(self):
        from core.accounts.forms import LegacyChangePasswordForm

        short = LegacyChangePasswordForm(
            {"password_attuale": "x", "nuova_password": "abc12345", "conferma_password": "abc12345"}
        )
        self.assertFalse(short.is_valid())
        common = LegacyChangePasswordForm(
            {"password_attuale": "x", "nuova_password": "password1234", "conferma_password": "password1234"}
        )
        self.assertFalse(common.is_valid())
        good = LegacyChangePasswordForm(
            {"password_attuale": "x", "nuova_password": "Turbina-Lotto-73!", "conferma_password": "Turbina-Lotto-73!"}
        )
        self.assertTrue(good.is_valid(), good.errors)


class WorkorderAttachmentAccessTests(SimpleTestCase):
    """B3: l'allegato di un OdL segue l'ACL della scheda dell'OdL."""

    def test_denied_when_workorder_page_denied(self):
        from assets import views

        request = RequestFactory().get("/assets/workorders/allegati/1/download/")
        request.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        request.legacy_user = SimpleNamespace(id=5)
        with patch.object(views, "_is_assets_admin", return_value=False), \
             patch("core.legacy_utils.legacy_auth_enabled", return_value=True), \
             patch("core.acl_v2.resolve_acl_access", return_value={"allowed": False}), \
             patch("core.middleware.enforce_strict_canonical", return_value=False):
            self.assertFalse(views._can_view_workorder(request, SimpleNamespace(pk=1)))
        with patch.object(views, "_is_assets_admin", return_value=False), \
             patch("core.legacy_utils.legacy_auth_enabled", return_value=True), \
             patch("core.acl_v2.resolve_acl_access", return_value={"allowed": True}), \
             patch("core.middleware.enforce_strict_canonical", return_value=False):
            self.assertTrue(views._can_view_workorder(request, SimpleNamespace(pk=1)))


class SafeRedirectTests(SimpleTestCase):
    """B4: "//evil.example" non e' un path del portale."""

    def test_protocol_relative_url_rejected(self):
        from core.redirects import safe_next

        request = RequestFactory().get("/", HTTP_HOST="hub.example.local")
        with override_settings(ALLOWED_HOSTS=["hub.example.local"]):
            self.assertEqual(safe_next(request, "//evil.example/x", "/fallback/"), "/fallback/")
            self.assertEqual(safe_next(request, "/\\evil.example", "/fallback/"), "/fallback/")
            self.assertEqual(safe_next(request, "/tasks/1/", "/fallback/"), "/tasks/1/")


class ReportTemplateEngineTests(SimpleTestCase):
    """B5: il template report caricato non usa debug/load/include/url."""

    def test_dangerous_tags_rejected(self):
        from django.template import Context, TemplateSyntaxError

        from anomalie.views import _restricted_report_engine

        engine = _restricted_report_engine()
        self.assertEqual(
            engine.from_string("{% for a in x %}{{ a|upper }}{% endfor %}{{ h }}").render(
                Context({"x": ["a"], "h": "<b>"})
            ),
            "A&lt;b&gt;",
        )
        for source in ("{% debug %}", "{% load static %}", '{% include "x.html" %}', '{% url "login" %}'):
            with self.assertRaises(TemplateSyntaxError, msg=source):
                engine.from_string(source)


class MailboxApprovalSenderTests(SimpleTestCase):
    """B6: una mail da Internet con From falsificato non decide un'approvazione."""

    def test_auth_as_header_is_read(self):
        from automazioni.mailbox_graph import normalize_message

        raw = {
            "id": "1",
            "subject": "APPROVO",
            "from": {"emailAddress": {"address": "capo@example.local"}},
            "internetMessageHeaders": [{"name": "X-MS-Exchange-Organization-AuthAs", "value": "Anonymous"}],
            "body": {"contentType": "text", "content": "APPROVO"},
        }
        self.assertEqual(normalize_message(raw).auth_as, "Anonymous")

    def test_only_internal_senders(self):
        from automazioni.mailbox_graph import _validate_sender_auth

        self.assertEqual(_validate_sender_auth("Internal"), "")
        self.assertNotEqual(_validate_sender_auth("Anonymous"), "")
        self.assertEqual(_validate_sender_auth(None), "")  # header assente: solo controllo mittente


class GraphTokenCacheTests(SimpleTestCase):
    """B7: il token Graph in cache non e' in chiaro."""

    def test_roundtrip_and_legacy_plaintext_ignored(self):
        from core.graph_utils import _decrypt_cached_token, _encrypt_token_for_cache

        stored = _encrypt_token_for_cache("ya29.token-sintetico", "secret-a")
        self.assertNotIn("ya29.token-sintetico", stored)
        self.assertEqual(_decrypt_cached_token(stored, "secret-a"), "ya29.token-sintetico")
        self.assertEqual(_decrypt_cached_token(stored, "secret-b"), "")
        self.assertEqual(_decrypt_cached_token("ya29.vecchio-in-chiaro", "secret-a"), "")


class NumberingRetryTests(TestCase):
    """S8: collisione sul numero progressivo -> nuovo tentativo, non errore 500."""

    def test_retries_on_integrity_error(self):
        from core.numbering_retry import save_with_next_number

        numbers = iter([1, 2])
        state = {}
        calls = []

        def assign():
            state["n"] = next(numbers)

        def save():
            calls.append(state["n"])
            if state["n"] == 1:
                raise IntegrityError("duplicate")
            return state["n"]

        self.assertEqual(save_with_next_number(assign, save), 2)
        self.assertEqual(calls, [1, 2])

    def test_gives_up_after_attempts(self):
        from core.numbering_retry import save_with_next_number

        def save():
            raise IntegrityError("duplicate")

        with self.assertRaises(IntegrityError):
            save_with_next_number(lambda: None, save, attempts=2)
