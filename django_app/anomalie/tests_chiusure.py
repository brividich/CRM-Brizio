"""Chiusure delle anomalie (26/11/2026): numero RDC con attesa del cliente, stati di
Configurazione, «Azione di recupero» + «Chiudi», stato finale, richieste aperte,
«Chiudi» con nota. Dati sintetici; tabella legacy ``anomalie`` in SQLite."""
from __future__ import annotations

from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from anomalie import views as av
from anomalie.chiusura_service import NOTA_RICHIESTA_CHIUSA, dopo_chiusura
from anomalie.mail_action_models import AnomaliaActionLog
from anomalie.quality_models import AnomaliaRichiestaInfo, AnomaliaSchedaQualita
from anomalie.segnalato_service import stato_canonico
from anomalie.tempi_service import serve_azione_per_chiudere
from anomalie.tests_rdc_attesa import OP, _TabellaAnomalieMixin, _fetch_sqlite

CLIENTE = av.AVANZAMENTO_RISPOSTA_CLIENTE
VARIANTE = "Avanzamento + In attesa di risposta cliente"
RISERVA = "Accettato con riserva ( necessario ripetere controlli successivi)"


class RegolaTests(SimpleTestCase):
    def test_numero_rdc_chiude_anche_in_attesa_del_cliente(self):
        self.assertTrue(av.chiusura_automatica(True, "592/2026", True, True, CLIENTE))
        self.assertTrue(av.chiusura_automatica(True, "590/2026", True, True, VARIANTE))

    def test_numero_rdc_non_chiude_senza_segnalato_o_con_chiarimenti(self):
        self.assertFalse(av.chiusura_automatica(True, "592/2026", True, False, CLIENTE))
        self.assertFalse(av.chiusura_automatica(True, "592/2026", True, True, CLIENTE, chiarimenti=True))
        self.assertFalse(av.chiusura_automatica(True, "592/2026", False, False, av.AVANZAMENTO_INFO_RICHIESTE))

    def test_senza_rdc_l_attesa_tiene_aperta_anche_la_variante(self):
        self.assertFalse(av.chiusura_automatica(False, "", True, True, CLIENTE))
        self.assertFalse(av.chiusura_automatica(False, "", True, True, VARIANTE))

    def test_accettato_con_riserva_chiude(self):
        self.assertTrue(av.chiusura_automatica(False, "", False, False, RISERVA))
        self.assertFalse(av.chiusura_automatica(False, "", False, False, RISERVA, cc_chiude=False))
        self.assertFalse(av.chiusura_automatica(False, "", False, False, "Finito trattato"))

    def test_stato_canonico(self):
        self.assertEqual(stato_canonico(VARIANTE), CLIENTE.lower())
        self.assertEqual(stato_canonico("  In attesa   risposta terzista "), av.AVANZAMENTO_RISPOSTA_TERZISTA.lower())
        self.assertEqual(stato_canonico("Accetto lo stato"), "accetto lo stato")


class ServeAzioneTests(TestCase):
    def test_prima_decisione_nello_stesso_salvataggio(self):
        self.assertTrue(serve_azione_per_chiudere(901, "Azione di recupero"))
        self.assertFalse(serve_azione_per_chiudere(901, "Accetto lo stato"))
        AnomaliaSchedaQualita.objects.create(anomalia_id=901, op_titolo=OP)
        self.assertTrue(serve_azione_per_chiudere(901, "Azione di recupero"))

    def test_prima_decisione_gia_scritta_vince(self):
        AnomaliaSchedaQualita.objects.create(anomalia_id=902, op_titolo=OP, prima_decisione_il=timezone.now(),
                                             primo_avanzamento="Accetto lo stato")
        self.assertFalse(serve_azione_per_chiudere(902, "Azione di recupero"))
        AnomaliaSchedaQualita.objects.create(anomalia_id=903, op_titolo=OP, prima_decisione_il=timezone.now(),
                                             primo_avanzamento="Azione di recupero")
        self.assertTrue(serve_azione_per_chiudere(903, "Accetto lo stato"))

    def test_azione_effettuata(self):
        AnomaliaSchedaQualita.objects.create(anomalia_id=904, op_titolo=OP, azione_effettuata_il=timezone.now())
        self.assertFalse(serve_azione_per_chiudere(904, "Azione di recupero"))


