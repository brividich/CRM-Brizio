import base64
import json

from django.contrib import messages
from django.contrib.messages.storage.cookie import CookieStorage
from django.contrib.messages.storage.base import Message
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase

from core.flash_messages import COOKIE, HEADER, FlashMessagesDeliveryMiddleware, group, summarize


def _request(**headers):
    request = RequestFactory().post("/x/", **headers)
    request._messages = CookieStorage(request)
    return request


def _render(request, body=""):
    tpl = Template("{% load flash_messages %}" + body + "{% flash_messages_fallback %}")
    return tpl.render(Context({"request": request, "messages": request._messages}))


class FlashFallbackTagTests(SimpleTestCase):
    def test_mostra_messaggi_non_stampati_dalla_pagina(self):
        request = _request()
        messages.success(request, "Profilo salvato.")
        html = _render(request)
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
        self.assertIn("Info ABC", _render(request, "{% if messages %}{% endif %}"))

    def test_escape_html(self):
        request = _request()
        messages.warning(request, "<b>x</b>")
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", _render(request))

    def test_messaggi_identici_raggruppati_con_contatore(self):
        request = _request()
        for _ in range(3):
            messages.success(request, "Profilo «Watchguard» salvato.")
        html = _render(request)
        self.assertEqual(html.count('class="hub-flash-text">Profilo «Watchguard» salvato.<'), 1)
        self.assertIn("&times;3", html)

    def test_messaggio_lungo_riassunto_con_dettagli(self):
        request = _request()
        lungo = "Kyocera: nessuna risposta dall'apparato entro il tempo massimo. " + "Cause possibili: " + "x" * 200
        messages.error(request, lungo)
        html = _render(request)
        self.assertIn("hub-flash-more", html)
        self.assertIn("x" * 200, html)  # testo intero nei dettagli


class SummarizeTests(SimpleTestCase):
    def test_testo_corto_invariato(self):
        self.assertEqual(summarize("Salvato."), "Salvato.")

    def test_taglia_alla_prima_frase(self):
        testo = "Kyocera: 10.0.0.217: nessuna risposta dall'apparato entro il tempo massimo. Cause possibili: " + "y" * 200
        self.assertEqual(summarize(testo), "Kyocera: 10.0.0.217: nessuna risposta dall'apparato entro il tempo massimo.")

    def test_senza_punteggiatura_tronca(self):
        self.assertTrue(summarize("z" * 300).endswith("…"))

    def test_group_conta_solo_stesso_livello(self):
        items = group([Message(25, "A"), Message(25, "A"), Message(40, "A")])
        self.assertEqual([(i["level"], i["count"]) for i in items], [("success", 2), ("error", 1)])


class DeliveryMiddlewareTests(SimpleTestCase):
    def _run(self, request, response, testo="Fatto."):
        def view(req):
            messages.success(req, testo)
            return response
        return FlashMessagesDeliveryMiddleware(view)(request)

    def test_htmx_riceve_header(self):
        request = _request(HTTP_HX_REQUEST="true")
        response = self._run(request, HttpResponse("ok"))
        self.assertEqual(json.loads(response[HEADER]), [{"level": "success", "text": "Fatto.", "count": 1}])

    def test_fetch_riceve_header(self):
        request = _request(HTTP_SEC_FETCH_MODE="cors")
        response = self._run(request, HttpResponse("{}", content_type="application/json"))
        self.assertIn(HEADER, response)

    def test_header_solo_ascii(self):
        request = _request(HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        response = self._run(request, HttpResponse("ok"), testo="Profilo «Kyocera» già salvato")
        response[HEADER].encode("ascii")
        self.assertEqual(json.loads(response[HEADER])[0]["text"], "Profilo «Kyocera» già salvato")

    def test_asincrona_non_ruba_i_messaggi_della_richiesta_precedente(self):
        request = _request(HTTP_HX_REQUEST="true")
        storage = request._messages
        storage._loaded_data = [Message(25, "Da mostrare nella pagina")]
        response = self._run(request, HttpResponse("ok"))
        self.assertEqual([i["text"] for i in json.loads(response[HEADER])], ["Fatto."])
        self.assertEqual([str(m) for m in storage._loaded_data], ["Da mostrare nella pagina"])
        self.assertFalse(storage.used)

    def test_hx_redirect_lascia_i_messaggi_alla_pagina_successiva(self):
        request = _request(HTTP_HX_REQUEST="true")
        resp = HttpResponse("")
        resp["HX-Redirect"] = "/altrove/"
        response = self._run(request, resp)
        self.assertNotIn(HEADER, response)
        self.assertEqual(len(request._messages._queued_messages), 1)

    def test_pagina_normale_non_toccata(self):
        request = _request(HTTP_SEC_FETCH_MODE="navigate")
        response = self._run(request, HttpResponse("ok"))
        self.assertNotIn(HEADER, response)
        self.assertNotIn(COOKIE, response.cookies)
        self.assertEqual(len(request._messages._queued_messages), 1)

    def test_download_mette_i_messaggi_nel_cookie(self):
        request = _request(HTTP_SEC_FETCH_MODE="navigate")
        resp = HttpResponse(b"xlsx", content_type="application/vnd.ms-excel")
        resp["Content-Disposition"] = 'attachment; filename="export.xlsx"'
        response = self._run(request, resp, testo="Export pronto")
        value = response.cookies[COOKIE].value
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        self.assertEqual(payload[0]["text"], "Export pronto")
        self.assertFalse(response.cookies[COOKIE]["httponly"])
        self.assertEqual(request._messages._queued_messages, [])

    def test_redirect_non_toccato(self):
        request = _request(HTTP_HX_REQUEST="true")
        resp = HttpResponse(status=302)
        resp["Location"] = "/"
        response = self._run(request, resp)
        self.assertNotIn(HEADER, response)
