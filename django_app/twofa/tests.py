from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from twofa.middleware import TwoFactorMiddleware, _is_exempt


class TwoFAExemptPrefixTests(SimpleTestCase):
    """La lista di esenzione 2FA non deve includere le superfici privilegiate."""

    def test_privileged_paths_are_not_exempt(self):
        # /admin/ e le altre superfici privilegiate DEVONO restare protette dal 2FA
        self.assertFalse(_is_exempt("/admin/"))
        self.assertFalse(_is_exempt("/admin-portale/hub/"))
        self.assertFalse(_is_exempt("/assets/public/scheda/1"))

    def test_expected_prefixes_remain_exempt(self):
        for path in (
            "/2fa/verifica/",
            "/login",
            "/logout",
            "/static/app.css",
            "/media/x.png",
            "/favicon.ico",
            "/automazioni/approvazione/tok/",
            "/approval-actions/x",
            "/healthz",
            "/readyz",
        ):
            self.assertTrue(_is_exempt(path), path)


class TwoFAMiddlewareEnforcementTests(SimpleTestCase):
    """Il middleware deve essere autorevole: l'enforcement non dipende dal flag di
    sessione `twofa_pending` (impostato solo dal login legacy), così le sessioni
    aperte via SSO Windows non bypassano il secondo fattore."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _request(self, path="/dashboard/"):
        request = self.factory.get(path)
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {}  # nessun twofa_pending: simula login SSO
        request.htmx = False
        return request

    def _middleware(self):
        return TwoFactorMiddleware(lambda r: HttpResponse("ok"))

    def test_enforces_without_twofa_pending_flag(self):
        with patch("twofa.utils.should_require_2fa", return_value=True), \
             patch("twofa.utils.is_2fa_verified", return_value=False):
            response = self._middleware()(self._request("/dashboard/"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/2fa/", response["Location"])

    def test_enforces_on_admin_path(self):
        # /admin/ non è più esente: una sessione non verificata viene reindirizzata
        with patch("twofa.utils.should_require_2fa", return_value=True), \
             patch("twofa.utils.is_2fa_verified", return_value=False):
            response = self._middleware()(self._request("/admin/"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/2fa/", response["Location"])

    def test_allows_when_verified(self):
        with patch("twofa.utils.should_require_2fa", return_value=True), \
             patch("twofa.utils.is_2fa_verified", return_value=True):
            response = self._middleware()(self._request("/dashboard/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"ok")

    def test_allows_when_2fa_not_required(self):
        with patch("twofa.utils.should_require_2fa", return_value=False), \
             patch("twofa.utils.is_2fa_verified", return_value=False):
            response = self._middleware()(self._request("/dashboard/"))
        self.assertEqual(response.status_code, 200)
