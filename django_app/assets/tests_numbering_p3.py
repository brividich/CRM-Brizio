"""3.3 — N. interno asset opt-in (nessuna auto-assegnazione alla creazione)."""
from __future__ import annotations

from django.test import TestCase

from .models import Asset


class AssetInternalNumberOptInTests(TestCase):
    def test_internal_number_vuoto_resta_vuoto_alla_creazione(self):
        a1 = Asset.objects.create(asset_tag="NUM-1", name="A1")
        a2 = Asset.objects.create(asset_tag="NUM-2", name="A2")
        self.assertEqual(a1.internal_number, "")
        self.assertEqual(a2.internal_number, "")

    def test_internal_number_esplicito_non_sovrascritto(self):
        a = Asset.objects.create(asset_tag="NUM-3", name="A3", internal_number="ABC-99")
        self.assertEqual(a.internal_number, "ABC-99")
