"""Thread per macchina: ritmo (minimo 2 s, jitter, backoff), riconnessione, watchdog, stop, orologio."""
from __future__ import annotations

import random
import threading
import time
import unittest
from collections.abc import Callable
from unittest import mock

from assets.collector_cnc import lavoratore, stati
from assets.collector_cnc.drivers import focas
from assets.collector_cnc.drivers.base import Lettura, spia
from assets.collector_cnc.lavoratore import Lavoratore, Orologio, Ritmo, Sorvegliante
from assets.tests_cnc.finti import FwlibFinta, PgmState, StatoLsv2
from assets.tests_cnc.test_drivers import SILENZIO, driver_lsv2


def attendi(condizione: Callable[[], bool], massimo: float = 10.0) -> None:
    limite = time.monotonic() + massimo
    while not condizione():
        if time.monotonic() > limite:
            raise AssertionError("attesa scaduta")
        time.sleep(0.01)


class RitmoTests(unittest.TestCase):
    """Requisito: polling mai sotto 2 s, jitter ±5 %, backoff da poll fino a 300 s."""

    def test_mai_sotto_due_secondi(self) -> None:
        for richiesto in (0, 0.1, 1.0, 1.99, -5):
            r = Ritmo(richiesto, random.Random(1))
            self.assertEqual(r.poll, 2.0)
            self.assertTrue(all(r.attesa() >= 2.0 for _ in range(500)))
            self.assertTrue(all(r.backoff(n) >= 2.0 for n in range(10)))

    def test_default_e_jitter(self) -> None:
        r = Ritmo(None, random.Random(2))
        self.assertEqual(r.poll, 5.0)
        attese = [r.attesa() for _ in range(2000)]
        self.assertTrue(all(4.75 <= a <= 5.25 for a in attese))
        self.assertGreater(max(attese) - min(attese), 0.3)   # c'è davvero il jitter
        self.assertTrue(all(0 <= r.avvio() <= 5.0 for _ in range(100)))

    def test_backoff(self) -> None:
        r = Ritmo(5, random.Random(3))
        medie = [sum(r.backoff(n) for _ in range(200)) / 200 for n in (1, 2, 3, 4, 10, 30)]
        self.assertAlmostEqual(medie[0], 5, delta=0.3)
        self.assertAlmostEqual(medie[1], 10, delta=0.5)
        self.assertAlmostEqual(medie[2], 20, delta=1)
        self.assertAlmostEqual(medie[3], 40, delta=2)
        self.assertTrue(all(r.backoff(n) <= 300 for n in range(60)))
        self.assertTrue(285 <= medie[5] <= 300)   # a regime: 300 s meno il jitter

    def test_avviso_se_la_config_chiede_meno(self) -> None:
        log = mock.Mock()
        Ritmo(0.5, log=log)
        self.assertIn("sotto il minimo", log.warning.call_args[0][0])


class OrologioTests(unittest.TestCase):
    def test_salto_dell_orologio(self) -> None:
        parete, monotono = [1000.0], [50.0]
        log = mock.Mock()
        o = Orologio(log, parete=lambda: parete[0], monotono=lambda: monotono[0])
        parete[0] += 30
        monotono[0] += 30
        self.assertIsNone(o.controlla())
        parete[0] += 3600 + 10   # l'orologio di sistema va avanti di un'ora (NTP, ora legale sbagliata)
        monotono[0] += 10
        self.assertAlmostEqual(o.controlla() or 0, 3600)
        self.assertEqual(o.salti, 1)
        self.assertIn("saltato", log.warning.call_args[0][0])
        parete[0] -= 120   # indietro di due minuti
        self.assertAlmostEqual(o.controlla() or 0, -120)


class _Raccolta:
    def __init__(self) -> None:
        self.letture: list[Lettura] = []
        self.lock = threading.Lock()

    def __call__(self, lettura: Lettura) -> None:
        with self.lock:
            self.letture.append(lettura)

    def stati(self) -> list[str]:
        with self.lock:
            return [lt.stato for lt in self.letture]


