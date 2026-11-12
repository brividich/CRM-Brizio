"""Catalogo delle specifiche a copertine per cartella della share."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gestione_specifiche import scaffale_clienti as sc
from gestione_specifiche.models import ClienteCartellaShare, Specifica

User = get_user_model()


ROOT = r"\\srv\SPECIFICHE"


@override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[ROOT])
class CopertineTests(TestCase):
    """Una copertina per cartella della share: dal PDF collegato, o dalla mappatura del cliente."""

    def setUp(self):
        self.su = User.objects.create_superuser("cop_su", "s@example.invalid", "x")
        self.client.force_login(self.su)
        Specifica.objects.create(codice="SP-A1", titolo="Saldatura", cliente="Alfa", percorso_esterno=ROOT + r"\ALFA AEROSPACE\SP-A1 REV.0.pdf")
        Specifica.objects.create(codice="SP-A2", titolo="Verniciatura", cliente="Altro nome", percorso_esterno=ROOT + r"\ALFA AEROSPACE\sub\SP-A2 REV.1.pdf")
        Specifica.objects.create(codice="SP-B1", titolo="Imballo", cliente="Beta Srl")
        Specifica.objects.create(codice="SP-X1", titolo="Interna", cliente="")
        ClienteCartellaShare.objects.create(cliente="Beta Srl", cartella="BETA ELICOTTERI")
        self.url = reverse("gestione_specifiche:lista")

    def test_sigla_e_colore(self):
        self.assertEqual(sc.sigla_di("Alfa Aerospace S.p.A."), "ALFA")
        self.assertEqual(sc.sigla_di("FERRARI - FERRARI GES"), "FERRARI")
        self.assertEqual(sc.colore_di("Beta Srl"), sc.colore_di("BETA SRL"))

    def test_una_copertina_per_cartella(self):
        cop = sc.copertine()
        self.assertEqual([c.nome for c in cop], ["ALFA AEROSPACE", "BETA ELICOTTERI", "Senza cartella"])
        self.assertEqual(cop[0].totale, 2)  # il cliente scritto nella scheda non conta: conta la cartella del file
        self.assertEqual(cop[1].clienti, ("Beta Srl",))

    def test_pagina_a_copertine_di_default(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'class="gs-vol"', count=3)
        self.assertNotContains(r, "SP-A1")
        self.assertContains(r, "?cartella=ALFA%20AEROSPACE")

    def test_cartella_aperta_mostra_le_sue_specifiche(self):
        r = self.client.get(self.url, {"cartella": "ALFA AEROSPACE"})
        self.assertContains(r, "SP-A1")
        self.assertContains(r, "SP-A2")
        self.assertNotContains(r, "SP-B1")
        self.assertContains(r, "Tutte le cartelle")
        r = self.client.get(self.url, {"cartella": "BETA ELICOTTERI"})
        self.assertContains(r, "SP-B1")
        self.assertContains(r, "Nuova per BETA")
        r = self.client.get(self.url, {"cartella": sc.SENZA_CARTELLA})
        self.assertContains(r, "SP-X1")
        self.assertNotContains(r, "SP-A1")
        self.assertNotContains(r, "SP-B1")

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


@override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[ROOT])
class PersonalizzaCopertinaTests(TestCase):
    def setUp(self):
        import shutil
        import tempfile

        from django.test import override_settings

        self._tmp = tempfile.mkdtemp(prefix="gs_logo_")
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)
        ov = override_settings(PRIVATE_ATTACHMENTS_ROOT=self._tmp)
        ov.enable()
        self.addCleanup(ov.disable)
        self.su = User.objects.create_superuser("cop_su2", "s2@example.invalid", "x")
        self.client.force_login(self.su)
        Specifica.objects.create(codice="SP-G1", titolo="Saldatura", cliente="Gamma Motori",
                                 percorso_esterno=r"\\srv\SPECIFICHE\GAMMA MOTORI\SP-G1 REV.0.pdf")

    def test_colore_sigla_icona_logo(self):
        import io
        from unittest import mock

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from gestione_specifiche.models import CopertinaCliente

        buf = io.BytesIO()
        Image.new("RGB", (30, 30), (0, 90, 200)).save(buf, format="PNG")
        with mock.patch("gestione_specifiche.views_copertine.utente_puo_admin", return_value=True):
            r = self.client.post(reverse("gestione_specifiche:copertina_salva"), {
                "cartella": "GAMMA MOTORI", "colore": "#123456", "sigla": "gm", "icona": "factory",
                "logo": SimpleUploadedFile("logo.png", buf.getvalue()),
            })
        self.assertEqual(r.status_code, 302)
        p = CopertinaCliente.objects.get(chiave="gamma motori")
        self.assertEqual((p.colore, p.sigla, p.icona), ("#123456", "GM", "factory"))
        cop = next(c for c in sc.copertine() if c.cartella == "GAMMA MOTORI")
        self.assertEqual((cop.colore, cop.sigla, cop.icona), ("#123456", "GM", "factory"))
        self.assertIn(f"/gestione-specifiche/copertina/{p.pk}/logo/", cop.logo_url)
        r = self.client.get(reverse("gestione_specifiche:lista"), {"vista": "copertine"})
        self.assertContains(r, 'class="gs-vol__ico"')
        self.assertContains(r, 'class="gs-vol__logo"')

    def test_solo_l_amministrazione(self):
        from unittest import mock

        from gestione_specifiche.models import CopertinaCliente

        with mock.patch("gestione_specifiche.views_copertine.utente_puo_admin", return_value=False):
            self.client.post(reverse("gestione_specifiche:copertina_salva"), {"cartella": "GAMMA MOTORI", "icona": "star"})
        self.assertFalse(CopertinaCliente.objects.exists())
