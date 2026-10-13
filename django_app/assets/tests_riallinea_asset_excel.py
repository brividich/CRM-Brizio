import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase
from openpyxl import Workbook

from assets.models import Asset, AssetEndpoint, AssetITDetails


class RiallineaAssetDaExcelTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        wb = Workbook()
        ws = wb.active
        ws.title = "Segmentation 192.168.23.x"
        ws.append(["REPARTO", "UTENTE", "NOME PC", "VLAN", "IP", "TIPO", "OS", "MODELLO", "ID", "PUNTO", "PORTA SWITCH", "RAM"])
        ws.append(["CED", None, "PCTEST", 23, 12, "PC", "WINDOWS 11", "OptiPlex", "SN123", "Q1.01", "A1.02", "16GB"])
        ws.append(["CED", None, "PCASSENTE", 23, 99, "PC", "WINDOWS 11", None, None, None, None, None])
        self.path = str(Path(self.dir.name) / "inv.xlsx")
        wb.save(self.path)
        self.asset = Asset.objects.create(name="PCTEST", asset_type=Asset.TYPE_PC, model="Vecchio")
        AssetEndpoint.objects.create(asset=self.asset, endpoint_name="PCTEST", vlan=23, ip="192.168.23.12")

    def _run(self, *extra):
        out = StringIO()
        call_command("riallinea_asset_da_excel", file=self.path, sheets="Segmentation", stdout=out, *extra)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        out = self._run()
        self.assertIn("DRY-RUN", out)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.model, "Vecchio")

    def test_apply_sovrascrive_e_non_crea(self):
        n_asset = Asset.objects.count()
        self._run("--apply")
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.model, "OptiPlex")
        self.assertEqual(self.asset.serial_number, "SN123")
        self.assertEqual(self.asset.reparto, "CED")
        ep = self.asset.endpoints.get()
        self.assertEqual((ep.punto, ep.switch_port, ep.ip), ("Q1.01", "A1.02", "192.168.23.12"))
        det = AssetITDetails.objects.get(asset=self.asset)
        self.assertEqual((det.os, det.ram), ("WINDOWS 11", "16GB"))
        self.assertEqual(Asset.objects.count(), n_asset)
        self.assertEqual(self.asset.name, "PCTEST")

    def test_riga_senza_asset_e_solo_segnalata(self):
        out = self._run("--apply")
        self.assertIn("non trovati=1", out)
