"""Asset "Prodotto chimico" — link 1:1 a schede_sicurezza.ProdottoChimico + schermata dedicata."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import Reparto
from schede_sicurezza.models import ProdottoChimico

from .forms import AssetForm, ChemicalAssetForm
from .models import Asset, AssetCategory
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
            "prodotto_mode": "new", "pc-nome": "Acetone 99%",
            "pc-reparto": rep.id, "pc-ubicazione": "Scaffale A",
        })
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.asset_type, Asset.TYPE_CHEMICAL)
        self.assertEqual(asset.prodotto_chimico.nome, "Acetone 99%")
        self.assertEqual(asset.prodotto_chimico.ubicazione, "Scaffale A")
        self.assertTrue(asset.asset_tag)  # autogenerato

    def test_chemical_form_salva_i_campi_prima_esclusivi_di_schede_sicurezza(self):
        """Il ramo "nuovo prodotto" chiede gli stessi dati della schermata SDS."""
        rep = Reparto.objects.create(nome="Chimica")
        form = ChemicalAssetForm(data={
            "name": "Sgrassante", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "pc-nome": "Sgrassante K", "pc-reparto": rep.id,
            "pc-famiglia": "Detergenti", "pc-sottocategoria": "Alcalini",
            "pc-numero_interno": "CH-014", "pc-codice_prodotto": "SK-9",
            "pc-quantita_presente": "20 L", "pc-attivo": "on",
            "pc-pittogrammi": ["GHS05", "GHS07"],
        })
        self.assertTrue(form.is_valid(), form.errors)
        prodotto = form.save().prodotto_chimico
        self.assertEqual(prodotto.famiglia, "Detergenti")
        self.assertEqual(prodotto.sottocategoria, "Alcalini")
        self.assertEqual(prodotto.numero_interno, "CH-014")
        self.assertEqual(prodotto.codice_prodotto, "SK-9")
        self.assertEqual(prodotto.quantita_presente, "20 L")
        self.assertEqual(prodotto.pittogrammi, ["GHS05", "GHS07"])
        self.assertTrue(prodotto.attivo)

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

    def test_chemical_form_aggancia_la_categoria_prodotti_chimici(self):
        """Senza categoria assegnata l'asset ricadeva sulla label del tipo
        ("Prodotto chimico", singolare) invece della vera AssetCategory."""
        categoria = AssetCategory.objects.create(
            code="prodotti-chimici", label="Prodotti chimici", base_asset_type=Asset.TYPE_CHEMICAL,
        )
        rep = Reparto.objects.create(nome="Chimica")
        form = ChemicalAssetForm(data={
            "name": "Acetone", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "pc-nome": "Acetone 99%", "pc-reparto": rep.id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.asset_category_id, categoria.id)
        self.assertEqual(asset.category_label, "Prodotti chimici")

    def test_chemical_form_aggancia_per_nome_se_base_asset_type_non_configurato(self):
        """Caso reale: la categoria "Prodotti Chimici" esiste ma è stata creata
        con `base_asset_type` di default ("Altro"), perché nessuna euristica di
        classificazione riconosceva "chimic*" come parola chiave prima di questo
        fix. Il match per `base_asset_type` da solo non trova nulla: deve
        ripiegare sul nome della categoria, non lasciare l'asset senza categoria."""
        categoria = AssetCategory.objects.create(
            code="prodotti-chimici-2", label="Prodotti Chimici", base_asset_type=Asset.TYPE_OTHER,
        )
        rep = Reparto.objects.create(nome="Chimica")
        form = ChemicalAssetForm(data={
            "name": "Diluente", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "pc-nome": "Diluente X", "pc-reparto": rep.id,
        })
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.asset_category_id, categoria.id)
        self.assertEqual(asset.category_label, "Prodotti Chimici")


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

    def test_chemical_create_view_mostra_il_selettore_pittogrammi(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:chemical_create"))
        self.assertContains(resp, 'name="pc-pittogrammi"')
        self.assertContains(resp, 'value="GHS02"')

    def test_chemical_create_view_creates_asset(self):
        rep = Reparto.objects.create(nome="Chimica")
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assets:chemical_create"), {
            "name": "Diluente", "status": Asset.STATUS_IN_STOCK,
            "prodotto_mode": "new", "pc-nome": "Diluente X",
            "pc-reparto": rep.id,
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

    def test_chemical_detail_mostra_i_pittogrammi_dichiarati_senza_sds(self):
        rep = Reparto.objects.create(nome="Chimica")
        p = ProdottoChimico.objects.create(nome="Soda", reparto=rep, pittogrammi=["GHS05"])
        a = Asset.objects.create(
            asset_tag="CHEM-6", name="Soda",
            asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p,
        )
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[a.id]))
        self.assertContains(resp, 'href="#ghs05"')

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


