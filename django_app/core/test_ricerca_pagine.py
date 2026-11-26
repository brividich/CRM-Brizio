"""Ricerca globale: le pagine dei sottomenu di tutti i moduli, non solo del modulo aperto.

Regressione: cercando «recruiting» da fuori Anagrafica la palette non proponeva la
pagina, perché conosceva solo il menu principale e il sottomenu della pagina corrente.
"""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from anagrafica.models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica
from core.ricerca_pagine import cerca_pagine, voci_dai_template


class RicercaPagineTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = get_user_model().objects.create_user(
            username="admin.ricerca@example.test", password="x", is_superuser=True
        )
        persone = SubnavCategoriaAnagrafica.objects.create(nome="Persone", ordine=1)
        SubnavLinkAnagrafica.objects.create(
            etichetta="Recruiting", url_type="named", url_value="anagrafica:recruiting_list",
            categoria=persone, ordine=5,
        )

    def _req(self, user=None):
        request = RequestFactory().get("/api/search/")
        request.user = user or self.admin
        request.legacy_user = None
        return request

    def test_indice_dei_template_contiene_i_sottomenu_dei_moduli(self):
        urls = {v.url: v.label for v in voci_dai_template()}
        self.assertEqual(urls.get("/dpi/banco/"), "Banco consegne")
        self.assertFalse(any(label.startswith("?") for label in urls.values()), "le guide non sono pagine")

    def test_recruiting_trovato_da_fuori_anagrafica(self):
        risultati = cerca_pagine(self._req(), "recruiting", puo_aprire=lambda _r, _p: True)
        self.assertIn(("Recruiting", "/anagrafica/recruiting/"), [(r["label"], r["url"]) for r in risultati])
        voce = next(r for r in risultati if r["url"] == "/anagrafica/recruiting/")
        self.assertEqual(voce["sub"], "Anagrafica · Persone")

    def test_senza_permesso_la_pagina_non_compare(self):
        aperti = []

        def nega(_request, percorso):
            aperti.append(percorso)
            return False

        self.assertEqual(cerca_pagine(self._req(), "recruiting", puo_aprire=nega), [])
        self.assertIn("/anagrafica/recruiting/", aperti, "il controllo dei permessi deve essere interrogato")

    def test_accenti_e_maiuscole_non_contano(self):
        risultati = cerca_pagine(self._req(), "RECRUÌTING", puo_aprire=lambda _r, _p: True)
        self.assertTrue(any(r["url"] == "/anagrafica/recruiting/" for r in risultati))

    def test_api_restituisce_le_pagine(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session["twofa_verified_until"] = "2999-01-01T00:00:00+00:00"
        session.save()
        risposta = self.client.get("/api/search/?q=recruiting", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(risposta.status_code, 200)
        pagine = [r for r in json.loads(risposta.content)["results"] if r["tipo"] == "pagina"]
        self.assertIn("/anagrafica/recruiting/", [r["url"] for r in pagine])
