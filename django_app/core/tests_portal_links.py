"""Link «Apri nel portale» delle mail e ingresso via accesso Windows."""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.accounts.portal_links import portal_link

PAGINA = "/gestione-anomalie?op=OP-1"


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
                   ALLOWED_HOSTS=["testserver"])
class PortalLinkTests(TestCase):
    @override_settings(SITE_URL="https://hub.example.local/", LDAP_ENABLED=True)
    def test_link_passa_da_accesso_windows(self):
        self.assertEqual(
            portal_link(PAGINA),
            "https://hub.example.local/login/windows/?next=%2Fgestione-anomalie%3Fop%3DOP-1",
        )

    @override_settings(SITE_URL="https://hub.example.local", LDAP_ENABLED=False)
    def test_senza_ldap_link_diretto(self):
        self.assertEqual(portal_link(PAGINA), "https://hub.example.local/gestione-anomalie?op=OP-1")

    @override_settings(SITE_URL="", LDAP_ENABLED=True)
    def test_senza_site_url_vuoto(self):
        self.assertEqual(portal_link(PAGINA), "")

    @override_settings(SITE_URL="https://hub.example.local", LDAP_ENABLED=False)
    def test_percorso_protocol_relative_resta_interno(self):
        self.assertEqual(portal_link("//evil.example/x"), "https://hub.example.local/evil.example/x")

    @override_settings(LDAP_ENABLED=True)
    def test_utente_gia_dentro_va_dritto_alla_pagina(self):
        user = get_user_model().objects.create_user(username="sso-link-user", password="pass12345")
        self.client.force_login(user)
        response = self.client.get(f"{reverse('windows_sso')}?next={PAGINA}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], PAGINA)

    @override_settings(LDAP_ENABLED=True)
    def test_sfida_windows_ha_ripiego_sul_login_con_ritorno(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        fake_spnego = SimpleNamespace(server=lambda **_kw: object())
        with patch.dict("sys.modules", {"spnego": fake_spnego}):
            response = self.client.get(f"{reverse('windows_sso')}?next={PAGINA}")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"], "Negotiate")
        body = response.content.decode()
        self.assertIn("/login/?next=%2Fgestione-anomalie%3Fop%3DOP-1", body)
        self.assertIn("Accedi con nome utente e password", body)

    @override_settings(LDAP_ENABLED=False)
    def test_accesso_windows_spento_porta_al_login_con_ritorno(self):
        response = self.client.get(f"{reverse('windows_sso')}?next={PAGINA}")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/login/?next=%2Fgestione-anomalie%3Fop%3DOP-1")

    @override_settings(LDAP_ENABLED=False)
    def test_next_esterno_resta_rifiutato(self):
        response = self.client.get(f"{reverse('windows_sso')}?next=https://evil.example/x")
        self.assertNotIn("evil.example", response["Location"])


@override_settings(SITE_URL="https://hub.example.local", LDAP_ENABLED=True)
class LinkMailModuliTests(TestCase):
    """Le mail degli altri moduli usano lo stesso ingresso via accesso Windows."""

    SSO = "https://hub.example.local/login/windows/?next="

    def test_suggestion_corner(self):
        from types import SimpleNamespace

        from suggestion_corner.notifications import _dettaglio_url

        self.assertEqual(_dettaglio_url(SimpleNamespace(pk=7)), self.SSO + "%2Fsuggestion-corner%2F7%2F")

    def test_gestione_specifiche_scadenze(self):
        from gestione_specifiche.scadenze import _abs_url

        self.assertEqual(_abs_url("/specifiche/3/"), self.SSO + "%2Fspecifiche%2F3%2F")
        self.assertEqual(_abs_url("https://altro.example/x"), "https://altro.example/x")

    def test_link_record_automazioni(self):
        from automazioni.services import _OBJECT_URL_PATH_BY_SOURCE, _build_object_url

        source = next(iter(_OBJECT_URL_PATH_BY_SOURCE))
        self.assertTrue(_build_object_url(source, {"id": 5}).startswith(self.SSO))

    @override_settings(SECURITY_CENTER_BASE_URL="")
    def test_security_center(self):
        from security.services.notifications import _link

        self.assertEqual(_link("/soc/tickets/1/"), self.SSO + "%2Fsoc%2Ftickets%2F1%2F")

    @override_settings(SECURITY_CENTER_BASE_URL="https://soc.example.local")
    def test_security_center_standalone_resta_diretto(self):
        from security.services.notifications import _link

        self.assertEqual(_link("/soc/tickets/1/"), "https://soc.example.local/soc/tickets/1/")
