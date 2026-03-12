from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, AssetCategory
from tickets.models import PrioritaTicket, Ticket, TicketCommento
from tickets.views import _get_assets_for_select


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketNuovoSafetyTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="ticket-user",
            password="pass12345",
            email="ticket@example.com",
        )
        self.client.force_login(self.user)

    def _base_payload(self, tipo: str, sicurezza: str = "0") -> dict:
        return {
            "tipo": tipo,
            "incide_sicurezza": sicurezza,
            "categoria": "PC" if tipo == "IT" else "CNC",
            "priorita": "MEDIA",
            "titolo": f"Ticket {tipo}",
            "descrizione": "Descrizione di test",
        }

    def test_get_form_shows_blocking_safety_section(self):
        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._get_assets_for_select", return_value=[]),
        ):
            response = self.client.get(reverse("tickets:nuovo"), {"tipo": "IT"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Repair Time")
        self.assertContains(response, "Seleziona una risposta prima di inviare il ticket.")

    def test_post_requires_safety_answer(self):
        payload = self._base_payload("IT")
        payload.pop("incide_sicurezza")

        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._legacy_identity", return_value=("Test User", "ticket@example.com", None)),
        ):
            response = self.client.post(reverse("tickets:nuovo"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indica se il problema incide sulla sicurezza sul lavoro")
        self.assertEqual(Ticket.objects.count(), 0)

    def test_post_creates_standard_it_ticket_when_security_is_yes(self):
        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._legacy_identity", return_value=("Test User", "ticket@example.com", None)),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        ):
            response = self.client.post(reverse("tickets:nuovo"), self._base_payload("IT", sicurezza="1"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 1)
        ticket = Ticket.objects.get()
        self.assertTrue(ticket.incide_sicurezza)
        self.assertEqual(ticket.priorita, PrioritaTicket.URGENTE)

    def test_post_creates_standard_man_ticket_when_security_is_yes(self):
        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._legacy_identity", return_value=("Test User", "ticket@example.com", None)),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        ):
            response = self.client.post(reverse("tickets:nuovo"), self._base_payload("MAN", sicurezza="1"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 1)
        ticket = Ticket.objects.get()
        self.assertTrue(ticket.incide_sicurezza)
        self.assertEqual(ticket.priorita, PrioritaTicket.URGENTE)

    def test_post_creates_standard_ticket_when_security_is_no(self):
        with (
            patch("tickets.views._can_open_tickets", return_value=True),
            patch("tickets.views._get_assets_for_select", return_value=[]),
            patch("tickets.views._legacy_identity", return_value=("Test User", "ticket@example.com", None)),
            patch("tickets.views._push_ticket_to_sharepoint", return_value=None),
        ):
            response = self.client.post(reverse("tickets:nuovo"), self._base_payload("IT", sicurezza="0"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Ticket.objects.count(), 1)
        ticket = Ticket.objects.get()
        self.assertFalse(ticket.incide_sicurezza)
        self.assertEqual(ticket.tipo, "IT")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketAssetSearchDataTests(TestCase):
    def test_asset_payload_contains_extended_search_fields(self):
        category = AssetCategory.objects.create(code="server-rack", label="Server rack")
        asset = Asset.objects.create(
            asset_tag="IT-000001",
            name="Server Produzione",
            asset_type=Asset.TYPE_SERVER,
            asset_category=category,
            manufacturer="Dell",
            model="PowerEdge R740",
            serial_number="SN12345",
            reparto="CED",
            status=Asset.STATUS_IN_USE,
        )

        payload = _get_assets_for_select()

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["id"], asset.id)
        self.assertEqual(payload[0]["asset_type_label"], "Server")
        self.assertEqual(payload[0]["asset_category"], "Server rack")
        self.assertEqual(payload[0]["manufacturer"], "Dell")
        self.assertEqual(payload[0]["model"], "PowerEdge R740")
        self.assertEqual(payload[0]["serial_number"], "SN12345")
        self.assertEqual(payload[0]["reparto"], "CED")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketPdfTests(TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="pdf-ticket-user",
            password="pass12345",
            email="pdf-ticket@example.com",
        )
        self.other_user = User.objects.create_user(
            username="other-ticket-user",
            password="pass12345",
            email="other-ticket@example.com",
        )
        self.ticket = Ticket.objects.create(
            tipo="IT",
            titolo="Ticket PDF",
            descrizione="Descrizione report PDF",
            categoria="PC",
            priorita=PrioritaTicket.MEDIA,
            incide_sicurezza=False,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
        )
        TicketCommento.objects.create(
            ticket=self.ticket,
            autore_nome=self.user.username,
            autore_email=self.user.email,
            testo="Commento pubblico PDF",
            is_interno=False,
        )

    def test_ticket_pdf_returns_pdf_for_requester(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("tickets:pdf", args=[self.ticket.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 800)

    def test_ticket_pdf_forbidden_for_other_user(self):
        self.client.force_login(self.other_user)

        response = self.client.get(reverse("tickets:pdf", args=[self.ticket.pk]))

        self.assertEqual(response.status_code, 403)
