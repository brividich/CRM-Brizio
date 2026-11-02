"""Guida d'uso del modulo Anomalie: contenuto, pagina, PDF e pulsante «?»."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie.guida import PAGINE, SEZIONI, sezione

_TIPI = {"p", "passi", "ul", "def", "nota"}


class GuidaContenutoTests(SimpleTestCase):
    def test_sezioni_ben_formate(self):
        ids = [s["id"] for s in SEZIONI]
        self.assertEqual(len(ids), len(set(ids)))
        for s in SEZIONI:
            with self.subTest(sezione=s["id"]):
                self.assertTrue(s["titolo"])
                self.assertTrue(s["blocchi"])
                for kind, contenuto in s["blocchi"]:
                    self.assertIn(kind, _TIPI)
                    self.assertTrue(contenuto)

    def test_ogni_pagina_punta_a_un_paragrafo_esistente(self):
        for pagina, sezione_id in PAGINE.items():
            with self.subTest(pagina=pagina):
                self.assertIsNotNone(sezione(sezione_id))

    def test_pdf(self):
        from core.guida_pdf import render_guida_pdf

        pdf = render_guida_pdf(titolo="Gestione anomalie", sottotitolo="Guida", sezioni=SEZIONI)
        self.assertTrue(pdf.startswith(b"%PDF"))


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class GuidaPagineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="guida-admin", password="x", is_superuser=True, is_staff=True
        )
        self.client.force_login(user)

    def test_la_guida_si_apre_da_ogni_pagina_del_modulo(self):
        for name in ("gestione_anomalie_page", "apertura_segnalazione", "anomalie_statistiche_page",
                     "anomalie_configurazione_page", "anomalie_nc_lista", "anomalie_menu"):
            with self.subTest(pagina=name):
                response = self.client.get(reverse(name), {"guida": "1"})
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "anomalie/pages/guida.html")
                for s in SEZIONI:
                    self.assertContains(response, f'id="{s["id"]}"')

    def test_pdf_scaricabile(self):
        response = self.client.get(reverse("gestione_anomalie_page"), {"guida": "pdf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_ogni_pagina_ha_il_pulsante_sul_suo_paragrafo(self):
        for name, sezione_id in (("gestione_anomalie_page", "gestione"), ("apertura_segnalazione", "controllo"),
                                 ("anomalie_statistiche_page", "statistiche"),
                                 ("anomalie_configurazione_page", "configurazione"),
                                 ("anomalie_nc_lista", "non-conformita"), ("anomalie_menu", "menu")):
            with self.subTest(pagina=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'href="?guida=1#{sezione_id}"')

    def test_senza_parametro_la_pagina_resta_quella(self):
        response = self.client.get(reverse("anomalie_statistiche_page"))
        self.assertTemplateNotUsed(response, "anomalie/pages/guida.html")


@override_settings(LEGACY_AUTH_ENABLED=True, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class GuidaPaginaMailTests(TestCase):
    """La pagina del link della mail è pubblica: la guida è nel riquadro, senza login."""

    def test_riquadro_come_funziona(self):
        from anomalie.mail_action_models import AnomaliaMailActionToken

        token = AnomaliaMailActionToken.objects.create(
            recipient_email="cc@example.local", recipient_display="Capocommessa Test",
            op_id="OP-GUIDA", anomalie_ids=[1], anomalie_snapshot=[], action="aggiorna_avanzamento",
            expires_at=timezone.now() + timedelta(hours=4),
        )
        righe = [{"id": 1, "descrizione": "Graffio sul pezzo", "avanzamento": "In attesa", "seriale": "SN-1"}]
        with patch("anomalie.mail_action_views._load_anomalie_live_by_op", return_value=righe), \
             patch("anomalie.views._list_attachments_for_local", return_value=[]):
            response = self.client.get(reverse("anomalie_mail_action", kwargs={"token": token.token}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Come funziona questa pagina")
        self.assertContains(response, "Conferma e invia aggiornamenti")
        self.assertNotContains(response, "?guida=1")


class GuideRuoliContenutoTests(SimpleTestCase):
    """Guide rapide del controllore e del capocommessa/CAR (``anomalie/guida_ruoli.py``)."""

    def test_sezioni_e_immagini(self):
        from django.contrib.staticfiles import finders

        from anomalie.guida_ruoli import GUIDE_RUOLI

        self.assertEqual(set(GUIDE_RUOLI), {"controllore", "capocommessa"})
        for chiave, guida in GUIDE_RUOLI.items():
            ids = [s["id"] for s in guida["sezioni"]]
            self.assertEqual(len(ids), len(set(ids)))
            for s in guida["sezioni"]:
                for kind, contenuto in s["blocchi"]:
                    with self.subTest(guida=chiave, sezione=s["id"], kind=kind):
                        self.assertIn(kind, _TIPI | {"img"})
                        if kind == "img":
                            self.assertIsNotNone(finders.find(contenuto[0]), contenuto[0])
                            self.assertTrue(contenuto[1])

    def test_pdf_con_immagini(self):
        from core.guida_pdf import render_guida_pdf

        from anomalie.guida_ruoli import GUIDE_RUOLI

        for guida in GUIDE_RUOLI.values():
            pdf = render_guida_pdf(titolo=guida["titolo"], sottotitolo=guida["sottotitolo"], sezioni=guida["sezioni"])
            self.assertTrue(pdf.startswith(b"%PDF"))
            self.assertIn(b"/Image", pdf)

    def test_immagine_mancante_lascia_la_didascalia(self):
        from core.guida_pdf import render_guida_pdf

        sezioni = [{"id": "x", "titolo": "X", "blocchi": [("img", ("anomalie/guida/non_esiste.jpg", "Didascalia"))]}]
        self.assertTrue(render_guida_pdf(titolo="T", sottotitolo="S", sezioni=sezioni).startswith(b"%PDF"))


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class GuideRuoliPagineTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(
            username="guida-ruoli", password="x", is_superuser=True, is_staff=True
        )
        self.client.force_login(user)

    def test_pagina_per_ruolo(self):
        from anomalie.guida_ruoli import GUIDE_RUOLI

        for chiave, guida in GUIDE_RUOLI.items():
            with self.subTest(guida=chiave):
                response = self.client.get(reverse("gestione_anomalie_page"), {"guida": chiave})
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "anomalie/pages/guida.html")
                self.assertContains(response, guida["titolo"])
                self.assertContains(response, f'href="?guida=pdf&amp;per={chiave}"')
                self.assertContains(response, "<img ")

    def test_pdf_per_ruolo(self):
        response = self.client.get(reverse("apertura_segnalazione"), {"guida": "pdf", "per": "controllore"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Guida_Anomalie_Controllore.pdf", response["Content-Disposition"])

    def test_guida_completa_rimanda_alle_guide_per_ruolo(self):
        response = self.client.get(reverse("gestione_anomalie_page"), {"guida": "1"})
        self.assertContains(response, 'href="?guida=controllore"')
        self.assertContains(response, 'href="?guida=capocommessa"')
