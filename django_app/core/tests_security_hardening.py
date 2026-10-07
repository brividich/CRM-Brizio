"""Hardening ottobre 2026: IP client, JSON negli script, redirect, rate limit,
token mail-action, allegati privati. Dati sintetici."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from django.core.cache import cache
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.net import client_ip
from core.redirects import safe_next


class ClientIpTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(TRUSTED_PROXY_IPS=set())
    def test_forwarded_header_ignored_without_trusted_proxy(self):
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.2.3.4")
        self.assertEqual(client_ip(request), "10.0.0.5")

    @override_settings(TRUSTED_PROXY_IPS={"127.0.0.1"})
    def test_rightmost_untrusted_hop_wins_behind_trusted_proxy(self):
        # Il client ha scritto "6.6.6.6"; il proxy fidato ha aggiunto l'IP reale.
        request = self.factory.get("/", REMOTE_ADDR="127.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 10.1.2.3")
        self.assertEqual(client_ip(request), "10.1.2.3")


class JsJsonFilterTests(SimpleTestCase):
    def test_script_breakout_is_neutralized(self):
        tpl = Template("{% load safe_json %}<script>var x = {{ data|js_json }};</script>")
        html = tpl.render(Context({"data": {"nome": "</script><script>alert(1)</script>"}}))
        self.assertNotIn("</script><script>", html)
        self.assertIn("\\u003C/script\\u003E", html)

    def test_already_serialized_string_is_escaped(self):
        tpl = Template("{% load safe_json %}{{ data|js_json }}")
        self.assertEqual(tpl.render(Context({"data": '{"a": "<b>"}'})), '{"a": "\\u003Cb\\u003E"}')


class SafeNextTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")

    def test_internal_path_kept(self):
        self.assertEqual(safe_next(self.request, "/notizie/", "/x/"), "/notizie/")

    def test_external_and_backslash_tricks_fall_back(self):
        for bad in ("https://evil.example/", "//evil.example/", "/\\evil.example/", "javascript:alert(1)"):
            self.assertEqual(safe_next(self.request, bad, "/x/"), "/x/", bad)


@override_settings(TRUSTED_PROXY_IPS=set())
class SuggestionCornerRateLimitTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def test_spoofed_forwarded_for_does_not_reset_the_limit(self):
        from suggestion_corner.ratelimit import is_rate_limited

        results = [
            is_rate_limited(self.factory.post("/", REMOTE_ADDR="10.0.0.9", HTTP_X_FORWARDED_FOR=f"1.1.1.{i}"))
            for i in range(6)
        ]
        self.assertEqual(results, [False] * 5 + [True])

    def test_global_limit_blocks_many_ips(self):
        from suggestion_corner import ratelimit

        with self.settings():
            original = ratelimit.GLOBAL_LIMIT
            ratelimit.GLOBAL_LIMIT = 3
            try:
                results = [
                    ratelimit.is_rate_limited(self.factory.post("/", REMOTE_ADDR=f"10.0.1.{i}")) for i in range(4)
                ]
            finally:
                ratelimit.GLOBAL_LIMIT = original
        self.assertEqual(results, [False, False, False, True])


class MailActionTokenClaimTests(TestCase):
    def test_token_can_be_claimed_only_once(self):
        from anomalie.mail_action_models import AnomaliaMailActionToken
        from anomalie.mail_action_views import _claim_token, _release_token

        token = AnomaliaMailActionToken.objects.create(
            action="chiudi", op_id="OP-SINT-1", expires_at=timezone.now() + timedelta(days=1)
        )
        request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.1")
        self.assertTrue(_claim_token(token, request))
        self.assertFalse(_claim_token(token, request))
        _release_token(token)
        self.assertTrue(_claim_token(token, request))


class NotiziaAllegatoPrivateTests(TestCase):
    def test_download_requires_visibility_and_file_is_not_public(self):
        import tempfile

        from django.contrib.auth import get_user_model
        from django.core.files.base import ContentFile

        from notizie.models import Notizia, NotiziaAllegato

        with tempfile.TemporaryDirectory() as tmp, override_settings(
            PRIVATE_ATTACHMENTS_ROOT=Path(tmp) / "private", MEDIA_ROOT=Path(tmp) / "media"
        ):
            notizia = Notizia.objects.create(titolo="Bozza sintetica", corpo="x")
            allegato = NotiziaAllegato(notizia=notizia, nome_file="doc.txt")
            allegato.file.save("doc.txt", ContentFile(b"contenuto sintetico"), save=True)

            self.assertTrue((Path(tmp) / "private").exists())
            self.assertFalse((Path(tmp) / "media" / "notizie").exists())
            with self.assertRaises(NotImplementedError):
                allegato.file.url

            user = get_user_model().objects.create_user("lettore", password="x")
            self.client.force_login(user)
            response = self.client.get(f"/notizie/allegato/{allegato.pk}/")
            # Notizia non pubblicata: un utente non gestore non la vede.
            self.assertIn(response.status_code, {302, 403})
