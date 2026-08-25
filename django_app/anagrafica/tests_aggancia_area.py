from __future__ import annotations

import io

from django.core.management import call_command
from django.test import TestCase

from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto


def _run(**kwargs) -> str:
    out = io.StringIO()
    call_command("aggancia_area_da_testo", stdout=out, **kwargs)
    return out.getvalue()


def _dip(legacy_id: int, area_testo: str, **extra) -> DipendenteAnagraficaAziendale:
    return DipendenteAnagraficaAziendale.objects.create(
        legacy_anagrafica_id=legacy_id, area=area_testo, **extra
    )


class AggancioAreaDaTestoTest(TestCase):
    def setUp(self):
        self.agg_mont = Reparto.objects.create(nome="AGG/MONT")
        self.logistica = Reparto.objects.create(nome="LOGISTICA")
        self.area_mascheratura = AreaAziendale.objects.create(
            nome="Mascheratura", reparto=self.agg_mont
        )
        # Il caso reale in cui l'area porta lo stesso nome del reparto.
        self.area_logistica = AreaAziendale.objects.create(
            nome="Logistica", reparto=self.logistica
        )

    def test_dry_run_non_scrive(self):
        dip = _dip(1001, "MASCHERATURA")
        output = _run()
        dip.refresh_from_db()
        self.assertIsNone(dip.area_aziendale_id)
        self.assertIn("Anteprima", output)

    def test_match_diretto_sul_nome_area(self):
        dip = _dip(1002, "mascheratura")  # maiuscole diverse: stessa etichetta
        _run(applica=True)
        dip.refresh_from_db()
        self.assertEqual(dip.area_aziendale_id, self.area_mascheratura.id)

    def test_alias_reparto_usa_area_omonima_al_reparto(self):
        """`AGG` non e' un'area, ma ALIAS_REPARTO dice che sta in AGG/MONT."""
        area_agg_mont = AreaAziendale.objects.create(nome="AGG/MONT", reparto=self.agg_mont)
        dip = _dip(1003, "AGG")
        _run(applica=True)
        dip.refresh_from_db()
        self.assertEqual(dip.area_aziendale_id, area_agg_mont.id)

    def test_area_mancante_non_creata_senza_flag(self):
        dip = _dip(1004, "MONT")
        output = _run(applica=True)
        dip.refresh_from_db()
        self.assertIsNone(dip.area_aziendale_id)
        self.assertIn("servono --crea-aree", output)

    def test_crea_aree_crea_sotto_il_reparto_giusto(self):
        dip = _dip(1005, "MONT")
        _run(applica=True, crea_aree=True)
        dip.refresh_from_db()
        self.assertIsNotNone(dip.area_aziendale_id)
        self.assertEqual(dip.area_aziendale.nome, "Mont")
        self.assertEqual(dip.area_aziendale.reparto_id, self.agg_mont.id)

    def test_etichetta_sconosciuta_resta_scollegata(self):
        dip = _dip(1006, "TORNI")
        output = _run(applica=True, crea_aree=True)
        dip.refresh_from_db()
        self.assertIsNone(dip.area_aziendale_id)
        self.assertIn("TORNI", output)

    def test_filtro_reparto_esclude_gli_altri(self):
        dip_agg = _dip(1007, "MASCHERATURA")
        dip_log = _dip(1008, "LOGISTICA")
        _run(applica=True, reparto="AGG/MONT")
        dip_agg.refresh_from_db()
        dip_log.refresh_from_db()
        self.assertEqual(dip_agg.area_aziendale_id, self.area_mascheratura.id)
        self.assertIsNone(dip_log.area_aziendale_id)

    def test_dipendente_gia_agganciato_non_viene_toccato(self):
        altra = AreaAziendale.objects.create(nome="Altra", reparto=self.logistica)
        dip = _dip(1009, "MASCHERATURA", area_aziendale=altra)
        _run(applica=True)
        dip.refresh_from_db()
        self.assertEqual(dip.area_aziendale_id, altra.id)

    def test_cessato_escluso(self):
        from datetime import date

        dip = _dip(1010, "MASCHERATURA", data_cessazione=date(2020, 1, 1))
        _run(applica=True)
        dip.refresh_from_db()
        self.assertIsNone(dip.area_aziendale_id)
