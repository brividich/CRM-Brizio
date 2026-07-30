from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .models import PresaVisioneScheda, ProdottoChimico, SchedaSicurezza

User = get_user_model()


def _valid_pdf_upload(name="sds.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4\n%finto contenuto SDS\n", content_type="application/pdf")


class UploadMimeValidationTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.admin = User.objects.create_user(username="admin1", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_rifiuta_estensione_pdf_con_mime_non_pdf(self):
        finto_pdf = SimpleUploadedFile("scheda.pdf", b"questo e' in realta' testo semplice", content_type="application/pdf")
        resp = self.client.post(
            reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk]),
            {"versione": "1", "pdf": finto_pdf},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.prodotto.schede.count(), 0)

    def test_accetta_pdf_valido(self):
        resp = self.client.post(
            reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk]),
            {"versione": "1", "pdf": _valid_pdf_upload()},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.prodotto.schede.count(), 1)


class DoppioIngressoAssetTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.admin = User.objects.create_user(username="admin3", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_prodotto_form_crea_asset_collegato(self):
        from assets.models import Asset

        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {
            "nome": "Acido", "reparto": self.reparto.id, "crea_asset": "on",
        })
        self.assertEqual(resp.status_code, 302)
        p = ProdottoChimico.objects.get(nome="Acido")
        asset = getattr(p, "asset_container", None)
        self.assertIsNotNone(asset)
        self.assertEqual(asset.asset_type, Asset.TYPE_CHEMICAL)

    def test_prodotto_form_senza_toggle_non_crea_asset(self):
        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {
            "nome": "Base", "reparto": self.reparto.id,
        })
        self.assertEqual(resp.status_code, 302)
        p = ProdottoChimico.objects.get(nome="Base")
        self.assertIsNone(getattr(p, "asset_container", None))

    def test_prodotto_form_crea_asset_aggancia_categoria_prodotti_chimici(self):
        """L'asset generato deve finire nella AssetCategory reale (es. "Prodotti
        chimici"), non restare senza categoria con la label del tipo (singolare,
        "Prodotto chimico") come unico fallback visivo."""
        from assets.models import Asset, AssetCategory

        categoria = AssetCategory.objects.create(
            code="prodotti-chimici", label="Prodotti chimici", base_asset_type=Asset.TYPE_CHEMICAL,
        )
        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {
            "nome": "Solvente", "reparto": self.reparto.id, "crea_asset": "on",
        })
        self.assertEqual(resp.status_code, 302)
        p = ProdottoChimico.objects.get(nome="Solvente")
        asset = p.asset_container
        self.assertEqual(asset.asset_category_id, categoria.id)
        self.assertEqual(asset.category_label, "Prodotti chimici")


class QrCodeTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.admin = User.objects.create_user(username="admin2", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_qr_endpoint_ritorna_png(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_qr", args=[self.prodotto.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertTrue(resp.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_url_scheda_mobile_usa_uuid_non_pk(self):
        url = reverse("schede_sicurezza:scheda_mobile", args=[str(self.prodotto.uuid)])
        self.assertIn(str(self.prodotto.uuid), url)
        self.assertNotIn(f"/{self.prodotto.pk}/", url)


class PresaVisioneViewTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.operatore = User.objects.create_user(username="operatore1", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.operatore)

    def test_conferma_presa_visione_idempotente(self):
        url = reverse("schede_sicurezza:presa_visione_conferma", args=[self.scheda.pk])
        resp1 = self.client.post(url)
        self.assertIn(resp1.status_code, (200, 302))
        self.assertEqual(
            PresaVisioneScheda.objects.filter(scheda=self.scheda, operatore=self.operatore).count(), 1
        )

        resp2 = self.client.post(url)
        self.assertIn(resp2.status_code, (200, 302))
        self.assertEqual(
            PresaVisioneScheda.objects.filter(scheda=self.scheda, operatore=self.operatore).count(), 1
        )

    def test_scheda_mobile_mostra_stato_presa_visione(self):
        url = reverse("schede_sicurezza:scheda_mobile", args=[str(self.prodotto.uuid)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Confermo di aver letto")


class AclGatingTest(TestCase):
    """La view non deve mai fidarsi del solo @login_required: senza permesso
    ACL v2 (nessun grant di ruolo, nessun override) l'accesso resta negato."""

    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.utente_senza_permesso = User.objects.create_user(username="senza_permesso", password="x")

    def test_scheda_mobile_negata_a_utente_senza_permesso(self):
        self.client.force_login(self.utente_senza_permesso)
        url = reverse("schede_sicurezza:scheda_mobile", args=[str(self.prodotto.uuid)])
        resp = self.client.get(url)
        self.assertNotEqual(resp.status_code, 200)

    def test_prodotto_list_negata_a_utente_senza_permesso(self):
        self.client.force_login(self.utente_senza_permesso)
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertNotEqual(resp.status_code, 200)

    def test_download_pdf_non_raggiungibile_senza_login(self):
        url = reverse("schede_sicurezza:scheda_download", args=[self.scheda.pk])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())


class ProdottoListFiltriTest(TestCase):
    def setUp(self):
        self.reparto_a = Reparto.objects.create(nome="Produzione")
        self.reparto_b = Reparto.objects.create(nome="Verniciatura")
        self.admin = User.objects.create_user(username="admin_filtri", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

        self.senza_scheda = ProdottoChimico.objects.create(
            nome="ProdottoOrfano", reparto=self.reparto_a, famiglia="Solventi",
        )
        self.con_scheda_recente = ProdottoChimico.objects.create(
            nome="Con scheda recente", reparto=self.reparto_a, famiglia="Acidi",
        )
        SchedaSicurezza.objects.create(
            prodotto=self.con_scheda_recente, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.con_scheda_vecchia = ProdottoChimico.objects.create(
            nome="Con scheda vecchia", reparto=self.reparto_b, famiglia="Solventi",
        )
        scheda_vecchia = SchedaSicurezza.objects.create(
            prodotto=self.con_scheda_vecchia, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        from datetime import timedelta

        from django.utils import timezone

        from .models import SCADENZA_SDS_GIORNI

        vecchia_data = timezone.now() - timedelta(days=SCADENZA_SDS_GIORNI + 10)
        SchedaSicurezza.objects.filter(pk=scheda_vecchia.pk).update(data_caricamento=vecchia_data)

    def test_filtro_reparto(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"reparto": self.reparto_b.pk})
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "ProdottoOrfano")
        self.assertNotContains(resp, "Con scheda recente")

    def test_filtro_famiglia(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"famiglia": "Acidi"})
        self.assertContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "ProdottoOrfano")

    def test_filtro_stato_senza_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "senza_scheda"})
        self.assertContains(resp, "ProdottoOrfano")
        self.assertNotContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "Con scheda vecchia")

    def test_filtro_stato_con_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "con_scheda"})
        self.assertContains(resp, "Con scheda recente")
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "ProdottoOrfano")

    def test_filtro_stato_da_rivedere(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"), {"stato": "da_rivedere"})
        self.assertContains(resp, "Con scheda vecchia")
        self.assertNotContains(resp, "Con scheda recente")
        self.assertNotContains(resp, "ProdottoOrfano")

    def test_badge_da_rivedere_visibile_in_lista(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, "Da rivedere")


class ModificaCampiEstrattiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.admin = User.objects.create_user(username="admin_edit_campi", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_modifica_campi_estratti_aggiorna_scheda_corrente(self):
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        resp = self.client.post(url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": "GHS02, GHS07",
            "frasi_h": "H225,  H319",
            "frasi_p": "P210",
            "classificazione_clp": "Liquido infiammabile categoria 2.",
            "dpi_testo": "Guanti e occhiali protettivi.",
            "primo_soccorso": "Sciacquare abbondantemente con acqua.",
            "incompatibilita": "Incompatibile con ossidanti forti.",
        })
        self.assertEqual(resp.status_code, 302)
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS02", "GHS07"])
        self.assertEqual(self.scheda.frasi_h, ["H225", "H319"])
        self.assertEqual(self.scheda.frasi_p, ["P210"])
        self.assertEqual(self.scheda.classificazione_clp, "Liquido infiammabile categoria 2.")
        self.assertEqual(self.scheda.dpi_testo, "Guanti e occhiali protettivi.")
        self.assertEqual(self.scheda.primo_soccorso, "Sciacquare abbondantemente con acqua.")
        self.assertEqual(self.scheda.incompatibilita, "Incompatibile con ossidanti forti.")

    def test_modifica_campi_estratti_ignora_virgole_vuote(self):
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        self.client.post(url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": "GHS02,, ,GHS07,",
            "frasi_h": "", "frasi_p": "",
            "classificazione_clp": "", "dpi_testo": "", "primo_soccorso": "", "incompatibilita": "",
        })
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS02", "GHS07"])
        self.assertEqual(self.scheda.frasi_h, [])

    def test_modifica_campi_estratti_richiede_permesso_gestisci(self):
        utente = User.objects.create_user(username="senza_permesso_edit", password="x")
        self.client.force_login(utente)
        url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])
        resp = self.client.post(url, {"form_type": "modifica_campi_estratti", "pittogrammi": "GHS02"})
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, [])

    def test_sezione_modifica_campi_presente_nel_dettaglio_con_scheda(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk]))
        self.assertContains(resp, "Modifica campi estratti")

    def test_sezione_modifica_campi_assente_senza_scheda_corrente(self):
        prodotto_senza = ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        resp = self.client.get(reverse("schede_sicurezza:prodotto_detail", args=[prodotto_senza.pk]))
        self.assertNotContains(resp, "Modifica campi estratti")


