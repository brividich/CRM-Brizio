"""«Correggi» un'anomalia chiusa senza riaprirla. Dati sintetici; tabella legacy in SQLite."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase

from anomalie import correggi_chiusa as cc
from anomalie.mail_action_models import AnomaliaActionLog
from anomalie.tests_rdc_attesa import OP, _fetch_sqlite

User = get_user_model()


class CorreggiChiusaTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, "
                        "descrizione TEXT, note_capocommessa TEXT, chiudere INTEGER, avanzamento TEXT, "
                        "created_by_user_id INTEGER)")
            cur.execute("INSERT INTO anomalie (ex_op_nominativo, descrizione, note_capocommessa, chiudere, avanzamento, "
                        "created_by_user_id) VALUES (%s, 'Intaco sul piano', 'Ripasare', 1, 'Accetto lo stato', 7)", [OP])
            self.aid = cur.lastrowid
        self.user = User.objects.create_user(username="corr.chiusa", password="pass12345")
        self._p = [
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value={"id", "descrizione", "note_capocommessa", "chiudere"}),
            patch("anomalie.views._fetch_all_dict", side_effect=_fetch_sqlite),
            patch("anomalie.views.get_legacy_user", return_value=None),
            patch("anomalie.views._is_controllore_anomalia", return_value=False),
            patch("anomalie.views._controlli_dell_utente", return_value=set()),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def _post(self, *, editor=False, me=None, **dati):
        request = RequestFactory().post("/api/anomalie/correggi-chiusa", data=json.dumps({"local_id": self.aid, **dati}),
                                        content_type="application/json")
        request.user = self.user
        with patch("anomalie.views._can_edit_anomalie_for_op", return_value=editor), \
             patch("anomalie.views._request_legacy_user_id", return_value=me):
            return cc.api_correggi_chiusa(request)

    def _riga(self):
        return _fetch_sqlite("SELECT * FROM anomalie WHERE id = %s", [self.aid])[0]

    def test_capocommessa_corregge_le_note_e_resta_chiusa(self):
        r = self._post(editor=True, note="Ripassare in macchina", motivo="errore di battitura")
        self.assertEqual(r.status_code, 200, r.content)
        riga = self._riga()
        self.assertEqual((riga["note_capocommessa"], riga["chiudere"], riga["avanzamento"]),
                         ("Ripassare in macchina", 1, "Accetto lo stato"))
        log = AnomaliaActionLog.objects.get(anomalia_id=self.aid, action="corretta")
        self.assertIn("errore di battitura", log.note)
        self.assertIn(["Note", "Ripasare", "Ripassare in macchina"], log.payload["modifiche"])

    def test_controllore_corregge_il_testo_ma_non_le_note(self):
        r = self._post(me=7, testo="Intacco sul piano", motivo="refuso")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._riga()["descrizione"], "Intacco sul piano")
        self.assertEqual(self._post(me=7, note="altro", motivo="refuso").status_code, 403)

    def test_altri_niente(self):
        self.assertEqual(self._post(me=99, testo="X", motivo="refuso").status_code, 403)

    def test_motivo_obbligatorio_e_niente_vuoti(self):
        self.assertEqual(self._post(editor=True, note="Nuova", motivo="").status_code, 400)
        self.assertEqual(self._post(editor=True, testo="", motivo="refuso").status_code, 400)
        self.assertEqual(self._post(editor=True, note="Ripasare", motivo="refuso").status_code, 400)

    def test_aperta_rifiutata(self):
        with connection.cursor() as cur:
            cur.execute("UPDATE anomalie SET chiudere = 0 WHERE id = %s", [self.aid])
        self.assertEqual(self._post(editor=True, note="Nuova", motivo="refuso").status_code, 400)

    def test_segna_righe(self):
        righe = [{"local_id": self.aid, "chiudere": True}, {"local_id": 999, "chiudere": True, "controllo_id": 5}]
        request = SimpleNamespace(user=self.user)
        with patch("anomalie.views._can_edit_anomalie_for_op", return_value=False), \
             patch("anomalie.views._request_legacy_user_id", return_value=7), \
             patch("anomalie.views._controlli_dell_utente", return_value={5}), \
             patch("anomalie.incaricati.per_anomalie", return_value={}):
            cc.segna_righe(request, righe, OP, {self.aid: 7, 999: 3})
        self.assertEqual(righe[0]["correggi_chiusa"], {"testo": True, "note": False})
        self.assertEqual(righe[1]["correggi_chiusa"], {"testo": True, "note": False})
