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

    def test_prodotto_form_crea_asset_aggancia_per_nome_se_base_asset_type_non_configurato(self):
        """Caso reale osservato in prod: la categoria "Prodotti Chimici" esiste
        con `base_asset_type` di default ("Altro"), non "Prodotto chimico" —
        il match deve ripiegare sul nome della categoria."""
        from assets.models import Asset, AssetCategory

        categoria = AssetCategory.objects.create(
            code="prodotti-chimici-2", label="Prodotti Chimici", base_asset_type=Asset.TYPE_OTHER,
        )
        resp = self.client.post(reverse("schede_sicurezza:prodotto_nuovo"), {
            "nome": "Ardrox", "reparto": self.reparto.id, "crea_asset": "on",
        })
        self.assertEqual(resp.status_code, 302)
        p = ProdottoChimico.objects.get(nome="Ardrox")
        asset = p.asset_container
        self.assertEqual(asset.asset_category_id, categoria.id)
        self.assertEqual(asset.category_label, "Prodotti Chimici")


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

    def test_scheda_mobile_e_pubblica_anche_senza_permesso(self):
        """scheda_mobile e' la landing del QR fisico sul contenitore: deve
        restare raggiungibile anche da un utente senza alcun grant ACL (e da un
        visitatore anonimo, vedi SchedaMobilePubblicaTest) — e' la scelta di
        prodotto voluta, non una falla: MIDDLEWARE_EXEMPT_PREFIXES esenta
        esplicitamente /schede-sicurezza/s/."""
        self.client.force_login(self.utente_senza_permesso)
        url = reverse("schede_sicurezza:scheda_mobile", args=[str(self.prodotto.uuid)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

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

    def test_zero_pittogrammi_con_estrazione_ok_non_dice_da_confermare(self):
        """Estrazione riuscita (stato OK) con zero pittogrammi e' un esito
        confermato (nessun pericolo dichiarato sulla SDS), non un'estrazione
        ancora da rivedere: la card non deve suggerire un'azione mancante."""
        from .models import EstrazioneStato

        prodotto = ProdottoChimico.objects.create(nome="Ardrox 9812", reparto=self.reparto_a)
        SchedaSicurezza.objects.create(
            prodotto=prodotto, pdf=_valid_pdf_upload(), versione="5",
            is_corrente=True, estrazione_stato=EstrazioneStato.OK, pittogrammi=[],
        )
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, "Nessun pittogramma indicato")

    def test_zero_pittogrammi_con_estrazione_non_ok_dice_da_confermare(self):
        prodotto = ProdottoChimico.objects.create(nome="Solvente Ignoto", reparto=self.reparto_a)
        SchedaSicurezza.objects.create(
            prodotto=prodotto, pdf=_valid_pdf_upload(), versione="1",
            is_corrente=True, pittogrammi=[],  # estrazione_stato di default: non_eseguita
        )
        resp = self.client.get(reverse("schede_sicurezza:prodotto_list"))
        self.assertContains(resp, "Pittogrammi da confermare")


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


class SchedaMobilePubblicaTest(TestCase):
    """La scheda mobile (QR fisico sul contenitore) e' consultabile senza login:
    chi scansiona non ha per forza un account (es. un contrattista in officina)."""

    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Bonderite M-CR 871 AERO", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
            pittogrammi=["GHS05"],
        )

    def test_accessibile_senza_login(self):
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile", args=[self.prodotto.uuid]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bonderite M-CR 871 AERO")

    def test_incrementa_il_contatore_visite(self):
        url = reverse("schede_sicurezza:scheda_mobile", args=[self.prodotto.uuid])
        self.assertEqual(self.prodotto.visite_qr, 0)
        self.client.get(url)
        self.client.get(url)
        self.prodotto.refresh_from_db()
        self.assertEqual(self.prodotto.visite_qr, 2)
        resp = self.client.get(url)
        self.assertContains(resp, "Aperture QR: 3")

    def test_visitatore_anonimo_non_vede_la_presa_visione(self):
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile", args=[self.prodotto.uuid]))
        self.assertNotContains(resp, "Confermo di aver letto")

    def test_utente_autenticato_vede_ancora_la_presa_visione(self):
        user = User.objects.create_user(username="op-sds", password="x")
        self.client.force_login(user)
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile", args=[self.prodotto.uuid]))
        self.assertContains(resp, "Confermo di aver letto")

    def test_prodotto_disattivato_404(self):
        self.prodotto.attivo = False
        self.prodotto.save(update_fields=["attivo"])
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile", args=[self.prodotto.uuid]))
        self.assertEqual(resp.status_code, 404)

    def test_senza_scheda_corrente_pagina_utile_non_404(self):
        """Chi scansiona e' davanti al contenitore: un 404 sarebbe un vicolo cieco."""
        prodotto_senza_scheda = ProdottoChimico.objects.create(nome="Senza SDS", reparto=self.reparto)
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile", args=[prodotto_senza_scheda.uuid]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Senza SDS")
        self.assertContains(resp, "Scheda di sicurezza non disponibile")

    def test_download_pdf_pubblico_senza_login(self):
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile_pdf", args=[self.prodotto.uuid]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")

    def test_download_pdf_prodotto_disattivato_404(self):
        self.prodotto.attivo = False
        self.prodotto.save(update_fields=["attivo"])
        resp = self.client.get(reverse("schede_sicurezza:scheda_mobile_pdf", args=[self.prodotto.uuid]))
        self.assertEqual(resp.status_code, 404)


