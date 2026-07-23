"""3.3 — N. interno asset progressivo."""
from __future__ import annotations

from django.test import TestCase

from .models import Asset


class AssetInternalNumberProgressiveTests(TestCase):
    def test_internal_number_progressivo_alla_creazione(self):
        a1 = Asset.objects.create(asset_tag="NUM-1", name="A1")
        a2 = Asset.objects.create(asset_tag="NUM-2", name="A2")
        self.assertTrue(a1.internal_number.isdigit())
        self.assertEqual(int(a2.internal_number), int(a1.internal_number) + 1)

    def test_internal_number_esplicito_non_sovrascritto(self):
        a = Asset.objects.create(asset_tag="NUM-3", name="A3", internal_number="ABC-99")
        self.assertEqual(a.internal_number, "ABC-99")

    def test_internal_number_ignora_legacy_alfanumerico(self):
        # Un numero interno legacy alfanumerico non deve rompere il progressivo.
        Asset.objects.create(asset_tag="NUM-4", name="Legacy", internal_number="MAG-XY")
        a = Asset.objects.create(asset_tag="NUM-5", name="Nuovo")
        self.assertTrue(a.internal_number.isdigit())
