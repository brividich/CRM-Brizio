"""Link mail del capocommessa allineato alla pagina Gestione anomalie: scelte di
avanzamento da Configurazione, «A quale CAR?», «Pezzi precedenti al benestare».
Dati sintetici."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from anomalie import mail_action_views as mv
from anomalie import segnalato_service as segn
from anomalie import views as av
from anomalie.quality_models import AnomaliaSchedaQualita

OP = "OP/2026/0992"


class SceltePaginaTests(SimpleTestCase):
    def test_avanzamenti_da_configurazione(self):
        with patch.object(av, "_load_anomalie_lists", return_value={"avanzamenti": ["Accetto lo stato", " Rilavorare ", ""]}):
            self.assertEqual(mv._avanzamenti_config(), ["Accetto lo stato", "Rilavorare"])

    def test_avanzamenti_vuoti_tornano_ai_predefiniti(self):
        with patch.object(av, "_load_anomalie_lists", return_value={}):
            self.assertEqual(mv._avanzamenti_config(), ["Accetto lo stato", "In attesa", "Finito trattato"])

    def test_car_opzioni_op_capi_reparto_e_gia_scelti(self):
        with patch.object(av, "_load_anomalie_lists", return_value={"capi_reparto": ["Bruno Neri", "anna verdi"]}):
            out = mv._car_opzioni("Anna Verdi | Carla Bianchi", [{"car_segnalati": ["Dario Gialli"]}])
        self.assertEqual(out, ["Anna Verdi", "Carla Bianchi", "Bruno Neri", "Dario Gialli"])


class SegnalaCarDalLinkTests(TestCase):
    def setUp(self):
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=601, op_titolo=OP)
        self.token = SimpleNamespace(op_id=OP, recipient_display="Mario Prova", recipient_email="")

    def _salva(self, car, scelti):
        stato = {"terzista": False, "car": car, "car_scelti": scelti,
                 "segnalati": {c: False for c in segn.DESTINATARI}, "gia": {c: False for c in segn.DESTINATARI},
                 "risposte": {c: "" for c in segn.DESTINATARI}, "risposta_info": ""}
        with patch.object(mv, "_car_di_op", return_value="Anna Verdi"), \
                patch.object(av, "_load_anomalie_lists", return_value={"capi_reparto": ["Bruno Neri"]}), \
                patch("anomalie.automazioni_service.invia_segnalazione_car") as invia:
            mv._salva_segnalati_mail(self.token, 601, stato)
        self.scheda.refresh_from_db()
        return [c.kwargs["car"] for c in invia.call_args_list]

    def test_mail_solo_ai_car_scelti_e_nuovi(self):
        self.assertEqual(self._salva(True, ["Bruno Neri"]), [["Bruno Neri"]])
        self.assertTrue(self.scheda.segnala_car)
        self.assertEqual(self.scheda.car_segnalati, "Bruno Neri")
        self.assertEqual(self._salva(True, ["Bruno Neri", "Anna Verdi"]), [["Anna Verdi"]])

    def test_nome_fuori_elenco_ignorato(self):
        self.assertEqual(self._salva(True, ["Estraneo Qualunque"]), [])
        self.assertFalse(self.scheda.segnala_car)

    def test_form_vecchio_senza_scelta_usa_car_dell_op(self):
        self.assertEqual(self._salva(True, None), [["Anna Verdi"]])


class PezziPrecedentiTests(SimpleTestCase):
    def test_aggiorna_pezzo_recuperato(self):
        eseguite = []

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params):
                eseguite.append((sql, params))

        conn = SimpleNamespace(cursor=lambda: _Cur())
        with patch("django.db.connections", {"default": conn}):
            ok = mv._apply_action_to_anomalia(anomalia_id=7, op_id=OP, action="aggiorna", nuovo_avanzamento="",
                                              note=None, pezzi_prec=True)
        self.assertTrue(ok)
        self.assertIn("pezzo_recuperato = %s", eseguite[0][0])
        self.assertEqual(eseguite[0][1], [1, 7])
