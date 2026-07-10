"""Test della predizione durata/ore (funzioni pure)."""
from datetime import date

from django.test import SimpleTestCase, TestCase

from assets.models import Asset

from .models import FamigliaPezzo, Macchina, Pianificazione
from .previsioni import (
    FONTE_CICLO,
    FONTE_FAMIGLIA,
    FONTE_NESSUNA,
    FONTE_STORICO,
    costruisci_indice_macchine_fase,
    costruisci_indice_macchine_fase_globale,
    finestra_carico_per_ore,
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

    def test_fase_cambia_il_ranking(self):
        # Stessa famiglia, ma fasi diverse -> macchine diverse: sgr su m10, fin su m11.
        freq = {1: [(10, 5), (11, 5)]}
        per_fase = {(1, "sgr"): [(10, 9), (11, 1)], (1, "fin"): [(11, 9), (10, 1)]}
        sgr = prevedi_macchina(1, freq, fase="sgr", freq_per_famiglia_fase=per_fase)
        self.assertEqual([r["macchina_id"] for r in sgr], [10, 11])
        fin = prevedi_macchina(1, freq, fase="fin", freq_per_famiglia_fase=per_fase)
        self.assertEqual([r["macchina_id"] for r in fin], [11, 10])
        # Fase senza storico -> fallback alla frequenza per sola famiglia.
        fb = prevedi_macchina(1, freq, fase="rip", freq_per_famiglia_fase=per_fase)
        self.assertEqual(sorted(r["macchina_id"] for r in fb), [10, 11])

    def test_recency_premia_storia_recente(self):
        # Stessa frequenza: vince la macchina con storia piu' recente.
        freq = {1: [(10, 5), (11, 5)]}
        ranked = prevedi_macchina(
            1, freq, recency_per_coppia={(10, 1): 1.0, (11, 1): 0.1}
        )
        self.assertEqual([r["macchina_id"] for r in ranked], [10, 11])

    def test_pesi_per_categoria_macchina(self):
        # Stessa frequenza; m10 vince su recency, m11 vince su carico.
        freq = {1: [(10, 5), (11, 5)]}
        comuni = dict(
            recency_per_coppia={(10, 1): 1.0, (11, 1): 0.0},
            carico_per_macchina={10: 1.0, 11: 0.0},
            stato_per_macchina={10: "attiva", 11: "attiva"},
        )
        # Pesi uniformi (default): il carico (.3) pesa piu' della recency (.2) -> vince m11.
        uniforme = prevedi_macchina(1, freq, **comuni)
        self.assertEqual(uniforme[0]["macchina_id"], 11)
        # Un profilo pesi dedicato alla CATEGORIA di m10 (recency-centrico) ribalta l'esito
        # solo per lei: il peso applicato dipende dalla categoria della macchina candidata,
        # non e' un unico override globale per l'intera chiamata.
        pesato = prevedi_macchina(
            1, freq, **comuni,
            categoria_per_macchina={10: "5_axis", 11: "torni"},
            pesi_per_categoria={"5_axis": {"freq": 0.05, "recency": 0.9, "carico": 0.05}},
        )
        self.assertEqual(pesato[0]["macchina_id"], 10)

    def test_cold_start_fallback_fase_globale(self):
        # Famiglia 99 senza ALCUNO storico proprio (ne' per famiglia ne' per fase) ->
        # fallback sulla fase GLOBALE (quali macchine fanno tipicamente quella lavorazione,
        # su qualunque famiglia), invece di restare senza suggerimento.
        globale = {"sgr": [(20, 10), (21, 2)]}
        ranked = prevedi_macchina(99, {}, fase="sgr", freq_fase_globale=globale)
        self.assertEqual([r["macchina_id"] for r in ranked], [20, 21])
        self.assertTrue(ranked[0]["fallback_globale"])

        # Se la famiglia HA storico proprio, il fallback globale non si attiva.
        freq = {1: [(10, 5)]}
        ranked2 = prevedi_macchina(1, freq, fase="sgr", freq_fase_globale=globale)
        self.assertEqual([r["macchina_id"] for r in ranked2], [10])
        self.assertFalse(ranked2[0]["fallback_globale"])

        # Senza freq_fase_globale, resta vuoto come prima (retro-compatibile).
        self.assertEqual(prevedi_macchina(99, {}), [])


class FinestraCaricoPerOreTest(SimpleTestCase):
    """Una finestra di saturazione fissa (14gg) sovra/sottostima il carico reale per
    lavori molto piu' corti o lunghi di 14gg: va dimensionata sulla durata tipica."""

    def test_senza_ore_medie_usa_il_default(self):
        self.assertEqual(finestra_carico_per_ore(None), 14)
        self.assertEqual(finestra_carico_per_ore(0), 14)

    def test_lavoro_breve_finestra_ridotta_al_minimo(self):
        # 8h (1 giorno lav.) -> il minimo (7gg), non 1: una finestra troppo stretta
        # sarebbe rumorosa (un solo giorno di carico non è rappresentativo).
        self.assertEqual(finestra_carico_per_ore(8), 7)

    def test_lavoro_lungo_finestra_proporzionale(self):
        # 160h / 8h-giorno = 20 giorni lavorativi -> finestra a 20 (tra min e max).
        self.assertEqual(finestra_carico_per_ore(160), 20)

    def test_lavoro_molto_lungo_finestra_limitata_al_massimo(self):
        # 400h -> 50 giorni, ma il tetto (30gg) evita di guardare troppo in la'
        # (previsioni lontane nel tempo sono meno affidabili).
        self.assertEqual(finestra_carico_per_ore(400), 30)


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


class CostruisciIndiceMacchineFaseTest(TestCase):
    """L'indice di affinita' per (famiglia, fase) deve imparare SOLO da lavori
    completati: una pianificazione ancora aperta non deve auto-rinforzare il
    proprio stesso suggerimento prima di essere mai stata eseguita (feedback loop)."""

    def setUp(self):
        a1 = Asset.objects.create(asset_tag="CNC-T1", name="T1", asset_type=Asset.TYPE_WORK_MACHINE)
        a2 = Asset.objects.create(asset_tag="CNC-T2", name="T2", asset_type=Asset.TYPE_WORK_MACHINE)
        self.m1 = Macchina.objects.create(asset=a1, categoria=Macchina.CAT_5AXIS)
        self.m2 = Macchina.objects.create(asset=a2, categoria=Macchina.CAT_5AXIS)
        self.fam = FamigliaPezzo.objects.create(nome="gimbal")

    def test_esclude_pianificazioni_non_completate(self):
        Pianificazione.objects.create(
            macchina=self.m1, famiglia=self.fam, fase="sgr",
            data=date(2026, 6, 22), turno="giorno",
            stato=Pianificazione.STATO_COMPLETATA, fonte=Pianificazione.FONTE_IMPORT,
        )
        # Assegnazione manuale ancora APERTA su m2: non deve pesare nell'indice.
        Pianificazione.objects.create(
            macchina=self.m2, famiglia=self.fam, fase="sgr",
            data=date(2026, 6, 23), turno="giorno",
            stato=Pianificazione.STATO_PIANIFICATA, fonte=Pianificazione.FONTE_MANUALE,
        )
        idx = costruisci_indice_macchine_fase()
        macchine = dict(idx[(self.fam.id, "sgr")])
        self.assertIn(self.m1.id, macchine)
        self.assertNotIn(self.m2.id, macchine)


class CostruisciIndiceMacchineFaseGlobaleTest(TestCase):
    """Fallback cold-start: aggregato su TUTTE le famiglie (non serve una famiglia
    specifica), solo lavori completati (stessa regola anti-feedback-loop)."""

    def setUp(self):
        a1 = Asset.objects.create(asset_tag="CNC-G1", name="G1", asset_type=Asset.TYPE_WORK_MACHINE)
        a2 = Asset.objects.create(asset_tag="CNC-G2", name="G2", asset_type=Asset.TYPE_WORK_MACHINE)
        self.m1 = Macchina.objects.create(asset=a1, categoria=Macchina.CAT_5AXIS)
        self.m2 = Macchina.objects.create(asset=a2, categoria=Macchina.CAT_5AXIS)
        self.fam_a = FamigliaPezzo.objects.create(nome="gimbal")
        self.fam_b = FamigliaPezzo.objects.create(nome="sombrero")

    def test_aggrega_su_tutte_le_famiglie_solo_completate(self):
        Pianificazione.objects.create(
            macchina=self.m1, famiglia=self.fam_a, fase="sgr",
            data=date(2026, 6, 22), turno="giorno",
            stato=Pianificazione.STATO_COMPLETATA, fonte=Pianificazione.FONTE_IMPORT,
        )
        Pianificazione.objects.create(
            macchina=self.m1, famiglia=self.fam_b, fase="sgr",
            data=date(2026, 6, 23), turno="giorno",
            stato=Pianificazione.STATO_COMPLETATA, fonte=Pianificazione.FONTE_IMPORT,
        )
        Pianificazione.objects.create(
            macchina=self.m2, famiglia=self.fam_a, fase="sgr",
            data=date(2026, 6, 24), turno="giorno",
            stato=Pianificazione.STATO_PIANIFICATA, fonte=Pianificazione.FONTE_MANUALE,
        )
        idx = costruisci_indice_macchine_fase_globale()
        macchine = dict(idx["sgr"])
        self.assertEqual(macchine.get(self.m1.id), 2)  # entrambe le famiglie completate
        self.assertNotIn(self.m2.id, macchine)  # non completata
