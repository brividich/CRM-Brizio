"""«Aprire RDC» / «Segnalare al cliente» non chiudono l'anomalia; «In attesa di ulteriori
informazioni» la rimanda al capocommessa con le spunte aperte. Dati sintetici; tabella
legacy ``anomalie`` in SQLite come in ``tests_tempi``."""
from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone

from anomalie import views as av
from anomalie.quality_models import AnomaliaSchedaQualita

User = get_user_model()
OP = "OP/2026/0555"
_COLS = {"id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "aprire_rdc", "numero_rdc",
         "segnalare_cliente", "chiudere", "avanzamento", "created_datetime"}
INFO = av.AVANZAMENTO_INFO_RICHIESTE


def _fetch_sqlite(sql, params=None):
    sql = sql.replace("SELECT TOP 1 ", "SELECT ")
    with connection.cursor() as cur:
        cur.execute(sql, params or [])
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


class ChiusuraAutomaticaTests(SimpleTestCase):
    def test_rdc_senza_numero_resta_aperta(self):
        self.assertFalse(av.chiusura_automatica(True, "", False, False, "Apertura ORE/RIPI"))
        self.assertFalse(av.chiusura_automatica(True, "  ", False, False, "Accetto lo stato"))

    def test_rdc_con_numero_si_chiude(self):
        self.assertTrue(av.chiusura_automatica(True, "RDC-2026-001", False, False, "Apertura ORE/RIPI"))

    def test_segnalare_senza_segnalato_resta_aperta(self):
        self.assertFalse(av.chiusura_automatica(False, "", True, False, "Accetto lo stato"))
        self.assertTrue(av.chiusura_automatica(False, "", True, True, "Accetto lo stato"))

    def test_stati_attesa_tengono_aperta(self):
        self.assertFalse(av.chiusura_automatica(True, "RDC-1", False, False, INFO))
        self.assertFalse(av.chiusura_automatica(False, "", True, True, av.AVANZAMENTO_RISPOSTA_CLIENTE))

    def test_senza_spunte_regola_di_sempre(self):
        self.assertTrue(av.chiusura_automatica(False, "", False, False, "Accetto lo stato"))
        self.assertFalse(av.chiusura_automatica(False, "", False, False, "Finito trattato"))

    def test_stato_info_canonico(self):
        with patch.object(av, "_load_anomalie_lists", return_value={"avanzamenti": ["In attesa"]}):
            self.assertEqual(av._canonicalize_avanzamento("in attesa di ulteriori informazioni"), INFO)


class _TabellaAnomalieMixin:
    """Tabella legacy ``anomalie`` in SQLite e ``_salva`` sulla riga di prova."""

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, note_capocommessa TEXT, aprire_rdc INTEGER, numero_rdc TEXT, segnalare_cliente INTEGER, "
                "chiudere INTEGER, avanzamento TEXT, created_datetime TEXT)"
            )
            cur.execute("INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, chiudere, avanzamento, created_datetime) "
                        "VALUES (%s, 'LCN00009', 'Graffio', 0, 'In attesa', '2026-11-12 08:00:00')", [OP])
            self.aid = cur.lastrowid
        self.user = User.objects.create_user(username="cc.rdc", password="pass12345")
        self.notifiche = []
        self._patches = [
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=_COLS),
            patch("anomalie.views._fetch_all_dict", side_effect=_fetch_sqlite),
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views.get_legacy_user", return_value=None),
            patch("anomalie.views._decisione_su_propria_anomalia", return_value=""),
            patch("anomalie.views._serve_azione_per_chiudere", return_value=False),
            patch("anomalie.views._notify_anomalia_event",
                  side_effect=lambda req, ev, *a: self.notifiche.append(ev)),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def _salva(self, **dati):
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = self.user
        esito = av._salva_riga_anomalia(request, {"item_id": f"local:{self.aid}", "op_id": OP, **dati},
                                        notifica_debounce=False)
        self.assertTrue(esito["success"], esito)
        return _fetch_sqlite("SELECT * FROM anomalie WHERE id = %s", [self.aid])[0]



