"""Header delle superfici raggiungibili senza login.

Il portale espone alcune rotte fuori dal perimetro autenticato
(``MIDDLEWARE_EXEMPT_PREFIXES``), e tre di queste hanno il **token dentro
l'URL**: approvazioni automazioni, proxy Entra, azioni via mail sulle anomalie.
Su quelle pagine `Referrer-Policy: no-referrer` non è cosmesi — senza, il token
viaggia nell'header `Referer` verso qualunque risorsa esterna o link in uscita.
"""
from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase, TestCase
from django.http import HttpResponse
from django.urls import reverse

from core.public_headers import HEADER_PUBBLICI, blinda_risposta_pubblica, risposta_pubblica


class HelperTests(SimpleTestCase):
    def test_applica_tutti_gli_header(self):
        risposta = blinda_risposta_pubblica(HttpResponse("ok"))
        for nome, valore in HEADER_PUBBLICI.items():
            self.assertEqual(risposta[nome], valore)

    def test_non_sovrascrive_una_cache_control_esplicita(self):
        risposta = HttpResponse("ok")
        risposta["Cache-Control"] = "public, max-age=60"
        blinda_risposta_pubblica(risposta)
        self.assertEqual(risposta["Cache-Control"], "public, max-age=60")
        self.assertEqual(risposta["Referrer-Policy"], "no-referrer")

    def test_decoratore_preserva_la_risposta_della_view(self):
        @risposta_pubblica
        def vista(request):
            return HttpResponse("contenuto", status=201)

        risposta = vista(RequestFactory().get("/x/"))
        self.assertEqual(risposta.status_code, 201)
        self.assertEqual(risposta.content, b"contenuto")
        self.assertEqual(risposta["X-Robots-Tag"], "noindex, nofollow, noarchive")

    def test_decoratore_copre_anche_i_redirect(self):
        from django.http import HttpResponseRedirect

        @risposta_pubblica
        def vista(request):
            return HttpResponseRedirect("/altrove/")

        risposta = vista(RequestFactory().get("/x/"))
        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(risposta["Referrer-Policy"], "no-referrer")


class RotteAtokenTests(TestCase):
    """Le rotte col token nell'URL: il token non deve uscire nel Referer."""

    def _asserisci_blindata(self, url: str):
        risposta = self.client.get(url)
        # Token inesistente: la view risponde comunque (errore/404/redirect),
        # e qualunque sia l'esito gli header devono esserci.
        self.assertEqual(risposta["Referrer-Policy"], "no-referrer")
        self.assertEqual(risposta["X-Robots-Tag"], "noindex, nofollow, noarchive")
        self.assertEqual(risposta["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", risposta["Cache-Control"])

    def test_approvazione_automazioni(self):
        token = "00000000-0000-4000-8000-000000000000"
        self._asserisci_blindata(
            reverse("automazioni:automazioni_approval_status", kwargs={"token": token})
        )

    def test_proxy_entra_approvazione(self):
        token = "00000000-0000-4000-8000-000000000000"
        self._asserisci_blindata(
            reverse("approval_proxy:approval_proxy_approve", kwargs={"token": token})
        )

    def test_azione_via_mail_anomalie(self):
        self._asserisci_blindata(
            reverse("anomalie_mail_action", kwargs={"token": "token-inesistente"})
        )

    def test_landing_qr_asset(self):
        """Token valido: sul percorso 404 gli header li mette il gestore di
        Django, non il decoratore (limite documentato in core.public_headers)."""
        from assets.models import Asset

        asset = Asset.objects.create(
            name="Tornio pubblico", asset_tag="PUB-QR-1",
            public_qr_token="token-valido-test", public_qr_enabled=True,
        )
        self.assertTrue(asset.public_qr_enabled)
        self._asserisci_blindata(
            reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": "token-valido-test"})
        )

    def test_form_pubblico_suggestion_corner(self):
        self._asserisci_blindata(reverse("suggestion_corner:nuova"))
