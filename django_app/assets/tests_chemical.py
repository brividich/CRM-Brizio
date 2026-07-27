"""Asset "Prodotto chimico" — link 1:1 a schede_sicurezza.ProdottoChimico + schermata dedicata."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Reparto
from schede_sicurezza.models import ProdottoChimico

from .forms import ChemicalAssetForm
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


class ChemicalAssetFormTests(TestCase):
    def test_chemical_form_creates_new_prodotto_inline(self):
        rep = Reparto.objects.create(nome="Chimica")
        form = ChemicalAssetForm(data={
            "name": "Acetone", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "nuovo_nome": "Acetone 99%",
            "reparto_prodotto": rep.id, "nuovo_ubicazione": "Scaffale A",
        })
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.asset_type, Asset.TYPE_CHEMICAL)
        self.assertEqual(asset.prodotto_chimico.nome, "Acetone 99%")
        self.assertEqual(asset.prodotto_chimico.ubicazione, "Scaffale A")
        self.assertTrue(asset.asset_tag)  # autogenerato

    def test_chemical_form_links_existing_prodotto(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Diluente", reparto=rep)
        form = ChemicalAssetForm(data={
            "name": "Diluente", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "existing", "prodotto_chimico": p.id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.prodotto_chimico, p)

    def test_chemical_form_rejects_already_linked_prodotto(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Acido", reparto=rep)
        Asset.objects.create(asset_tag="CHEM-X", name="Acido",
                             asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p)
        form = ChemicalAssetForm(data={
            "name": "Acido 2", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "existing", "prodotto_chimico": p.id,
        })
        self.assertFalse(form.is_valid())

    def test_chemical_form_new_requires_nome_and_reparto(self):
        form = ChemicalAssetForm(data={
            "name": "X", "status": Asset.STATUS_IN_STOCK, "prodotto_mode": "new",
        })
        self.assertFalse(form.is_valid())
