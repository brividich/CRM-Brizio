import json

from django.contrib import messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from core.flash_messages import HtmxFlashMessagesMiddleware


def _request(htmx=False):
    headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
    request = RequestFactory().post("/x/", **headers)
    request._messages = CookieStorage(request)
    return request


def _render(request, body):
    tpl = Template("{% load flash_messages %}" + body + "{% flash_messages_fallback %}")
    return tpl.render(Context({"request": request, "messages": request._messages}))


class FlashFallbackTagTests(SimpleTestCase):
    def test_mostra_messaggi_non_stampati_dalla_pagina(self):
        request = _request()
        messages.success(request, "Profilo salvato.")
        html = _render(request, "")
        self.assertIn("Profilo salvato.", html)
        self.assertIn("hub-flash-success", html)
        self.assertTrue(request._messages.used)

    def test_non_duplica_se_la_pagina_li_ha_gia_stampati(self):
        request = _request()
        messages.error(request, "Errore XYZ")
        html = _render(request, "{% for m in messages %}<p>{{ m }}</p>{% endfor %}")
        self.assertEqual(html.count("Errore XYZ"), 1)

    def test_if_messages_non_conta_come_stampa(self):
        request = _request()
        messages.info(request, "Info ABC")
        html = _render(request, "{% if messages %}{% endif %}")
        self.assertIn("Info ABC", html)

    def test_escape_html(self):
        request = _request()
        messages.warning(request, "<b>x</b>")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", _render(request, ""))


class HtmxFlashMiddlewareTests(SimpleTestCase):
    def _run(self, request, response):
        def view(req):
            messages.success(req, "Fatto.")
            return response
        return HtmxFlashMessagesMiddleware(view)(request)

    def test_htmx_consuma_e_invia_hx_trigger(self):
        request = _request(htmx=True)
        response = self._run(request, HttpResponse("ok"))
        payload = json.loads(response["HX-Trigger"])
        self.assertEqual(payload["hubFlash"], [{"level": "success", "text": "Fatto."}])
        self.assertTrue(request._messages.used)

    def test_unisce_hx_trigger_esistente(self):
        request = _request(htmx=True)
        resp = HttpResponse("ok")
        resp["HX-Trigger"] = "refreshList"
        payload = json.loads(self._run(request, resp)["HX-Trigger"])
        self.assertIn("refreshList", payload)
        self.assertIn("hubFlash", payload)

    def test_hx_redirect_lascia_i_messaggi_alla_pagina_successiva(self):
        request = _request(htmx=True)
        resp = HttpResponse("")
        resp["HX-Redirect"] = "/altrove/"
        response = self._run(request, resp)
        self.assertNotIn("HX-Trigger", response)
        self.assertFalse(request._messages.used)

    def test_richiesta_normale_non_toccata(self):
        request = _request(htmx=False)
        response = self._run(request, HttpResponse("ok"))
        self.assertNotIn("HX-Trigger", response)
        self.assertFalse(request._messages.used)
