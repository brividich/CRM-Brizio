"""Incaricato per singola anomalia e registro attività (clona, allegati, eliminazione).
Dati sintetici; tabella legacy ``anomalie`` in SQLite."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from anomalie import decisione_qualita as dq
from anomalie import incaricati_views as iv
from anomalie import registro_views as rv
from anomalie.mail_action_models import AnomaliaActionLog
from anomalie.quality_models import AnomaliaIncaricato
from anomalie.tests_rdc_attesa import OP, _COLS, _TabellaAnomalieMixin

_RIGA = {"chiudere": 0, "aprire_rdc": 0, "segnalare_cliente": 0, "note_capocommessa": "", "avanzamento": "In attesa",
         "created_by_user_id": 9}


class InCaricoConIncaricatoTests(SimpleTestCase):
    def _info(self, **inc):
        return {**dq._info_vuota(), "incaricati": {r: {"id": uid, "nome": f"Persona {uid}"} for r, uid in inc.items()}}

    def test_ruolo_affidato_tocca_solo_all_incaricato(self):
        info = self._info(cc=42)
        self.assertTrue(dq.in_carico_a_me({"legacy_id": 42}, _RIGA, info))
        # Il capocommessa di serie non ce l'ha più in carico.
        self.assertFalse(dq.in_carico_a_me({"cc": True, "legacy_id": 7}, _RIGA, info))

    def test_senza_incaricato_vale_la_regola_di_serie(self):
        self.assertTrue(dq.in_carico_a_me({"cc": True}, _RIGA, dq._info_vuota()))

    def test_incaricato_di_un_altro_ruolo_non_conta_finche_non_tocca_a_lui(self):
        info = self._info(qualita=42)
        self.assertFalse(dq.in_carico_a_me({"legacy_id": 42}, _RIGA, info))
        self.assertTrue(dq.in_carico_a_me({"legacy_id": 42}, {**_RIGA, "aprire_rdc": 1}, info))
        self.assertFalse(dq.in_carico_a_me({"qualita": True, "legacy_id": 5}, {**_RIGA, "aprire_rdc": 1}, info))


class CambiaIncaricatoApiTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.avvisi = []
        self._p2 = [
            patch("anomalie.qualita_views.legacy_table_columns", return_value=_COLS),
            patch("anomalie.views._capo_car_di_op", return_value=("BIANCHI LUCA", "")),
            patch("anomalie.incaricati.puo_cambiare", return_value=True),
            patch("anomalie.incaricati.persona", side_effect=lambda uid: {"id": int(uid), "nome": f"PERSONA {uid}"}),
            patch("anomalie.incaricati.avvisa", side_effect=lambda **kw: self.avvisi.append(kw) or {"mail": True, "email": "x@example.com"}),
        ]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in self._p2:
            p.stop()
        super().tearDown()

    def _post(self, **dati):
        request = RequestFactory().post("/api/anomalie/incaricato", data=json.dumps({"local_id": self.aid, **dati}),
                                        content_type="application/json")
        request.user = self.user
        return iv.api_incaricato_cambia(request)

    def test_affida_registra_e_avvisa(self):
        r = self._post(ruolo="cc", persona_id=42, nota="Segue lui la commessa")
        self.assertEqual(r.status_code, 200, r.content)
        d = json.loads(r.content)
        self.assertEqual(d["incaricati"]["cc"]["nome"], "PERSONA 42")
        x = AnomaliaIncaricato.objects.get(anomalia_id=self.aid, ruolo="cc")
        self.assertEqual((x.legacy_user_id, x.nota), (42, "Segue lui la commessa"))
        ev = AnomaliaActionLog.objects.get(anomalia_id=self.aid, action="incaricato")
        self.assertEqual(ev.payload["modifiche"], [["Incaricato capocommessa", "BIANCHI LUCA (di serie)", "PERSONA 42"]])
        self.assertEqual(self.avvisi[0]["persona_id"], 42)

    def test_torna_di_serie(self):
        self._post(ruolo="cc", persona_id=42)
        r = self._post(ruolo="cc", persona_id="")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(AnomaliaIncaricato.objects.filter(anomalia_id=self.aid).exists())
        self.assertEqual(AnomaliaActionLog.objects.filter(anomalia_id=self.aid, action="incaricato").count(), 2)

    def test_stessa_persona_rifiutata(self):
        self._post(ruolo="cc", persona_id=42)
        r = self._post(ruolo="cc", persona_id=42)
        self.assertEqual(r.status_code, 400)

    def test_senza_permesso(self):
        with patch("anomalie.incaricati.puo_cambiare", return_value=False):
            r = self._post(ruolo="cc", persona_id=42)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(AnomaliaIncaricato.objects.exists())

    def test_ruolo_non_valido(self):
        self.assertEqual(self._post(ruolo="boh", persona_id=42).status_code, 400)


class RegistroNuoveAzioniTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="sup.reg", password="pass12345",
                                                               email="sup@example.com")

    def _registro(self, **filtri):
        request = RequestFactory().get("/api/anomalie/registro", data=filtri)
        request.user = self.admin
        return json.loads(rv.api_registro(request).content)

    def test_clona_allegati_eliminazione_incaricato(self):
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="crea", user_display="A",
                                         payload={"clonata_da": 7})
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="allegato", user_display="A",
                                         note="foto.jpg", payload={"allegati": ["foto.jpg"], "dove": "decisione qualità"})
        AnomaliaActionLog.objects.create(anomalia_id=999, op_id=OP, action="elimina", user_display="A",
                                         payload={"seriale": "LCN00077"})
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="incaricato", user_display="A",
                                         payload={"modifiche": [["Incaricato CAR", "x (di serie)", "Y"]]})
        d = self._registro()
        verbi = {e["azione"]: e for e in d["eventi"]}
        self.assertEqual(verbi["crea"]["verbo"], "ha clonato da AN-00007")
        self.assertEqual(verbi["allegato"]["verbo"], "ha allegato file alla decisione qualità di")
        self.assertEqual(verbi["elimina"]["seriale"], "LCN00077")
        self.assertEqual(verbi["incaricato"]["modifiche"][0][2], "Y")
        self.assertEqual([e["azione"] for e in self._registro(azione="allegati")["eventi"]], ["allegato"])
        self.assertEqual([e["azione"] for e in self._registro(azione="clona")["eventi"]], ["crea"])
