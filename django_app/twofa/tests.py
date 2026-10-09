from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

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

    def test_uses_impersonator_user_during_impersonation(self):
        """Durante l'impersonazione il 2FA valutato è quello dell'admin reale."""
        request = self._request("/dashboard/")
        request.user = SimpleNamespace(is_authenticated=True, name="target")
        request.impersonator_user = SimpleNamespace(is_authenticated=True, name="admin")
        seen = []

        def fake_should(req, user):
            seen.append(user.name)
            return False

        with patch("twofa.utils.should_require_2fa", side_effect=fake_should):
            self._middleware()(request)
        self.assertEqual(seen, ["admin"])


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SetupTOTPEnrollmentGuardTests(TestCase):
    """Audit C1: con la sola password non si sostituisce un secondo fattore attivo."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="c1-user", password="pass12345")
        self.client.force_login(self.user)

    def _confirmed_totp(self):
        from twofa.models import UserTwoFactor
        from twofa.utils import encrypt_totp_secret, generate_totp_secret

        return UserTwoFactor.objects.create(
            user=self.user,
            method="totp",
            totp_secret_enc=encrypt_totp_secret(generate_totp_secret()),
            totp_confirmed=True,
        )

    def test_established_totp_cannot_be_replaced_from_unverified_session(self):
        import pyotp

        u2f = self._confirmed_totp()
        old_enc = u2f.totp_secret_enc
        attacker_secret = "JBSWY3DPEHPK3PXP"
        session = self.client.session
        session["twofa_totp_setup_secret"] = attacker_secret
        session.save()

        response = self.client.post(
            reverse("twofa:setup_totp"),
            {"code": pyotp.TOTP(attacker_secret).now()},
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("twofa:verify"), response["Location"])
        u2f.refresh_from_db()
        self.assertEqual(u2f.totp_secret_enc, old_enc)
        self.assertNotIn("twofa_verified_until", self.client.session)

    def test_established_email_factor_cannot_switch_to_totp(self):
        from twofa.models import UserTwoFactor

        UserTwoFactor.objects.create(user=self.user, method="email")
        response = self.client.get(reverse("twofa:setup_totp"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("twofa:verify"), response["Location"])

    def test_first_enrollment_is_allowed(self):
        response = self.client.get(reverse("twofa:setup_totp"))
        self.assertEqual(response.status_code, 200)

    def test_enrollment_allowed_after_admin_reset(self):
        u2f = self._confirmed_totp()
        u2f.force_setup = True
        u2f.save(update_fields=["force_setup"])
        response = self.client.get(reverse("twofa:setup_totp"))
        self.assertEqual(response.status_code, 200)


class PrivilegedAccountsPolicyTests(TestCase):
    """Audit A2: superuser/staff soggetti al 2FA anche senza Profile."""

    def setUp(self):
        super().setUp()
        from twofa.models import TwoFactorPolicy

        policy = TwoFactorPolicy.get()
        policy.enabled = True
        policy.when_required = TwoFactorPolicy.WHEN_ALWAYS
        policy.required_role_ids = []
        policy.save()
        self.request = RequestFactory().get("/")
        self.User = get_user_model()

    def test_superuser_without_profile_requires_2fa(self):
        from twofa.utils import should_require_2fa

        su = self.User.objects.create_superuser(username="a2-root", password="pass12345", email="")
        self.assertTrue(should_require_2fa(self.request, su))

    def test_regular_user_without_profile_not_required(self):
        from twofa.utils import should_require_2fa

        user = self.User.objects.create_user(username="a2-user", password="pass12345")
        self.assertFalse(should_require_2fa(self.request, user))

    def test_policy_error_is_fail_closed_for_privileged(self):
        from twofa.utils import should_require_2fa

        su = self.User.objects.create_superuser(username="a2-root2", password="pass12345", email="")
        user = self.User.objects.create_user(username="a2-user2", password="pass12345")
        with patch("twofa.models.TwoFactorPolicy.get", side_effect=RuntimeError("db down")):
            self.assertTrue(should_require_2fa(self.request, su))
            self.assertFalse(should_require_2fa(self.request, user))

    def test_policy_disabled_does_not_require(self):
        from twofa.models import TwoFactorPolicy
        from twofa.utils import should_require_2fa

        TwoFactorPolicy.objects.filter(pk=1).update(enabled=False)
        su = self.User.objects.create_superuser(username="a2-root3", password="pass12345", email="")
        self.assertFalse(should_require_2fa(self.request, su))
