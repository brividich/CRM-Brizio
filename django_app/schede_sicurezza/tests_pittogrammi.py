"""Catalogo pittogrammi CLP, selettore e filtro per pericolo nella lista card."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from . import pittogrammi as ghs
from .models import ProdottoChimico, SchedaSicurezza
from .services.ingestion import pittogrammi_proposti

User = get_user_model()


def _valid_pdf_upload(name="sds.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4\n%finto contenuto SDS\n", content_type="application/pdf")


class CatalogoPittogrammiTest(TestCase):
    def test_catalogo_ha_i_nove_simboli_clp(self):
        self.assertEqual(len(ghs.PITTOGRAMMI_GHS), 9)
        self.assertEqual(
            [codice for codice, _ in ghs.PITTOGRAMMI_GHS],
            [f"GHS0{n}" for n in range(1, 10)],
        )

    def test_normalizza_maiuscola_pulisce_e_deduplica(self):
        self.assertEqual(ghs.normalizza([" ghs02 ", "GHS02", "ghs07"]), ["GHS02", "GHS07"])

    def test_normalizza_conserva_ordine_di_inserimento(self):
        self.assertEqual(ghs.normalizza(["GHS07", "GHS02"]), ["GHS07", "GHS02"])

    def test_normalizza_su_lista_vuota_o_none(self):
        self.assertEqual(ghs.normalizza([]), [])
        self.assertEqual(ghs.normalizza(None), [])

    def test_dettaglio_marca_i_codici_fuori_catalogo(self):
        voci = ghs.dettaglio(["GHS02", "SIMBOLO-INTERNO"])
        self.assertEqual(voci[0], {"codice": "GHS02", "nome": "Infiammabile", "noto": True})
        self.assertFalse(voci[1]["noto"])
        # Un codice sconosciuto resta visibile invece di sparire dalla scheda.
        self.assertEqual(voci[1]["codice"], "SIMBOLO-INTERNO")

    def test_catalogo_segna_selezionati_e_proposti(self):
        voci = {v["codice"]: v for v in ghs.catalogo(selezionati=["GHS02"], proposti=["GHS02", "GHS05"])}
        self.assertTrue(voci["GHS02"]["selezionato"])
        self.assertTrue(voci["GHS02"]["proposto"])
        self.assertFalse(voci["GHS05"]["selezionato"])
        self.assertTrue(voci["GHS05"]["proposto"])
        self.assertFalse(voci["GHS09"]["selezionato"])


class PittogrammiPropostiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)

    def test_proposti_letti_dalla_sezione_2_dell_estratto(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
            estratto_grezzo={"2": "SEZIONE 2\nPittogrammi: GHS02, GHS07"},
        )
        self.assertEqual(pittogrammi_proposti(scheda), ["GHS02", "GHS07"])

    def test_proposti_vuoti_senza_estratto(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
        )
        self.assertEqual(pittogrammi_proposti(scheda), [])

    def test_proposti_restano_anche_se_i_curati_sono_stati_corretti(self):
        scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
            estratto_grezzo={"2": "SEZIONE 2\nGHS02"},
            pittogrammi=["GHS05"],
        )
        self.assertEqual(pittogrammi_proposti(scheda), ["GHS02"])


class SelettorePittogrammiTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione")
        self.prodotto = ProdottoChimico.objects.create(nome="Sgrassante XY", reparto=self.reparto)
        self.scheda = SchedaSicurezza.objects.create(
            prodotto=self.prodotto, pdf=_valid_pdf_upload(), versione="1", is_corrente=True,
            pittogrammi=["GHS02"],
        )
        self.admin = User.objects.create_user(
            username="admin_sel_pitto", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.url = reverse("schede_sicurezza:prodotto_detail", args=[self.prodotto.pk])

    def test_selettore_rendered_con_i_nove_simboli(self):
        resp = self.client.get(self.url)
        for codice in ("GHS01", "GHS05", "GHS09"):
            self.assertContains(resp, f'value="{codice}"')
        self.assertContains(resp, "Pittogrammi di pericolo")

    def test_selettore_salva_le_caselle_spuntate(self):
        self.client.post(self.url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": ["GHS02", "GHS05", "GHS09"],
            "frasi_h": "", "frasi_p": "", "classificazione_clp": "",
            "dpi_testo": "", "primo_soccorso": "", "incompatibilita": "",
        })
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS02", "GHS05", "GHS09"])

    def test_nessuna_casella_spuntata_svuota_i_pittogrammi(self):
        self.client.post(self.url, {
            "form_type": "modifica_campi_estratti",
            "frasi_h": "", "frasi_p": "", "classificazione_clp": "",
            "dpi_testo": "", "primo_soccorso": "", "incompatibilita": "",
        })
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, [])

    def test_forma_a_testo_libero_resta_accettata(self):
        # Compatibilita' con il vecchio campo a virgole (e con eventuali script).
        self.client.post(self.url, {
            "form_type": "modifica_campi_estratti",
            "pittogrammi": "ghs05, ghs07",
            "frasi_h": "", "frasi_p": "", "classificazione_clp": "",
            "dpi_testo": "", "primo_soccorso": "", "incompatibilita": "",
        })
        self.scheda.refresh_from_db()
        self.assertEqual(self.scheda.pittogrammi, ["GHS05", "GHS07"])

    def test_pittogramma_corrente_mostrato_come_simbolo(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'href="#ghs02"')


class ListaCardPittogrammiTest(TestCase):
    def setUp(self):
        self.galvanica = Reparto.objects.create(nome="Galvanica")
        self.verniciatura = Reparto.objects.create(nome="Verniciatura")
        self.admin = User.objects.create_user(
            username="admin_card_pitto", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

        self.infiammabile = ProdottoChimico.objects.create(nome="DiluenteNitro", reparto=self.verniciatura)
        SchedaSicurezza.objects.create(
            prodotto=self.infiammabile, pdf=_valid_pdf_upload(), versione="7", is_corrente=True,
            pittogrammi=["GHS02", "GHS07"],
        )
        self.corrosivo = ProdottoChimico.objects.create(nome="AcidoCloridrico", reparto=self.galvanica)
        SchedaSicurezza.objects.create(
            prodotto=self.corrosivo, pdf=_valid_pdf_upload(), versione="2", is_corrente=True,
            pittogrammi=["GHS05"],
        )
        self.orfano = ProdottoChimico.objects.create(nome="PassivanteSenzaScheda", reparto=self.galvanica)
        self.url = reverse("schede_sicurezza:prodotto_list")

    def test_card_raggruppate_per_reparto(self):
        resp = self.client.get(self.url)
        gruppi = [g["reparto"] for g in resp.context["gruppi"]]
        self.assertEqual(gruppi, ["Galvanica", "Verniciatura"])
        self.assertEqual(len(resp.context["gruppi"][0]["cards"]), 2)
        self.assertEqual(resp.context["gruppi"][0]["n_senza_scheda"], 1)

    def test_stato_card_riflette_la_scheda(self):
        resp = self.client.get(self.url)
        stati = {c["prodotto"].nome: c["stato"] for g in resp.context["gruppi"] for c in g["cards"]}
        self.assertEqual(stati["DiluenteNitro"], "ok")
        self.assertEqual(stati["PassivanteSenzaScheda"], "bad")

    def test_rastrelliera_conta_i_prodotti_per_pericolo(self):
        resp = self.client.get(self.url)
        conteggi = {p["codice"]: p["n"] for p in resp.context["rastrelliera"]}
        self.assertEqual(conteggi["GHS02"], 1)
        self.assertEqual(conteggi["GHS05"], 1)
        self.assertEqual(conteggi["GHS07"], 1)
        self.assertEqual(conteggi["GHS01"], 0)

    def test_filtro_per_pittogramma(self):
        resp = self.client.get(self.url, {"pittogramma": "GHS05"})
        self.assertContains(resp, "AcidoCloridrico")
        self.assertNotContains(resp, "DiluenteNitro")
        self.assertNotContains(resp, "PassivanteSenzaScheda")

    def test_filtro_per_pittogramma_accetta_minuscolo(self):
        resp = self.client.get(self.url, {"pittogramma": "ghs02"})
        self.assertContains(resp, "DiluenteNitro")
        self.assertNotContains(resp, "AcidoCloridrico")

    def test_conteggi_rastrelliera_non_collassano_col_filtro_attivo(self):
        # I numeri sulla rastrelliera restano quelli del set senza il filtro
        # per pericolo, altrimenti dopo il primo click gli altri simboli
        # mostrerebbero tutti zero.
        resp = self.client.get(self.url, {"pittogramma": "GHS05"})
        conteggi = {p["codice"]: p["n"] for p in resp.context["rastrelliera"]}
        self.assertEqual(conteggi["GHS02"], 1)

    def test_filtro_pittogramma_si_combina_col_reparto(self):
        resp = self.client.get(self.url, {"pittogramma": "GHS05", "reparto": self.verniciatura.pk})
        self.assertEqual(resp.context["n_mostrati"], 0)

    def test_prodotto_senza_scheda_segnalato_in_card(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Nessuna scheda caricata")
        self.assertContains(resp, "SDS mancante")

    def test_simboli_resi_come_svg_non_come_codice(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'href="#ghs05"')