class SalvaRdcTests(_TabellaAnomalieMixin, TestCase):
    def test_aprire_rdc_non_chiude_anche_se_il_client_lo_chiede(self):
        riga = self._salva(aprire_rdc=True, avanzamento="Apertura ORE/RIPI", chiudere=True)
        self.assertEqual((riga["aprire_rdc"], riga["chiudere"]), (1, 0))

    def test_numero_rdc_chiude(self):
        riga = self._salva(aprire_rdc=True, numero_rdc="RDC-2026-014", avanzamento="Apertura ORE/RIPI", chiudere=True)
        self.assertEqual(riga["chiudere"], 1)

    def test_segnalare_chiude_solo_dopo_segnalato(self):
        riga = self._salva(segnalare=True, avanzamento="Accetto lo stato", chiudere=True)
        self.assertEqual(riga["chiudere"], 0)
        AnomaliaSchedaQualita.objects.create(anomalia_id=self.aid, op_titolo=OP, segnalato_cliente_il=timezone.now())
        riga = self._salva(segnalare=True, avanzamento="Accetto lo stato", chiudere=True)
        self.assertEqual(riga["chiudere"], 1)

    def test_info_richieste_lascia_spunte_e_avvisa_il_capocommessa(self):
        self._salva(aprire_rdc=True, segnalare=True, avanzamento=av.AVANZAMENTO_RISPOSTA_CLIENTE)
        riga = self._salva(aprire_rdc=True, segnalare=True, avanzamento=INFO, chiudere=True,
                           note="Serve la misura del lotto")
        self.assertEqual((riga["aprire_rdc"], riga["segnalare_cliente"], riga["chiudere"], riga["avanzamento"]),
                         (1, 1, 0, INFO))
        self.assertIn("info_richieste", self.notifiche)
        self.notifiche.clear()
        self._salva(aprire_rdc=True, segnalare=True, avanzamento=INFO, note="ancora")
        self.assertNotIn("info_richieste", self.notifiche)


class TerzistaRegolaTests(SimpleTestCase):
    def test_terzista_chiude_solo_dopo_segnalato(self):
        self.assertFalse(av.chiusura_automatica(False, "", False, False, "Accetto lo stato", True, False))
        self.assertTrue(av.chiusura_automatica(False, "", False, False, "Accetto lo stato", True, True))

    def test_attesa_risposta_terzista_resta_aperta(self):
        self.assertFalse(av.chiusura_automatica(False, "", False, False, av.AVANZAMENTO_RISPOSTA_TERZISTA, True, True))

    def test_stato_terzista_canonico(self):
        with patch.object(av, "_load_anomalie_lists", return_value={"avanzamenti": ["In attesa"]}):
            self.assertEqual(av._canonicalize_avanzamento("in attesa risposta terzista"), av.AVANZAMENTO_RISPOSTA_TERZISTA)


