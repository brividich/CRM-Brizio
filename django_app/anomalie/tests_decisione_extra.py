"""Decisione del capocommessa: «Dove sono i pezzi?», «Segnala a terzista», «Segnala a CAR»,
allegati della decisione e referenti RDC in «In carico a me». Dati sintetici."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase

from anomalie import automazioni_service as aus
from anomalie import views as av
from anomalie.quality_models import AnomaliaSchedaQualita

OP = "OP/2026/0991"


def _req():
    r = RequestFactory().post("/api/anomalie/salva")
    r.user = SimpleNamespace(is_authenticated=True, is_superuser=False, username="cc.test",
                             get_full_name=lambda: "Mario Prova")
    return r


class SeparaCarTests(SimpleTestCase):
    def test_testo_e_lista_senza_doppioni(self):
        self.assertEqual(aus.separa_car_scelti("Anna Verdi; anna verdi, Bruno Neri"), ["Anna Verdi", "Bruno Neri"])
        self.assertEqual(aus.separa_car_scelti(["  Carla  Bianchi ", ""]), ["Carla Bianchi"])
        self.assertEqual(aus.separa_car_scelti(None), [])


class AllegatoDecisioneTests(SimpleTestCase):
    def test_suffisso(self):
        self.assertTrue(av._is_allegato_decisione("abc123-cc__foto.jpg"))
        self.assertFalse(av._is_allegato_decisione("abc123__foto-cc.jpg"))
        self.assertFalse(av._is_allegato_decisione("abc123__foto.jpg"))
        self.assertTrue(av._ALLEGATI_FILE_ID_RE.match("abc123-cc__foto.jpg"))


class ReferenteRdcTests(SimpleTestCase):
    def _check(self, lista, nomi, email=""):
        r = _req()
        with patch.object(av, "_load_anomalie_lists", return_value={"referenti_rdc": lista}), \
                patch.object(av, "_request_name_norms", return_value=nomi), \
                patch.object(av, "_current_user_identity", return_value={"email_norm": email}):
            return av._is_referente_rdc(r)

    def test_nome_in_qualunque_ordine(self):
        self.assertTrue(self._check(["Paolo Rossi"], {"ROSSI PAOLO"}))

    def test_email(self):
        self.assertTrue(self._check(["referente@example.test"], set(), "REFERENTE@EXAMPLE.TEST"))

    def test_non_in_lista(self):
        self.assertFalse(self._check(["Paolo Rossi"], {"LUIGI ROSSI"}))
        self.assertFalse(self._check([], {"PAOLO ROSSI"}))


class ReferenteRdcModificaTests(SimpleTestCase):
    def _puo(self, referente, ha_rdc):
        r = _req()
        with patch.object(av, "get_legacy_user", return_value=None), \
                patch.object(av, "_request_anomalie_global_access_level", return_value="NONE"), \
                patch.object(av, "_is_referente_rdc", return_value=referente), \
                patch.object(av, "_op_ha_rdc_o_cliente", return_value=ha_rdc), \
                patch("core.permessi.sistema_ruoli_attivo", return_value=True), \
                patch.object(av, "_dati_op_per_permessi", return_value=("", "", set())), \
                patch.object(av, "_modifica_op_ruoli", return_value=False):
            return av._can_edit_anomalie_for_op(r, OP)

    def test_referente_modifica_op_con_rdc(self):
        self.assertTrue(self._puo(True, True))

    def test_referente_non_modifica_op_senza_rdc(self):
        self.assertFalse(self._puo(True, False))

    def test_non_referente_non_modifica(self):
        self.assertFalse(self._puo(False, True))


class SalvaDecisioneExtraTests(TestCase):
    def setUp(self):
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=501, op_titolo=OP)

    def _salva(self, data, *, puo=True):
        mandate = []
        with patch.object(av, "_can_edit_anomalie_for_op", return_value=puo), \
                patch.object(av, "_programma_mail_segnala_car",
                             side_effect=lambda req, sch, d, car: mandate.append(list(car))):
            av._salva_dove_pezzi_terzista(_req(), self.scheda, {"op_id": OP, **data})
        self.scheda.refresh_from_db()
        return mandate

    def test_salva_dove_pezzi_e_terzista(self):
        self._salva({"dove_pezzi": " Area NC ", "segnala_terzista": True})
        self.assertEqual(self.scheda.dove_pezzi, "Area NC")
        self.assertTrue(self.scheda.segnala_terzista)

    def test_senza_permesso_non_salva(self):
        self._salva({"dove_pezzi": "Area NC", "segnala_terzista": True}, puo=False)
        self.assertEqual(self.scheda.dove_pezzi, "")
        self.assertFalse(self.scheda.segnala_terzista)

    def test_campi_assenti_non_azzerano(self):
        self._salva({"dove_pezzi": "Reparto 2"})
        self._salva({"note": "altro"})
        self.assertEqual(self.scheda.dove_pezzi, "Reparto 2")

    def test_segnala_car_mail_solo_ai_nuovi(self):
        self.assertEqual(self._salva({"segnala_car": True, "car_segnalati": ["Anna Verdi"]}), [["Anna Verdi"]])
        self.assertTrue(self.scheda.segnala_car)
        self.assertIsNotNone(self.scheda.car_segnalati_il)
        # Stessa decisione risalvata: nessuna nuova mail.
        self.assertEqual(self._salva({"segnala_car": True, "car_segnalati": ["Anna Verdi"]}), [])
        # Aggiunto un CAR: mail solo a lui.
        self.assertEqual(self._salva({"segnala_car": True, "car_segnalati": ["Anna Verdi", "Bruno Neri"]}),
                         [["Bruno Neri"]])
        self.assertEqual(self.scheda.car_segnalati, "Anna Verdi; Bruno Neri")

    def test_segnala_car_senza_scelta_non_parte(self):
        self.assertEqual(self._salva({"segnala_car": True, "car_segnalati": []}), [])
        self.assertFalse(self.scheda.segnala_car)

    def test_togliere_la_spunta_azzera(self):
        self._salva({"segnala_car": True, "car_segnalati": ["Anna Verdi"]})
        self._salva({"segnala_car": False, "car_segnalati": ["Anna Verdi"]})
        self.assertFalse(self.scheda.segnala_car)
        self.assertEqual(self.scheda.car_segnalati, "")
        # Rispuntato: la mail riparte.
        self.assertEqual(self._salva({"segnala_car": True, "car_segnalati": ["Anna Verdi"]}), [["Anna Verdi"]])


class InviaSegnalazioneCarTests(TestCase):
    def test_nominativo_non_univoco_non_riceve(self):
        with patch("anomalie.mail_action_service.find_legacy_user_by_name", return_value=None), \
                patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}), \
                patch.object(aus, "_send") as send:
            esito = aus.invia_segnalazione_car(anomalia_id=1, op_id=OP, car=["Nome Ambiguo"])
        self.assertEqual(esito["non_trovati"], ["Nome Ambiguo"])
        send.assert_not_called()

    def test_mail_al_car_con_email(self):
        with patch("anomalie.mail_action_service.find_legacy_user_by_name", return_value=SimpleNamespace(id=77)), \
                patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}), \
                patch.object(aus, "contatto_operatore", return_value=("car@example.test", "Anna Verdi")), \
                patch.object(aus, "op_portal_link", return_value="http://hub.test/gestione-anomalie"), \
                patch.object(aus, "_send", return_value=True) as send:
            esito = aus.invia_segnalazione_car(anomalia_id=1, op_id=OP, car=["Anna Verdi"], seriale="SN-1",
                                               dove_pezzi="Area NC")
        self.assertEqual(esito["inviate"], 1)
        self.assertEqual(send.call_args.kwargs["to"], ["car@example.test"])
        self.assertEqual(send.call_args.kwargs["kind"], "segnala_car")
        self.assertIn("Area NC", "\n".join(send.call_args.kwargs["lines"]))

    def test_interruttore_spento(self):
        with patch("anomalie.escalation_config.get_escalation_config", return_value={"segnala_car_attivo": False}), \
                patch.object(aus, "_send") as send:
            esito = aus.invia_segnalazione_car(anomalia_id=1, op_id=OP, car=["Anna Verdi"])
        self.assertEqual(esito["inviate"], 0)
        send.assert_not_called()


class SegnalatoTests(TestCase):
    """Spunta «Segnalato»: registra quando e chi, nessuna mail di aggiornamento."""

    def setUp(self):
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=502, op_titolo=OP)

    def _post(self, body, *, riga=None, puo=True):
        import json

        r = RequestFactory().post("/api/anomalie/segnalato", data=json.dumps(body), content_type="application/json")
        r.user = _req().user
        riga = riga if riga is not None else {"id": 502, "ex_op_nominativo": OP, "segnalare_cliente": 1}
        with patch.object(av, "_has_table", return_value=True), \
                patch.object(av, "_fetch_all_dict", return_value=[riga]), \
                patch.object(av, "_can_edit_anomalie_for_op", return_value=puo), \
                patch("anomalie.qualita_service.sync_da_anomalia", return_value=self.scheda), \
                patch.object(av, "_current_user_identity", return_value={"name": "Mario Prova"}), \
                patch.object(av, "get_legacy_user", return_value=None), \
                patch.object(av, "log_action"), \
                patch("anomalie.mail_action_service.log_anomalia_portal_action") as timeline, \
                patch("anomalie.mail_action_service.register_pending_update") as coda, \
                patch.object(av, "_programma_mail_segnala_car") as car:
            resp = av.api_segnalato.__wrapped__(r)
        coda.assert_not_called()
        car.assert_not_called()
        self.scheda.refresh_from_db()
        return resp, timeline

    def test_segnalato_cliente_registra_senza_mail(self):
        resp, timeline = self._post({"local_id": 502, "chi": "cliente", "segnalato": True})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self.scheda.segnalato_cliente_il)
        self.assertEqual(self.scheda.segnalato_cliente_da, "Mario Prova")
        self.assertEqual(timeline.call_args.kwargs["action"], "segnalato")

    def test_togliere_la_spunta(self):
        self._post({"local_id": 502, "chi": "cliente", "segnalato": True})
        self._post({"local_id": 502, "chi": "cliente", "segnalato": False})
        self.assertIsNone(self.scheda.segnalato_cliente_il)
        self.assertEqual(self.scheda.segnalato_cliente_da, "")

    def test_terzista_solo_se_richiesto(self):
        resp, _t = self._post({"local_id": 502, "chi": "terzista", "segnalato": True})
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(self.scheda.segnalato_terzista_il)
        self.scheda.segnala_terzista = True
        self.scheda.save()
        resp, _t = self._post({"local_id": 502, "chi": "terzista", "segnalato": True})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(self.scheda.segnalato_terzista_il)

    def test_cliente_non_richiesto(self):
        resp, _t = self._post({"local_id": 502, "chi": "cliente", "segnalato": True},
                              riga={"id": 502, "ex_op_nominativo": OP, "segnalare_cliente": 0})
        self.assertEqual(resp.status_code, 400)

    def test_senza_permesso(self):
        resp, _t = self._post({"local_id": 502, "chi": "cliente", "segnalato": True}, puo=False)
        self.assertEqual(resp.status_code, 403)
        self.assertIsNone(self.scheda.segnalato_cliente_il)

    def test_payload_lista(self):
        self._post({"local_id": 502, "chi": "cliente", "segnalato": True})
        rows = [{"local_id": 502}]
        av._segna_dove_pezzi_terzista(rows)
        self.assertEqual(rows[0]["segnalato_cliente"]["da"], "Mario Prova")
        self.assertIsNone(rows[0]["segnalato_terzista"])
