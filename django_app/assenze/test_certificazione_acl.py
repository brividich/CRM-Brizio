from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from assenze import views


class CertificazionePresenzaGateTests(SimpleTestCase):
    """SEC: certificazione_presenza è una funzione amministrativa. Senza il gate
    admin_assenze elencava tutte le presenze e permetteva create/update/delete
    (con auto-inserimento di un'assenza già approvata) a qualunque autenticato."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _req(self, method="get"):
        req = getattr(self.factory, method)("/assenze/certificazione-presenza/")
        req.user = SimpleNamespace(is_authenticated=True, is_superuser=False)
        return req

    def test_non_admin_is_forbidden_before_any_db_access(self):
        with patch("assenze.views.user_can_modulo_action", return_value=False), \
             patch("assenze.views.render", return_value=HttpResponse(status=403)) as mock_render:
            resp = views.certificazione_presenza(self._req("get"))
        self.assertEqual(resp.status_code, 403)
        args, kwargs = mock_render.call_args
        self.assertEqual(args[1], "core/pages/forbidden.html")
        self.assertEqual(kwargs.get("status"), 403)

    def test_non_admin_post_is_forbidden(self):
        # Anche le mutazioni (create/update/delete) sono bloccate prima di eseguire.
        with patch("assenze.views.user_can_modulo_action", return_value=False), \
             patch("assenze.views.render", return_value=HttpResponse(status=403)) as mock_render:
            resp = views.certificazione_presenza(self._req("post"))
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(mock_render.called)
