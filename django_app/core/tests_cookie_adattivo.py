from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware import AdaptiveSecureCookieMiddleware


def _risposta(_request):
    r = HttpResponse("ok")
    r.set_cookie("sessionid", "x", secure=True)
    return r


class CookieAdattivoTests(SimpleTestCase):
    """Audit P2: con i cookie sicuri chiesti dalla configurazione non si declassa niente."""

    @override_settings(SESSION_COOKIE_SECURE=False)
    def test_http_senza_cookie_sicuri_declassa(self):
        resp = AdaptiveSecureCookieMiddleware(_risposta)(RequestFactory().get("/"))
        self.assertEqual(resp.cookies["sessionid"]["secure"], "")

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_http_con_cookie_sicuri_resta_secure(self):
        resp = AdaptiveSecureCookieMiddleware(_risposta)(RequestFactory().get("/"))
        self.assertTrue(resp.cookies["sessionid"]["secure"])
