"""Tabella «Chi ha in carico l'anomalia» e Storia modificabile (note, passi). Dati sintetici."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from anomalie import decisione_qualita as dq
from anomalie import regole_carico as rc
from anomalie import registro_views as rv
from anomalie.mail_action_models import AnomaliaActionLog, AnomaliaActionNota
from anomalie.tests_rdc_attesa import _COLS, _TabellaAnomalieMixin

_RIGA = {"chiudere": 0, "aprire_rdc": 0, "segnalare_cliente": 0, "note_capocommessa": "", "avanzamento": "In attesa"}


class DestinazioneTests(SimpleTestCase):
    def test_di_serie_come_prima(self):
        self.assertEqual(rc.destinazione(_RIGA, dq._info_vuota(), {}), {"cc"})
        self.assertEqual(rc.destinazione({**_RIGA, "aprire_rdc": 1}, dq._info_vuota(), {}), {"qualita"})

    def test_flag_rdc_a_una_persona(self):
        regole = {"flag:rdc": "persona:42"}
        riga = {**_RIGA, "aprire_rdc": 1, "numero_rdc": ""}
        self.assertEqual(rc.destinazione(riga, dq._info_vuota(), regole), {"p:42"})
        # Con il numero RDC la riga non corrisponde più: regola di serie.
        self.assertEqual(rc.destinazione({**riga, "numero_rdc": "RDC-1"}, dq._info_vuota(), regole), {"qualita"})

    def test_fase_vince_sulle_righe_sotto(self):
        regole = {"fase:da_decidere": "ruolo:car_op", "altre": "ruolo:controllore"}
        self.assertEqual(rc.destinazione(_RIGA, dq._info_vuota(), regole), {"car_op"})
        self.assertEqual(rc.destinazione({**_RIGA, "avanzamento": "Accetto lo stato"}, dq._info_vuota(), regole),
                         {"controllore"})

    def test_avanzamento_qualita_e_avanzamento(self):
        info = {**dq._info_vuota(), "avanzamento_qualita": "In attesa"}
        regole = {"qualita:in attesa": "persona:7", "avanzamento:Accetto lo stato": "ruolo:cc"}
        riga = {**_RIGA, "avanzamento": "Accetto lo stato"}
        self.assertEqual(rc.destinazione(riga, info, regole), {"p:7"})
        self.assertEqual(rc.destinazione(riga, dq._info_vuota(), regole), {"cc"})

    def test_in_carico_a_me_persona_e_car_op(self):
        with patch("anomalie.regole_carico.carica", return_value={"regole": {"altre": "persona:42"}, "nomi": {}}):
            riga = {**_RIGA, "aprire_rdc": 1}
            self.assertTrue(dq.in_carico_a_me({"legacy_id": 42}, riga, None))
            self.assertFalse(dq.in_carico_a_me({"qualita": True, "legacy_id": 5}, riga, None))
        with patch("anomalie.regole_carico.carica", return_value={"regole": {"altre": "ruolo:car_op"}, "nomi": {}}):
            self.assertTrue(dq.in_carico_a_me({"car_op": True}, {**_RIGA, "aprire_rdc": 1}, None))


class SalvaRegoleTests(TestCase):
    def tearDown(self):
        rc._CACHE["v"] = None  # la copia in memoria sopravvive al rollback del test

    def test_salva_e_carica(self):
        rc.salva({"flag:rdc": "persona:42", "altre": "ruolo:qualita", "x": "boh"}, {"42": "ROSSI MARIO", "9": "X"})
        dati = rc.carica()
        self.assertEqual(dati["regole"], {"flag:rdc": "persona:42", "altre": "ruolo:qualita"})
        self.assertEqual(dati["nomi"], {"42": "ROSSI MARIO"})


class StoriaModificabileTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="sup.storia", password="pass12345",
                                                               email="sup@example.com")
        self._p2 = [patch("anomalie.qualita_views.legacy_table_columns", return_value=_COLS)]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in self._p2:
            p.stop()
        super().tearDown()

    def _post(self, view, url, body, *args):
        request = RequestFactory().post(url, data=json.dumps(body), content_type="application/json")
        request.user = self.admin
        return view(request, *args)

    def test_passo_e_nota(self):
        r = self._post(rv.api_registro_passo, "/x", {"local_id": self.aid, "testo": "Telefonato al cliente"})
        self.assertEqual(r.status_code, 200, r.content)
        log = AnomaliaActionLog.objects.get(anomalia_id=self.aid, action="passo")
        self.assertEqual(log.note, "Telefonato al cliente")
        r = self._post(rv.api_registro_nota, "/x", {"testo": "Il cliente ha richiamato"}, log.pk)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(AnomaliaActionNota.objects.get(log=log).testo, "Il cliente ha richiamato")
        # L'evento non cambia; la nota compare nel registro sotto l'evento.
        request = RequestFactory().get("/api/anomalie/registro", data={"codice": f"AN-{self.aid}"})
        request.user = self.admin
        d = json.loads(rv.api_registro(request).content)
        ev = next(e for e in d["eventi"] if e["azione"] == "passo")
        self.assertEqual(ev["verbo"], "ha aggiunto un passo a")
        self.assertEqual(ev["note_margine"][0]["testo"], "Il cliente ha richiamato")

    def test_testo_vuoto_rifiutato(self):
        r = self._post(rv.api_registro_passo, "/x", {"local_id": self.aid, "testo": "  "})
        self.assertEqual(r.status_code, 400)

    def test_storia_di_una_anomalia_per_chi_vede_l_op(self):
        utente = get_user_model().objects.create_user(username="cc.storia", password="pass12345")
        request = RequestFactory().get("/api/anomalie/registro", data={"codice": f"AN-{self.aid}"})
        request.user = utente
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=True):
            self.assertEqual(rv.api_registro(request).status_code, 200)
        request = RequestFactory().get("/api/anomalie/registro")
        request.user = utente
        self.assertEqual(rv.api_registro(request).status_code, 403)