class SegnalatoRispostaChiudiTests(_TabellaAnomalieMixin, TestCase):
    """«Segnalato…» salvato con la decisione, nota congelata, risposta, «Chiudi»."""

    def setUp(self):
        super().setUp()
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=self.aid, op_titolo=OP)

    def _salva_err(self, **dati):
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = self.user
        return av._salva_riga_anomalia(request, {"item_id": f"local:{self.aid}", "op_id": OP, **dati},
                                       notifica_debounce=False)

    def test_segnalare_da_solo_non_cambia_stato(self):
        riga = self._salva(segnalare=True, avanzamento="In attesa", note="Da comunicare al cliente")
        self.assertEqual(riga["avanzamento"], "In attesa")
        self.assertEqual(riga["chiudere"], 0)

    def test_segnalato_senza_rdc_chiude_e_registra(self):
        riga = self._salva(segnalare=True, segnalato_cliente=True, avanzamento="In attesa", note="Mandata foto")
        self.assertEqual((riga["avanzamento"], riga["chiudere"]), ("In attesa", 1))
        self.scheda.refresh_from_db()
        self.assertIsNotNone(self.scheda.segnalato_cliente_il)
        self.assertEqual(self.scheda.segnalato_cliente_ruolo, "cc")

    def test_segnalato_con_attesa_risposta_resta_aperta(self):
        riga = self._salva(segnalare=True, segnalato_cliente=True, avanzamento=av.AVANZAMENTO_RISPOSTA_CLIENTE)
        self.assertEqual(riga["chiudere"], 0)

    def test_segnalato_con_rdc_senza_numero_resta_aperta(self):
        riga = self._salva(aprire_rdc=True, segnalare=True, segnalato_cliente=True, avanzamento="In attesa")
        self.assertEqual(riga["chiudere"], 0)

    def test_segnalato_terzista(self):
        riga = self._salva(segnala_terzista=True, segnalato_terzista=True, avanzamento="In attesa")
        self.assertEqual(riga["chiudere"], 1)
        self.scheda.refresh_from_db()
        self.assertIsNotNone(self.scheda.segnalato_terzista_il)

    def test_segnalato_senza_segnalare_ignorato(self):
        self._salva(segnalare=False, segnalato_cliente=True, avanzamento="Finito trattato")
        self.scheda.refresh_from_db()
        self.assertIsNone(self.scheda.segnalato_cliente_il)

    def test_nota_congelata_in_attesa_di_risposta(self):
        self._salva(segnalare=True, segnalato_cliente=True, avanzamento=av.AVANZAMENTO_RISPOSTA_CLIENTE, note="Nota mandata")
        riga = self._salva(segnalare=True, segnalato_cliente=True, avanzamento="Accetto lo stato", note="Riscritta")
        self.assertEqual(riga["note_capocommessa"], "Nota mandata")

    def test_risposta_registrata_e_chiusura(self):
        from anomalie.quality_models import AnomaliaEsito

        self._salva(segnalare=True, segnalato_cliente=True, avanzamento=av.AVANZAMENTO_RISPOSTA_CLIENTE, note="Nota mandata")
        riga = self._salva(segnalare=True, segnalato_cliente=True, avanzamento="Accetto lo stato", chiudere=True,
                           risposta_cliente="Il cliente accetta in deroga")
        self.assertEqual(riga["chiudere"], 1)
        esito = AnomaliaEsito.objects.get(anomalia_id=self.aid)
        self.assertEqual((esito.tipo, esito.testo), (AnomaliaEsito.Tipo.RISPOSTA_CLIENTE, "Il cliente accetta in deroga"))

    def test_risposta_senza_stato_definitivo_rifiutata(self):
        esito = self._salva_err(segnalare=True, segnalato_cliente=True, avanzamento=av.AVANZAMENTO_RISPOSTA_CLIENTE,
                                risposta_cliente="Risposto")
        self.assertFalse(esito["success"])
        self.assertEqual(esito["error"], av.MSG_RISPOSTA_SENZA_STATO)

    def test_risposta_terzista(self):
        from anomalie.quality_models import AnomaliaEsito

        self._salva(segnala_terzista=True, segnalato_terzista=True, avanzamento="Finito trattato",
                    risposta_terzista="Ripassano il lotto")
        self.assertTrue(AnomaliaEsito.objects.filter(anomalia_id=self.aid, tipo=AnomaliaEsito.Tipo.RISPOSTA_TERZISTA).exists())

    def test_chiudi_manuale_chiude_comunque(self):
        riga = self._salva(aprire_rdc=True, segnalare=True, avanzamento="In attesa", chiudi_manuale=True)
        self.assertEqual(riga["chiudere"], 1)
