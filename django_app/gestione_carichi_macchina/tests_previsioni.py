"""Test della predizione durata/ore (funzioni pure)."""
from datetime import date

from django.test import SimpleTestCase

from .previsioni import (
    FONTE_CICLO,
    FONTE_FAMIGLIA,
    FONTE_NESSUNA,
    FONTE_STORICO,
    prevedi_macchina,
    prevedi_ore,
    rischio_ritardo,
)


class PrevediOreTest(SimpleTestCase):
    def test_da_tempo_ciclo(self):
        ore, fonte, conf = prevedi_ore(
            qta=10, macchina_id=1, famiglia_id=2,
            ciclo_tempi={(2, 1): 550}, affinita_ore={}, famiglia_ore={},
        )
        self.assertEqual(ore, 55.0)  # 10 * 550 / 100
        self.assertEqual(fonte, FONTE_CICLO)
        self.assertEqual(conf, "alta")

    def test_fallback_storico_affinita(self):
        ore, fonte, _ = prevedi_ore(
            qta=None, macchina_id=1, famiglia_id=2,
            ciclo_tempi={}, affinita_ore={(1, 2): 33.0}, famiglia_ore={},
        )
        self.assertEqual(ore, 33.0)
        self.assertEqual(fonte, FONTE_STORICO)

    def test_fallback_media_famiglia(self):
        ore, fonte, _ = prevedi_ore(
            qta=5, macchina_id=9, famiglia_id=2,
            ciclo_tempi={}, affinita_ore={}, famiglia_ore={2: 20.0},
        )
        self.assertEqual(ore, 20.0)
        self.assertEqual(fonte, FONTE_FAMIGLIA)

    def test_nessuna_predizione(self):
        ore, fonte, conf = prevedi_ore(
            qta=5, macchina_id=1, famiglia_id=None,
            ciclo_tempi={}, affinita_ore={}, famiglia_ore={},
        )
        self.assertIsNone(ore)
        self.assertEqual(fonte, FONTE_NESSUNA)
        self.assertEqual(conf, "assente")

    def test_priorita_ciclo_su_storico(self):
        # se c'e' sia il ciclo sia lo storico, vince il ciclo
        ore, fonte, _ = prevedi_ore(
            qta=10, macchina_id=1, famiglia_id=2,
            ciclo_tempi={(2, 1): 100}, affinita_ore={(1, 2): 99.0}, famiglia_ore={},
        )
        self.assertEqual(ore, 10.0)
        self.assertEqual(fonte, FONTE_CICLO)


class PrevediMacchinaTest(SimpleTestCase):
    def test_ranking_per_occorrenze(self):
        freq = {2: [(10, 5), (11, 20), (12, 1)]}
        ranked = prevedi_macchina(2, freq)
        self.assertEqual([r["macchina_id"] for r in ranked], [11, 10, 12])
        self.assertAlmostEqual(ranked[0]["prob"], 20 / 26, places=3)

    def test_famiglia_assente(self):
        self.assertEqual(prevedi_macchina(99, {}), [])

    def test_carico_penalizza_macchina_satura(self):
        # m10 ha piu' storia (6 vs 4) ma e' satura; m11 e' libera.
        freq = {1: [(10, 6), (11, 4)]}
        # Senza segnali: vince la sola frequenza storica (m10).
        storico = prevedi_macchina(1, freq)
        self.assertEqual([r["macchina_id"] for r in storico], [10, 11])
        # Con il carico attuale: la macchina libera (m11) supera quella satura (m10).
        pesato = prevedi_macchina(
            1, freq,
            carico_per_macchina={10: 1.0, 11: 0.0},
            stato_per_macchina={10: "attiva", 11: "attiva"},
        )
        self.assertEqual([r["macchina_id"] for r in pesato], [11, 10])
        self.assertIn("score", pesato[0])
        self.assertIn("componenti", pesato[0])

    def test_stato_esclude_macchina_non_disponibile(self):
        freq = {1: [(10, 6), (11, 4)]}
        ranked = prevedi_macchina(1, freq, stato_per_macchina={10: "guasto"})
        self.assertEqual([r["macchina_id"] for r in ranked], [11])

    def test_recency_premia_storia_recente(self):
        # Stessa frequenza: vince la macchina con storia piu' recente.
        freq = {1: [(10, 5), (11, 5)]}
        ranked = prevedi_macchina(
            1, freq, recency_per_coppia={(10, 1): 1.0, (11, 1): 0.1}
        )
        self.assertEqual([r["macchina_id"] for r in ranked], [10, 11])


class RischioRitardoTest(SimpleTestCase):
    def test_in_ritardo(self):
        # lun 22/06, 24h @8/gg = 3 gg lavorativi -> fine mer 24/06; consegna mar 23 -> ritardo
        r = rischio_ritardo(
            data_inizio=date(2026, 6, 22), ore_previste=24, ore_giorno=8,
            data_consegna=date(2026, 6, 23),
        )
        self.assertTrue(r["valutabile"])
        self.assertTrue(r["in_ritardo"])
        self.assertEqual(r["fine_prevista"], date(2026, 6, 24))

    def test_in_tempo_con_margine(self):
        r = rischio_ritardo(
            data_inizio=date(2026, 6, 22), ore_previste=8, ore_giorno=8,
            data_consegna=date(2026, 6, 26),
        )
        self.assertFalse(r["in_ritardo"])
        self.assertGreater(r["giorni_margine"], 0)

    def test_non_valutabile_senza_ore(self):
        r = rischio_ritardo(
            data_inizio=date(2026, 6, 22), ore_previste=None, ore_giorno=8,
            data_consegna=date(2026, 6, 26),
        )
        self.assertFalse(r["valutabile"])
