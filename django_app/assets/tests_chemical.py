"""Asset "Prodotto chimico" — link 1:1 a schede_sicurezza.ProdottoChimico + schermata dedicata."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Reparto
from schede_sicurezza.models import ProdottoChimico

from .forms import ChemicalAssetForm
from .models import Asset
from .tests import _complete_onboarding

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ChemicalAssetViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chem-user", password="pass12345")
        _complete_onboarding(self.user)

    def test_chemical_create_view_get_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:chemical_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Prodotto chimico")

    def test_chemical_create_view_creates_asset(self):
        rep = Reparto.objects.create(nome="Chimica")
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assets:chemical_create"), {
            "name": "Diluente", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "nuovo_nome": "Diluente X",
            "reparto_prodotto": rep.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            Asset.objects.filter(name="Diluente", asset_type=Asset.TYPE_CHEMICAL).exists()
        )

    def test_asset_create_redirects_chemical_type(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_create") + "?asset_type=PRODOTTO_CHIMICO")
        self.assertRedirects(resp, reverse("assets:chemical_create"),
                             fetch_redirect_response=False)

    def test_chemical_detail_shows_sds_and_hides_maintenance(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Acetone", reparto=rep, ubicazione="Scaffale A")
        a = Asset.objects.create(
            asset_tag="CHEM-3", name="Acetone",
            asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Scaffale A")        # logistica dal prodotto
        self.assertContains(resp, "Pittogrammi")       # blocco pericolosità
        # Il corpo standard (manutenzione/scadenze/assistenza) è nascosto: la sua
        # sezione contenitore non deve comparire per i chimici. Si ancora su
        # class="af-sections" (l'elemento HTML), non sulla stringa "af-sections"
        # che compare anche nelle regole CSS .af-sections del blocco <style>.
        self.assertNotContains(resp, 'class="af-sections"')

    def test_chemical_detail_rende_i_pittogrammi_come_simboli(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from schede_sicurezza.models import SchedaSicurezza

        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Diluente", reparto=rep)
        SchedaSicurezza.objects.create(
            prodotto=p, versione="1", is_corrente=True,
            pdf=SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n%finto\n", content_type="application/pdf"),
            pittogrammi=["GHS02", "GHS07"],
        )
        a = Asset.objects.create(
            asset_tag="CHEM-4", name="Diluente",
            asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[a.id]))
        # Gli stessi rombi CLP di schede_sicurezza, non il codice come testo.
        self.assertContains(resp, 'href="#ghs02"')
        self.assertContains(resp, 'href="#ghs07"')

    def test_chemical_detail_senza_pittogrammi_lo_dice(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Acqua demi", reparto=rep)
        a = Asset.objects.create(
            asset_tag="CHEM-5", name="Acqua demi",
            asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[a.id]))
        self.assertContains(resp, "SDS non disponibile")

    def test_non_chemical_detail_still_shows_maintenance(self):
        a = Asset.objects.create(asset_tag="IT-1", name="PC", asset_type=Asset.TYPE_PC)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="af-sections"')  # non-chimico: corpo standard presente
