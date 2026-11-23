"""Allegati serviti in base al contenuto (audit 22/11, voce [56]). Dati sintetici."""
from django.http import HttpResponse
from django.test import SimpleTestCase

from core.download_security import ALLEGATI_INLINE_MIME_TYPES, harden_sniffed_response, sniff_head

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452")


class AllegatiInlineTests(SimpleTestCase):
    def _risposta(self, nome, testa, tipi=ALLEGATI_INLINE_MIME_TYPES):
        return harden_sniffed_response(HttpResponse(b""), nome, testa, inline_types=tipi)

    def test_foto_vera_si_apre_nel_browser(self):
        r = self._risposta("foto.png", PNG)
        self.assertTrue(r["Content-Disposition"].startswith("inline"))
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")

    def test_html_travestito_da_foto_si_scarica_in_sandbox(self):
        r = self._risposta("foto.png", b"<html><script>")
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))
        self.assertEqual(r["Content-Type"], "application/octet-stream")
        self.assertIn("sandbox", r["Content-Security-Policy"])

    def test_download_forzato_resta_allegato(self):
        r = self._risposta("foto.png", PNG, tipi=frozenset())
        self.assertTrue(r["Content-Disposition"].startswith("attachment"))

    def test_firme_webp_gif(self):
        self.assertEqual(sniff_head(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertEqual(sniff_head(b"GIF89a"), "image/gif")