class SchedaMobileRobustezzaTest(TestCase):
    """Il perimetro pubblico del QR: cosa può e cosa non può uscire da qui."""

    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Solvente Alfa", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto,
            pdf=SimpleUploadedFile("alfa.pdf", b"%PDF-1.4\nSDS ALFA\n", content_type="application/pdf"),
            versione="1", is_corrente=True,
        )
        self.altro = ProdottoChimico.objects.create(nome="Solvente Beta", reparto=self.reparto)
        self.scheda_altro = SchedaSicurezza.objects.create(
            prodotto=self.altro,
            pdf=SimpleUploadedFile("beta.pdf", b"%PDF-1.4\nSDS BETA\n", content_type="application/pdf"),
            versione="1", is_corrente=True,
        )

    def _url(self, prodotto, nome="schede_sicurezza:scheda_mobile"):
        return reverse(nome, args=[prodotto.uuid])

    # -- risoluzione del prodotto -------------------------------------------

    def test_uuid_inesistente_404(self):
        sconosciuto = "00000000-0000-4000-8000-000000000000"
        for nome in ("schede_sicurezza:scheda_mobile", "schede_sicurezza:scheda_mobile_pdf"):
            with self.subTest(vista=nome):
                self.assertEqual(self.client.get(reverse(nome, args=[sconosciuto])).status_code, 404)

    def test_pk_sequenziale_non_e_una_chiave_valida(self):
        """L'unico identificatore accettato è l'uuid: il PK non entra nell'URL."""
        resp = self.client.get(f"/schede-sicurezza/s/{self.prodotto.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_prodotto_senza_scheda_404_solo_sul_pdf(self):
        """Il PDF non c'e' davvero (404); la pagina invece informa (200)."""
        orfano = ProdottoChimico.objects.create(nome="Senza scheda", reparto=self.reparto)
        self.assertEqual(self.client.get(self._url(orfano, "schede_sicurezza:scheda_mobile_pdf")).status_code, 404)
        self.assertEqual(self.client.get(self._url(orfano)).status_code, 200)

    # -- header --------------------------------------------------------------

    def test_header_di_sicurezza_sulle_risposte_pubbliche(self):
        attesi = {
            "X-Robots-Tag": "noindex, nofollow, noarchive",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store, max-age=0",
        }
        for nome in ("schede_sicurezza:scheda_mobile", "schede_sicurezza:scheda_mobile_pdf"):
            resp = self.client.get(self._url(self.prodotto, nome))
            self.assertEqual(resp.status_code, 200)
            for header, valore in attesi.items():
                with self.subTest(vista=nome, header=header):
                    self.assertEqual(resp[header], valore)

    # -- download ------------------------------------------------------------

    def test_download_serve_solo_la_sds_del_prodotto_richiesto(self):
        resp = self.client.get(self._url(self.prodotto, "schede_sicurezza:scheda_mobile_pdf"))
        self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4\nSDS ALFA\n")

        resp_altro = self.client.get(self._url(self.altro, "schede_sicurezza:scheda_mobile_pdf"))
        self.assertEqual(b"".join(resp_altro.streaming_content), b"%PDF-1.4\nSDS BETA\n")

    def test_nome_file_anomalo_normalizzato_nel_content_disposition(self):
        self.prodotto.nome = '../../etc/passwd"; rm -rf /'
        self.prodotto.save(update_fields=["nome"])
        resp = self.client.get(self._url(self.prodotto, "schede_sicurezza:scheda_mobile_pdf"))

        # `inline` e' voluto: la SDS si apre nel visualizzatore del telefono di
        # chi ha appena scansionato il QR, non si scarica.
        disposition = resp["Content-Disposition"]
        self.assertEqual(disposition, 'inline; filename="....etcpasswd_rm_-rf__v1.pdf"')
        nome_file = disposition.split("filename=", 1)[1].strip('"')
        for pericoloso in ('"', "/", "\\", ";"):
            with self.subTest(carattere=pericoloso):
                self.assertNotIn(pericoloso, nome_file)

    def test_nome_prodotto_tutto_da_scartare_ha_comunque_un_nome_file(self):
        self.prodotto.nome = "///"
        self.prodotto.save(update_fields=["nome"])
        self.scheda.versione = "/"
        self.scheda.save(update_fields=["versione"])
        resp = self.client.get(self._url(self.prodotto, "schede_sicurezza:scheda_mobile_pdf"))
        self.assertIn("scheda-sicurezza.pdf", resp["Content-Disposition"])

    def test_content_type_dichiarato_esplicitamente(self):
        """Il tipo non si deduce dall'estensione: lo si impone, con nosniff."""
        resp = self.client.get(self._url(self.prodotto, "schede_sicurezza:scheda_mobile_pdf"))
        self.assertEqual(resp["Content-Type"], "application/pdf")

    # -- contatore -----------------------------------------------------------

    def test_incremento_contatore_e_atomico(self):
        """L'incremento passa da un UPDATE ... SET x = x + 1: nessun valore
        letto in Python, quindi nessun aggiornamento perso fra due scansioni."""
        ProdottoChimico.objects.filter(pk=self.prodotto.pk).update(visite_qr=41)
        # Istanza "stantia" (visite_qr=0 in memoria) come sarebbe quella di una
        # richiesta partita prima dell'aggiornamento altrui.
        self.client.get(self._url(self.prodotto))
        self.prodotto.refresh_from_db()
        self.assertEqual(self.prodotto.visite_qr, 42)

    def test_il_download_non_incrementa_il_contatore(self):
        self.client.get(self._url(self.prodotto, "schede_sicurezza:scheda_mobile_pdf"))
        self.prodotto.refresh_from_db()
        self.assertEqual(self.prodotto.visite_qr, 0)

    # -- perimetro autenticato invariato -------------------------------------

    def test_accesso_anonimo_ancora_consentito(self):
        self.assertEqual(self.client.get(self._url(self.prodotto)).status_code, 200)

    def test_pagina_senza_sds_mostra_i_pittogrammi_dichiarati(self):
        """L'unica informazione di pericolo che il portale possiede in quello stato."""
        orfano = ProdottoChimico.objects.create(
            nome="Chimico senza scheda", reparto=self.reparto, pittogrammi=["GHS02"],
        )
        resp = self.client.get(self._url(orfano))
        self.assertContains(resp, "Pericoli dichiarati sul prodotto")

    def test_pagina_senza_sds_resta_blindata(self):
        orfano = ProdottoChimico.objects.create(nome="Orfano header", reparto=self.reparto)
        resp = self.client.get(self._url(orfano))
        self.assertEqual(resp["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", resp["Cache-Control"])

    def test_pagina_senza_sds_conta_l_apertura(self):
        orfano = ProdottoChimico.objects.create(nome="Orfano contatore", reparto=self.reparto)
        self.client.get(self._url(orfano))
        orfano.refresh_from_db()
        self.assertEqual(orfano.visite_qr, 1)

    def test_segnalazione_riservata_agli_autenticati(self):
        from core.audit import storico_oggetto

        orfano = ProdottoChimico.objects.create(nome="Orfano segnalabile", reparto=self.reparto)
        url = self._url(orfano)

        # Anonimo: nessun pulsante e nessuna scrittura anche forzando la POST.
        self.assertNotContains(self.client.get(url), "Segnala scheda mancante")
        self.client.post(url, {"segnala": "1"})
        self.assertEqual(list(storico_oggetto(orfano)), [])

        operatore = User.objects.create_user(username="op-segnala", password="x")
        self.client.force_login(operatore)
        self.assertContains(self.client.get(url), "Segnala scheda mancante")
        resp = self.client.post(url, {"segnala": "1"})
        self.assertContains(resp, "Segnalazione registrata")
        self.assertEqual(
            [v.azione for v in storico_oggetto(orfano)], ["segnalazione_sds_mancante"],
        )

    def test_presa_visione_resta_riservata_agli_autenticati(self):
        url = reverse("schede_sicurezza:presa_visione_conferma", args=[self.scheda.pk])
        resp = self.client.post(url, {"note": ""})
        self.assertIn(resp.status_code, (302, 403))
        self.assertEqual(PresaVisioneScheda.objects.count(), 0)

        operatore = User.objects.create_user(username="op-pv", password="x", is_superuser=True)
        self.client.force_login(operatore)
        self.client.post(url, {"note": ""})
        self.assertEqual(PresaVisioneScheda.objects.filter(scheda=self.scheda).count(), 1)
