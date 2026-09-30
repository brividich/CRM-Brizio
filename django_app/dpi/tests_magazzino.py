"""Magazzino DPI: giacenza come somma dei movimenti (carico DDT, consegna, rettifica)."""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from . import magazzino
from .models import (
    CategoriaDPI,
    ConsegnaDPI,
    ModelloDPI,
    MovimentoMagazzinoDPI,
    RichiestaDPI,
    StatoRichiesta,
    TipoDPI,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MagazzinoDpiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-mag", password="x", email="m@y.z")
        self.client.force_login(self.admin)
        cat = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=180)
        tipo = TipoDPI.objects.create(categoria=cat, nome="Guanti")
        self.modello = ModelloDPI.objects.create(tipo=tipo, codice="GT-1", nome="Blade Safe")
        self.cat = cat

    def _richiesta(self, quantita=2):
        return RichiestaDPI.objects.create(
            categoria=self.cat, modello_dpi=self.modello, quantita=quantita,
            stato=StatoRichiesta.APPROVATA, richiedente_nome="Mario Rossi",
        )

    def test_carico_ddt_aumenta_la_giacenza(self):
        self.client.post(reverse("dpi:magazzino"), {
            "azione": "carico", "modello": self.modello.pk, "quantita": "50",
            "ddt_numero": "1234/2026", "data": "2026-09-30", "fornitore": "Alfa",
        })
        self.assertEqual(magazzino.giacenza(self.modello.pk), 50)
        mov = MovimentoMagazzinoDPI.objects.get()
        self.assertEqual((mov.tipo, mov.ddt_numero, mov.fornitore, mov.data), ("CARICO", "1234/2026", "Alfa", date(2026, 9, 30)))

    def test_carico_con_quantita_non_valida_rifiutato(self):
        self.client.post(reverse("dpi:magazzino"), {"azione": "carico", "modello": self.modello.pk, "quantita": "0"})
        self.client.post(reverse("dpi:magazzino"), {"azione": "carico", "modello": self.modello.pk, "quantita": "abc"})
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())

    def test_consegna_scarica_la_quantita_una_sola_volta(self):
        magazzino.carica_ddt(self.modello, 10)
        richiesta = self._richiesta(quantita=3)
        with mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF"):
            self.client.post(reverse("dpi:consegna", args=[richiesta.pk]), {"data_consegna": "2026-09-30"})
        self.assertEqual(magazzino.giacenza(self.modello.pk), 7)
        magazzino.scarica_per_consegna(richiesta, date(2026, 9, 30))  # richiamo: idempotente
        self.assertEqual(magazzino.giacenza(self.modello.pk), 7)
        self.assertTrue(ConsegnaDPI.objects.filter(richiesta=richiesta).exists())

    def test_consegna_oltre_la_giacenza_non_e_bloccata_ma_avvisa(self):
        richiesta = self._richiesta(quantita=2)
        with mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF"):
            response = self.client.post(reverse("dpi:consegna", args=[richiesta.pk]), {"data_consegna": "2026-09-30"})
        self.assertEqual(magazzino.giacenza(self.modello.pk), -2)
        testi = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("Giacenza di magazzino negativa" in t for t in testi), testi)

    def test_rettifica_porta_la_giacenza_al_valore_contato(self):
        magazzino.carica_ddt(self.modello, 10)
        self.client.post(reverse("dpi:magazzino"), {"azione": "rettifica", "modello": self.modello.pk, "giacenza": "4"})
        self.assertEqual(magazzino.giacenza(self.modello.pk), 4)
        self.assertEqual(MovimentoMagazzinoDPI.objects.filter(tipo="RETTIFICA").get().quantita, -6)

    def test_stato_scorta_e_soglia(self):
        self.assertEqual(magazzino.stato_scorta(0, 5), magazzino.STATO_ESAURITO)
        self.assertEqual(magazzino.stato_scorta(5, 5), magazzino.STATO_SOTTO_SCORTA)
        self.assertEqual(magazzino.stato_scorta(6, 5), magazzino.STATO_OK)
        self.assertEqual(magazzino.stato_scorta(1, 0), magazzino.STATO_OK)
        self.client.post(reverse("dpi:magazzino"), {"azione": "soglia", "modello": self.modello.pk, "scorta_minima": "8"})
        self.modello.refresh_from_db()
        self.assertEqual(self.modello.scorta_minima, 8)

    def test_pagina_e_riservata_ai_gestori(self):
        self.assertContains(self.client.get(reverse("dpi:magazzino")), "Magazzino DPI")
        with mock.patch("dpi.views._is_gestore", return_value=False):
            self.assertEqual(self.client.get(reverse("dpi:magazzino")).status_code, 302)
            self.client.post(reverse("dpi:magazzino"), {"azione": "carico", "modello": self.modello.pk, "quantita": "5"})
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())

    def test_dettaglio_richiesta_mostra_la_giacenza(self):
        magazzino.carica_ddt(self.modello, 1)
        richiesta = self._richiesta(quantita=3)
        page = self.client.get(reverse("dpi:gestione_detail", args=[richiesta.pk]))
        self.assertContains(page, "In magazzino: 1 pz")
        self.assertContains(page, "insufficienti per 3 richiesti")
