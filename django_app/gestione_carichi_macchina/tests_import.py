"""Test di integrazione dell'importer: algoritmo (importa) e reader (openpyxl)."""
import tempfile
from datetime import date
from pathlib import Path

from django.test import TestCase

from assets.models import Asset

from .importer import Voce, importa, leggi_workbook
from .models import (
    FamigliaPezzo,
    Macchina,
    MacchinaAlias,
    MacchinaFamigliaAffinita,
    Pianificazione,
)


def _wm(tag, name):
    return Asset.objects.create(asset_tag=tag, name=name, asset_type=Asset.TYPE_WORK_MACHINE)


def _voci():
    d = date
    return [
        # snapshot vivo (idx 0)
        Voce("DM3", "5_axis", "giorno", d(2026, 6, 1), "8 gimbal (33h)", 0),
        Voce("DM3", "5_axis", "notte", d(2026, 6, 1), "2 gimbal fin", 0),
        Voce("MZ5", "5_axis", "giorno", d(2026, 6, 1), "2 koala", 0),   # non mappato
        Voce("DM6", "5_axis", "giorno", d(2026, 6, 2), "3 sottobas", 0),
        Voce("DM12", "5_axis", "giorno", d(2026, 6, 3), "3 sottobas", 0),
        Voce("DM6", "5_axis", "giorno", d(2026, 6, 4), "manutenzione", 0),  # ferma
        # snapshot piu' vecchio (idx 1): DM3 gimbal ripetuto -> settimane_presente 2
        Voce("DM3", "5_axis", "giorno", d(2026, 6, 1), "8 gimbal (33h)", 1),
    ]


class ImportAlgoritmoTest(TestCase):
    def setUp(self):
        _wm("CNC-DM3-12280000463", "DM3 - DMG Mori DMC 85")
        _wm("CNC-DM6-000060148189", "DM6-DMGMoriDMC125U")
        _wm("CNC-DM12-12670000953", "DM12-DMGMoriDMC160U")

    def test_import_popola_e_riporta_non_mappati(self):
        report = importa(_voci())

        self.assertEqual(report["macchine_mappate"], 3)
        self.assertEqual(Macchina.objects.count(), 3)
        codici_non_mappati = [c for c, _conf, _m in report["non_mappati"]]
        self.assertIn("MZ5", codici_non_mappati)

        # 4 lavori nel piano vivo (i 2 DM3, DM6 sottobas, DM12 sottobas); ferma e non-mappato esclusi
        self.assertEqual(report["pianificazioni_live"], 4)
        self.assertEqual(Pianificazione.objects.count(), 4)

        # DM6 marcata in manutenzione dalla cella 'manutenzione'
        dm6 = Macchina.objects.get(asset__asset_tag="CNC-DM6-000060148189")
        self.assertEqual(dm6.stato_pianificazione, Macchina.STATO_MANUTENZIONE)

        # settimane_presente dedotto dallo storico (gimbal DM3 6-1 presente in 2 snapshot)
        p = Pianificazione.objects.get(
            macchina__asset__asset_tag="CNC-DM3-12280000463",
            data=date(2026, 6, 1), turno="giorno",
        )
        self.assertEqual(p.settimane_presente, 2)
        self.assertEqual(p.ore, 33)

    def test_pool_equivalenza_da_confermare(self):
        importa(_voci())
        # DM6 e DM12 su 'sottobas' con stesse occorrenze e date disgiunte -> stesso pool
        aff = MacchinaFamigliaAffinita.objects.filter(
            famiglia__nome="sottobas"
        ).exclude(pool_equivalenza="")
        self.assertEqual(aff.count(), 2)
        pool_ids = set(aff.values_list("pool_equivalenza", flat=True))
        self.assertEqual(len(pool_ids), 1)
        self.assertTrue(all(a.da_confermare for a in aff))

    def test_idempotente(self):
        importa(_voci())
        importa(_voci())  # seconda esecuzione: nessun duplicato
        self.assertEqual(Macchina.objects.count(), 3)
        self.assertEqual(Pianificazione.objects.count(), 4)
        self.assertEqual(MacchinaAlias.objects.count(), 3)
        self.assertEqual(
            MacchinaFamigliaAffinita.objects.count(), 3
        )  # DM3/gimbal, DM6/sottobas, DM12/sottobas

    def test_dry_run_non_scrive(self):
        report = importa(_voci(), dry_run=True)
        self.assertEqual(report["macchine_mappate"], 3)
        self.assertEqual(Macchina.objects.count(), 0)
        self.assertEqual(Pianificazione.objects.count(), 0)

    def test_backlog_e_cicli(self):
        from .models import CicloStandard, Commessa, Operazione

        backlog = ["6 ragni ferrari", "Riordino APRILIA 1000"]
        cicli = ["CICLI APRILIA:", "* BAS SUP", "op1 DM3 = 550 cent/cad"]
        report = importa(_voci(), backlog=backlog, cicli_lines=cicli)

        self.assertEqual(report["commesse"], 2)
        c = Commessa.objects.get(nome="6 ragni ferrari")
        self.assertEqual(c.quantita, 6)  # pezzi dal numero iniziale

        self.assertEqual(report["cicli"], 1)
        self.assertEqual(report["operazioni"], 1)
        op = Operazione.objects.get()
        self.assertEqual(op.tempo_cent_cad, 550)
        self.assertIsNotNone(op.macchina_preferita_id)  # DM3 risolta sull'asset


class ReaderWorkbookTest(TestCase):
    def test_legge_layout_sintetico(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "AGG 01-06-2026"  # Excel vieta '/' nei titoli dei fogli
        ws.append(["", date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)])
        ws.append(["macchine 5 axis", None, None, None])
        ws.append(["DM3", "8 gimbal (33h)", "4 gimbal sgr", None])
        ws.append(["notturno", "2 gimbal fin", None, None])
        ws.append(["DM12", None, "3 sottobas", None])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sint.xlsx"
            wb.save(path)
            voci, titoli, backlog, cicli_lines = leggi_workbook(str(path))

        self.assertEqual(titoli, ["AGG 01-06-2026"])
        self.assertEqual(len(voci), 4)
        notte = [v for v in voci if v.turno == "notte"]
        self.assertEqual(len(notte), 1)
        self.assertEqual(notte[0].codice_macchina, "DM3")  # eredita la macchina sopra
        self.assertEqual(notte[0].data, date(2026, 6, 1))
        self.assertTrue(all(v.categoria == "5_axis" for v in voci))
        self.assertTrue(all(v.snapshot_idx == 0 for v in voci))
