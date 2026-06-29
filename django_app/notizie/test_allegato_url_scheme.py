from __future__ import annotations

from django.test import TestCase

from notizie.forms import NotiziaAllegatoForm


class NotiziaAllegatoUrlSchemeTests(TestCase):
    """SEC: url_esterno è un CharField reso in un href; deve accettare solo
    http/https o percorsi relativi, mai javascript:/data: (stored XSS al click)."""

    def _form(self, url):
        return NotiziaAllegatoForm(data={"nome_file": "Allegato", "url_esterno": url})

    def test_javascript_uri_rejected(self):
        form = self._form("javascript:alert(document.cookie)")
        self.assertFalse(form.is_valid())
        self.assertIn("http", str(form.errors).lower())

    def test_data_uri_rejected(self):
        form = self._form("data:text/html,<script>alert(1)</script>")
        self.assertFalse(form.is_valid())

    def test_https_url_accepted(self):
        form = self._form("https://example.com/doc.pdf")
        # Non deve esserci l'errore di schema (altri eventuali errori non riguardano l'URL).
        form.is_valid()
        self.assertNotIn("http:// o https://", str(form.errors))

    def test_relative_path_accepted(self):
        form = self._form("/media/x.pdf")
        form.is_valid()
        self.assertNotIn("http:// o https://", str(form.errors))
