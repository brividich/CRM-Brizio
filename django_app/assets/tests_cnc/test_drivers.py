"""Driver LSV2 e FOCAS su simulatori: normalizzazione, whitelist, disattivazione, errori, handle."""
from __future__ import annotations

import ctypes
import logging
import os
import tempfile
import unittest
from unittest import mock

from assets.collector_cnc import stati
from assets.collector_cnc.drivers import focas, lsv2
from assets.collector_cnc.drivers.base import (
    ErroreConnessione,
    FunzioniOpzionali,
    LibreriaAssente,
    LoginRifiutato,
    ProxySolaLettura,
    spia,
)
from assets.tests_cnc.finti import ExecState, FwlibFinta, PgmState, StatoLsv2, modulo_lsv2

SILENZIO = logging.getLogger("test.cnc.silenzio")
SILENZIO.addHandler(logging.NullHandler())
SILENZIO.propagate = False


def driver_lsv2(stato: StatoLsv2, **k: object) -> lsv2.DriverLsv2:
    return lsv2.DriverLsv2("AGV1", "192.0.2.105", log=SILENZIO, modulo=modulo_lsv2(stato), **k)  # type: ignore[arg-type]


class Lsv2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.s = StatoLsv2()
        self.d = driver_lsv2(self.s)
        self.d.connetti()

    def tearDown(self) -> None:
        self.d.chiudi()

    def test_apertura_con_opzioni_giuste(self) -> None:
        client = object.__getattribute__(self.d._client, "_bersaglio")
        self.assertEqual((client.port, client.safe_mode, client.compatibility_mode), (19000, False, True))
        self.assertEqual(self.d.versione, "TNC640 340595 10 SP2")

    def test_lettura_normalizzata(self) -> None:
        self.s.programma = PgmState.STARTED
        self.s.override = (80.0, 110.0, 50.0)
        self.s.messaggi = [(1, 2, 300, "Finecorsa X+")]
        lettura = self.d.leggi()
        self.assertEqual((lettura.stato, lettura.execution, lettura.mode), (stati.LAVORO, "RUNNING", "AUTO"))
        self.assertEqual((lettura.program, lettura.subprogram, lettura.line), ("TNC:\\nc_prog\\PEZZO_A.h", "TNC:\\nc_prog\\SUB.h", 10))
        self.assertEqual((lettura.feed_ovr, lettura.spindle_ovr, lettura.rapid_ovr), (80.0, 110.0, 50.0))
        self.assertEqual((lettura.messaggi[0].codice, lettura.alarm_text), ("1-2-300", "Finecorsa X+"))
        self.assertEqual(lettura.driver, "lsv2")
        self.assertIsNotNone(lettura.ts.tzinfo)

    def test_cicli_dal_fronte_finished(self) -> None:
        self.s.programma = PgmState.STARTED
        self.d.leggi()
        self.s.programma = PgmState.FINISHED
        self.assertEqual(self.d.leggi().parts_total, 1)
        self.assertEqual(self.d.leggi().parts_total, 1)   # FINISHED stabile: niente doppio conteggio

    def test_override_anomalo_scartato(self) -> None:
        self.s.override = (float("nan"), 300.0, -5.0)
        lettura = self.d.leggi()
        self.assertEqual((lettura.feed_ovr, lettura.spindle_ovr, lettura.rapid_ovr), (None, None, None))

    def test_login_dnc_rifiutato(self) -> None:
        self.s.dnc = False
        with self.assertRaises(LoginRifiutato) as ctx:
            self.d.leggi()
        self.assertIn("#18", str(ctx.exception))

    def test_cavo_staccato_durante_la_lettura(self) -> None:
        self.s.acceso = False
        with self.assertRaises(ErroreConnessione):
            self.d.leggi()

    def test_disattivazione_dopo_tre_errori(self) -> None:
        self.s.override_rotto = True
        for _ in range(3):
            self.assertIsNone(self.d.leggi().feed_ovr)
        self.assertIn("override_state", self.d.funzioni.disattivate)
        n = self.s.chiamate.count("override_state")
        self.d.leggi()
        self.assertEqual(self.s.chiamate.count("override_state"), n)   # non si chiama più

    def test_whitelist(self) -> None:
        for nome in ("send_file", "recive_file", "delete_file", "set_machine_parameter", "send_key_code", "login"):
            with self.subTest(nome=nome), self.assertRaises(PermissionError):
                getattr(self.d._client, nome)
        with self.assertRaises(PermissionError):
            self.d._client.versions.control = "X"   # anche gli oggetti restituiti sono di sola lettura

    def test_chiusura_su_ogni_percorso(self) -> None:
        self.d.chiudi()
        self.d.chiudi()   # idempotente
        self.assertEqual(self.s.disconnessioni, 1)
        spento = StatoLsv2()
        spento.acceso = False
        d = driver_lsv2(spento)
        with self.assertRaises(ErroreConnessione):
            d.connetti()
        self.assertEqual(spento.disconnect_tentate, 1)   # disconnect tentata anche se l'apertura è fallita
        with self.assertRaises(ErroreConnessione):
            d.leggi()   # connessione chiusa

    def test_libreria_assente(self) -> None:
        with mock.patch("importlib.import_module", side_effect=ImportError("pyLSV2")):
            with self.assertRaises(LibreriaAssente):
                lsv2.carica_pylsv2()

    def test_classificazione_errori(self) -> None:
        self.assertTrue(lsv2.errore_di_connessione(TimeoutError()))
        self.assertTrue(lsv2.errore_di_connessione(type("LSV2ProtocolException", (Exception,), {})()))
        self.assertFalse(lsv2.errore_di_connessione(ValueError()))


class FocasTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lib = FwlibFinta()
        self.d = focas.DriverFocas("HYUNDAI", "192.0.2.117", log=SILENZIO, raw=self.lib)
        self.d.connetti()

    def tearDown(self) -> None:
        self.d.chiudi()

    def test_lettura_normalizzata(self) -> None:
        self.lib.run = 3
        lettura = self.d.leggi()
        self.assertEqual((lettura.stato, lettura.execution, lettura.mode), (stati.LAVORO, "RUNNING", "AUTO"))
        self.assertEqual((lettura.program, lettura.feed, lettura.speed, lettura.part_count), ("O1234", 1200.0, 8000.0, 100))
        self.assertEqual(lettura.raw["o_num"], 1234)
        self.lib.emergency = 1
        self.assertEqual(self.d.leggi().stato, stati.EMERGENZA)

    def test_pezzi_baseline_delta_azzeramento(self) -> None:
        self.assertEqual(self.d.leggi().parts_total, 0)   # base
        self.lib.pezzi = 104
        self.assertEqual(self.d.leggi().parts_total, 4)
        self.lib.pezzi = 1
        self.assertEqual(self.d.leggi().parts_total, 4)   # azzerato: non si sottrae
        self.assertEqual(self.d.azzeramenti, 1)
        self.lib.pezzi = 3
        self.assertEqual(self.d.leggi().parts_total, 6)

    def test_codici_di_connessione_persa(self) -> None:
        for codice in (-16, -8):
            with self.subTest(codice=codice):
                self.lib.codici["cnc_statinfo"] = codice
                with self.assertRaises(ErroreConnessione):
                    self.d.leggi()
        self.lib.codici.clear()

    def test_funzione_non_supportata_disattivata(self) -> None:
        self.lib.codici["cnc_acts"] = 1   # EW_FUNC
        for _ in range(3):
            self.assertIsNone(self.d.leggi().speed)
        self.assertIn("cnc_acts", self.d.funzioni.disattivate)
        n = self.lib.chiamate.count("cnc_acts")
        self.d.leggi()
        self.assertEqual(self.lib.chiamate.count("cnc_acts"), n)

    def test_statinfo_che_fallisce_fa_riconnettere(self) -> None:
        self.lib.codici["cnc_statinfo"] = 1
        self.d.leggi()
        self.d.leggi()
        with self.assertRaises(ErroreConnessione):
            self.d.leggi()

    def test_occupato_non_conta(self) -> None:
        self.lib.codici["cnc_actf"] = -1
        for _ in range(5):
            self.d.leggi()
        self.assertNotIn("cnc_actf", self.d.funzioni.disattivate)

    def test_whitelist(self) -> None:
        lib = focas.carica_fwlib(raw=self.lib)
        for nome in ("cnc_wrparam", "pmc_wrpmcrng", "cnc_dwnstart3", "cnc_reset", "_FuncPtr", "__dict__"):
            with self.subTest(nome=nome), self.assertRaises(PermissionError):
                getattr(lib, nome)
        self.assertIsInstance(lib, ProxySolaLettura)

    def test_handle_liberato_su_ogni_percorso(self) -> None:
        h = self.d._handle
        self.d.chiudi()
        self.d.chiudi()
        self.assertEqual(self.lib.handle_liberati, [h])
        self.assertEqual(self.lib.handle_aperti, set())
        self.lib.acceso = False
        d = focas.DriverFocas("HYUNDAI", "192.0.2.117", log=SILENZIO, raw=self.lib)
        with self.assertRaises(ErroreConnessione):
            d.connetti()
        d.chiudi()
        self.assertEqual(self.lib.handle_aperti, set())

    def test_strutture_e_lunghezze(self) -> None:
        self.assertEqual(ctypes.sizeof(focas.ODBST), 18)
        self.assertEqual(ctypes.sizeof(focas.IODBPSD), ctypes.sizeof(focas.IODBPSD()))
        self.assertGreaterEqual(ctypes.sizeof(focas.IODBPSD), 4 + ctypes.sizeof(ctypes.c_long))

    def test_spia_dentro_la_whitelist(self) -> None:
        with spia() as chiamate:
            self.lib.run = 3
            self.d.leggi()
            self.d.chiudi()
        self.assertTrue({n for _d, n in chiamate} <= focas.FWLIB_AMMESSE)


