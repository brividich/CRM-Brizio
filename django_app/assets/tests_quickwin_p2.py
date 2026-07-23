"""Blocco 2 — quick-win P2. 3.2: data acquisto + data fabbricazione sull'asset."""
from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import AssetForm, WorkMachineAssetForm
from .models import Asset

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetDataFabbricazioneTests(TestCase):
    def test_form_label_data_fabbricazione(self):
        self.assertEqual(AssetForm.Meta.labels["production_date"], "Data fabbricazione")
        self.assertEqual(WorkMachineAssetForm.Meta.labels["production_date"], "Data fabbricazione")

    def test_detail_mostra_data_acquisto_e_fabbricazione(self):
        admin = User.objects.create_superuser(
            username="asset_p2", email="asset_p2@x.local", password="x"
        )
        self.client.force_login(admin)
        asset = Asset.objects.create(
            asset_tag="P2-001", name="Tornio P2",
            purchase_date=date(2020, 3, 15), production_date=date(2019, 6, 1),
        )
        resp = self.client.get(reverse("assets:asset_view", args=[asset.id]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Data acquisto", body)
        self.assertIn("Data fabbricazione", body)
        self.assertIn("15-03-2020", body)
        self.assertIn("01-06-2019", body)
