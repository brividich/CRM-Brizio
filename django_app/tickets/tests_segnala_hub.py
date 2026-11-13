"""Voce «Segnalazione NOVICROM HUB» e incolla allegati nel Nuovo ticket. Solo dati sintetici."""
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import Profile, UserOnboarding
from tickets.models import CategoriaTicket, TipoTicket

User = get_user_model()


def _render_link(path="/assenze/richiesta/"):
    request = RequestFactory().get(path)
    html = Template("{% load tickets_nav %}{% link_segnala_hub %}").render(Context({"request": request}))
    return unescape(html)  # nell'href «&» esce come «&amp;»


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SegnalaHubTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_link_con_categoria_hub_e_pagina_di_partenza(self):
        CategoriaTicket.objects.create(tipo=TipoTicket.IT, codice="SYN_HUB", etichetta="Novicrom Hub")
        url = urlparse(_render_link("/assenze/richiesta/?x=1"))
        qs = parse_qs(url.query)
        self.assertEqual(url.path, reverse("tickets:nuovo"))
        self.assertEqual(qs["tipo"], ["IT"])
        self.assertEqual(qs["categoria"], ["SYN_HUB"])
        self.assertEqual(qs["asset_libero"], ["NOVICROM HUB"])
        self.assertEqual(qs["sicurezza"], ["0"])
        self.assertIn("Pagina: /assenze/richiesta/?x=1", qs["descrizione"][0])

    def test_senza_categoria_hub_apre_ticket_it_semplice(self):
        CategoriaTicket.objects.create(tipo=TipoTicket.IT, codice="SYN_PC", etichetta="PC")
        CategoriaTicket.objects.create(tipo=TipoTicket.IT, codice="SYN_HUB_OFF", etichetta="Hub", attivo=False)
        qs = parse_qs(urlparse(_render_link()).query)
        self.assertEqual(qs["tipo"], ["IT"])
        self.assertNotIn("categoria", qs)

    def test_form_precompila_la_categoria_dal_link(self):
        user = User.objects.create_user(username="syn.hub.utente")
        Profile.objects.create(user=user, legacy_user_id=992101)
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})
        self.client.force_login(user)
        cats = [("SYN_PC", "PC"), ("SYN_HUB", "Novicrom Hub")]
        with patch("tickets.views._can_open_tickets", return_value=True), \
             patch("tickets.views._get_assets_for_select", return_value=[]), \
             patch("tickets.views.get_categorie", return_value=cats):
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=IT&categoria=SYN_HUB&asset_libero=NOVICROM+HUB&sicurezza=0")
            senza = self.client.get(reverse("tickets:nuovo") + "?tipo=IT&sicurezza=1")
        self.assertContains(page, '<option value="SYN_HUB" selected>')
        self.assertContains(page, 'id="sic-no" required checked')
        self.assertNotContains(senza, " checked>")  # il «Sì» non si preimposta mai
        self.assertContains(page, 'value="NOVICROM HUB"')
        self.assertContains(page, "incolla uno screenshot con Ctrl+V")