@mock.patch.object(lavoratore, "POLL_MINIMO", 0.01)
class LavoratoreTests(unittest.TestCase):
    def _sorvegliante(self, crea: Callable[[], object], poll: float = 0.02) -> tuple[Sorvegliante, _Raccolta]:
        raccolta = _Raccolta()
        s = Sorvegliante("AGV1", crea, Ritmo(poll, random.Random(4)), raccolta, SILENZIO)  # type: ignore[arg-type]
        return s, raccolta

    def test_macchina_spenta_all_avvio_poi_accesa(self) -> None:
        st = StatoLsv2()
        st.acceso = False
        s, r = self._sorvegliante(lambda: driver_lsv2(st))
        s.avvia()
        try:
            attendi(lambda: stati.OFFLINE in r.stati())
            st.acceso = True
            st.programma = PgmState.STARTED
            attendi(lambda: stati.LAVORO in r.stati())
        finally:
            self.assertEqual(s.ferma(5), [])
        self.assertEqual(st.connessioni, st.disconnessioni)   # nessuna connessione lasciata aperta
        self.assertGreaterEqual(st.chiamate.count("connect"), 2)

    def test_una_connessione_persistente(self) -> None:
        st = StatoLsv2()
        s, r = self._sorvegliante(lambda: driver_lsv2(st))
        s.avvia()
        try:
            attendi(lambda: len(r.letture) >= 10)
        finally:
            s.ferma(5)
        self.assertEqual(st.connessioni, 1)   # dieci letture, una sola connessione
        self.assertEqual(st.disconnessioni, 1)

    def test_cavo_staccato_e_riavvio_del_controllo(self) -> None:
        st = StatoLsv2()
        st.programma = PgmState.STARTED
        s, r = self._sorvegliante(lambda: driver_lsv2(st))
        s.avvia()
        try:
            attendi(lambda: stati.LAVORO in r.stati())
            st.guasto_lettura = ConnectionResetError("cavo staccato")
            attendi(lambda: stati.OFFLINE in r.stati())
            st.acceso = False   # il controllo si riavvia
            time.sleep(0.1)
            st.acceso = True
            n = len(r.letture)
            attendi(lambda: len(r.letture) > n + 3 and r.stati()[-1] == stati.LAVORO)
        finally:
            s.ferma(5)
        self.assertEqual(st.connessioni, st.disconnessioni)
        self.assertGreaterEqual(st.connessioni, 2)

    def test_login_dnc_rifiutato_non_e_offline(self) -> None:
        st = StatoLsv2()
        st.dnc = False
        s, r = self._sorvegliante(lambda: driver_lsv2(st))
        with mock.patch.object(lavoratore, "BACKOFF_MASSIMO", 0.05):
            s.avvia()
            try:
                attendi(lambda: stati.NON_LEGGIBILE in r.stati())
            finally:
                s.ferma(5)
        lettura = next(lt for lt in r.letture if lt.stato == stati.NON_LEGGIBILE)
        self.assertIn("#18", lettura.errore)
        self.assertNotIn(stati.OFFLINE, r.stati())

    def test_fwlib_assente(self) -> None:
        s, r = self._sorvegliante(lambda: focas.DriverFocas("HYUNDAI", "192.0.2.117", log=SILENZIO,
                                                            percorso="Z:/non/esiste/Fwlib64.dll"))
        with mock.patch.object(focas, "_libreria", None), mock.patch.object(lavoratore, "BACKOFF_MASSIMO", 0.05):
            s.avvia()
            try:
                attendi(lambda: stati.NON_LEGGIBILE in r.stati())
            finally:
                s.ferma(5)
        self.assertIn("Fwlib", r.letture[0].errore)

    def test_errore_imprevisto_del_driver_fa_riconnettere(self) -> None:
        st = StatoLsv2()
        s, r = self._sorvegliante(lambda: driver_lsv2(st))
        s.avvia()
        try:
            attendi(lambda: len(r.letture) >= 2)
            with mock.patch("assets.collector_cnc.drivers.lsv2.stati.stato_heidenhain", side_effect=KeyError("bug")):
                attendi(lambda: stati.OFFLINE in r.stati())
            attendi(lambda: r.stati()[-1] == stati.FERMA)
        finally:
            s.ferma(5)
        self.assertEqual(st.connessioni, st.disconnessioni)

    def test_watchdog_thread_bloccato(self) -> None:
        st = StatoLsv2()
        sblocca = threading.Event()
        s, r = self._sorvegliante(lambda: driver_lsv2(st, timeout=0.05))
        s.avvia()
        try:
            attendi(lambda: len(r.letture) >= 2)
            primo = s.lavoratore
            st.blocca = sblocca          # la prossima lettura resta appesa
            attendi(lambda: primo.in_chiamata_dal is not None)
            attendi(lambda: primo.bloccato())   # oltre 3 x 0,05 s
            self.assertTrue(s.controlla())
            self.assertEqual(s.bloccati, 1)
            self.assertIsNot(s.lavoratore, primo)
            self.assertTrue(primo.abbandonato.is_set())
            self.assertEqual(r.stati()[-1], stati.OFFLINE)   # buco esplicito, niente stato allungato
            st.blocca = None
            sblocca.set()                # il vecchio thread si sblocca: i suoi record non passano più
            attendi(lambda: not primo.is_alive())
            n = len(r.letture)
            attendi(lambda: len(r.letture) > n + 2)   # il thread nuovo legge
        finally:
            self.assertEqual(s.ferma(5), [])
        self.assertEqual(st.connessioni, st.disconnessioni)

    def test_watchdog_non_scatta_senza_blocco(self) -> None:
        t = Lavoratore("X", mock.Mock(), Ritmo(1), mock.Mock(), threading.Event(), SILENZIO)
        self.assertFalse(t.bloccato())
        t.in_chiamata_dal = time.monotonic() - 100
        t.timeout = 5
        self.assertTrue(t.bloccato())

    def test_stop_durante_la_riconnessione(self) -> None:
        st = StatoLsv2()
        st.acceso = False
        s, r = self._sorvegliante(lambda: driver_lsv2(st), poll=5)
        with mock.patch.object(lavoratore, "POLL_MINIMO", 2.0):
            s = Sorvegliante("AGV1", lambda: driver_lsv2(st), Ritmo(30, random.Random(5)), r, SILENZIO)
            s.lavoratore.ritmo.avvio = lambda: 0.0  # type: ignore[method-assign]
            s.avvia()
            attendi(lambda: stati.OFFLINE in r.stati())   # ora aspetta 30 s prima di riprovare
            inizio = time.monotonic()
            self.assertEqual(s.ferma(5), [])
            self.assertLess(time.monotonic() - inizio, 1.0)   # lo stop interrompe l'attesa subito
        self.assertEqual(st.connessioni, st.disconnessioni)

    def test_ferma_segnala_i_thread_che_non_escono(self) -> None:
        st = StatoLsv2()
        sblocca = threading.Event()
        st.blocca = sblocca
        s, _r = self._sorvegliante(lambda: driver_lsv2(st, timeout=60))
        s.avvia()
        try:
            attendi(lambda: s.lavoratore.in_chiamata_dal is not None)
            self.assertEqual(len(s.ferma(0.1)), 1)
        finally:
            sblocca.set()
            s.lavoratore.join(5)

    def test_spia_lsv2_e_focas_dentro_la_whitelist(self) -> None:
        from assets.collector_cnc.drivers import lsv2

        st = StatoLsv2()
        st.programma = PgmState.STARTED
        lib = FwlibFinta()
        with spia() as chiamate:
            s1, r1 = self._sorvegliante(lambda: driver_lsv2(st))
            s2, r2 = self._sorvegliante(lambda: focas.DriverFocas("HYUNDAI", "192.0.2.117", log=SILENZIO, raw=lib))
            s1.avvia()
            s2.avvia()
            try:
                attendi(lambda: len(r1.letture) >= 5 and len(r2.letture) >= 5)
                st.acceso = False
                lib.acceso = False
                attendi(lambda: stati.OFFLINE in r1.stati() and stati.OFFLINE in r2.stati())
            finally:
                s1.ferma(5)
                s2.ferma(5)
        per_driver: dict[str, set[str]] = {}
        for driver, nome in chiamate:
            per_driver.setdefault(driver, set()).add(nome)
        self.assertLessEqual(per_driver["lsv2"], lsv2.LSV2_AMMESSI | lsv2.DATI_AMMESSI)
        self.assertLessEqual(per_driver["focas"], focas.FWLIB_AMMESSE)
        self.assertNotIn("send_file", st.chiamate)
        self.assertEqual(lib.handle_aperti, set())   # nessun handle FOCAS perso


class LogMacchinaTests(unittest.TestCase):
    def test_contesto_in_ogni_riga(self) -> None:
        with self.assertLogs("collector", "INFO") as cm:
            lavoratore.log_macchina("DM6", "lsv2", "192.0.2.114").info("connessa")
        self.assertIn("[DM6 lsv2 192.0.2.114] connessa", cm.output[0])
        self.assertEqual(cm.records[0].macchina, "DM6")  # type: ignore[attr-defined]
