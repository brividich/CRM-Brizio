"""Tessere KPI delle statistiche anomalie: la ricerca dettaglio con la condizione della
tessera (data-kpi-filtro) conta lo stesso numero della tessera."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings

from anomalie import views as anomalie_views

COLS = {"id", "op_lookup_id", "ex_op_nominativo", "chiudere", "created_by_user_id", "aprire_rdc",
        "segnalare_cliente", "pezzo_recuperato", "avanzamento"}

# (chiave JSON della tessera, condizione aggiunta dalla tessera alla ricerca dettaglio)
TESSERE = (
    ("totale", {}),
    ("aperte", {"stato": "aperte"}),
    ("chiuse", {"stato": "chiuse"}),
    ("in_attesa", {"avanzamento": "In attesa"}),
    ("rdc_aperti", {"rdc": "si"}),
    ("segnalazioni", {"segnalazione": "si"}),
    ("recuperati", {"recuperato": "si"}),
)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class StatisticheKpiLinkTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY, op_lookup_id INTEGER, ex_op_nominativo TEXT, "
                "chiudere INTEGER, created_by_user_id INTEGER, aprire_rdc INTEGER, segnalare_cliente INTEGER, "
                "pezzo_recuperato INTEGER, avanzamento TEXT)"
            )
            righe = (
                (1, 0, 1, 0, 0, "In attesa"),
                (2, 0, 0, 1, 1, "In lavorazione"),
                (3, 1, 1, 1, 1, "Chiusa"),
                (4, None, 0, 0, 1, "In attesa"),
            )
            for pk, chiudere, rdc, seg, rec, avanz in righe:
                cur.execute(
                    "INSERT INTO anomalie VALUES (%s, 1, 'OP/1', %s, 9, %s, %s, %s, %s)",
                    [pk, chiudere, rdc, seg, rec, avanz],
                )
        user = get_user_model().objects.create_user(username="kpi-anom-link", password="x")
        self.user = user
        self.factory = RequestFactory()

    def _api(self, view, params):
        request = self.factory.get("/", params)
        request.user = self.user
        request.legacy_user = SimpleNamespace(id=9, nome="Mario Rossi", email="")
        with patch("anomalie.views._request_anomalie_list_scope", return_value=anomalie_views.AnomalieListScope.ALL), \
             patch("anomalie.views.legacy_table_columns", return_value=COLS), \
             patch("anomalie.views._has_table", return_value=True), \
             patch("anomalie.tempi_service.tempi_per_anomalie", return_value=[]):
            return json.loads(view.__wrapped__(request).content)

    def test_ogni_tessera_conta_le_righe_della_ricerca_filtrata(self):
        for filtri_pagina in ({}, {"rdc": "si"}):
            stat = self._api(anomalie_views.api_anomalie_statistiche, filtri_pagina)
            for chiave, condizione in TESSERE:
                ricerca = self._api(anomalie_views.api_anomalie_ricerca, {**filtri_pagina, **condizione})
                self.assertEqual(ricerca["totale"], stat[chiave], f"{chiave} {filtri_pagina}")
        stat = self._api(anomalie_views.api_anomalie_statistiche, {})
        self.assertEqual(stat["aperte"], 3)  # chiudere NULL conta come aperta
        self.assertEqual(stat["recuperati"], 3)

    def test_tessere_sono_link_alla_ricerca(self):
        html = render_to_string("anomalie/pages/anomalie_statistiche.html", {"db_has_anomalie": True})
        self.assertEqual(html.count('href="#ricerca-dettaglio"'), 8)
        self.assertIn('id="ricerca-dettaglio"', html)
        self.assertIn("data-kpi-filtro='{\"recuperato\":\"si\"}'", html)
