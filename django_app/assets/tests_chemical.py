"""Asset "Prodotto chimico" — link 1:1 a schede_sicurezza.ProdottoChimico + schermata dedicata."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Reparto
from schede_sicurezza.models import ProdottoChimico

from .models import Asset

User = get_user_model()


class AssetProdottoChimicoModelTests(TestCase):
    def test_asset_can_link_prodotto_chimico(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Acetone", reparto=rep)
        a = Asset.objects.create(
            asset_tag="CHEM-1", name="Acetone",
            asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p,
        )
        self.assertEqual(a.asset_type, "PRODOTTO_CHIMICO")
        self.assertEqual(p.asset_container, a)
