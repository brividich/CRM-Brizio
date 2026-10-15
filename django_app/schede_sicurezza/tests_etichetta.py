from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Reparto

from .forms import ImpostazioniEtichettaForm
from .models import ImpostazioniEtichetta, ProdottoChimico
from .services.etichetta import impagina

User = get_user_model()


def _dati_form(**override) -> dict:
    dati = {
        "larghezza_mm": "100", "altezza_mm": "50", "posizione_qr": "destra",
        "testo_qr": "Scheda di sicurezza e primo soccorso",
        "mostra_logo": "on", "logo_altezza_mm": "8", "nome_dimensione_pt": "11",
        "nome_maiuscolo": "on", "riga_extra": "", "mostra_pittogrammi": "on",
        "testo_emergenza": "", "colore_fascia": "",
    }
    dati.update(override)
    return {k: v for k, v in dati.items() if v is not None}


class ImpaginazioneTest(TestCase):
    def setUp(self):
        self.prodotto = ProdottoChimico.objects.create(
            nome="Sgrassante XY", reparto=Reparto.objects.create(nome="Produzione"),
            pittogrammi=["GHS02", "GHS07"], numero_interno="CH-012",
        )

    def test_default_10x5(self):
        layout = impagina(ImpostazioniEtichetta.correnti(), self.prodotto)
        self.assertEqual(layout["mm"]["larghezza"], "100.0")
        self.assertEqual(layout["mm"]["altezza"], "50.0")
        self.assertEqual(float(layout["mm"]["pittogramma"]), 16.0)
        self.assertEqual(len(layout["pittogrammi"]), 2)

    def test_formato_piccolo_e_molti_pittogrammi_restano_nel_bordo(self):
        imp = ImpostazioniEtichetta.correnti()
        imp.larghezza_mm, imp.altezza_mm = 70, 40
        imp.testo_emergenza = "Emergenza 112"
        self.prodotto.pittogrammi = ["GHS01", "GHS02", "GHS05", "GHS06", "GHS07", "GHS08", "GHS09"]
        layout = impagina(imp, self.prodotto)
        lato = float(layout["mm"]["pittogramma"])
        qr = float(layout["mm"]["qr"])
        # 4 per riga devono stare nella colonna accanto al QR.
        colonna = 70 - 2 * 2.5 - qr - 2.0
        self.assertLessEqual(4 * lato + 3 * 0.8, colonna + 0.01)
        self.assertGreaterEqual(lato, 6.0)
        self.assertLess(qr, 40 - 5)

    def test_pittogrammi_spenti_e_riga_extra(self):
        imp = ImpostazioniEtichetta.correnti()
        imp.mostra_pittogrammi = False
        imp.riga_extra = ImpostazioniEtichetta.RigaExtra.NUMERO_INTERNO
        layout = impagina(imp, self.prodotto)
        self.assertEqual(layout["pittogrammi"], [])
        self.assertEqual(layout["riga_extra"], "CH-012")


class ImpostazioniEtichettaFormTest(TestCase):
    def test_limiti_formato(self):
        form = ImpostazioniEtichettaForm(_dati_form(larghezza_mm="20"), instance=ImpostazioniEtichetta.correnti())
        self.assertFalse(form.is_valid())
        self.assertIn("larghezza_mm", form.errors)

    def test_colore_non_valido(self):
        form = ImpostazioniEtichettaForm(_dati_form(colore_fascia="rosso"), instance=ImpostazioniEtichetta.correnti())
        self.assertFalse(form.is_valid())
        self.assertIn("colore_fascia", form.errors)

    def test_logo_non_immagine_rifiutato(self):
        finto = SimpleUploadedFile("logo.png", b"%PDF-1.4 non e' un png", content_type="image/png")
        form = ImpostazioniEtichettaForm(_dati_form(), {"logo": finto}, instance=ImpostazioniEtichetta.correnti())
        self.assertFalse(form.is_valid())
        self.assertIn("logo", form.errors)


class ImpostazioniEtichettaViewTest(TestCase):
    def setUp(self):
        self.prodotto = ProdottoChimico.objects.create(
            nome="Sgrassante XY", reparto=Reparto.objects.create(nome="Produzione"), pittogrammi=["GHS05"],
        )
        self.admin = User.objects.create_user(username="admin_et", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)

    def test_pagina_mostra_form_e_anteprima(self):
        resp = self.client.get(reverse("schede_sicurezza:etichetta_impostazioni"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Personalizza etichetta")
        self.assertContains(resp, f"/schede-sicurezza/{self.prodotto.pk}/etichetta/?anteprima=1")

    def test_salvataggio_cambia_etichetta(self):
        resp = self.client.post(reverse("schede_sicurezza:etichetta_impostazioni"), _dati_form(
            larghezza_mm="70", altezza_mm="40", posizione_qr="sinistra",
            testo_emergenza="Emergenza 112", colore_fascia="#b91c1c",
        ))
        self.assertEqual(resp.status_code, 302)
        imp = ImpostazioniEtichetta.correnti()
        self.assertEqual((imp.larghezza_mm, imp.altezza_mm), (70, 40))
        self.assertEqual(imp.colore_fascia, "#B91C1C")
        self.assertEqual(imp.aggiornato_da, self.admin)

        etichetta = self.client.get(reverse("schede_sicurezza:prodotto_etichetta", args=[self.prodotto.pk]))
        self.assertContains(etichetta, "size: 70.0mm 40.0mm")
        self.assertContains(etichetta, "row-reverse")
        self.assertContains(etichetta, "Emergenza 112")
        self.assertContains(etichetta, "background: #B91C1C")

    def test_anteprima_non_salva(self):
        resp = self.client.post(reverse("schede_sicurezza:etichetta_anteprima"), _dati_form(
            larghezza_mm="148", altezza_mm="105", prodotto=str(self.prodotto.pk),
        ))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "size: 148.0mm 105.0mm")
        self.assertNotContains(resp, "Stampa etichetta")
        self.assertEqual(ImpostazioniEtichetta.correnti().larghezza_mm, 100)

    def test_anteprima_con_valori_fuori_limite_usa_quelle_salvate(self):
        resp = self.client.post(reverse("schede_sicurezza:etichetta_anteprima"), _dati_form(larghezza_mm="5"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "size: 100.0mm 50.0mm")

    def test_non_gestore_non_accede(self):
        utente = User.objects.create_user(username="semplice_et", password="x")
        self.client.force_login(utente)
        resp = self.client.get(reverse("schede_sicurezza:etichetta_impostazioni"))
        self.assertIn(resp.status_code, (302, 403, 404))
        resp = self.client.post(reverse("schede_sicurezza:etichetta_anteprima"), _dati_form())
        self.assertIn(resp.status_code, (302, 403, 404))
