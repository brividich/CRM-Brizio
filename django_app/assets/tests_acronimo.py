from django.test import TestCase

from .forms import AssetForm, WorkMachineAssetForm
from .models import Asset
from .services.ricerca_flessibile import testo_q


class AssetAcronimoTests(TestCase):
    def test_vuoto_di_default(self):
        asset = Asset.objects.create(asset_tag="ACR-1", name="Tornio")
        self.assertEqual(asset.acronimo, "")

    def test_non_univoco(self):
        Asset.objects.create(asset_tag="ACR-2", name="Centro A", acronimo="DM11")
        Asset.objects.create(asset_tag="ACR-3", name="Centro B", acronimo="DM11")
        self.assertEqual(Asset.objects.filter(acronimo="DM11").count(), 2)

    def test_campo_nei_form(self):
        self.assertIn("acronimo", AssetForm.Meta.fields)
        self.assertEqual(AssetForm.Meta.labels["acronimo"], "Acronimo")
        self.assertIn("acronimo", WorkMachineAssetForm.Meta.fields)
        self.assertIn("acronimo", WorkMachineAssetForm.asset_field_names)

    def test_ricerca_trova_per_acronimo(self):
        asset = Asset.objects.create(asset_tag="ACR-4", name="Carrello automatico", acronimo="AGV1")
        Asset.objects.create(asset_tag="ACR-5", name="Altro")
        trovati = Asset.objects.filter(testo_q("agv 1", ("name", "acronimo"), compatti=("name", "acronimo")))
        self.assertEqual(list(trovati), [asset])
