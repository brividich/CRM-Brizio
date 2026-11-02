"""Banco consegne: coda del magazzino per persona, consegna multipla con una firma,
consegna diretta dei consumabili, chi consegna per categoria (scarpe escluse)."""

from __future__ import annotations

import base64
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import flusso, magazzino
from .models import (
    CategoriaDPI,
    ConsegnaDPI,
    DPIImpostazioni,
    ModelloDPI,
    MovimentoMagazzinoDPI,
    RichiestaDPI,
    StatoRichiesta,
    TipoDPI,
)

User = get_user_model()

_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class BancoConsegneTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-banco", password="x", email="b@y.z")
        self.client.force_login(self.admin)
        self.guanti = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=30)
        self.scarpe = CategoriaDPI.objects.create(nome="Calzature", icona_emoji="boots", consegna_magazzino=False)
        self.mod_guanti = ModelloDPI.objects.create(
            tipo=TipoDPI.objects.create(categoria=self.guanti, nome="Guanti"), codice="GT-1", nome="Blade Safe"
        )
        self.mod_scarpe = ModelloDPI.objects.create(
            tipo=TipoDPI.objects.create(categoria=self.scarpe, nome="S3"), codice="SC-1", nome="Scarpa S3"
        )
        self.url = reverse("dpi:banco")
        patcher = mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _richiesta(self, modello, nome="Mario Rossi", legacy=101, quantita=1):
        return RichiestaDPI.objects.create(
            categoria=modello.tipo.categoria, tipo_dpi=modello.tipo, modello_dpi=modello, quantita=quantita,
            stato=StatoRichiesta.APPROVATA, richiedente_nome=nome, richiedente_legacy_id=legacy,
        )

    def test_banco_raggruppa_per_persona_e_esclude_le_scarpe(self):
        self._richiesta(self.mod_guanti)
        self._richiesta(self.mod_guanti, quantita=2)
        self._richiesta(self.mod_scarpe)
        self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        persone = resp.context["persone"]
        self.assertEqual([p["nome"] for p in persone], ["Luigi Verdi", "Mario Rossi"])
        self.assertEqual(len(persone[1]["righe"]), 2)  # la scarpa resta fuori
        self.assertEqual(resp.context["n_altre"], 1)
        self.assertContains(resp, "Mostra anche gli altri DPI (1")
        tutte = self.client.get(self.url + "?tutte=1")
        self.assertEqual(len(tutte.context["persone"][1]["righe"]), 3)

    def test_giacenza_insufficiente_segnalata(self):
        magazzino.carica_ddt(self.mod_guanti, 1)
        self._richiesta(self.mod_guanti, quantita=3)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["n_mancanti"], 1)

    def test_consegna_multipla_con_una_firma(self):
        magazzino.carica_ddt(self.mod_guanti, 10)
        a = self._richiesta(self.mod_guanti)
        b = self._richiesta(self.mod_guanti, quantita=2)
        resp = self.client.post(self.url, {
            "azione": "consegna", "ids": [a.pk, b.pk], "data_consegna": "2026-11-02", "firma_immagine": _PNG,
        })
        self.assertEqual(resp.status_code, 302)
        for r in (a, b):
            r.refresh_from_db()
            self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)
            self.assertEqual(r.consegna.firma_immagine, _PNG)
            self.assertTrue(r.consegna.firmato_ricevuta)
        self.assertEqual(magazzino.giacenza(self.mod_guanti.pk), 7)
        # La seconda consegna dello stesso tipo sostituisce la prima, come dalla scheda.
        self.assertEqual(ConsegnaDPI.objects.filter(sostituita_da__isnull=True).count(), 1)

    def test_consegna_ignora_richieste_non_approvate(self):
        r = self._richiesta(self.mod_guanti)
        r.stato = StatoRichiesta.INVIATA
        r.save()
        self.client.post(self.url, {"azione": "consegna", "ids": [r.pk], "data_consegna": "2026-11-02"})
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.INVIATA)
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())

    def test_pronto_per_il_ritiro_in_blocco(self):
        a = self._richiesta(self.mod_guanti)
        b = self._richiesta(self.mod_guanti)
        with mock.patch.object(flusso, "notifica_pronta_ritiro") as avviso:
            self.client.post(self.url, {"azione": "pronta", "ids": [a.pk, b.pk]})
            self.client.post(self.url, {"azione": "pronta", "ids": [a.pk]})  # gia' pronta: niente secondo avviso
        self.assertEqual(avviso.call_count, 2)
        a.refresh_from_db()
        self.assertIsNotNone(a.pronta_ritiro_il)

    def test_consegna_diretta_solo_categorie_abilitate(self):
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[{"id": 101, "nome": "Mario Rossi"}]):
            self.client.post(self.url, {"azione": "diretta", "dipendente": 101, "modello_dpi_id": self.mod_guanti.pk})
            self.assertFalse(RichiestaDPI.objects.exists())
            self.guanti.consegna_diretta = True
            self.guanti.save()
            resp = self.client.post(self.url, {
                "azione": "diretta", "dipendente": 101, "modello_dpi_id": self.mod_guanti.pk, "quantita": "3",
            })
        r = RichiestaDPI.objects.get()
        self.assertEqual((r.stato, r.quantita, r.richiedente_legacy_id), (StatoRichiesta.APPROVATA, 3, 101))
        self.assertIn("Consegna diretta al banco", r.note_gestione)
        self.assertTrue(resp["Location"].endswith("#apri-p101"))

    def test_consegna_diretta_dipendente_non_selezionabile(self):
        self.guanti.consegna_diretta = True
        self.guanti.save()
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[]):
            self.client.post(self.url, {"azione": "diretta", "dipendente": 999, "modello_dpi_id": self.mod_guanti.pk})
        self.assertFalse(RichiestaDPI.objects.exists())

    def test_banco_negato_a_chi_non_gestisce(self):
        from core.models import UserOnboarding

        utente = User.objects.create_user(username="dpi-op", password="x")
        UserOnboarding.objects.update_or_create(user=utente, defaults={"completed": True})
        self.client.force_login(utente)
        with mock.patch("dpi.views._is_gestore", return_value=False):
            resp = self.client.get(self.url)
            self.client.post(self.url, {"azione": "consegna", "ids": [self._richiesta(self.mod_guanti).pk],
                                        "data_consegna": "2026-11-02"})
        self.assertRedirects(resp, reverse("dpi:dashboard"), fetch_redirect_response=False)
        self.assertFalse(ConsegnaDPI.objects.exists())


class DestinatariConsegnaTests(TestCase):
    def test_scarpe_ai_referenti_il_resto_al_magazzino(self):
        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.notifica_email_extra = "rspp@example.test"
        impost.save()
        guanti = CategoriaDPI.objects.create(nome="Mani")
        scarpe = CategoriaDPI.objects.create(nome="Calzature", consegna_magazzino=False)
        self.assertEqual(flusso.destinatari_consegna(RichiestaDPI(categoria=guanti)), ["magazzino@example.test"])
        self.assertEqual(flusso.destinatari_consegna(RichiestaDPI(categoria=scarpe)), ["rspp@example.test"])
