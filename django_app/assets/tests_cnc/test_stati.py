"""Tabelle di mappatura degli stati, contatori di cicli e pezzi, pulizia dei valori (``stati.py``)."""
from __future__ import annotations

import logging
import math
import unittest
from unittest import mock

from assets.collector_cnc import stati
from assets.collector_cnc.stati import (
    ALLARME,
    EMERGENZA,
    FERMA,
    INTERROTTA,
    LAVORO,
    SETUP,
    ContatoreCicli,
    ContatorePezzi,
    LogLimitato,
    Pulitore,
    norm_execution,
    stato_fanuc,
    stato_heidenhain,
)

ESEC_HEIDENHAIN = ("AUTOMATIC", "MANUAL", "MDI", "SINGLE_STEP", "PASS_REFERENCES", "UNDEFINED")


class HeidenhainTests(unittest.TestCase):
    """Requisito D: tabella Heidenhain riga per riga, per ogni modalità."""

    def test_tabella_completa(self) -> None:
        attesi_per_programma = {
            "ERROR": (ALLARME, "ALARM"), "STOPPED": (INTERROTTA, "INTERRUPTED"),
            "INTERRUPTED": (INTERROTTA, "INTERRUPTED"), "IDLE": (FERMA, "IDLE"), "FINISHED": (FERMA, "IDLE"),
            "CANCELLED": (FERMA, "IDLE"), "ERROR_CLEARED": (FERMA, "IDLE"), "UNDEFINED": (FERMA, "UNKNOWN"),
        }
        for esec in ESEC_HEIDENHAIN:
            for pgm, atteso in attesi_per_programma.items():
                with self.subTest(esecuzione=esec, programma=pgm):
                    self.assertEqual(stato_heidenhain(esec, pgm)[:2], atteso)

    def test_started(self) -> None:
        casi = {"AUTOMATIC": LAVORO, "MANUAL": SETUP, "MDI": SETUP, "SINGLE_STEP": SETUP,
                "PASS_REFERENCES": SETUP, "UNDEFINED": SETUP}
        for esec, atteso in casi.items():
            with self.subTest(esecuzione=esec):
                self.assertEqual(stato_heidenhain(esec, "STARTED"), (atteso, "RUNNING", stati.HEIDENHAIN_MODO[esec]))

    def test_valori_assenti_o_sconosciuti(self) -> None:
        self.assertEqual(stato_heidenhain(None, None), (FERMA, "UNKNOWN", "UNKNOWN"))
        self.assertEqual(stato_heidenhain("BOH", "BOH"), (FERMA, "UNKNOWN", "UNKNOWN"))


class FanucTests(unittest.TestCase):
    """Requisito D: tabella Fanuc, emergenza prima di tutto."""

    def test_emergenza_vince_su_tutto(self) -> None:
        for aut in range(11):
            for run in range(5):
                for alarm in (0, 1):
                    for emergency in (1, 2, 3):
                        with self.subTest(aut=aut, run=run, alarm=alarm, emergency=emergency):
                            self.assertEqual(stato_fanuc(aut, run, emergency, alarm)[0], EMERGENZA)

    def test_allarme_dopo_emergenza(self) -> None:
        for aut in range(11):
            for run in range(5):
                with self.subTest(aut=aut, run=run):
                    self.assertEqual(stato_fanuc(aut, run, 0, 1)[:2], (ALLARME, "ALARM"))

    def test_start(self) -> None:
        for run in (3, 4):   # START, MSTR
            for aut, atteso in {1: LAVORO, 10: LAVORO, 0: SETUP, 5: SETUP, 4: SETUP, 8: SETUP, 9: SETUP, 3: SETUP}.items():
                with self.subTest(aut=aut, run=run):
                    self.assertEqual(stato_fanuc(aut, run, 0, 0)[:2], (atteso, "RUNNING"))

    def test_stop_hold_reset(self) -> None:
        for aut in range(11):
            with self.subTest(aut=aut):
                self.assertEqual(stato_fanuc(aut, 1, 0, 0)[:2], (INTERROTTA, "INTERRUPTED"))
                self.assertEqual(stato_fanuc(aut, 2, 0, 0)[:2], (INTERROTTA, "INTERRUPTED"))
                self.assertEqual(stato_fanuc(aut, 0, 0, 0)[:2], (FERMA, "IDLE"))
        self.assertEqual(stato_fanuc(1, 9, 0, 0)[:2], (FERMA, "UNKNOWN"))

    def test_modalita(self) -> None:
        self.assertEqual(stato_fanuc(1, 3, 0, 0)[2], "AUTO")
        self.assertEqual(stato_fanuc(0, 3, 0, 0)[2], "MDI")
        self.assertEqual(stato_fanuc(5, 3, 0, 0)[2], "MANUAL")
        self.assertEqual(stato_fanuc(42, 3, 0, 0)[2], "UNKNOWN")


