"""Arricchimento email gestione_specifiche allo standard grafico «anomalie».

Verifica che i mittenti (nuova specifica + scadenze) producano:
- un corpo HTML instradato nel frame HUB (send_hub_mail) con tabella fatti + CTA;
- un `text/plain` alternativo pulito (niente tag HTML grezzi — bug storico risolto).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from gestione_specifiche.models import MOD133, NotificaConfig, Specifica
from gestione_specifiche.notifiche_gs import notifica_nuova_specifica
from gestione_specifiche.scadenze import invia_reminder_mod133

User = get_user_model()


def _html_alt(email) -> str:
    for content, mimetype in getattr(email, "alternatives", []):
        if mimetype == "text/html":
            return content
    return ""


class NuovaSpecificaEmailTests(TestCase):
    def setUp(self):
        self.inc = User.objects.create_user("inc", email="inc@x.it", password="x")
        cfg = NotificaConfig.get_config()
        cfg.email_attiva = True
        cfg.save()

    def test_html_instradato_nel_frame_con_facts_e_cta(self):
        spec = Specifica.objects.create(
            codice="SP-RICH", titolo="Titolo X", cliente="ACME", incaricato=self.inc,
        )
        notifica_nuova_specifica(spec)
        self.assertGreaterEqual(len(mail.outbox), 1)
        html = _html_alt(mail.outbox[0])
        self.assertIn("novicrmhub.png", html)   # instradata nel frame HUB (send_hub_mail)
        self.assertIn("SP-RICH", html)
        self.assertIn("ACME", html)             # cliente nella tabella fatti
        self.assertIn("<table", html)
        self.assertIn("<a", html)               # CTA «apri la scheda»

    def test_plain_text_senza_tag_html(self):
        spec = Specifica.objects.create(codice="SP-PLAIN", titolo="T", incaricato=self.inc)
        notifica_nuova_specifica(spec)
        self.assertGreaterEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        self.assertNotIn("<", body)             # niente HTML grezzo nel corpo testo
        self.assertIn("SP-PLAIN", body)         # ma il codice resta leggibile


class ScadenzeEmailTests(TestCase):
    def setUp(self):
        self.dm = User.objects.create_user("dm", email="dm@x.it", password="x")

    def _avvia(self, codice="SP-SC"):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.dm)
        spec.save()
        return spec, MOD133.objects.get(specifica=spec)

    def test_reminder_email_ha_facts_e_cta_e_plain_pulito(self):
        spec, mod = self._avvia("SP-REM")
        invia_reminder_mod133(now=mod.timer_anchor + timedelta(days=8))
        self.assertGreaterEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        html = _html_alt(email)
        self.assertIn("SP-REM", html)
        self.assertIn("non preso in carico", html)  # tabella fatti (situazione)
        self.assertIn("<a", html)                    # CTA verso la scheda
        self.assertNotIn("<", email.body)            # plain pulito
