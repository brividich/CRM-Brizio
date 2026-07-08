"""Arricchimento email dei digest/reminder anagrafica allo standard «anomalie».

Due livelli:
- unit sul helper puro ``anagrafica.services.email_digest`` (badge scadenza +
  fragment a sezioni), senza DB;
- e2e sul comando ``send_visite_mediche_digest`` (solo modelli Django): l'HTML
  deve contenere card + badge di stato, il ``text/plain`` niente tag HTML.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from anagrafica.services.email_digest import digest_fragment, scadenza_badge

User = get_user_model()


def _html_alt(email) -> str:
    for content, mimetype in getattr(email, "alternatives", []):
        if mimetype == "text/html":
            return content
    return ""


class ScadenzaBadgeTests(SimpleTestCase):
    def test_scaduto_e_danger(self):
        text, tone = scadenza_badge(12, scaduto=True)
        self.assertEqual(tone, "danger")
        self.assertIn("12", text)

    def test_in_scadenza_e_warning(self):
        text, tone = scadenza_badge(5)
        self.assertEqual(tone, "warning")
        self.assertIn("5", text)

    def test_label_personalizzabile(self):
        text, _ = scadenza_badge(3, scaduto=True, label_scaduto="Scaduta")
        self.assertIn("Scaduta", text)

    def test_senza_giorni_non_esplode(self):
        text, tone = scadenza_badge(None)
        self.assertEqual(tone, "warning")
        self.assertTrue(text)


class DigestFragmentTests(SimpleTestCase):
    def test_rende_heading_e_card(self):
        html = digest_fragment([
            ("Visite scadute (1)",
             [{"title": "Mario Rossi", "badge": ("Scaduta da 3 gg", "danger")}]),
        ])
        self.assertIn("Visite scadute (1)", html)
        self.assertIn("Mario Rossi", html)
        self.assertIn("Scaduta da 3 gg", html)
        self.assertIn("<table", html)

    def test_salta_sezioni_vuote(self):
        html = digest_fragment([
            ("Sezione vuota", []),
            ("Sezione piena (1)", [{"title": "X"}]),
        ])
        self.assertNotIn("Sezione vuota", html)
        self.assertIn("Sezione piena (1)", html)

    def test_tutte_vuote_stringa_vuota(self):
        self.assertEqual(digest_fragment([("A", []), ("B", [])]), "")

    def test_escape_del_heading(self):
        html = digest_fragment([("<b>x</b>", [{"title": "T"}])])
        self.assertNotIn("<b>x</b>", html)
        self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)


class VisiteMedicheDigestEmailTests(TestCase):
    def setUp(self):
        User.objects.create_superuser("hr", "hr@x.it", "x")
        from anagrafica.models import TipoVisitaMedica, VisitaMedica
        # durata_mesi=1 + svolta oggi → data_scadenza (auto = svolgimento + 1 mese)
        # cade entro i 60 giorni della finestra.
        tipo = TipoVisitaMedica.objects.create(nome="Sorveglianza", durata_mesi=1)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=77, tipo=tipo,
            data_svolgimento=timezone.localdate(),
            esito=VisitaMedica.Esito.IDONEO,
        )

    def test_email_ha_card_badge_e_plain_pulito(self):
        call_command("send_visite_mediche_digest", "--days", "60")
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        html = _html_alt(email)
        self.assertIn("novicrmhub.png", html)                      # frame HUB
        self.assertIn("Visite in scadenza entro 60 giorni", html)  # heading sezione
        self.assertIn("#77", html)                                 # dipendente nella card
        self.assertIn("In scadenza", html)                         # badge stato
        self.assertIn("gg", html)                                  # giorni residui nel badge
        self.assertNotIn("<", email.body)                          # plain senza tag HTML
