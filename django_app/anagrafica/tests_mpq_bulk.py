"""1.8 — Abilitazione MPQ in bulk: più dipendenti su un processo."""
from __future__ import annotations

from django.test import TestCase

from .models_mpq import AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato
from .views_mpq import bulk_abilita_processo


class BulkAbilitaProcessoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cli = ClienteQualificante.objects.create(nome="ACME")
        cls.proc = ProcessoQualificato.objects.create(nome="NDT-PT", cliente=cls.cli)

    @staticmethod
    def _ruoli():
        return {
            "is_qualificato": True,
            "is_addetto": False,
            "is_controllore": False,
            "is_part145": False,
        }

    def test_crea_n_abilitazioni(self):
        creati, gia = bulk_abilita_processo(
            self.proc, [10, 20, 30], ruoli=self._ruoli(), stato="ATTIVA"
        )
        self.assertEqual(len(creati), 3)
        self.assertEqual(gia, 0)
        self.assertEqual(
            AbilitazioneProcesso.objects.filter(processo=self.proc).count(), 3
        )

    def test_idempotente_e_dedup(self):
        AbilitazioneProcesso.objects.create(
            legacy_anagrafica_id=10, nominativo_esterno="", processo=self.proc
        )
        creati, gia = bulk_abilita_processo(
            self.proc, [10, 10, 20], ruoli=self._ruoli(), stato="ATTIVA"
        )
        self.assertEqual(len(creati), 1)
        self.assertEqual(creati[0].legacy_anagrafica_id, 20)
        self.assertEqual(gia, 1)

    def test_lista_vuota_non_crea_nulla(self):
        creati, gia = bulk_abilita_processo(
            self.proc, [], ruoli=self._ruoli(), stato="ATTIVA"
        )
        self.assertEqual(creati, [])
        self.assertEqual(gia, 0)
        self.assertEqual(
            AbilitazioneProcesso.objects.filter(processo=self.proc).count(), 0
        )

    def test_ruoli_e_stato_applicati(self):
        creati, _ = bulk_abilita_processo(
            self.proc,
            [42],
            ruoli={"is_qualificato": True, "is_addetto": True,
                   "is_controllore": False, "is_part145": True},
            stato="ATTIVA",
            note="da corso X",
        )
        ab = creati[0]
        self.assertTrue(ab.is_addetto)
        self.assertTrue(ab.is_part145)
        self.assertEqual(ab.note, "da corso X")
