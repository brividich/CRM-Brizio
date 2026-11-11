"""Catalogo delle specifiche a copertine per cliente."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import scaffale_clienti as sc
from gestione_specifiche.models import ClienteCartellaShare, Specifica

User = get_user_model()


class CopertineTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("cop_su", "s@example.invalid", "x")
        self.client.force_login(self.su)
        Specifica.objects.create(codice="SP-A1", titolo="Saldatura", cliente="Alfa Aerospace S.p.A.")
        Specifica.objects.create(codice="SP-A2", titolo="Verniciatura", cliente="ALFA AEROSPACE S.P.A.")
        Specifica.objects.create(codice="SP-B1", titolo="Imballo", cliente="Beta Srl")
        Specifica.objects.create(codice="SP-X1", titolo="Interna", cliente="")
        ClienteCartellaShare.objects.create(cliente="Beta Srl", cartella="BETA")
        self.url = reverse("gestione_specifiche:lista")

    def test_sigla_e_colore(self):
        self.assertEqual(sc.sigla_di("Alfa Aerospace S.p.A."), "ALFA")
        self.assertEqual(sc.sigla_di("Beta Srl"), "BETA")
        self.assertEqual(sc.colore_di("Beta Srl"), sc.colore_di("BETA SRL"))

    def test_una_copertina_per_cliente(self):
        cop = sc.copertine()
        self.assertEqual([c.nome for c in cop][-1], "Senza cliente")
        alfa = next(c for c in cop if c.sigla == "ALFA")
        self.assertEqual(alfa.totale, 2)
        self.assertEqual(next(c for c in cop if c.sigla == "BETA").cartella_share, "BETA")

    def test_pagina_a_copertine_di_default(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'class="gs-vol"', count=3)
        self.assertNotContains(r, "SP-A1")
        self.assertContains(r, "?cartella=Beta%20Srl")

    def test_cliente_aperto_mostra_le_sue_specifiche(self):
        r = self.client.get(self.url, {"cartella": "alfa aerospace s.p.a."})
        self.assertContains(r, "SP-A1")
        self.assertContains(r, "SP-A2")
        self.assertNotContains(r, "SP-B1")
        self.assertContains(r, "Tutti i clienti")
        r = self.client.get(self.url, {"cartella": sc.SENZA_CLIENTE})
        self.assertContains(r, "SP-X1")
        self.assertNotContains(r, "SP-A1")

    def test_la_ricerca_mostra_l_elenco(self):
        r = self.client.get(self.url, {"q": "Imballo"})
        self.assertContains(r, "SP-B1")
        self.assertNotContains(r, 'class="gs-vol"')

    def test_vista_elenco_ricordata(self):
        r = self.client.get(self.url, {"vista": "elenco"})
        self.assertContains(r, "SP-A1")
        self.assertEqual(r.cookies["gs_vista"].value, "elenco")
        r = self.client.get(self.url)
        self.assertContains(r, "SP-A1")

    def test_nuova_dal_cliente(self):
        r = self.client.get(reverse("gestione_specifiche:nuova"), {"cliente": "Beta Srl"})
        self.assertContains(r, 'value="Beta Srl"')