class SalvaChiusureTests(_TabellaAnomalieMixin, TestCase):
    def setUp(self):
        super().setUp()
        # La vera verifica dell'azione effettuata (il mixin la spegne).
        self._p_serve = patch("anomalie.views._serve_azione_per_chiudere",
                              side_effect=lambda aid, nuovo=None: serve_azione_per_chiudere(aid, nuovo))
        self._p_serve.start()

    def tearDown(self):
        self._p_serve.stop()
        super().tearDown()

    def _salva_err(self, **dati):
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = self.user
        return av._salva_riga_anomalia(request, {"item_id": f"local:{self.aid}", "op_id": OP, **dati},
                                       notifica_debounce=False)

    def test_azione_di_recupero_e_chiudi_insieme_rifiutato(self):
        esito = self._salva_err(avanzamento="Azione di recupero", note="Ripassare in macchina", chiudi_manuale=True)
        self.assertFalse(esito["success"])
        riga = _fetch_sqlite("SELECT chiudere FROM anomalie WHERE id = %s", [self.aid])[0]
        self.assertEqual(riga["chiudere"], 0)

    def test_chiudi_con_nota_chiede_lo_stato_anche_con_rdc(self):
        esito = self._salva_err(aprire_rdc=True, segnalare=True, avanzamento="In attesa", note="Rimandati a Metalsud",
                                chiudi_manuale=True)
        self.assertFalse(esito["success"])
        self.assertEqual(esito["error"], av.MSG_NOTA_STATO_IN_ATTESA)

    def test_numero_rdc_chiude_in_attesa_del_cliente(self):
        AnomaliaSchedaQualita.objects.create(anomalia_id=self.aid, op_titolo=OP, segnalato_cliente_il=timezone.now())
        riga = self._salva(aprire_rdc=True, numero_rdc="592/2026", segnalare=True, segnalato_cliente=True,
                           avanzamento=CLIENTE)
        self.assertEqual(riga["chiudere"], 1)

    def test_chiusura_chiude_le_richieste_e_riprende_l_ultima_decisione(self):
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="aggiorna", source="portal",
                                         new_status=CLIENTE)
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="riapri", source="portal",
                                         new_status="In attesa")
        AnomaliaRichiestaInfo.objects.create(anomalia_id=self.aid, destinatari=["cc"], messaggio="Quantificare")
        riga = self._salva(aprire_rdc=True, segnalare=True, avanzamento="In attesa", chiudi_manuale=True)
        self.assertEqual(riga["chiudere"], 1)
        self.assertEqual(riga["avanzamento"], CLIENTE)
        r = AnomaliaRichiestaInfo.objects.get(anomalia_id=self.aid)
        self.assertEqual((r.risposta, r.risposta_ruolo), (NOTA_RICHIESTA_CHIUSA, "chiusura"))
        self.assertIsNotNone(r.risposta_il)

    def test_senza_decisioni_resta_in_attesa(self):
        with connection.cursor() as cur:
            cur.execute("UPDATE anomalie SET chiudere = 1 WHERE id = %s", [self.aid])
        dopo_chiusura(self.aid)
        riga = _fetch_sqlite("SELECT avanzamento FROM anomalie WHERE id = %s", [self.aid])[0]
        self.assertEqual(riga["avanzamento"], "In attesa")

    def test_aperta_non_tocca_niente(self):
        AnomaliaActionLog.objects.create(anomalia_id=self.aid, op_id=OP, action="aggiorna", source="portal",
                                         new_status="Accetto lo stato")
        AnomaliaRichiestaInfo.objects.create(anomalia_id=self.aid, destinatari=["cc"], messaggio="?")
        dopo_chiusura(self.aid)
        self.assertEqual(_fetch_sqlite("SELECT avanzamento FROM anomalie WHERE id = %s", [self.aid])[0]["avanzamento"],
                         "In attesa")
        self.assertEqual(AnomaliaRichiestaInfo.objects.filter(risposta_il__isnull=True).count(), 1)


class RiepilogoChiusaTests(TestCase):
    """Mail «Aggiornamento anomalie»: dice se l'anomalia è chiusa, anche se la chiusura è
    arrivata dopo il salvataggio messo in coda (es. «Registra e chiudi» in «Tempi ed esiti»)."""

    def _invia(self, righe_live, updates):
        from django.core import mail

        from anomalie.mail_action_service import send_anomalie_update_confirmation

        with patch("automazioni.services._resolve_op_recipients", return_value=[]), \
             patch("anomalie.mail_action_service._resolve_segnalante_email", return_value=("op@example.local", "Op")), \
             patch("anomalie.mail_action_service._resolve_lista_fissa_conferma", return_value=[]), \
             patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}), \
             patch("anomalie.views._fetch_all_dict", return_value=righe_live):
            self.assertTrue(send_anomalie_update_confirmation(op_id=OP, op_nominativo=OP, anomalie_rows=[],
                                                              updates_summary=updates))
        return mail.outbox[-1]

    def test_chiusura_arrivata_dopo_la_coda(self):
        msg = self._invia([{"id": 320, "chiudere": 1, "avanzamento": "Azione di recupero"}],
                          [{"id": 320, "seriale": "SN-1", "avanzamento": "Azione di recupero", "chiudere": False,
                            "azione_effettuata": "Riparazione · pezzo riverificato conforme"}])
        self.assertTrue(msg.subject.endswith("· 1 chiusa"), msg.subject)
        self.assertIn("[Chiusa]", msg.body)
        self.assertIn("Azione effettuata: Riparazione", msg.body)
        html = msg.alternatives[0][0]
        self.assertIn("Anomalia chiusa", html)
        self.assertIn("Chiusa", html)

    def test_riaperta_dopo_la_coda_non_risulta_chiusa(self):
        msg = self._invia([{"id": 321, "chiudere": 0, "avanzamento": "In attesa"}],
                          [{"id": 321, "seriale": "SN-2", "avanzamento": "Accetto lo stato", "chiudere": True}])
        self.assertNotIn("chius", msg.subject)
        self.assertNotIn("[Chiusa]", msg.body)