class FwlibCaricamentoTests(unittest.TestCase):
    def test_libreria_assente(self) -> None:
        with tempfile.TemporaryDirectory() as cartella, mock.patch.object(focas, "_libreria", None):
            with self.assertRaises(LibreriaAssente) as ctx:
                focas.carica_fwlib(os.path.join(cartella, "Fwlib64.dll"))
            self.assertIn("CNC_FWLIB_PATH", str(ctx.exception))

    def test_libreria_non_caricabile(self) -> None:
        with tempfile.TemporaryDirectory() as cartella, mock.patch.object(focas, "_libreria", None):
            finta = os.path.join(cartella, focas.nome_standard())
            with open(finta, "wb") as f:
                f.write(b"non una libreria")
            with mock.patch.dict(os.environ, {"CNC_FWLIB_PATH": cartella}):
                self.assertEqual(focas.percorso_libreria(), finta)
                with self.assertRaises(LibreriaAssente):
                    focas.carica_fwlib()

    def test_nome_standard(self) -> None:
        with mock.patch.object(focas.sys, "platform", "linux"):
            self.assertEqual(focas.nome_standard(), "libfwlib32.so")
        with mock.patch.dict(os.environ, {"CNC_FWLIB_PATH": ""}):
            self.assertEqual(focas.percorso_libreria(), focas.nome_standard())

    def test_firme_configurate_sulla_libreria_vera(self) -> None:
        class Funzione:
            argtypes: object = None
            restype: object = None

        raw = mock.Mock(spec=[*focas.FWLIB_AMMESSE])
        for nome in focas.FWLIB_AMMESSE:
            setattr(raw, nome, Funzione())
        focas._configura(raw)
        self.assertIs(raw.cnc_statinfo.restype, ctypes.c_short)
        self.assertEqual(len(raw.cnc_rdparam.argtypes), 5)


class FunzioniOpzionaliTests(unittest.TestCase):
    def test_errore_di_connessione_classificato(self) -> None:
        f = FunzioniOpzionali(SILENZIO, lambda e: isinstance(e, OSError))
        with self.assertRaises(ErroreConnessione):
            f.chiama("x", lambda: (_ for _ in ()).throw(OSError("giù")))
        self.assertEqual(f.chiama("y", lambda: 5), 5)
        self.assertTrue(f.attiva("y"))


class EnumLsv2Tests(unittest.TestCase):
    def test_nomi_degli_enum(self) -> None:
        self.assertEqual(lsv2._nome(ExecState.AUTOMATIC), "AUTOMATIC")
        self.assertIsNone(lsv2._nome(None))
        self.assertEqual(lsv2._nome("X"), "X")