class BackfillChemicalAssetCategoryCommandTests(TestCase):
    """Comando one-shot per gli asset chimici gia' esistenti rimasti senza categoria."""

    def setUp(self):
        self.rep = Reparto.objects.create(nome="Chimica")
        self.categoria = AssetCategory.objects.create(
            code="prodotti-chimici", label="Prodotti Chimici", base_asset_type=Asset.TYPE_OTHER,
        )

    def _asset_senza_categoria(self, tag: str, nome: str) -> Asset:
        p = ProdottoChimico.objects.create(nome=nome, reparto=self.rep)
        return Asset.objects.create(asset_tag=tag, name=nome, asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p)

    def test_dry_run_non_modifica_nulla(self):
        from django.core.management import call_command

        a = self._asset_senza_categoria("CHEM-BF1", "Acetone")
        call_command("backfill_chemical_asset_category", "--dry-run")
        a.refresh_from_db()
        self.assertIsNone(a.asset_category_id)

    def test_aggiorna_solo_gli_asset_chimici_senza_categoria(self):
        from django.core.management import call_command

        a1 = self._asset_senza_categoria("CHEM-BF2", "Diluente")
        a2 = self._asset_senza_categoria("CHEM-BF3", "Solvente")
        altro_gia_categorizzato = AssetCategory.objects.create(code="altro-cat", label="Altro")
        p3 = ProdottoChimico.objects.create(nome="Soda", reparto=self.rep)
        a3 = Asset.objects.create(
            asset_tag="CHEM-BF4", name="Soda", asset_type=Asset.TYPE_CHEMICAL,
            prodotto_chimico=p3, asset_category=altro_gia_categorizzato,
        )
        non_chimico = Asset.objects.create(asset_tag="IT-BF1", name="PC", asset_type=Asset.TYPE_PC)

        call_command("backfill_chemical_asset_category")

        a1.refresh_from_db()
        a2.refresh_from_db()
        a3.refresh_from_db()
        non_chimico.refresh_from_db()
        self.assertEqual(a1.asset_category_id, self.categoria.id)
        self.assertEqual(a2.asset_category_id, self.categoria.id)
        self.assertEqual(a3.asset_category_id, altro_gia_categorizzato.id)  # non toccato: gia' categorizzato
        self.assertIsNone(non_chimico.asset_category_id)  # non e' un asset chimico

    def test_senza_categoria_chimica_disponibile_alza_errore(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        self.categoria.delete()
        self._asset_senza_categoria("CHEM-BF5", "Acido")
        with self.assertRaises(CommandError):
            call_command("backfill_chemical_asset_category")


class AssetFormEsclusioneCategoriaChimicaTests(TestCase):
    """La categoria chimica ha un form dedicato (ChemicalAssetForm): il form Assets
    generico non deve poterla assegnare, altrimenti l'asset prende il trattamento
    da asset di produzione (numero interno, manutenzione, contratti) invece della
    scheda dedicata SDS — il bug segnalato su "MOBIL VACTRA OIL NO. 2"."""

    def setUp(self):
        self.categoria_chimica = AssetCategory.objects.create(
            code="prodotti-chimici", label="Prodotti chimici", base_asset_type=Asset.TYPE_CHEMICAL,
        )
        self.categoria_normale = AssetCategory.objects.create(
            code="altimetri", label="Altimetri", base_asset_type=Asset.TYPE_OTHER,
        )
        self.user = User.objects.create_superuser("form-chem-su", "form-chem-su@test.local", "x")
        self.client.force_login(self.user)

    def test_dropdown_esclude_la_categoria_chimica(self):
        form = AssetForm()
        ids = set(form.fields["asset_category"].queryset.values_list("id", flat=True))
        self.assertNotIn(self.categoria_chimica.id, ids)
        self.assertIn(self.categoria_normale.id, ids)

    def _payload(self, **overrides):
        payload = {
            "asset_tag": "", "name": "Bidone olio", "asset_category": "",
            "reparto": "", "manufacturer": "", "model": "", "serial_number": "",
            "status": Asset.STATUS_IN_USE, "sharepoint_folder_url": "", "sharepoint_folder_path": "",
            "assignment_to": "", "assignment_reparto": "", "assignment_location": "", "notes": "",
        }
        payload.update(overrides)
        return payload

    def test_rifiuta_la_categoria_chimica_forzata_via_post(self):
        """Il campo la esclude gia' dal queryset (test sopra): forzando l'id via
        POST diretto, Django la rifiuta a livello di campo prima ancora del
        clean() del form (stesso comportamento gia' in uso per le Macchine di
        lavoro) — non crea comunque l'asset con quella categoria."""
        resp = self.client.post(
            reverse("assets:asset_create"),
            self._payload(asset_category=str(self.categoria_chimica.id)),
        )
        self.assertEqual(resp.status_code, 200)  # form ri-renderizzato, non redirect
        self.assertFalse(Asset.objects.filter(name="Bidone olio").exists())

    def test_accetta_una_categoria_normale(self):
        resp = self.client.post(
            reverse("assets:asset_create"),
            self._payload(asset_category=str(self.categoria_normale.id)),
        )
        self.assertEqual(resp.status_code, 302)
        asset = Asset.objects.get(name="Bidone olio")
        self.assertEqual(asset.asset_category_id, self.categoria_normale.id)


class DeclassifyGenericAssetsFromChemicalCategoryCommandTests(TestCase):
    """Comando one-shot per gli asset non-chimici finiti nella categoria chimica
    prima che il form Assets la escludesse (es. "MOBIL VACTRA OIL NO. 2")."""

    def setUp(self):
        self.categoria = AssetCategory.objects.create(
            code="prodotti-chimici", label="Prodotti Chimici", base_asset_type=Asset.TYPE_CHEMICAL,
        )

    def test_dry_run_non_modifica_nulla(self):
        from django.core.management import call_command

        a = Asset.objects.create(
            asset_tag="OBA-003", name="Mobil Vactra Oil No. 2",
            asset_type=Asset.TYPE_OTHER, asset_category=self.categoria,
        )
        call_command("declassify_generic_assets_from_chemical_category", "--dry-run")
        a.refresh_from_db()
        self.assertEqual(a.asset_category_id, self.categoria.id)

    def test_scategorizza_solo_i_non_chimici_della_categoria_chimica(self):
        from django.core.management import call_command

        rep = Reparto.objects.create(nome="Chimica")
        non_chimico = Asset.objects.create(
            asset_tag="OBA-003", name="Mobil Vactra Oil No. 2",
            asset_type=Asset.TYPE_OTHER, asset_category=self.categoria,
        )
        p = ProdottoChimico.objects.create(nome="Bonderite", reparto=rep)
        chimico_vero = Asset.objects.create(
            asset_tag="CHEM-DC1", name="Bonderite", asset_type=Asset.TYPE_CHEMICAL,
            asset_category=self.categoria, prodotto_chimico=p,
        )
        altra_categoria = AssetCategory.objects.create(code="altro-cat", label="Altro reparto")
        non_toccato = Asset.objects.create(
            asset_tag="IT-DC1", name="PC ufficio", asset_type=Asset.TYPE_PC, asset_category=altra_categoria,
        )

        call_command("declassify_generic_assets_from_chemical_category")

        non_chimico.refresh_from_db()
        chimico_vero.refresh_from_db()
        non_toccato.refresh_from_db()
        self.assertIsNone(non_chimico.asset_category_id)
        self.assertEqual(chimico_vero.asset_category_id, self.categoria.id)  # non toccato: e' chimico vero
        self.assertEqual(non_toccato.asset_category_id, altra_categoria.id)  # non toccato: altra categoria

    def test_senza_categoria_chimica_non_fa_nulla(self):
        from django.core.management import call_command

        self.categoria.delete()
        call_command("declassify_generic_assets_from_chemical_category")  # non deve sollevare
