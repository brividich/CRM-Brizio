from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from anagrafica.models import (
    AreaAziendale, DipendenteAnagraficaAziendale, Reparto,
)

User = get_user_model()


class DipendentiReportCanonicoTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-rep", "su-rep@test.local", "x")
        self.rep = Reparto.objects.create(nome="Produzione Canonica")
        self.area = AreaAziendale.objects.create(nome="Linea A", reparto=self.rep)

    def _get(self, **params):
        from anagrafica.views import dipendenti_report
        rf = RequestFactory()
        request = rf.get("/anagrafica/dipendenti/report/", params)
        request.user = self.su
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return dipendenti_report(request)

    def test_pagina_non_ha_colonna_reparto_legacy(self):
        resp = self._get()
        body = resp.content.decode()
        self.assertNotIn("Reparto (legacy)", body)
        self.assertIn("Reparto", body)  # colonna canonica

    def test_csv_header_senza_reparto_legacy_con_area(self):
        resp = self._get(format="csv")
        header = resp.content.decode(errors="ignore").splitlines()[0]
        self.assertIn("Reparto", header)
        self.assertIn("Area aziendale", header)
