"""Scarpe al negozio: convenzione (riepilogo, poi consegna normale) e fuori convenzione (chiusura con fattura)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import flusso, magazzino, negozio
from .models import (
    CategoriaDPI,
    DPIImpostazioni,
    FatturaNegozioDPI,
    ModalitaNegozio,
    ModelloDPI,
    MovimentoMagazzinoDPI,
    OrdineNegozioDPI,
    RichiestaDPI,
    StatoRichiesta,
    TagliaDPI,
    TipoDPI,
)

User = get_user_model()
CONV = ModalitaNegozio.CONVENZIONE
FUORI = ModalitaNegozio.FUORI
PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NegozioTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-neg", password="x", email="n@y.z")
        self.client.force_login(self.admin)
        self.scarpe = CategoriaDPI.objects.create(
            nome="Scarpe", consegna_magazzino=False, si_ordina_al_negozio=True, vita_utile_giorni=365,
        )
        self.guanti = CategoriaDPI.objects.create(nome="Guanti")
        tipo = TipoDPI.objects.create(categoria=self.scarpe, nome="Bassa")
        self.modello = ModelloDPI.objects.create(tipo=tipo, codice="SC-1", nome="Runner")
        self.taglia = TagliaDPI.objects.create(modello=self.modello, valore="43")
        impost = DPIImpostazioni.get_singleton()
        impost.negozio_email = "ordini@negozio.example"
        impost.negozio_operatore_emails = "operatore@esempio.example"
        impost.magazzino_emails = "magazzino@esempio.example"
        impost.save()
        self.url = reverse("dpi:negozio")

    def _scarpe(self, modalita, stato=StatoRichiesta.APPROVATA, nome="Persona Prova", **campi):
        return RichiestaDPI.objects.create(
            categoria=self.scarpe, stato=stato, richiedente_legacy_id=None, richiedente_nome=nome,
            modalita_negozio=modalita, tipo_dpi=self.modello.tipo, modello_dpi=self.modello, taglia_dpi=self.taglia, **campi,
        )

    def _post(self, azione, richieste, **extra):
        return self.client.post(self.url, {"azione": azione, "ids": [r.pk for r in richieste], **extra})

    # --- nuova richiesta

    def test_la_richiesta_registra_la_modalita(self):
        with mock.patch("dpi.flusso.notifica_nuova_richiesta"):
            self.client.post(reverse("dpi:nuova"), {"categoria_id": self.scarpe.pk, "quantita": "1", "modalita_negozio": FUORI})
        self.assertEqual(RichiestaDPI.objects.get().modalita_negozio, FUORI)

    def test_modalita_obbligatoria_per_le_scarpe(self):
        self.assertEqual(self.client.post(reverse("dpi:nuova"), {"categoria_id": self.scarpe.pk, "quantita": "1"}).status_code, 200)
        self.assertFalse(RichiestaDPI.objects.exists())

    def test_i_dpi_normali_restano_senza_modalita(self):
        with mock.patch("dpi.flusso.notifica_nuova_richiesta"):
            self.client.post(reverse("dpi:nuova"), {"categoria_id": self.guanti.pk, "quantita": "1", "modalita_negozio": FUORI})
        self.assertEqual(RichiestaDPI.objects.get().modalita_negozio, "")

    # --- destinatari

    def test_approvata_avvisa_l_operatore_non_il_magazzino(self):
        for modalita, parola in ((CONV, "prossimo ordine"), (FUORI, "avvisa il negozio")):
            mail.outbox.clear()
            flusso.notifica_approvata(self._scarpe(modalita))
            self.assertEqual(len(mail.outbox), 1, modalita)
            self.assertIn("operatore@esempio.example", mail.outbox[0].recipients())
            self.assertNotIn("magazzino@esempio.example", mail.outbox[0].recipients())
            self.assertIn(parola, mail.outbox[0].body)

    def test_guanti_restano_al_magazzino(self):
        r = RichiestaDPI.objects.create(categoria=self.guanti, stato=StatoRichiesta.APPROVATA, richiedente_nome="X")
        self.assertEqual(flusso.destinatari_consegna(r), ["magazzino@esempio.example"])

    def test_luogo_di_ritiro_nella_mail(self):
        mail.outbox.clear()
        flusso.notifica_pronta_ritiro(self._scarpe(FUORI, richiedente_email="p@esempio.example"))
        # senza anagrafica il dipendente non ha mail: conta il testo della funzione
        self.assertIn("PROTEGGI", flusso.luogo_ritiro(self._scarpe(FUORI)))
        self.assertEqual(flusso.luogo_ritiro(self._scarpe(CONV)), "dall'ufficio amministrativo")
        self.assertEqual(flusso.luogo_ritiro(RichiestaDPI(categoria=self.guanti)), "in magazzino")

    # --- convenzione

    def test_invia_ordine_solo_le_spuntate(self):
        a, b = self._scarpe(CONV, nome="Anna"), self._scarpe(CONV, nome="Bruno")
        mail.outbox.clear()
        self._post("invia_ordine", [a], note="Consegna al mattino")
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNotNone(a.ordine_negozio_id)
        self.assertIsNone(b.ordine_negozio_id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ordini@negozio.example", mail.outbox[0].recipients())
        self.assertIn("Anna", mail.outbox[0].body)
        self.assertNotIn("Bruno", mail.outbox[0].body)
        self.assertIn("taglia 43", mail.outbox[0].body)
        self.assertIn("Consegna al mattino", mail.outbox[0].body)

    def test_invio_fallito_lascia_l_ordine_da_fare(self):
        a = self._scarpe(CONV)
        with mock.patch("dpi.flusso.invia_ordine_negozio", return_value=0):
            self._post("invia_ordine", [a])
        a.refresh_from_db()
        self.assertIsNone(a.ordine_negozio_id)
        self.assertFalse(OrdineNegozioDPI.objects.exists())

    def test_senza_mail_del_negozio_si_puo_segnare_a_mano(self):
        DPIImpostazioni.objects.update(negozio_email="")
        a = self._scarpe(CONV)
        self._post("invia_ordine", [a])
        a.refresh_from_db()
        self.assertIsNone(a.ordine_negozio_id)
        mail.outbox.clear()
        self._post("segna_ordinato", [a])
        a.refresh_from_db()
        self.assertIsNotNone(a.ordine_negozio_id)
        self.assertEqual(mail.outbox, [])

    def test_banco_solo_dopo_l_ordine(self):
        a = self._scarpe(CONV)
        banco = reverse("dpi:banco") + "?tutte=1"
        self.assertNotContains(self.client.get(banco), a.numero)
        self._post("segna_ordinato", [a])
        self.assertContains(self.client.get(banco), a.numero)

    def test_pronto_bloccato_prima_dell_ordine(self):
        a = self._scarpe(CONV)
        self.client.post(reverse("dpi:pronta_ritiro", args=[a.pk]))
        a.refresh_from_db()
        self.assertIsNone(a.pronta_ritiro_il)

    def test_convenzione_si_chiude_come_adesso_senza_scarico(self):
        a = self._scarpe(CONV)
        self._post("segna_ordinato", [a])
        magazzino.carica_ddt(self.modello, 5)
        with mock.patch("dpi.views._chiedi_conferma") as conferma:
            self.client.post(reverse("dpi:consegna", args=[a.pk]), {"data_consegna": timezone.localdate().isoformat()})
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.CONSEGNATA)
        self.assertTrue(conferma.called)
        self.assertFalse(MovimentoMagazzinoDPI.objects.filter(tipo=MovimentoMagazzinoDPI.Tipo.SCARICO).exists())

    # --- fuori convenzione

    def test_fuori_non_si_consegna_dal_banco_ne_dalla_scheda(self):
        a = self._scarpe(FUORI)
        self.assertNotContains(self.client.get(reverse("dpi:banco") + "?tutte=1"), a.numero)
        self.client.post(reverse("dpi:consegna", args=[a.pk]), {"data_consegna": timezone.localdate().isoformat()})
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.APPROVATA)

    def test_negozio_avvisato_segna_pronta(self):
        a = self._scarpe(FUORI)
        self._post("negozio_avvisato", [a])
        a.refresh_from_db()
        self.assertIsNotNone(a.pronta_ritiro_il)

    def test_fattura_chiude_solo_le_spuntate(self):
        a, b = self._scarpe(FUORI, nome="Anna"), self._scarpe(FUORI, nome="Bruno")
        data = timezone.localdate() - timedelta(days=2)
        with mock.patch("dpi.views._chiedi_conferma") as conferma:
            self._post("fattura", [a], fattura=SimpleUploadedFile("f.pdf", PDF, content_type="application/pdf"),
                       fattura_numero="F-12", fattura_data=data.isoformat())
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.CONSEGNATA)
        self.assertEqual(b.stato, StatoRichiesta.APPROVATA)
        self.assertEqual(a.consegna.data_consegna, data)
        self.assertEqual(a.consegna.data_scadenza_stimata, data + timedelta(days=365))
        self.assertIn("F-12", a.consegna.note_consegna)
        self.assertEqual(a.fattura_negozio.numero, "F-12")
        self.assertFalse(conferma.called)
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())
        self.addCleanup(a.fattura_negozio.file.delete, save=False)
        self.assertEqual(self.client.get(reverse("dpi:fattura_download", args=[a.fattura_negozio.pk])).status_code, 200)

    def test_stessa_fattura_non_crea_doppioni(self):
        a, b = self._scarpe(FUORI), self._scarpe(FUORI)
        data = timezone.localdate().isoformat()
        self._post("fattura", [a], fattura=SimpleUploadedFile("f.pdf", PDF, content_type="application/pdf"),
                   fattura_numero="F-20", fattura_data=data)
        self._post("fattura", [b], fattura_numero="f-20", fattura_data=data)
        a.refresh_from_db()
        b.refresh_from_db()
        self.addCleanup(a.fattura_negozio.file.delete, save=False)
        self.assertEqual(FatturaNegozioDPI.objects.count(), 1)
        self.assertEqual(b.stato, StatoRichiesta.CONSEGNATA)
        self.assertEqual(b.fattura_negozio_id, a.fattura_negozio_id)

    def test_fattura_incompleta_non_chiude_nulla(self):
        a = self._scarpe(FUORI)
        self._post("fattura", [a], fattura_numero="F-1", fattura_data=timezone.localdate().isoformat())
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.APPROVATA)
        self.assertFalse(FatturaNegozioDPI.objects.exists())

    def test_fattura_file_non_ammesso(self):
        a = self._scarpe(FUORI)
        self._post("fattura", [a], fattura=SimpleUploadedFile("f.exe", b"MZ", content_type="application/octet-stream"),
                   fattura_numero="F-1", fattura_data=timezone.localdate().isoformat())
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.APPROVATA)

    # --- permessi, promemoria, cruscotto

    def test_senza_gestire_niente_pagina_ne_fattura(self):
        utente = User.objects.create_user(username="dpi-neg-dip", password="x")
        self.client.force_login(utente)
        with mock.patch("dpi.views_negozio._is_gestore", return_value=False):
            self.assertEqual(self.client.get(self.url).status_code, 302)
            a = self._scarpe(FUORI)
            self.client.post(self.url, {"azione": "negozio_avvisato", "ids": [a.pk]})
            self.assertEqual(self.client.get(reverse("dpi:fattura_download", args=[1])).status_code, 302)
        a.refresh_from_db()
        self.assertIsNone(a.pronta_ritiro_il)

    def test_promemoria_dopo_i_giorni_e_non_ripetuto_subito(self):
        self._scarpe(CONV)
        oggi = timezone.localdate()
        mail.outbox.clear()
        self.assertEqual(negozio.promemoria_ordine(oggi), 0)
        self.assertGreater(negozio.promemoria_ordine(oggi + timedelta(days=15)), 0)
        self.assertEqual(mail.outbox[0].recipients(), ["operatore@esempio.example"])
        self.assertEqual(negozio.promemoria_ordine(oggi + timedelta(days=16)), 0)
        self.assertGreater(negozio.promemoria_ordine(oggi + timedelta(days=18)), 0)

    def test_promemoria_niente_coda_niente_mail(self):
        self.assertEqual(negozio.promemoria_ordine(timezone.localdate() + timedelta(days=100)), 0)

    def test_scarpe_fuori_dai_conti_del_magazzino(self):
        altro = ModelloDPI.objects.create(tipo=TipoDPI.objects.create(categoria=self.guanti, nome="G"), codice="G-1", nome="G")
        magazzino.carica_ddt(altro, 5)
        self.assertEqual(magazzino.da_riordinare(), 0)
        self.assertNotIn(self.modello.pk, [r["modello"].pk for r in magazzino.report(30)["righe"]])
        righe = self.client.get(reverse("dpi:magazzino")).context["righe"]
        self.assertEqual([r["modello"].pk for r in righe], [altro.pk])

    def test_tessera_scarpe_nella_dashboard(self):
        self._scarpe(CONV)
        self._scarpe(FUORI)
        tessere = {t["etichetta"]: t for t in self.client.get(reverse("dpi:dashboard")).context["da_fare"]}
        self.assertEqual(tessere["Scarpe da gestire"]["n"], 2)
        self.assertEqual(tessere["Da consegnare"]["n"], 0)