class NormExecutionTests(unittest.TestCase):
    def test_tabella_generica(self) -> None:
        for valore, atteso in [("ACTIVE", "RUNNING"), ("feed hold", "INTERRUPTED"), ("READY", "IDLE"), ("ERROR", "ALARM"),
                               ("UNAVAILABLE", "OFFLINE"), ("???", "UNKNOWN"), (None, "UNKNOWN"), (True, "UNKNOWN"),
                               (stati.__name__, "UNKNOWN")]:
            with self.subTest(valore=valore):
                self.assertEqual(norm_execution(valore), atteso)

    def test_enum_e_mappa_personalizzata(self) -> None:
        from assets.tests_cnc.finti import PgmState

        self.assertEqual(norm_execution(PgmState.STARTED), "RUNNING")
        mappa = {1: "running", "2": "interrupted", 3: "nonsense"}
        self.assertEqual(norm_execution(1, mappa), "RUNNING")
        self.assertEqual(norm_execution(2, mappa), "INTERRUPTED")
        self.assertEqual(norm_execution(3, mappa), "UNKNOWN")
        self.assertEqual(norm_execution([1], mappa), "UNKNOWN")


class ContatoriTests(unittest.TestCase):
    def test_cicli_solo_sul_fronte_in_automatico(self) -> None:
        c = ContatoreCicli(10)
        seq = [("AUTOMATIC", "FINISHED"),   # prima lettura: base, non conta
               ("AUTOMATIC", "STARTED"), ("AUTOMATIC", "FINISHED"),   # +1
               ("AUTOMATIC", "FINISHED"), ("AUTOMATIC", "FINISHED"),  # FINISHED stabile: niente
               ("MDI", "STARTED"), ("MDI", "FINISHED"),               # non in automatico: niente
               ("AUTOMATIC", "STARTED"), ("MANUAL", "FINISHED")]      # era in automatico: +1
        contati = [c.aggiorna(e, p) for e, p in seq]
        self.assertEqual(contati, [False, False, True, False, False, False, False, False, True])
        self.assertEqual(c.totale, 12)

    def test_cicli_rebase_dopo_riconnessione(self) -> None:
        c = ContatoreCicli()
        c.aggiorna("AUTOMATIC", "STARTED")
        c.rebase()
        self.assertFalse(c.aggiorna("AUTOMATIC", "FINISHED"))   # dopo la riconnessione è solo la base
        self.assertEqual(c.totale, 0)

    def test_pezzi_base_delta_e_azzeramento(self) -> None:
        p = ContatorePezzi()
        self.assertEqual(p.aggiorna(500).delta, 0)          # base
        self.assertEqual(p.aggiorna(503).delta, 3)
        esito = p.aggiorna(2)                                # azzerato dall'operatore
        self.assertTrue(esito.azzerato)
        self.assertEqual(esito.delta, 0)
        self.assertEqual(p.aggiorna(5).delta, 3)
        self.assertEqual(p.totale, 6)

    def test_pezzi_ripresi_da_machines_db(self) -> None:
        p = ContatorePezzi(totale=40, ultimo_grezzo=100)
        self.assertEqual(p.aggiorna(104).delta, 4)   # pezzi fatti a collector fermo: non persi
        self.assertEqual(p.totale, 44)


class PulitoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.log = mock.Mock(spec=logging.Logger)
        self.p = Pulitore(self.log)

    def test_valori_anomali_scartati(self) -> None:
        self.assertIsNone(self.p.override("feed_ovr", math.nan))
        self.assertIsNone(self.p.override("feed_ovr", 250.0))
        self.assertIsNone(self.p.override("feed_ovr", -1.0))
        self.assertIsNone(self.p.override("feed_ovr", "100"))
        self.assertIsNone(self.p.override("feed_ovr", True))
        self.assertIsNone(self.p.intero("part_count", 3.5))
        self.assertIsNone(self.p.numero("feed", math.inf))
        self.assertIsNone(self.p.testo("messaggio", 42))
        self.assertIsNone(self.p.testo("program", "   ", vuoto_ammesso=False))
        self.assertEqual(self.p.scartati, 9)
        self.assertEqual(self.p.override("feed_ovr", 100), 100.0)
        self.assertEqual(self.p.intero("part_count", 7.0), 7)
        self.assertEqual(self.p.testo("program", b"O1234\x00\x00rest"), "O1234")
        self.assertEqual(self.p.testo("program", "  P1\x07 "), "P1")
        self.assertIsNone(self.p.numero("x", None))

    def test_log_a_frequenza_limitata(self) -> None:
        for _ in range(50):
            self.p.override("feed_ovr", 999.0)
        self.assertEqual(self.log.warning.call_count, 1)

    def test_log_limitato_dice_quanti_ne_ha_taciuti(self) -> None:
        log = mock.Mock(spec=logging.Logger)
        limitato = LogLimitato(log, intervallo=0.0)
        limitato.intervallo = 1000
        self.assertTrue(limitato.warning("k", "messaggio"))
        self.assertFalse(limitato.warning("k", "messaggio"))
        limitato.intervallo = 0
        self.assertTrue(limitato.warning("k", "messaggio"))
        self.assertIn("altri 1 uguali taciuti", log.warning.call_args[0][0])
