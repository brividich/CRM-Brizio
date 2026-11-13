"""Scheda dipendente: codice fiscale nella card «Anagrafica civile» e salvataggio per sezione.

I moduli «Anagrafica civile» e «Dati riservati HR» salvano sulla stessa view: ognuno deve
scrivere solo i suoi campi (prima il form completo azzerava quelli assenti dal POST e il
modulo HR, senza il formset dei figli, non veniva mai salvato).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .models import DipendenteAnagraficaCivile
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

CF = "RSSMRA80A01H501U"  # sintetico
IBAN = "IT60X0542811101000000123456"  # sintetico
FIGLI_VUOTO = {"figli-TOTAL_FORMS": "0", "figli-INITIAL_FORMS": "0", "figli-MIN_NUM_FORMS": "0", "figli-MAX_NUM_FORMS": "1000"}


class AnagraficaCivileSezioniTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, attivo) VALUES (%s, %s, %s, %s, %s)",
                ["m.rossi", "Mario", "Rossi", "Produzione", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["m.rossi"])
            self.lid = int(cursor.fetchone()[0])
        self.civile = DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=self.lid, codice_fiscale=CF, iban=IBAN, nome_banca="Banca Prova",
            data_nascita=date(1980, 1, 1), luogo_nascita="Pisa",
        )
        self.user = get_user_model().objects.create_superuser("civ-sez", "civ-sez@example.invalid", "x-Civ-2026!")
        self.client.force_login(self.user)
        self.url = reverse("anagrafica:dipendente_civile_save", args=[self.lid])

    def test_modulo_hr_salva_senza_azzerare_i_dati_civili(self):
        r = self.client.post(self.url, {"sezione": "hr", "nome_banca": "Banca Nuova", "iban": IBAN, "intestatario_conto": "Mario Rossi"})
        self.assertEqual(r.status_code, 302)
        self.civile.refresh_from_db()
        self.assertEqual(self.civile.nome_banca, "Banca Nuova")
        self.assertEqual(self.civile.data_nascita, date(1980, 1, 1))
        self.assertEqual(self.civile.luogo_nascita, "Pisa")
        self.assertEqual(self.civile.codice_fiscale, CF)

    def test_modulo_civile_non_azzera_iban_e_banca(self):
        r = self.client.post(self.url, {"sezione": "civile", "codice_fiscale": CF.lower(), "luogo_nascita": "Lucca", **FIGLI_VUOTO})
        self.assertEqual(r.status_code, 302)
        self.civile.refresh_from_db()
        self.assertEqual(self.civile.luogo_nascita, "Lucca")
        self.assertEqual(self.civile.iban, IBAN)
        self.assertEqual(self.civile.nome_banca, "Banca Prova")
        self.assertEqual(self.civile.codice_fiscale, CF)

    def test_senza_permesso_hr_niente_modulo_hr_ne_codice_fiscale(self):
        with patch("anagrafica.views._helpers._check_hr_permission", return_value=False):
            self.client.post(self.url, {"sezione": "hr", "iban": "IT00X0000000000000000000000"})
            self.client.post(self.url, {"sezione": "civile", "codice_fiscale": "AAAAAA00A00A000A", "luogo_nascita": "Lucca", **FIGLI_VUOTO})
        self.civile.refresh_from_db()
        self.assertEqual(self.civile.iban, IBAN)
        self.assertEqual(self.civile.codice_fiscale, CF)
        self.assertEqual(self.civile.luogo_nascita, "Lucca")

    def test_codice_fiscale_nella_card_anagrafica_civile(self):
        html = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.lid])).content.decode()
        card = html.split("🪪 Anagrafica civile", 1)[1].split("Modifica dati civili", 1)[0]
        self.assertIn("Codice fiscale", card)
        self.assertIn(CF, card)
