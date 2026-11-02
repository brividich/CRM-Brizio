"""Pulsante «Apri nel portale» nelle mail anomalie (decisione e riepilogo modifiche)."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from anomalie.mail_action_service import build_anomalie_action_email, send_anomalie_update_confirmation

SITE = "https://hub.example.local"
SSO_LINK = f"{SITE}/login/windows/?next=%2Fgestione-anomalie%3Fop%3DOP-LINK-1"
DIRECT_LINK = f"{SITE}/gestione-anomalie?op=OP-LINK-1"


def _rows():
    return [{"id": 1, "descrizione": "Graffio sul bordo", "seriale": "SN-1", "avanzamento": "In attesa"}]


@override_settings(SITE_URL=SITE, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class LinkPortaleMailAnomalieTests(TestCase):
    def _azione(self):
        return build_anomalie_action_email(
            recipient_email="cc@example.local", recipient_display="Capo Commessa",
            op_id="OP-LINK-1", op_nominativo="", anomalie_rows=_rows(), action="aggiorna_avanzamento",
            token_str="tok-sintetico", expires_at=timezone.now() + timedelta(hours=48), site_url=SITE,
        )

    @override_settings(LDAP_ENABLED=True)
    def test_mail_decisione_ha_pulsante_portale_con_accesso_windows(self):
        _subject, text, html = self._azione()
        self.assertIn("Apri nel portale", html)
        self.assertIn(SSO_LINK, html)
        self.assertIn(SSO_LINK, text)
        # Il pulsante della pagina di decisione resta.
        self.assertIn(f"{SITE}/gestione-anomalie/mail-action/tok-sintetico/", html)

    @override_settings(LDAP_ENABLED=False)
    def test_senza_accesso_windows_link_diretto_alla_pagina(self):
        _subject, text, html = self._azione()
        self.assertIn(DIRECT_LINK, html)
        self.assertNotIn("/login/windows/", html + text)

    @override_settings(LDAP_ENABLED=True)
    def test_sso_nascosto_dal_login_usa_link_diretto(self):
        from core.models import SiteConfig
        SiteConfig.objects.update_or_create(chiave="login_sso_visibile", defaults={"valore": "0"})
        _subject, _text, html = self._azione()
        self.assertIn(DIRECT_LINK, html)
        self.assertNotIn("/login/windows/", html)

    @override_settings(LDAP_ENABLED=True, SITE_URL="")
    def test_senza_site_url_niente_pulsante(self):
        _subject, _text, html = build_anomalie_action_email(
            recipient_email="cc@example.local", recipient_display="Capo Commessa",
            op_id="OP-LINK-1", op_nominativo="", anomalie_rows=_rows(), action="aggiorna_avanzamento",
            token_str="tok-sintetico", expires_at=None, site_url="",
        )
        self.assertNotIn("Apri nel portale", html)

    @override_settings(LDAP_ENABLED=True)
    def test_mail_riepilogo_modifiche_ha_pulsante_portale(self):
        with patch("automazioni.services._resolve_op_recipients", return_value=[]), \
             patch("anomalie.mail_action_service._resolve_segnalante_email", return_value=("op@example.local", "Op")), \
             patch("anomalie.mail_action_service._resolve_lista_fissa_conferma", return_value=[]), \
             patch("anomalie.mail_action_service._fetch_pn_for_ops", return_value={}):
            inviata = send_anomalie_update_confirmation(
                op_id="OP-LINK-1", op_nominativo="", anomalie_rows=_rows(),
                updates_summary=[{"id": 1, "seriale": "SN-1", "avanzamento": "Rilavorazione"}],
            )
        self.assertTrue(inviata)
        msg = mail.outbox[-1]
        html = msg.alternatives[0][0]
        self.assertIn("Apri l'OP nel portale", html)
        self.assertIn(SSO_LINK, html)
        self.assertIn(SSO_LINK, msg.body)
