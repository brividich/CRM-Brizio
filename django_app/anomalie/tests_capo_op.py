"""«Cambia capocommessa» su tutto l'OP o su alcune anomalie (``AnomaliaOpIncaricato``).
Dati sintetici; tabella legacy ``anomalie`` in SQLite."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, TestCase

from anomalie import incaricati as inc
from anomalie import incaricati_views as iv
from anomalie.mail_action_models import AnomaliaActionLog
from anomalie.quality_models import AnomaliaIncaricato, AnomaliaOpIncaricato
from anomalie.tests_rdc_attesa import OP, _COLS, _TabellaAnomalieMixin

ALTRO_OP = "OP/2026/0999"


class CambiaCapoOpTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.aid2 = self._inserisci(OP, "LCN00010")
        self.aid_altro = self._inserisci(ALTRO_OP, "LCN00500")
        self.avvisi = []
        self._p2 = [
            patch("anomalie.qualita_views.legacy_table_columns", return_value=_COLS),
            patch("anomalie.views._capo_car_di_op", return_value=("BIANCHI LUCA", "")),
            patch("anomalie.incaricati.puo_cambiare_su_op", return_value=True),
            patch("anomalie.incaricati.puo_cambiare", return_value=True),
            patch("anomalie.incaricati.persona", side_effect=lambda uid: {"id": int(uid), "nome": f"PERSONA {uid}"}),
            patch("anomalie.incaricati.avvisa_op",
                  side_effect=lambda **kw: self.avvisi.append(kw) or {"mail": True, "email": "x@example.com"}),
        ]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in self._p2:
            p.stop()
        super().tearDown()

    def _inserisci(self, op, seriale, chiudere=0):
        with connection.cursor() as cur:
            cur.execute("INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, chiudere, avanzamento) "
                        "VALUES (%s, %s, 'Graffio', %s, 'In attesa')", [op, seriale, chiudere])
            return cur.lastrowid

    def _post(self, **dati):
        request = RequestFactory().post("/api/anomalie/incaricato/op", data=json.dumps({"op_id": OP, **dati}),
                                        content_type="application/json")
        request.user = self.user
        return iv.api_incaricato_op(request)

    def _cc(self, aid):
        return (inc.per_anomalie([aid]).get(aid) or {}).get("cc")

    def test_tutto_l_op_vale_per_tutte_le_anomalie_e_le_future(self):
        r = self._post(persona_id=42, nota="Passa a lui la commessa")
        self.assertEqual(r.status_code, 200, r.content)
        x = AnomaliaOpIncaricato.objects.get(op_key=OP.lower(), ruolo="cc")
        self.assertEqual((x.legacy_user_id, x.op_id), (42, OP))
        for aid in (self.aid, self.aid2):
            self.assertEqual((self._cc(aid)["id"], self._cc(aid)["op"]), (42, True))
        self.assertIsNone(self._cc(self.aid_altro))
        # Un'anomalia aperta dopo sull'OP lo eredita.
        nuova = self._inserisci(OP, "LCN00011")
        self.assertEqual(self._cc(nuova)["id"], 42)
        ev = AnomaliaActionLog.objects.get(anomalia_id=0, action="capo_op")
        self.assertEqual(ev.payload["modifiche"][0], ["Capocommessa dell'OP", "BIANCHI LUCA (di serie)", "PERSONA 42"])
        self.assertTrue(self.avvisi[0]["tutto_op"])
        self.assertEqual(self.avvisi[0]["persona_id"], 42)

    def test_tutto_l_op_toglie_le_scelte_fatte_sulle_singole_anomalie(self):
        AnomaliaIncaricato.objects.create(anomalia_id=self.aid, ruolo="cc", legacy_user_id=77, nome="PERSONA 77")
        r = self._post(persona_id=42)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(AnomaliaIncaricato.objects.filter(anomalia_id=self.aid, ruolo="cc").exists())
        self.assertEqual(self._cc(self.aid)["id"], 42)

    def test_scelta_su_alcune_anomalie_prevale_sull_op(self):
        self._post(persona_id=42)
        r = self._post(persona_id=50, ambito="anomalie", anomalie=[self.aid2])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._cc(self.aid2)["id"], 50)
        self.assertEqual(self._cc(self.aid)["id"], 42)
        self.assertFalse(self.avvisi[-1]["tutto_op"])
        # «Torna di serie» sulla singola: torna a seguire l'OP.
        r = self._post(persona_id="", ambito="anomalie", anomalie=[self.aid2])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._cc(self.aid2)["id"], 42)

    def test_solo_alcune_senza_cambiare_il_resto(self):
        r = self._post(persona_id=50, ambito="anomalie", anomalie=[self.aid])
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._cc(self.aid)["id"], 50)
        self.assertIsNone(self._cc(self.aid2))
        self.assertFalse(AnomaliaOpIncaricato.objects.exists())

    def test_torna_di_serie_su_tutto_l_op(self):
        self._post(persona_id=42)
        r = self._post(persona_id="")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(AnomaliaOpIncaricato.objects.exists())
        self.assertIsNone(self._cc(self.aid))
        self.assertEqual(self._post(persona_id="").status_code, 400)

    def test_stessa_persona_rifiutata(self):
        self._post(persona_id=42)
        self.assertEqual(self._post(persona_id=42).status_code, 400)

    def test_anomalia_di_un_altro_op_rifiutata(self):
        r = self._post(persona_id=50, ambito="anomalie", anomalie=[self.aid_altro])
        self.assertEqual(r.status_code, 400)
        self.assertFalse(AnomaliaIncaricato.objects.exists())

    def test_senza_permesso(self):
        with patch("anomalie.incaricati.puo_cambiare_su_op", return_value=False):
            self.assertEqual(self._post(persona_id=42).status_code, 403)
        with patch("anomalie.incaricati.puo_cambiare", return_value=False):
            self.assertEqual(self._post(persona_id=42, ambito="anomalie", anomalie=[self.aid]).status_code, 403)
        self.assertFalse(AnomaliaOpIncaricato.objects.exists())
        self.assertFalse(AnomaliaIncaricato.objects.exists())

    def test_nuovo_capocommessa_vede_e_modifica_l_op(self):
        self._post(persona_id=42)
        request = RequestFactory().get("/")
        request.user = self.user
        with patch("anomalie.views._request_legacy_user_id", return_value=42):
            self.assertIn(OP.lower(), inc.op_incaricato(request, ruoli={"cc"}))

    def test_mail_dell_op_al_nuovo_capocommessa(self):
        from automazioni.services import _resolve_op_recipients

        self._post(persona_id=42)
        with connection.cursor() as cur:
            cur.execute("CREATE TABLE ordini_produzione (title TEXT, capocomessa TEXT, incaricato TEXT)")
            cur.execute("INSERT INTO ordini_produzione VALUES (%s, 'BIANCHI', '')", [OP])
        try:
            with patch("anomalie.automazioni_service.contatto_operatore", return_value=("nuovo@example.com", "Nuovo Capo")):
                rec = _resolve_op_recipients(OP)
        finally:
            with connection.cursor() as cur:
                cur.execute("DROP TABLE ordini_produzione")
        self.assertEqual(rec, [{"email": "nuovo@example.com", "display": "Nuovo Capo", "role": "CC"}])
