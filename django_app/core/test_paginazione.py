"""Elenchi a caricamento passo passo: helper, tag del pager e preferenze tabella."""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase

from core.paginazione import pagina_elenco


class PaginaElencoTests(TestCase):
    def test_pagina_dal_parametro_proprio(self):
        request = RequestFactory().get("/x/", {"log_page": "2"})
        page = pagina_elenco(request, list(range(250)), param="log_page")
        self.assertEqual(page.number, 2)
        self.assertEqual(list(page.object_list)[0], 100)
        self.assertEqual(page.paginator.num_pages, 3)

    def test_pagina_non_valida_torna_alla_prima(self):
        request = RequestFactory().get("/x/", {"page": "abc"})
        self.assertEqual(pagina_elenco(request, list(range(10))).number, 1)


class PagerPassoPassoTests(TestCase):
    def _render(self, request, page, param=""):
        tpl = Template(
            '{% include "core/components/_pager_passo_passo.html" with page_obj=page param=param %}'
        )
        return tpl.render(Context({"request": request, "page": page, "param": param}))

    def test_link_tengono_i_filtri_e_cambiano_solo_la_pagina(self):
        request = RequestFactory().get("/x/", {"reparto": ["A", "B"], "q": "rossi"})
        html = self._render(request, pagina_elenco(request, list(range(350))))
        self.assertIn('data-fm-last-page="4"', html)
        self.assertIn('data-fm-page-param="page"', html)
        self.assertIn("reparto=A&amp;reparto=B", html)
        self.assertIn("page=2", html)
        self.assertIn("350 righe in totale", html)

    def test_parametro_proprio(self):
        request = RequestFactory().get("/x/", {"tab": "log"})
        page = pagina_elenco(request, list(range(150)), param="mail_page")
        html = self._render(request, page, param="mail_page")
        self.assertIn('data-fm-page-param="mail_page"', html)
        self.assertIn("tab=log&amp;mail_page=2", html)

    def test_una_sola_pagina_niente_pager(self):
        request = RequestFactory().get("/x/")
        self.assertNotIn("fm-pager", self._render(request, pagina_elenco(request, list(range(5)))))


class TablePrefsCapTests(TestCase):
    """La view direttamente: il gate ACL delle API è coperto dai suoi test."""

    TABLE_ID = "auto.test.t1.abc"

    def setUp(self):
        self.user = get_user_model().objects.create_user("tabprefs", password="x-Tab-2026!")
        self.factory = RequestFactory()

    def _call(self, method, state=None):
        from core.views import api_table_prefs

        url = f"/api/table-prefs/{self.TABLE_ID}/"
        if method == "post":
            request = self.factory.post(url, data=json.dumps({"state": state}), content_type="application/json")
        else:
            request = self.factory.get(url)
        request.user = self.user
        return api_table_prefs(request, self.TABLE_ID)

    def _post(self, state):
        return self._call("post", state)

    def test_larghezze_di_molte_colonne_si_salvano(self):
        cols = ["voce_retributiva_numero_%03d" % i for i in range(120)]
        state = {"visible": cols, "order": cols, "sort": [], "widths": {c: 120 for c in cols}}
        self.assertGreater(len(json.dumps(state)), 10240)
        resp = self._post(state)
        self.assertEqual(resp.status_code, 200, resp.content)
        got = json.loads(self._call("get").content)["state"]
        self.assertEqual(got["widths"][cols[0]], 120)

    def test_blob_enorme_rifiutato(self):
        resp = self._post({"q": "x" * 40000})
        self.assertEqual(resp.status_code, 400)
