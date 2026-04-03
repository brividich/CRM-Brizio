from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetCategory
from core.upload_mime import UploadMimeValidationError
from tickets.models import PrioritaTicket, Ticket, TicketAllegato, TicketCommento, TicketIntervento, TicketStatoLog
from tickets.views import _build_ticket_activity_feed, _get_assets_for_select


def _test_tmp_root() -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp_py"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _reset_test_dir(name: str) -> Path:
    path = _test_tmp_root() / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


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
class TicketDashboardTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="dashboard-ticket-user",
            password="pass12345",
            email="dashboard-ticket@example.com",
        )
        self.client.force_login(self.user)

    def test_dashboard_shows_related_asset_column(self):
        asset = Asset.objects.create(
            asset_tag="IT-009999",
            name="Notebook Ufficio Acquisti",
            asset_type=Asset.TYPE_NOTEBOOK,
            status=Asset.STATUS_IN_USE,
        )
        Ticket.objects.create(
            tipo="IT",
            titolo="Problema stampante virtuale",
            descrizione="Descrizione ticket con asset",
            categoria="PC",
            priorita=PrioritaTicket.MEDIA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
            asset=asset,
        )
        Ticket.objects.create(
            tipo="MAN",
            titolo="Verifica compressore",
            descrizione="Descrizione ticket con asset libero",
            categoria="CNC",
            priorita=PrioritaTicket.ALTA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
            asset_descrizione_libera="Compressore linea 2",
        )

        response = self.client.get(reverse("tickets:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Asset interessato")
        self.assertContains(response, "Notebook Ufficio Acquisti")
        self.assertContains(response, "IT-009999")
        self.assertContains(response, "Compressore linea 2")


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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketAttachmentPrivacyTests(TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="ticket-attachment-user",
            password="pass12345",
            email="ticket-attachment@example.com",
        )
        self.other_user = User.objects.create_user(
            username="ticket-attachment-other",
            password="pass12345",
            email="ticket-attachment-other@example.com",
        )
        self.ticket = Ticket.objects.create(
            tipo="IT",
            titolo="Ticket Allegato",
            descrizione="Verifica allegati privati",
            categoria="PC",
            priorita=PrioritaTicket.MEDIA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
        )

    def test_api_upload_stores_attachment_privately_and_returns_protected_url(self):
        test_dir = _reset_test_dir("tickets_attachment_upload")
        media_root = test_dir / "media"
        private_root = test_dir / "media_private"
        media_root.mkdir(parents=True, exist_ok=True)
        private_root.mkdir(parents=True, exist_ok=True)
        try:
            with override_settings(MEDIA_ROOT=media_root, TICKETS_PRIVATE_ROOT=private_root):
                self.client.force_login(self.user)
                with patch("tickets.views.validate_extension_and_mime", return_value="text/plain"):
                    response = self.client.post(
                        reverse("tickets:api_allegato"),
                        {
                            "ticket_id": str(self.ticket.pk),
                            "file": SimpleUploadedFile("diagnosi.txt", b"contenuto allegato", content_type="text/plain"),
                        },
                    )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                allegato = TicketAllegato.objects.get(pk=payload["allegato_id"])

                self.assertEqual(payload["url"], reverse("tickets:download_allegato", args=[allegato.pk]))
                self.assertTrue((private_root / allegato.file.name).exists())
                self.assertFalse((media_root / allegato.file.name).exists())
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_api_upload_rejects_spoofed_extension_when_mime_validation_fails(self):
        self.client.force_login(self.user)
        with patch(
            "tickets.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("file.pdf: tipo MIME non consentito (application/x-msdownload)."),
        ):
            response = self.client.post(
                reverse("tickets:api_allegato"),
                {
                    "ticket_id": str(self.ticket.pk),
                    "file": SimpleUploadedFile("file.pdf", b"MZ...", content_type="application/pdf"),
                },
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("tipo MIME non consentito", payload["error"])

    def test_api_upload_fails_closed_when_mime_engine_is_unavailable(self):
        self.client.force_login(self.user)
        with patch(
            "tickets.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("Validazione MIME non disponibile sul server. Upload bloccato."),
        ):
            response = self.client.post(
                reverse("tickets:api_allegato"),
                {
                    "ticket_id": str(self.ticket.pk),
                    "file": SimpleUploadedFile("file.pdf", b"%PDF-1.4", content_type="application/pdf"),
                },
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("Validazione MIME non disponibile", payload["error"])

    def test_download_view_serves_legacy_media_file_only_to_authorized_users(self):
        test_dir = _reset_test_dir("tickets_attachment_legacy_download")
        media_root = test_dir / "media"
        private_root = test_dir / "media_private"
        media_root.mkdir(parents=True, exist_ok=True)
        private_root.mkdir(parents=True, exist_ok=True)
        legacy_relative = Path("tickets/allegati/2026/03/legacy.txt")
        legacy_path = media_root / legacy_relative
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_bytes = b"legacy attachment bytes"
        legacy_path.write_bytes(legacy_bytes)

        try:
            with override_settings(MEDIA_ROOT=media_root, TICKETS_PRIVATE_ROOT=private_root):
                allegato = TicketAllegato.objects.create(
                    ticket=self.ticket,
                    file=str(legacy_relative).replace("\\", "/"),
                    nome_originale="legacy.txt",
                    tipo_mime="text/plain",
                    uploaded_by_nome=self.user.username,
                )

                self.client.force_login(self.user)
                ok_response = self.client.get(reverse("tickets:download_allegato", args=[allegato.pk]))
                self.assertEqual(ok_response.status_code, 200)
                self.assertEqual(b"".join(ok_response.streaming_content), legacy_bytes)

                self.client.force_login(self.other_user)
                forbidden_response = self.client.get(reverse("tickets:download_allegato", args=[allegato.pk]))
                self.assertEqual(forbidden_response.status_code, 403)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)
