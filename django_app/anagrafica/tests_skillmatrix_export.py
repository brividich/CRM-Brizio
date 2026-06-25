"""Test F2a — export codici asset + match report OFFLINE da CSV (ambiente target)."""
from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from assets.models import Asset
from .management.commands.skm_asset_match_report import Command as ReportCmd


class ExportAssetsTests(TestCase):
    def test_export_scrive_solo_metadati_asset(self):
        Asset.objects.create(asset_tag="CNC-DM3-001", name="DMG DMC 85", asset_type="CNC")
        Asset.objects.create(asset_tag="IT-PC-01", name="PC ufficio", asset_type="PC")
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "assets.csv"
            call_command("skm_export_assets", output=str(out))
            righe = list(csv.DictReader(out.open(encoding="utf-8-sig"), delimiter=";"))
        self.assertEqual(len(righe), 2)
        intestazioni = set(righe[0].keys())
        self.assertEqual(intestazioni, {"id", "asset_tag", "internal_number", "name", "asset_type"})
        tags = {r["asset_tag"] for r in righe}
        self.assertEqual(tags, {"CNC-DM3-001", "IT-PC-01"})


class ReportOfflineTests(TestCase):
    @staticmethod
    def _scrivi_catalogo(path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["competenza_key", "competenza_display", "tipo",
                        "codice_asset_match", "alias_storici", "note"])
            w.writerow(["DM3", "DM3 - DMG DMC 85", "macchina", "DM3", "", ""])
            w.writerow(["FRES", "Fresatrice generica", "processo", "", "", ""])

    @staticmethod
    def _scrivi_assets(path: Path) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["id", "asset_tag", "internal_number", "name", "asset_type"])
            w.writerow(["7", "CNC-DM3-12280", "", "DMG Mori DMC 85", "CNC"])

    def test_match_offline_non_legge_il_db(self):
        # Nessun Asset nel DB: il match deve venire SOLO dal CSV degli asset.
        self.assertEqual(Asset.objects.count(), 0)
        with tempfile.TemporaryDirectory() as d:
            cat, assets, out = Path(d) / "c.csv", Path(d) / "a.csv", Path(d) / "r.csv"
            self._scrivi_catalogo(cat)
            self._scrivi_assets(assets)
            call_command("skm_asset_match_report",
                         catalogo=str(cat), assets_csv=str(assets), output=str(out))
            righe = list(csv.DictReader(out.open(encoding="utf-8-sig"), delimiter=";"))
        # Solo la macchina entra nel report (il processo è escluso).
        self.assertEqual(len(righe), 1)
        self.assertEqual(righe[0]["competenza_key"], "DM3")
        self.assertEqual(righe[0]["confidenza"], "esatto")
        self.assertEqual(righe[0]["asset_tag"], "CNC-DM3-12280")
        self.assertEqual(righe[0]["asset_match_id"], "7")

    def test_fallback_catalogo_da_modulo(self):
        # Senza CSV catalogo, il report ripiega sul modulo impacchettato: 42 macchine.
        competenze = ReportCmd._competenze_da_modulo()
        self.assertEqual(len(competenze), 42)
        self.assertTrue(all(c["competenza_key"] for c in competenze))
        self.assertIn("DM3", {c["competenza_key"] for c in competenze})
