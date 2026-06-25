"""F2b — test importer baseline (dry-run, apply, idempotenza, blocchi, CAR)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from assets.models import Asset

from .models import (
    AbilitazioneMacchina, AbilitazioneMacchinaStorico, SkmCorsiAttivati,
)
from .services.skillmatrix_importer import importa_skill_matrix

# Anagrafica sintetica: DEI MIRKO=1, BADALASSI ANDREA=2 (ROSSI MARIO assente).
FAKE_ANAG = [
    {"id": 1, "nome": "MIRKO", "cognome": "DEI"},
    {"id": 2, "nome": "ANDREA", "cognome": "BADALASSI"},
]

OPERATORI = """nome,reparto_area,turno_as_is,turno_to_be,is_car,is_academy,car_di_riferimento
DEI MIRKO,CN5G,N,,SI,NO,DEI MIRKO
BADALASSI ANDREA,CN5G,T2,,NO,NO,DEI MIRKO
ROSSI MARIO,CN5G,T1,,NO,NO,
"""

MATRICE = """operatore,competenza_key,livello,valore_grezzo,snapshot
DEI MIRKO,DM3,O,O,2026-04-30
BADALASSI ANDREA,DM3,U,U,2026-04-30
BADALASSI ANDREA,DM3,L,L,2024-04-22
BADALASSI ANDREA,MZ5,U,U,2026-04-30
BADALASSI ANDREA,Affilatura,U,U,2026-04-30
DEI MIRKO,corsi attivati,,5,2026-04-30
ROSSI MARIO,DM3,U,U,2026-04-30
BADALASSI ANDREA,QQNOKEY,U,U,2026-04-30
"""

STORICO = """operatore,competenza_key,liv_2024_04_22,liv_2026_04_30,variazione
BADALASSI ANDREA,DM3,L,U,promozione
"""


class ImporterTests(TestCase):
    def setUp(self):
        # DM3 esiste come asset → match esatto auto-confermato dal seed; MZ5 no.
        Asset.objects.create(asset_tag="CNC-DM3-001", name="DM3 DMG", asset_type="CNC")
        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        (d / "skm_operatori.csv").write_text(OPERATORI, encoding="utf-8")
        (d / "skm_matrice_livelli.csv").write_text(MATRICE, encoding="utf-8")
        (d / "skm_storico_delta.csv").write_text(STORICO, encoding="utf-8")
        self.dir = str(d)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, **kw):
        with patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=FAKE_ANAG):
            return importa_skill_matrix(base_dir=self.dir, **kw)

    def test_dry_run_non_scrive_ma_pianifica(self):
        stats = self._run(apply=False)
        self.assertFalse(stats["apply"])
        self.assertEqual(stats["operatori"]["risolti"], 2)
        self.assertIn("ROSSI MARIO", stats["operatori"]["non_risolti"])
        self.assertEqual(stats["abilitazioni"]["in_lista"], 2)   # DEI/DM3, BADALASSI/DM3
        self.assertEqual(stats["macchine_bloccate"], ["MZ5"])    # no asset confermato
        self.assertEqual(stats["processi_saltati"], 1)           # Affilatura
        self.assertEqual(stats["contatori"], 1)                  # corsi attivati
        self.assertIn("QQNOKEY", stats["competenze_sconosciute"])
        self.assertEqual(stats["storico"]["scatti"], 3)          # DM3: 2x2026 + 1x2024
        self.assertEqual(stats["coerenza_storico"]["mismatch"], [])
        # Nessuna scrittura in dry-run.
        self.assertEqual(AbilitazioneMacchina.objects.count(), 0)
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 0)

    def test_apply_scrive_baseline_e_storico(self):
        stats = self._run(apply=True)
        self.assertEqual(stats["abilitazioni"]["create"], 2)
        self.assertEqual(AbilitazioneMacchina.objects.count(), 2)
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 3)
        # CAR (DEI) → conteggiabile_nel_carico False; academy/normale True.
        dei = AbilitazioneMacchina.objects.get(legacy_anagrafica_id=1)
        self.assertFalse(dei.conteggiabile_nel_carico)
        self.assertEqual(dei.livello, "O")
        bad = AbilitazioneMacchina.objects.get(legacy_anagrafica_id=2)
        self.assertTrue(bad.conteggiabile_nel_carico)
        # Contatore corsi attivati.
        self.assertEqual(SkmCorsiAttivati.objects.get(legacy_anagrafica_id=1).numero, 5)
        # MZ5 bloccata → nessuna abilitazione su asset inesistente.
        self.assertEqual(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=2).count(), 1)

    def test_apply_idempotente(self):
        self._run(apply=True)
        self._run(apply=True)
        self.assertEqual(AbilitazioneMacchina.objects.count(), 2)
        self.assertEqual(AbilitazioneMacchinaStorico.objects.count(), 3)
        self.assertEqual(SkmCorsiAttivati.objects.count(), 1)
