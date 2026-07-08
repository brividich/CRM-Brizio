"""Test dei blocchi-contenuto email riusabili di core.email_utils.

Questi helper producono frammenti HTML email-safe (solo tabelle + inline style)
da passare a send_hub_mail(..., body_html_fragment=...). Verifichiamo che:
- i blocchi attesi siano presenti,
- il contenuto utente sia sempre escapato (niente HTML injection),
- lo stile sia inline (niente <style>/CSS esterno, per compatibilità client email).
"""
from django.test import SimpleTestCase

from core.email_utils import (
    email_badge,
    email_cta,
    email_facts_table,
    email_item_cards,
)


class EmailBadgeTests(SimpleTestCase):
    def test_rende_span_con_testo(self):
        html = email_badge("Scaduto", tone="danger")
        self.assertIn("<span", html)
        self.assertIn("Scaduto", html)
        self.assertIn("style=", html)  # inline style
        self.assertNotIn("<style", html)  # niente CSS esterno

    def test_toni_diversi_colori_diversi(self):
        ok = email_badge("OK", tone="success")
        ko = email_badge("KO", tone="danger")
        self.assertNotEqual(ok, ko)

    def test_tono_sconosciuto_non_esplode(self):
        html = email_badge("Boh", tone="inesistente")
        self.assertIn("Boh", html)
        self.assertIn("<span", html)

    def test_escape_del_testo(self):
        html = email_badge("<script>alert(1)</script>", tone="info")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class EmailFactsTableTests(SimpleTestCase):
    def test_rende_etichetta_e_valore(self):
        html = email_facts_table([("Codice", "SPEC-001"), ("Cliente", "ACME")])
        self.assertIn("<table", html)
        self.assertIn("Codice", html)
        self.assertIn("SPEC-001", html)
        self.assertIn("Cliente", html)
        self.assertIn("ACME", html)

    def test_escape_dei_valori(self):
        html = email_facts_table([("X", "<b>grassetto</b>")])
        self.assertNotIn("<b>grassetto</b>", html)
        self.assertIn("&lt;b&gt;grassetto&lt;/b&gt;", html)

    def test_righe_vuote_stringa_vuota(self):
        self.assertEqual(email_facts_table([]), "")

    def test_solo_inline_style(self):
        html = email_facts_table([("A", "B")])
        self.assertIn("style=", html)
        self.assertNotIn("<style", html)


class EmailCtaTests(SimpleTestCase):
    def test_ha_link_ed_etichetta(self):
        html = email_cta("Apri la scheda", "https://hub.example/x/1/")
        self.assertIn("<a", html)
        self.assertIn('href="https://hub.example/x/1/"', html)
        self.assertIn("Apri la scheda", html)

    def test_url_escapato_negli_attributi(self):
        html = email_cta("Vai", 'https://hub.example/?q="onmouseover=alert(1)')
        self.assertNotIn('"onmouseover=alert(1)', html)
        self.assertIn("&quot;", html)

    def test_nota_opzionale(self):
        html = email_cta("Vai", "https://hub.example/", note="Link personale e tracciato.")
        self.assertIn("Link personale e tracciato.", html)


class EmailItemCardsTests(SimpleTestCase):
    def test_rende_campi_card(self):
        html = email_item_cards([
            {"title": "Visita medica", "subtitle": "Mario Rossi",
             "badge": ("Scaduta", "danger"), "note": "Esito: idoneo"},
        ])
        self.assertIn("<table", html)
        self.assertIn("Visita medica", html)
        self.assertIn("Mario Rossi", html)
        self.assertIn("Scaduta", html)
        self.assertIn("Esito: idoneo", html)

    def test_escape_del_titolo(self):
        html = email_item_cards([{"title": "<img src=x onerror=alert(1)>"}])
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img", html)

    def test_lista_vuota_stringa_vuota(self):
        self.assertEqual(email_item_cards([]), "")

    def test_badge_come_stringa_semplice(self):
        html = email_item_cards([{"title": "T", "badge": "In scadenza"}])
        self.assertIn("In scadenza", html)
        self.assertIn("<span", html)  # badge stringa -> pill neutra
