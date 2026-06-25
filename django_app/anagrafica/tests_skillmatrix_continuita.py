"""F5 — test continuità operativa: sospensione/riattivazione automatica + seed."""
from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, ContinuitaOperativa,
    LivelloSkm, ProcessoCriticoContinuita,
)
from .services.skillmatrix_continuita import MARKER, applica_sospensioni

OGGI = date(2026, 6, 25)


class ContinuitaSospensioneTests(TestCase):
    def setUp(self):
        self.proc = ProcessoCriticoContinuita.objects.create(
            nome="TEST-PT", finestra_mesi=12, preavviso_mesi=9)
        self.asset = Asset.objects.create(asset_tag="CNC-PT-1", name="Linea PT", asset_type="CNC")
        self.ab = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=1, asset=self.asset, livello=LivelloSkm.AUTONOMO)
        self.co = ContinuitaOperativa.objects.create(
            legacy_anagrafica_id=1, processo=self.proc, abilitazione=self.ab,
            ultima_esecuzione=OGGI - timedelta(days=400))  # > 12 mesi → persa

    def test_persa_sospende_abilitazione(self):
        stats = applica_sospensioni(oggi=OGGI)
        self.assertEqual(stats["sospese"], 1)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.stato, AbilitazioneMacchina.STATO_SOSPESA)
        self.assertIn(MARKER, self.ab.note)
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 1)

    def test_dry_run_non_scrive(self):
        stats = applica_sospensioni(oggi=OGGI, apply=False)
        self.assertEqual(stats["da_sospendere"], 1)
        self.assertEqual(stats["sospese"], 0)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.stato, AbilitazioneMacchina.STATO_ATTIVA)

    def test_idempotente(self):
        applica_sospensioni(oggi=OGGI)
        stats = applica_sospensioni(oggi=OGGI)
        self.assertEqual(stats["sospese"], 0)  # già sospesa
        self.assertEqual(AbilitazioneMacchina.objects.filter(
            stato=AbilitazioneMacchina.STATO_SOSPESA).count(), 1)

    def test_recupero_riattiva_solo_se_marcata(self):
        applica_sospensioni(oggi=OGGI)            # sospende (marker)
        self.co.ultima_esecuzione = OGGI          # continuità recuperata
        self.co.save()
        stats = applica_sospensioni(oggi=OGGI)
        self.assertEqual(stats["riattivate"], 1)
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.stato, AbilitazioneMacchina.STATO_ATTIVA)
        self.assertNotIn(MARKER, self.ab.note)

    def test_non_riattiva_sospensioni_di_altra_origine(self):
        # Abilitazione sospesa manualmente (senza marker) + continuità mantenuta.
        a2 = Asset.objects.create(asset_tag="CNC-PT-2", name="Linea PT2", asset_type="CNC")
        ab2 = AbilitazioneMacchina.objects.create(
            legacy_anagrafica_id=2, asset=a2, livello=LivelloSkm.AUTONOMO,
            stato=AbilitazioneMacchina.STATO_SOSPESA, note="sospesa per altro motivo")
        ContinuitaOperativa.objects.create(
            legacy_anagrafica_id=2, processo=self.proc, abilitazione=ab2,
            ultima_esecuzione=OGGI)  # mantenuta
        applica_sospensioni(oggi=OGGI)
        ab2.refresh_from_db()
        self.assertEqual(ab2.stato, AbilitazioneMacchina.STATO_SOSPESA)  # NON riattivata


class ContinuitaSeedTests(TestCase):
    def test_seed_cndpt_presente(self):
        # La data migration 0073 semina CND-PT.
        self.assertTrue(ProcessoCriticoContinuita.objects.filter(nome="CND-PT").exists())
