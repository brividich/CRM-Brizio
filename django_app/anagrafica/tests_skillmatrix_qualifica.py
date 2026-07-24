"""Skill Matrix MOD.187 — gate qualificante I→L (1.12).

Un'abilitazione a livello ≥ L (INTERMEDIO) su una macchina è consentita solo se
il dipendente ha il **corso qualificante** della macchina completato e valido
(``TrainingDeadline``). Il corso qualificante è dichiarato su
``CompetenzaSkm.corso_qualificante``. L'override resta possibile ma va tracciato
sullo storico append-only (``AbilitazioneMacchinaStorico``). Nessun dato reale.
"""
from __future__ import annotations

from django.test import TestCase

from assets.models import Asset

from .models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
    TrainingCourse,
    TrainingDeadline,
    TrainingPlan,
)
from .services import skillmatrix_qualifica as Q


def _corso(codice="QC"):
    plan = TrainingPlan.objects.create(codice=f"PL-{codice}", nome="Piano")
    return TrainingCourse.objects.create(
        piano=plan, codice=codice, titolo=f"Corso {codice}", durata_ore_teorica=1)


class GateSetup(TestCase):
    def setUp(self):
        SkillMatrixConfig.get_instance()
        self.asset = Asset.objects.create(asset_tag="CNC-Q", name="Macchina Q",
                                          asset_type="CNC", reparto="Officina")
        self.corso = _corso()
        self.comp = CompetenzaSkm.objects.create(
            competenza_key="Q", tipo="macchina", asset=self.asset,
            corso_qualificante=self.corso)

    def _deadline(self, legacy, stato):
        return TrainingDeadline.objects.create(
            corso=self.corso, legacy_anagrafica_id=legacy, stato_scadenza=stato)


class CorsoQualificanteTests(GateSetup):
    def test_risolve_corso_da_asset(self):
        self.assertEqual(Q.corso_qualificante_asset(self.asset.id), self.corso)

    def test_none_se_non_dichiarato(self):
        a2 = Asset.objects.create(asset_tag="CNC-Z", name="Z", asset_type="CNC")
        CompetenzaSkm.objects.create(competenza_key="Z", tipo="macchina", asset=a2)
        self.assertIsNone(Q.corso_qualificante_asset(a2.id))


class ValidaLivelloTests(GateSetup):
    def test_livello_i_sempre_ammesso(self):
        r = Q.valida_livello(500, self.asset.id, LivelloSkm.IN_FORMAZIONE)
        self.assertTrue(r["ammesso"])
        self.assertFalse(r["richiede_corso"])

    def test_l_senza_corso_valido_negato(self):
        r = Q.valida_livello(500, self.asset.id, LivelloSkm.INTERMEDIO)  # nessuna deadline
        self.assertFalse(r["ammesso"])
        self.assertEqual(r["corso"], self.corso)

    def test_l_con_corso_valido_ammesso(self):
        self._deadline(500, "VALIDO")
        r = Q.valida_livello(500, self.asset.id, LivelloSkm.INTERMEDIO)
        self.assertTrue(r["ammesso"])

    def test_l_con_corso_scaduto_negato(self):
        self._deadline(500, "SCADUTO")
        r = Q.valida_livello(500, self.asset.id, LivelloSkm.AUTONOMO)
        self.assertFalse(r["ammesso"])

    def test_l_senza_corso_dichiarato_ammesso(self):
        a2 = Asset.objects.create(asset_tag="CNC-N", name="N", asset_type="CNC")
        CompetenzaSkm.objects.create(competenza_key="N", tipo="macchina", asset=a2)
        r = Q.valida_livello(500, a2.id, LivelloSkm.AUTONOMO)
        self.assertTrue(r["ammesso"])
        self.assertFalse(r["richiede_corso"])


class ImpostaLivelloTests(GateSetup):
    def test_gate_violato_senza_forza_solleva(self):
        ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=500, asset=self.asset, livello=LivelloSkm.IN_FORMAZIONE)
        with self.assertRaises(ValueError):
            Q.imposta_livello(ab, LivelloSkm.INTERMEDIO)
        ab.refresh_from_db()
        self.assertEqual(ab.livello, LivelloSkm.IN_FORMAZIONE)  # invariato
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 0)

    def test_override_forza_applica_e_logga(self):
        ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=500, asset=self.asset, livello=LivelloSkm.IN_FORMAZIONE)
        Q.imposta_livello(ab, LivelloSkm.INTERMEDIO, forza=True)
        ab.refresh_from_db()
        self.assertEqual(ab.livello, LivelloSkm.INTERMEDIO)
        st = AbilitazioneMacchinaStorico.objects.get(legacy_anagrafica_id=500)
        self.assertEqual(st.fonte, AbilitazioneMacchinaStorico.FONTE_MANUALE)
        self.assertIn("OVERRIDE", st.note)

    def test_gate_ok_applica_senza_eccezione(self):
        self._deadline(500, "VALIDO")
        ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=500, asset=self.asset, livello=LivelloSkm.IN_FORMAZIONE)
        Q.imposta_livello(ab, LivelloSkm.AUTONOMO)
        ab.refresh_from_db()
        self.assertEqual(ab.livello, LivelloSkm.AUTONOMO)
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 0)


class ContatoreOperativiTests(GateSetup):
    """Contatore abilitati operativi per macchina (header colonna)."""

    def test_conta_operativi(self):
        # soglia operativa default = U (AUTONOMO). Due operativi, uno sotto soglia.
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=2, asset=self.asset, livello=LivelloSkm.ESPERTO)
        AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=3, asset=self.asset, livello=LivelloSkm.INTERMEDIO)
        counts = Q.conta_operativi_per_asset([self.asset.id])
        self.assertEqual(counts.get(self.asset.id), 2)