class FormProdottoUnificatoTest(TestCase):
    """Il form prodotto e' uno solo: stessi campi e stesso selettore CLP ovunque."""

    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.admin = User.objects.create_user(username="admin_form_unico", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_selettore_pittogrammi_presente_in_creazione(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_nuovo"))
        self.assertContains(resp, 'name="pittogrammi"')
        self.assertContains(resp, 'value="GHS09"')

    def test_salva_pittogrammi_dichiarati_sul_prodotto(self):
        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {
            "nome": "Acido nitrico", "reparto": self.reparto.id,
            "pittogrammi": ["GHS05", "GHS03"], "attivo": "on",
        })
        self.assertEqual(resp.status_code, 302)
        p = ProdottoChimico.objects.get(nome="Acido nitrico")
        self.assertEqual(p.pittogrammi, ["GHS05", "GHS03"])
        self.assertEqual(p.pittogrammi_effettivi(), ["GHS05", "GHS03"])

    def test_form_invalido_non_crea_e_resta_in_pagina(self):
        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {"nome": "Senza reparto"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ProdottoChimico.objects.filter(nome="Senza reparto").exists())

    def test_modifica_prodotto_propaga_i_pittogrammi_alla_scheda_corrente(self):
        prodotto = ProdottoChimico.objects.create(nome="Diluente", reparto=self.reparto)
        scheda = SchedaSicurezza.objects.create(
            prodotto=prodotto, versione="1", is_corrente=True,
            pdf=SimpleUploadedFile("sds.pdf", b"%PDF-1.4\n", content_type="application/pdf"),
            pittogrammi=["GHS02"],
        )
        resp = self.client.post(
            reverse("schede_sicurezza:prodotto_modifica", args=[prodotto.pk]),
            {"nome": "Diluente", "reparto": self.reparto.id,
             "pittogrammi": ["GHS02", "GHS07"], "attivo": "on"},
        )
        self.assertEqual(resp.status_code, 302)
        scheda.refresh_from_db()
        self.assertEqual(scheda.pittogrammi, ["GHS02", "GHS07"])

    def test_scheda_corrente_ha_la_precedenza_sui_pittogrammi_del_prodotto(self):
        prodotto = ProdottoChimico.objects.create(
            nome="Solvente", reparto=self.reparto, pittogrammi=["GHS07"],
        )
        SchedaSicurezza.objects.create(
            prodotto=prodotto, versione="2", is_corrente=True,
            pdf=SimpleUploadedFile("sds2.pdf", b"%PDF-1.4\n", content_type="application/pdf"),
            pittogrammi=["GHS02", "GHS08"],
        )
        self.assertEqual(prodotto.pittogrammi_effettivi(), ["GHS02", "GHS08"])


class RepartoMancanteCtaTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin_reparto_cta", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_link_aree_list_presente_senza_reparti(self):
        resp = self.client.get(reverse("schede_sicurezza:prodotto_nuovo"))
        self.assertContains(resp, reverse("anagrafica:aree_list"))

    def test_select_normale_con_almeno_un_reparto(self):
        Reparto.objects.create(nome="Produzione")
        resp = self.client.get(reverse("schede_sicurezza:prodotto_nuovo"))
        self.assertNotContains(resp, reverse("anagrafica:aree_list"))
