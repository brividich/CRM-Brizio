"""Decisione qualità, «in carico» per singola anomalia, richieste di informazioni e
«Il capocommessa può chiudere». Dati sintetici; tabella legacy ``anomalie`` in SQLite."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from anomalie import decisione_qualita as dq
from anomalie import qualita_views as qv
from anomalie import views as av
from anomalie.quality_models import AnomaliaRichiestaInfo, AnomaliaSchedaQualita
from anomalie.tests_rdc_attesa import OP, _COLS, _TabellaAnomalieMixin

_RIGA = {"chiudere": 0, "aprire_rdc": 0, "segnalare_cliente": 0, "note_capocommessa": "", "avanzamento": "In attesa"}


class RuoliInCaricoTests(SimpleTestCase):
    def test_da_decidere_al_capocommessa(self):
        self.assertEqual(dq.ruoli_in_carico(_RIGA, None), {"cc"})

    def test_decisa_alla_qualita(self):
        self.assertEqual(dq.ruoli_in_carico({**_RIGA, "aprire_rdc": 1}, None), {"qualita"})
        self.assertEqual(dq.ruoli_in_carico({**_RIGA, "avanzamento": "Azione di recupero"}, None), {"qualita"})

    def test_chiusa_a_nessuno(self):
        self.assertEqual(dq.ruoli_in_carico({**_RIGA, "chiudere": 1}, None), set())

    def test_richiesta_aperta_a_chi_deve_rispondere(self):
        info = {**dq._info_vuota(), "richiesta_aperta": ["controllore"]}
        self.assertEqual(dq.ruoli_in_carico({**_RIGA, "aprire_rdc": 1}, info), {"controllore"})

    def test_attesa_risposta_a_chi_ha_segnalato(self):
        riga = {**_RIGA, "segnalare_cliente": 1, "avanzamento": av.AVANZAMENTO_RISPOSTA_CLIENTE}
        self.assertEqual(dq.ruoli_in_carico(riga, {**dq._info_vuota(), "segnalato_cliente_ruolo": "qualita"}), {"qualita"})
        self.assertEqual(dq.ruoli_in_carico(riga, dq._info_vuota()), {"cc"})

    def test_ulteriori_informazioni_al_capocommessa(self):
        riga = {**_RIGA, "aprire_rdc": 1, "avanzamento": av.AVANZAMENTO_INFO_RICHIESTE}
        self.assertEqual(dq.ruoli_in_carico(riga, None), {"cc"})

    def test_car_solo_se_segnalato(self):
        info = {**dq._info_vuota(), "car_assegnati": ["Anna Neri"]}
        self.assertIn("car", dq.ruoli_in_carico({**_RIGA, "aprire_rdc": 1}, info))
        self.assertNotIn("car", dq.ruoli_in_carico({**_RIGA, "aprire_rdc": 1}, None))

    def test_in_carico_a_me(self):
        riga = {**_RIGA, "aprire_rdc": 1, "created_by_user_id": 9}
        self.assertTrue(dq.in_carico_a_me({"qualita": True}, riga, None))
        self.assertFalse(dq.in_carico_a_me({"cc": True}, riga, None))
        info = {**dq._info_vuota(), "richiesta_aperta": ["controllore"]}
        self.assertTrue(dq.in_carico_a_me({"legacy_id": 9}, riga, info))


class ChiusuraRegolaTests(SimpleTestCase):
    def test_segnalato_senza_rdc_chiude(self):
        self.assertTrue(av.chiusura_automatica(False, "", True, True, "In attesa"))
        self.assertTrue(av.chiusura_automatica(False, "", False, False, "In attesa", True, True))

    def test_con_rdc_serve_il_numero(self):
        self.assertFalse(av.chiusura_automatica(True, "", True, True, "In attesa"))
        self.assertTrue(av.chiusura_automatica(True, "RDC-1", True, True, "In attesa"))

    def test_chiarimenti_tengono_aperta(self):
        self.assertFalse(av.chiusura_automatica(False, "", True, True, "In attesa", chiarimenti=True))

    def test_capocommessa_che_non_chiude(self):
        self.assertFalse(av.chiusura_automatica(False, "", False, False, "Accetto lo stato", cc_chiude=False))
        self.assertTrue(av.chiusura_automatica(False, "", False, False, "Accetto lo stato", cc_chiude=True))


class DecisioneQualitaApiTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=self.aid, op_titolo=OP)
        self._p2 = [
            patch("anomalie.qualita_views.legacy_table_columns", return_value=_COLS),
            patch("anomalie.qualita_views.puo_decisione_qualita", return_value=True),
            patch("anomalie.qualita_mail.invia_richiesta_info", return_value={"inviate": 1}),
            patch("anomalie.qualita_mail.invia_risposta_info"),
        ]
        for p in self._p2:
            p.start()

    def tearDown(self):
        for p in self._p2:
            p.stop()
        super().tearDown()

    def _post(self, view, **dati):
        request = RequestFactory().post("/x", data=json.dumps({"local_id": self.aid, **dati}),
                                        content_type="application/json")
        request.user = self.user
        return view(request)

    def _riga(self):
        from anomalie.tests_rdc_attesa import _fetch_sqlite
        return _fetch_sqlite("SELECT * FROM anomalie WHERE id = %s", [self.aid])[0]

    def test_numero_rdc_della_qualita_chiude(self):
        self._salva(aprire_rdc=True, avanzamento="In attesa", note="Aprire RDC")
        self.assertEqual(self._riga()["chiudere"], 0)
        r = self._post(qv.api_qualita_salva, numero_rdc="RDC-2026-9", avanzamento_qualita="In attesa")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self._riga()["numero_rdc"], self._riga()["chiudere"]), ("RDC-2026-9", 1))

    def test_capocommessa_non_cancella_il_numero_rdc(self):
        self._salva(aprire_rdc=True, avanzamento="In attesa", note="x")
        self._post(qv.api_qualita_salva, numero_rdc="", avanzamento_qualita="In attesa")
        with connection_cursor() as cur:
            cur.execute("UPDATE anomalie SET numero_rdc = 'RDC-7' WHERE id = %s", [self.aid])
        self._salva(aprire_rdc=True, avanzamento="In attesa", note="y")
        self.assertEqual(self._riga()["numero_rdc"], "RDC-7")

    def test_segnalato_dalla_qualita(self):
        self._salva(segnalare=True, avanzamento="In attesa", note="Da segnalare")
        self.assertEqual(self._riga()["chiudere"], 0)
        r = self._post(qv.api_qualita_salva, segnalato_cliente=True, avanzamento_qualita="")
        self.assertEqual(r.status_code, 200, r.content)
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.segnalato_cliente_ruolo, "qualita")
        self.assertEqual(self._riga()["chiudere"], 1)

    def test_chiudi_della_qualita(self):
        self._salva(aprire_rdc=True, avanzamento="In attesa", note="x")
        r = self._post(qv.api_qualita_salva, chiudi=True, note_qualita="Chiusa dalla qualità")
        self.assertTrue(json.loads(r.content)["chiusa"])
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.note_qualita, "Chiusa dalla qualità")

    def test_avanzamento_fuori_lista_rifiutato(self):
        r = self._post(qv.api_qualita_salva, avanzamento_qualita="Inventato")
        self.assertEqual(r.status_code, 400)

    def test_solo_la_qualita(self):
        with patch("anomalie.qualita_views.puo_decisione_qualita", return_value=False):
            self.assertEqual(self._post(qv.api_qualita_salva, avanzamento_qualita="").status_code, 403)
            self.assertEqual(self._post(qv.api_qualita_richiedi_info, destinatari=["cc"], messaggio="?").status_code, 403)

    def test_richiesta_e_risposta_info(self):
        self._salva(aprire_rdc=True, avanzamento="In attesa", note="x")
        r = self._post(qv.api_qualita_richiedi_info, destinatari=["cc", "controllore"], messaggio="Serve la misura")
        self.assertEqual(r.status_code, 200, r.content)
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.avanzamento_qualita, dq.AVANZAMENTO_CHIARIMENTI)
        info = dq.info_per_anomalie([self.aid])[self.aid]
        self.assertEqual(sorted(info["richiesta_aperta"]), ["cc", "controllore"])
        # Con la richiesta aperta non si chiude da sola.
        self._post(qv.api_qualita_salva, numero_rdc="RDC-1", avanzamento_qualita=dq.AVANZAMENTO_CHIARIMENTI)
        self.assertEqual(self._riga()["chiudere"], 0)
        # Risponde il capocommessa: la richiesta resta aperta per il controllore.
        r = self._post(qv.api_qualita_rispondi_info, testo="Misura 12,04")
        self.assertEqual(r.status_code, 200, r.content)
        richiesta = AnomaliaRichiestaInfo.objects.get(anomalia_id=self.aid)
        self.assertEqual(richiesta.risposta, "Misura 12,04")
        self.assertFalse(richiesta.aperta)
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.avanzamento_qualita, "In attesa")

    def test_risposta_senza_richiesta(self):
        r = self._post(qv.api_qualita_rispondi_info, testo="ciao")
        self.assertEqual(r.status_code, 400)


class CapocommessaChiudeConfigTests(_TabellaAnomalieMixin, TestCase):
    def test_spento_non_chiude_ne_con_stato_ne_a_mano(self):
        with patch("anomalie.decisione_qualita.cc_puo_chiudere", return_value=False):
            riga = self._salva(avanzamento="Accetto lo stato", chiudere=True, note="ok")
            self.assertEqual(riga["chiudere"], 0)
            riga = self._salva(avanzamento="Finito trattato", chiudi_manuale=True, note="ok")
            self.assertEqual(riga["chiudere"], 0)

    def test_acceso_chiude(self):
        riga = self._salva(avanzamento="Accetto lo stato", chiudere=True, note="ok")
        self.assertEqual(riga["chiudere"], 1)

    def test_salvataggio_configurazione(self):
        self.assertTrue(dq.cc_puo_chiudere())
        dq.salva_cc_puo_chiudere(False)
        self.assertFalse(dq.cc_puo_chiudere())


def connection_cursor():
    from django.db import connection
    return connection.cursor()


class CodiceAnomaliaTests(SimpleTestCase):
    def test_codice_e_ritorno(self):
        from anomalie.codice import codice_anomalia, id_da_codice

        self.assertEqual(codice_anomalia(123), "AN-00123")
        self.assertEqual(codice_anomalia("local:7"), "AN-00007")
        self.assertEqual(codice_anomalia(None), "")
        for testo in ("AN-00123", "an123", "#123", "123"):
            self.assertEqual(id_da_codice(testo), 123)

    def test_filtro_template(self):
        from django.template import Context, Template

        self.assertEqual(Template("{% load anomalie_extra %}{{ x|codice_anomalia }}").render(Context({"x": 5})), "AN-00005")
