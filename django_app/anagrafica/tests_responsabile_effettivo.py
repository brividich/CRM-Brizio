from django.test import TestCase
from anagrafica.models import (
    AreaAziendale, DipendenteAnagraficaAziendale, Reparto,
)
from anagrafica.services.reparto_canonico import (
    resolve_responsabile_effettivo, build_responsabile_effettivo_map,
)


class ResponsabileEffettivoTests(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="Produzione", caporeparto_legacy_id=10)
        self.area_con_resp = AreaAziendale.objects.create(
            nome="Qualità", reparto=self.rep, responsabile_legacy_id=20,
        )
        self.area_senza_resp = AreaAziendale.objects.create(
            nome="Linea 1", reparto=self.rep,
        )

    def test_area_vince_sul_reparto_quando_differisce(self):
        self.assertEqual(
            resolve_responsabile_effettivo(area=self.area_con_resp, reparto=self.rep), 20
        )

    def test_fallback_al_caporeparto_se_area_senza_responsabile(self):
        self.assertEqual(
            resolve_responsabile_effettivo(area=self.area_senza_resp, reparto=self.rep), 10
        )

    def test_none_se_nessuno(self):
        rep2 = Reparto.objects.create(nome="Vuoto")
        area2 = AreaAziendale.objects.create(nome="A2", reparto=rep2)
        self.assertIsNone(resolve_responsabile_effettivo(area=area2, reparto=rep2))

    def test_map_per_dipendente(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=100, area_aziendale=self.area_con_resp,
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=101, area_aziendale=self.area_senza_resp,
        )
        m = build_responsabile_effettivo_map([100, 101])
        self.assertEqual(m, {100: 20, 101: 10})


class SyncResponsabileEffettivoTests(TestCase):
    def setUp(self):
        self.rep = Reparto.objects.create(nome="RepX", caporeparto_legacy_id=10)
        self.area = AreaAziendale.objects.create(
            nome="AreaX", reparto=self.rep, responsabile_legacy_id=20,
        )

    def test_sync_scrive_responsabile_area_non_capo_reparto(self):
        from anagrafica.views import _sync_aziendale_from_reparto
        _sync_aziendale_from_reparto(
            legacy_id=100, reparto_nome="RepX",
            area_aziendale_id=self.area.id, saved_by=None,
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=100)
        self.assertEqual(az.caporeparto_legacy_id, 20)  # area vince

    def test_sync_fallback_capo_reparto_se_area_senza_responsabile(self):
        area2 = AreaAziendale.objects.create(nome="AreaY", reparto=self.rep)
        from anagrafica.views import _sync_aziendale_from_reparto
        _sync_aziendale_from_reparto(
            legacy_id=101, reparto_nome="RepX",
            area_aziendale_id=area2.id, saved_by=None,
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=101)
        self.assertEqual(az.caporeparto_legacy_id, 10)
