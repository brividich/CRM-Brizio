"""Test F2a — matcher competenza-macchina → assets.Asset (sola lettura).

Copre la precisione del match (DM1≠DM10), i codici sole-lettere/numerici, gli
ambigui, gli assenti, il caso ZEISS (nome completo) e lo smoke del comando.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import TestCase, override_settings

from assets.models import Asset

from .services.skillmatrix_match import (
    CONF_ASSENTE,
    CONF_ESATTO,
    CONF_PARZIALE,
    STR_ASSET_TAG,
    STR_MANUALE,
    STR_NAME,
    IndiceAssetSkm,
    costruisci_righe_report,
    match_per_codice,
    match_per_nome,
    riepilogo,
)


@dataclass
class StubAsset:
    id: int
    asset_tag: str
    name: str
    asset_type: str = "CNC"


def _indice(*assets) -> IndiceAssetSkm:
    return IndiceAssetSkm.costruisci(list(assets))


class MatcherUnitTests(TestCase):
    def test_match_esatto_su_tag(self):
        idx = _indice(StubAsset(1, "CNC-DM3-001", "DM3 - DMG DMC 85"))
        r = match_per_codice("DM3", idx)
        self.assertEqual(r.confidenza, CONF_ESATTO)
        self.assertEqual(r.strategia, STR_ASSET_TAG)
        self.assertEqual(r.asset.id, 1)

    def test_match_parziale_solo_su_nome(self):
        idx = _indice(StubAsset(1, "INV-00045", "DM3 - DMG DMC 85"))
        r = match_per_codice("DM3", idx)
        self.assertEqual(r.confidenza, CONF_PARZIALE)
        self.assertEqual(r.strategia, STR_NAME)
        self.assertEqual(r.asset.id, 1)

    def test_precisione_dm1_vs_dm10_dm11(self):
        idx = _indice(
            StubAsset(1, "CNC-DM1-001", "DM1 - DIXI"),
            StubAsset(10, "CNC-DM10-010", "DM10 - DMC 85 Duoblock"),
            StubAsset(11, "CNC-DM11-011", "DM11 - DMC 85 Monoblock"),
        )
        self.assertEqual(match_per_codice("DM1", idx).asset.id, 1)
        self.assertEqual(match_per_codice("DM10", idx).asset.id, 10)
        self.assertEqual(match_per_codice("DM11", idx).asset.id, 11)

    def test_codice_sole_lettere(self):
        idx = _indice(StubAsset(7, "CNC-STZ-7", "STZ - Stozzatrice"))
        r = match_per_codice("STZ", idx)
        self.assertEqual(r.confidenza, CONF_ESATTO)
        self.assertEqual(r.asset.id, 7)

    def test_codice_cifra_iniziale(self):
        idx = _indice(StubAsset(8, "CNC-35S-8", "35S - AKEBONO ANCL 35 XL"))
        r = match_per_codice("35S", idx)
        self.assertEqual(r.confidenza, CONF_ESATTO)
        self.assertEqual(r.asset.id, 8)

    def test_ambiguo_su_tag(self):
        idx = _indice(
            StubAsset(1, "CNC-DM6-A", "DM6 uno"),
            StubAsset(2, "CNC-DM6-B", "DM6 due"),
        )
        r = match_per_codice("DM6", idx)
        self.assertEqual(r.confidenza, CONF_PARZIALE)
        self.assertEqual(r.strategia, STR_MANUALE)
        self.assertIsNone(r.asset)

    def test_assente(self):
        idx = _indice(StubAsset(1, "CNC-DM3-001", "DM3 - DMG"))
        r = match_per_codice("ZZZ9", idx)
        self.assertEqual(r.confidenza, CONF_ASSENTE)
        self.assertIsNone(r.asset)

    def test_zeiss_nome_completo(self):
        idx = _indice(
            StubAsset(1, "CMM-001", "ZEISS CONTURA G2"),
            StubAsset(2, "CMM-002", "ZEISS PRISMO NAVIGATOR"),
        )
        r = match_per_nome("ZEISS - CONTURA G2", idx)
        self.assertEqual(r.confidenza, CONF_PARZIALE)
        self.assertEqual(r.asset.id, 1)

    def test_zeiss_assente_se_nessun_overlap(self):
        idx = _indice(StubAsset(1, "CNC-DM3-001", "DM3 - DMG"))
        r = match_per_nome("ZEISS - CONTURA G2", idx)
        self.assertEqual(r.confidenza, CONF_ASSENTE)

    def test_declassa_match_su_asset_non_macchina(self):
        # Match esatto su tag ma tipo non-macchina (PC) → declassato.
        idx = _indice(StubAsset(900, "CNC-DM3-001-PC", "DM3 pc", asset_type="PC"))
        righe = costruisci_righe_report(
            [{"competenza_key": "DM3", "display": "DM3", "codice": "DM3"}], idx,
        )
        self.assertEqual(righe[0]["confidenza"], CONF_PARZIALE)
        self.assertIn("non-macchina", righe[0]["azione_suggerita"])

    def test_declassa_codice_corto(self):
        # 'HI' colpisce IT-PC-HI (mistippato OTHER): regola codice corto ≤2.
        idx = _indice(StubAsset(521, "IT-PC-HI", "PCHI", asset_type="OTHER"))
        righe = costruisci_righe_report(
            [{"competenza_key": "HI", "display": "HI - HITACHI", "codice": "HI"}], idx,
        )
        self.assertEqual(righe[0]["confidenza"], CONF_PARZIALE)
        self.assertIn("corto", righe[0]["azione_suggerita"])

    def test_costruisci_righe_e_riepilogo(self):
        idx = _indice(
            StubAsset(1, "CNC-DM3-001", "DM3 - DMG"),
            StubAsset(2, "CMM-002", "ZEISS CONTURA G2"),
        )
        competenze = [
            {"competenza_key": "DM3", "display": "DM3 - DMG", "codice": "DM3"},
            {"competenza_key": "ZEISS - CONTURA G2", "display": "ZEISS - CONTURA G2", "codice": ""},
            {"competenza_key": "XYZ9", "display": "XYZ9 - inesistente", "codice": "XYZ9"},
        ]
        righe = costruisci_righe_report(competenze, idx)
        self.assertEqual(len(righe), 3)
        rep = riepilogo(righe)
        self.assertEqual(rep[CONF_ESATTO], 1)
        self.assertEqual(rep[CONF_PARZIALE], 1)
        self.assertEqual(rep[CONF_ASSENTE], 1)


@override_settings(SECURE_SSL_REDIRECT=False)
class CommandSmokeTests(TestCase):
    def test_comando_scrive_report(self):
        Asset.objects.create(asset_tag="CNC-DM3-001", name="DM3 - DMG DMC 85")
        with TemporaryDirectory() as tmp:
            catalogo = Path(tmp) / "cat.csv"
            output = Path(tmp) / "report.csv"
            with catalogo.open("w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh)
                w.writerow(["competenza_key", "competenza_display", "tipo", "codice_asset_match", "alias_storici", "note"])
                w.writerow(["DM3", "DM3 - DMG DMC 85", "macchina", "DM3", "", ""])
                w.writerow(["Affilatura", "Affilatura", "processo", "", "", ""])  # ignorata
                w.writerow(["corsi attivati", "corsi attivati", "contatore", "", "", ""])  # ignorata
            call_command("skm_asset_match_report", catalogo=str(catalogo), output=str(output))
            self.assertTrue(output.exists())
            with output.open("r", encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh, delimiter=";"))
            # solo la riga macchina nel report
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["competenza_key"], "DM3")
            self.assertEqual(rows[0]["confidenza"], CONF_ESATTO)
