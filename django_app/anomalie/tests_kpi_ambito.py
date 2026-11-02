"""Contatori delle anomalie con l'ambito dell'utente (ALL / ASSIGNED / OWN_ANOMALIE).

Statistiche, ricerca e contatore della home devono contare le stesse righe
che l'elenco OP mostra: prima le statistiche ignoravano lo scope e la home
confrontava il nome della persona con il titolo dell'OP.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings

from anomalie import views as anomalie_views

COLS = {"id", "op_lookup_id", "ex_op_nominativo", "chiudere", "created_by_user_id"}


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnomalieAmbitoContatoriTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE ordini_produzione (sharepoint_item_id TEXT, title TEXT, capocomessa TEXT, incaricato TEXT)"
            )
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY, op_lookup_id INTEGER, ex_op_nominativo TEXT, "
                "chiudere INTEGER, created_by_user_id INTEGER)"
            )
            cur.execute("INSERT INTO ordini_produzione VALUES ('1', 'OP/1', 'Mario Rossi', '')")
            cur.execute("INSERT INTO ordini_produzione VALUES ('2', 'OP/2', 'Luca Bianchi', '')")
            for pk, op, chiudere, autore in ((1, 1, 0, 9), (2, 1, 0, 9), (3, 2, 0, 5), (4, 2, 1, 9)):
                cur.execute(
                    "INSERT INTO anomalie VALUES (%s, %s, %s, %s, %s)", [pk, op, f"OP/{op}", chiudere, autore]
                )
        user = get_user_model().objects.create_user(username="kpi-anom", password="x")
        self.request = RequestFactory().get("/", {})
        self.request.user = user
        self.request.legacy_user = SimpleNamespace(id=5, nome="Mario Rossi", email="")

    def _con_scope(self, scope):
        return (
            patch("anomalie.views._request_anomalie_list_scope", return_value=scope),
            patch("anomalie.views.legacy_table_columns", return_value=COLS),
            patch("anomalie.views._has_table", return_value=True),
        )

    def _conta(self, scope):
        a, b, c = self._con_scope(scope)
        with a, b, c:
            return anomalie_views.conta_anomalie_aperte_visibili(self.request)

    def test_tutte_conta_tutte_le_aperte(self):
        self.assertEqual(self._conta(anomalie_views.AnomalieListScope.ALL), 3)

    def test_assegnate_conta_solo_gli_op_da_capocommessa(self):
        self.assertEqual(self._conta(anomalie_views.AnomalieListScope.ASSIGNED), 2)

    def test_proprie_conta_gli_op_su_cui_ha_aperto_un_anomalia(self):
        # L'utente (legacy 5) ha aperto la 3 sull'OP/2: vede le aperte dell'OP/2.
        self.assertEqual(self._conta(anomalie_views.AnomalieListScope.OWN_ANOMALIE), 1)

    def test_senza_nome_ambito_assegnate_non_vede_nulla(self):
        self.request.legacy_user = SimpleNamespace(id=5, nome="", email="")
        self.request.user.first_name = self.request.user.last_name = ""
        self.request.user.username = ""
        self.assertEqual(self._conta(anomalie_views.AnomalieListScope.ASSIGNED), 0)

    def test_statistiche_e_ricerca_rispettano_lo_scope(self):
        a, b, c = self._con_scope(anomalie_views.AnomalieListScope.ASSIGNED)
        with a, b, c:
            stat = json.loads(anomalie_views.api_anomalie_statistiche.__wrapped__(self.request).content)
            ricerca = json.loads(anomalie_views.api_anomalie_ricerca.__wrapped__(self.request).content)
        self.assertEqual(stat["totale"], 2)
        self.assertEqual(stat["aperte"], 2)
        self.assertEqual(stat["capocommessa_disponibili"], ["OP/1"])
        self.assertEqual(ricerca["totale"], 2)
        self.assertEqual({r["id"] for r in ricerca["righe"]}, {1, 2})

    def test_stesso_numero_su_home_e_statistiche(self):
        a, b, c = self._con_scope(anomalie_views.AnomalieListScope.ASSIGNED)
        with a, b, c:
            home = anomalie_views.conta_anomalie_aperte_visibili(self.request)
            stat = json.loads(anomalie_views.api_anomalie_statistiche.__wrapped__(self.request).content)
        self.assertEqual(home, stat["aperte"])
