"""F3 — test del resolver bridge read-only (pool, livello, KPI, copertura)."""
from __future__ import annotations

from django.test import TestCase

from assets.models import Asset

from .models import AbilitazioneMacchina, CompetenzaSkm, LivelloSkm, SkillMatrixConfig
from .services import skillmatrix_resolver as R


class ResolverTests(TestCase):
    def setUp(self):
        # Soglia operativa = U (default). Macchina A in reparto "Officina".
        SkillMatrixConfig.get_instance()
        self.a = Asset.objects.create(asset_tag="CNC-A", name="Macchina A",
                                      asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="A", tipo="macchina", asset=self.a)

        def ab(legacy, livello, **kw):
            return AbilitazioneMacchina.objects.create(
                legacy_anagrafica_id=legacy, asset=self.a, livello=livello, **kw)

        ab(101, LivelloSkm.AUTONOMO)                               # operativo (academy/normale)
        ab(102, LivelloSkm.ESPERTO)                                # operativo
        ab(103, LivelloSkm.INTERMEDIO)                             # sotto soglia (L < U)
        ab(104, LivelloSkm.AUTONOMO, conteggiabile_nel_carico=False)  # CAR: fuori pool
        ab(105, LivelloSkm.AUTONOMO, in_lista=False)              # non in lista
        ab(106, LivelloSkm.AUTONOMO, stato=AbilitazioneMacchina.STATO_SOSPESA)  # sospesa

    def test_pool_esclude_car_sottosoglia_sospese_e_fuorilista(self):
        self.assertEqual(set(R.pool_abilitati(self.a)), {101, 102})

    def test_pool_include_car_come_riserva_se_richiesto(self):
        self.assertEqual(set(R.pool_abilitati(self.a, includi_riserva=True)), {101, 102, 104})

    def test_pool_accetta_id_oltre_a_istanza(self):
        self.assertEqual(set(R.pool_abilitati(self.a.id)), {101, 102})

    def test_pool_livello_min_override(self):
        # Solo livello O e superiori.
        self.assertEqual(set(R.pool_abilitati(self.a, livello_min=LivelloSkm.ESPERTO)), {102})

    def test_livello_operatore(self):
        self.assertEqual(R.livello_operatore(101, self.a), "U")
        self.assertIsNone(R.livello_operatore(105, self.a))   # non in lista
        self.assertIsNone(R.livello_operatore(999, self.a))   # inesistente

    def test_kpi_uomo_solo(self):
        kpi = R.kpi_uomo_solo(self.a)
        self.assertEqual(kpi["n_operativi"], 2)
        self.assertEqual(kpi["soglia"], 2)
        self.assertFalse(kpi["a_rischio"])  # 2 >= 2

        b = Asset.objects.create(asset_tag="CNC-B", name="Macchina B",
                                 asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="B", tipo="macchina", asset=b)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=201, asset=b,
                                            livello=LivelloSkm.AUTONOMO)
        self.assertTrue(R.kpi_uomo_solo(b)["a_rischio"])  # 1 < 2

    def test_macchine_scoperte(self):
        # C è una macchina senza nessun abilitato in lista → scoperta.
        c = Asset.objects.create(asset_tag="CNC-C", name="Macchina C",
                                 asset_type="CNC", reparto="Officina")
        CompetenzaSkm.objects.create(competenza_key="C", tipo="macchina", asset=c)
        scoperte = R.macchine_scoperte("Officina")
        self.assertIn(c.id, scoperte)
        self.assertNotIn(self.a.id, scoperte)

    def test_prontezza_squadra(self):
        p = R.prontezza_squadra("Officina")
        # in lista attive su A: 101(U),102(O),103(L),104(U-CAR) = 4; operativi = 101,102 = 2.
        self.assertEqual(p["totale_in_lista"], 4)
        self.assertEqual(p["operativi"], 2)
        self.assertEqual(p["percentuale"], 50.0)
        self.assertEqual(p["n_macchine"], 1)

    def test_resolver_non_scrive(self):
        prima = AbilitazioneMacchina.objects.count()
        R.pool_abilitati(self.a)
        R.prontezza_squadra("Officina")
        R.macchine_scoperte("Officina")
        self.assertEqual(AbilitazioneMacchina.objects.count(), prima)
