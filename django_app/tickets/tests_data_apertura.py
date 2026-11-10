"""«Aperto il» nel Nuovo ticket (anche retroattivo) e conferma di inserimento. Solo dati sintetici."""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Profile, UserOnboarding
from tickets.models import Ticket

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DataAperturaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="syn.data.utente", first_name="Uten", last_name="Te")
        Profile.objects.create(user=self.user, legacy_user_id=992001)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)

    def _payload(self, **extra):
        data = {
            "tipo": "IT", "incide_sicurezza": "0", "categoria": "PC", "priorita": "MEDIA",
            "titolo": "Mouse sintetico rotto", "descrizione": "Descrizione sintetica",
            "asset_descrizione_libera": "PC sintetico",
        }
        data.update(extra)
        return data

    def _post(self, payload):
        with patch("tickets.views._can_open_tickets", return_value=True), \
             patch("tickets.views._can_manage_tickets", return_value=False), \
             patch("tickets.views._get_assets_for_select", return_value=[]), \
             patch("tickets.views._push_ticket_to_sharepoint", return_value=None):
            return self.client.post(reverse("tickets:nuovo") + "?tipo=IT", payload)

    def test_il_form_ha_il_campo_aperto_il(self):
        with patch("tickets.views._can_open_tickets", return_value=True), \
             patch("tickets.views._get_assets_for_select", return_value=[]):
            page = self.client.get(reverse("tickets:nuovo") + "?tipo=IT")
        self.assertContains(page, 'name="aperto_il"')
        self.assertContains(page, "Aperto il")

    def test_vuoto_vale_adesso_e_la_scheda_conferma(self):
        prima = timezone.now()
        response = self._post(self._payload())
        ticket = Ticket.objects.get()
        self.assertRedirects(response, reverse("tickets:detail", args=[ticket.pk]) + "?creato=1",
                             fetch_redirect_response=False)
        self.assertGreaterEqual(ticket.created_at, prima)
        detail = self.client.get(response.url)
        self.assertContains(detail, f"Ticket {ticket.numero_ticket} inviato")
        self.assertContains(detail, "Vai a I miei ticket")
        self.assertContains(detail, reverse("tickets:dashboard"))
        # Senza ?creato=1 il riquadro non c'è (non va ripetuto a ogni visita)
        self.assertNotContains(self.client.get(reverse("tickets:detail", args=[ticket.pk])),
                               "Vai a I miei ticket")

    def test_data_retroattiva_diventa_la_data_di_apertura(self):
        passato = (timezone.localtime() - timedelta(days=3, hours=2)).strftime("%Y-%m-%dT%H:%M")
        response = self._post(self._payload(aperto_il=passato))
        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get()
        self.assertEqual(timezone.localtime(ticket.created_at).strftime("%Y-%m-%dT%H:%M"), passato)
        self.assertEqual(ticket.stato_log.count(), 0)

    def test_data_futura_o_non_valida_non_crea_e_conserva_il_campo(self):
        futuro = (timezone.localtime() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        for valore, messaggio in ((futuro, "non può essere futura"), ("2026-13-45T10:00", "non è valida")):
            with self.subTest(valore=valore):
                response = self._post(self._payload(aperto_il=valore))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, messaggio)
                self.assertContains(response, f'value="{valore}"')
                self.assertEqual(Ticket.objects.count(), 0)
