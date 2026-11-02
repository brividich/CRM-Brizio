"""OP nuovo creato solo al primo salvataggio e «Segnalare al cliente» → «In attesa risposta cliente».

La pagina «Nuova segnalazione» chiede a ``/api/anomalie/db/ordini/crea`` solo una
verifica (``verifica: true``): nessun inserimento finché non si salva un blocco.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as av

_NUOVO = {"causale_doc": "OP", "anno": "2026", "numero": "1399", "pn": "PN-7781-A",
          "capocommessa": "Mario Rossi", "car": "Anna Neri"}


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class VerificaOpTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE ordini_produzione (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, sharepoint_item_id TEXT)")
        user = get_user_model().objects.create_superuser(username="op-verifica", password="pass12345", email="v@example.local")
        self.client.force_login(user)
        self._patches = [
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value={"id", "title", av.OP_ITEM_ID_COL}),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE ordini_produzione")

    def _conta(self):
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ordini_produzione")
            return cur.fetchone()[0]

    def _post(self, body):
        return self.client.post(reverse("api_anomalie_db_ordini_crea"), json.dumps(body), content_type="application/json")

    def test_verifica_non_crea_niente(self):
        r = self._post({**_NUOVO, "verifica": True})
        self.assertEqual(r.status_code, 200)
        dati = r.json()
        self.assertTrue(dati["verifica"])
        self.assertEqual(dati["op"]["id"], "OP/2026/1399")
        self.assertIsNone(dati["op"]["item_id"])
        self.assertEqual(self._conta(), 0)

    def test_verifica_op_gia_esistente(self):
        with connection.cursor() as cur:
            cur.execute("INSERT INTO ordini_produzione (title, sharepoint_item_id) VALUES ('OP/2026/1399', '-1')")
        r = self._post({**_NUOVO, "verifica": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("esiste già", r.json()["error"])
        self.assertEqual(self._conta(), 1)

    def test_verifica_campi_obbligatori(self):
        r = self._post({**_NUOVO, "car": "", "verifica": True})
        self.assertEqual(r.status_code, 400)


class SegnalareClienteTests(TestCase):
    def test_stato_libero_diventa_attesa_cliente(self):
        self.assertEqual(av.avanzamento_dopo_segnalazione(True, "In attesa"), av.AVANZAMENTO_RISPOSTA_CLIENTE)
        self.assertEqual(av.avanzamento_dopo_segnalazione(True, ""), av.AVANZAMENTO_RISPOSTA_CLIENTE)

    def test_stato_scelto_resta(self):
        self.assertEqual(av.avanzamento_dopo_segnalazione(True, "Azione di recupero"), "Azione di recupero")
        self.assertEqual(av.avanzamento_dopo_segnalazione(False, "In attesa"), "In attesa")

    def test_vuoto_vale_lo_stato_attuale(self):
        # Dalla mail «invariato» = vuoto: conta lo stato già salvato.
        self.assertEqual(av.avanzamento_dopo_segnalazione(True, "", "Finito trattato"), "")
        self.assertEqual(av.avanzamento_dopo_segnalazione(True, "", "In attesa"), av.AVANZAMENTO_RISPOSTA_CLIENTE)

    def test_nota_con_segnalazione_non_bloccata(self):
        # Prima «Segnalare al cliente» + nota + «In attesa» veniva rifiutato: ora lo
        # stato passa a «In attesa risposta cliente» e il salvataggio prosegue.
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = SimpleNamespace(is_superuser=True, is_authenticated=True)
        with (
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=set()),
        ):
            esito = av._salva_riga_anomalia(request, {
                "item_id": "local:1", "op_id": "OP/1", "note": "Chiesto al cliente", "avanzamento": "In attesa",
                "segnalare": True,
            })
        self.assertNotEqual(esito.get("error"), av.MSG_NOTA_STATO_IN_ATTESA)

    def test_stato_fuori_catalogo_accettato(self):
        with patch("anomalie.views._load_anomalie_lists", return_value={"avanzamenti": ["In attesa"]}):
            self.assertEqual(av._canonicalize_avanzamento("in attesa risposta cliente"), av.AVANZAMENTO_RISPOSTA_CLIENTE)
