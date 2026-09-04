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
from core.models import UserOnboarding
from tickets.models import (
    PrioritaTicket,
    Ticket,
    TicketAllegato,
    TicketCommento,
    TicketImpostazioni,
    TicketIntervento,
    TicketStatoLog,
    TipoTicket,
)
from tickets.views import _build_ticket_activity_feed, _get_assets_for_select


def _complete_onboarding(user) -> None:
    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={
            "completed": True,
            "skipped": False,
            "completed_at": timezone.now(),
        },
    )


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
        _complete_onboarding(self.user)
        self.client.force_login(self.user)

    def _base_payload(self, tipo: str, sicurezza: str = "0") -> dict:
        return {
            "tipo": tipo,
            "incide_sicurezza": sicurezza,
            "categoria": "PC" if tipo == "IT" else "CNC",
            "priorita": "MEDIA",
            "titolo": f"Ticket {tipo}",
            "descrizione": "Descrizione di test",
            "asset_descrizione_libera": "Asset generico di test",
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
class TicketNuovoAssetsJsonScriptTests(TestCase):
    """Verifica che il catalogo asset sia serializzato con json_script (no XSS)."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="ticket-jsonscript-user",
            password="pass12345",
            email="ticket-jsonscript@example.com",
        )
        _complete_onboarding(self.user)
        self.client.force_login(self.user)

    def test_asset_name_with_script_tag_does_not_break_out(self):
        Asset.objects.create(
            asset_tag="IT-XSS-01",
            name="</script><script>window.__xss=1</script>",
            asset_type=Asset.TYPE_PC,
            status=Asset.STATUS_IN_USE,
        )
        with patch("tickets.views._can_open_tickets", return_value=True):
            response = self.client.get(reverse("tickets:nuovo"), {"tipo": "IT"})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        # json_script escapa '<' in '<': il payload non deve comparire grezzo.
        self.assertIn('id="assets-list-data"', html)
        self.assertNotIn("</script><script>window.__xss=1</script>", html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketCopilotaTests(TestCase):
    """Copilota triage AI (Ondata 3.1): proposta read-only, validata, fail-safe."""

    CATEGORIE = [("PC", "PC / Notebook"), ("RETE", "Rete / Connettività")]
    GESTORI = [
        {"nome": "Mario Rossi", "email": "mario@example.com"},
        {"nome": "Lucia Bianchi", "email": "lucia@example.com"},
    ]

    def setUp(self):
        super().setUp()
        import json as _json
        self._json = _json
        self.user = get_user_model().objects.create_user(
            username="copilota-user", password="pass12345", email="copilota@example.com",
        )
        _complete_onboarding(self.user)
        self.client.force_login(self.user)
        TicketImpostazioni.objects.create(tipo=TipoTicket.IT, team_gestori=self.GESTORI)

    # --- unit test su proponi_triage (niente DB/HTTP) ---

    def _proponi(self, raw_ai: str):
        from tickets.ai_copilota import proponi_triage
        with patch("tickets.ai_copilota._chiama_ai", return_value=raw_ai):
            return proponi_triage(
                titolo="PC non si accende", descrizione="Schermo nero dopo aggiornamento",
                tipo="IT", categorie=self.CATEGORIE, gestori=self.GESTORI,
            )

    def test_proponi_triage_valid(self):
        raw = self._json.dumps({
            "categoria": "PC", "priorita": "alta", "incide_sicurezza": False,
            "assegnatario_email": "mario@example.com",
            "bozza_risoluzione": "Verificare alimentatore e RAM.",
            "motivazione": "Hardware PC, impatto su un utente.",
        })
        p = self._proponi(raw)
        self.assertTrue(p["proposto"])
        self.assertTrue(p["ai_disponibile"])
        self.assertEqual(p["categoria"], "PC")
        self.assertEqual(p["priorita"], "ALTA")
        self.assertFalse(p["incide_sicurezza"])
        self.assertEqual(p["assegnatario"], {"nome": "Mario Rossi", "email": "mario@example.com"})
        self.assertIn("alimentatore", p["bozza_risoluzione"])

    def test_proponi_triage_rejects_out_of_list(self):
        raw = self._json.dumps({
            "categoria": "INVENTATA", "priorita": "SUPER",
            "assegnatario_email": "estraneo@example.com",
        })
        p = self._proponi(raw)
        self.assertEqual(p["categoria"], "")        # categoria fuori lista scartata
        self.assertEqual(p["priorita"], "")          # priorita fuori enum scartata
        self.assertIsNone(p["assegnatario"])         # assegnatario non tra i gestori

    def test_proponi_triage_security_forces_urgente(self):
        raw = self._json.dumps({
            "categoria": "PC", "priorita": "BASSA", "incide_sicurezza": True,
        })
        p = self._proponi(raw)
        self.assertTrue(p["incide_sicurezza"])
        self.assertEqual(p["priorita"], PrioritaTicket.URGENTE)

    def test_proponi_triage_ai_offline_failsafe(self):
        p = self._proponi("")  # AI non disponibile
        self.assertTrue(p["proposto"])
        self.assertFalse(p["ai_disponibile"])
        self.assertEqual(p["categoria"], "")
        self.assertEqual(p["priorita"], "")
        self.assertIsNone(p["assegnatario"])

    # --- endpoint ---

    def test_api_copilota_requires_gestore(self):
        # utente non gestore (nessun admin, nessuna acl_gestione) -> 403
        response = self.client.post(
            reverse("tickets:api_copilota"),
            data=self._json.dumps({"tipo": "IT", "titolo": "x", "descrizione": "y"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_api_copilota_happy_path(self):
        raw = self._json.dumps({
            "categoria": "PC", "priorita": "MEDIA",
            "assegnatario_email": "lucia@example.com",
            "bozza_risoluzione": "Controllo connettività.",
        })
        with (
            patch("tickets.views._can_manage_tickets", return_value=True),
            patch("tickets.ai_copilota._chiama_ai", return_value=raw),
        ):
            response = self.client.post(
                reverse("tickets:api_copilota"),
                data=self._json.dumps({
                    "tipo": "IT", "titolo": "Rete lenta",
                    "descrizione": "La rete del reparto e' lentissima",
                }),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        prop = data["proposta"]
        self.assertEqual(prop["categoria"], "PC")
        self.assertEqual(prop["priorita"], "MEDIA")
        self.assertEqual(prop["assegnatario"]["email"], "lucia@example.com")

    def test_gestione_detail_shows_copilota_button(self):
        ticket = Ticket.objects.create(
            tipo=TipoTicket.IT, titolo="PC lento", descrizione="Tutto lento",
            categoria="PC", richiedente_nome="Tester",
        )
        with patch("tickets.views._can_manage_tickets", return_value=True):
            response = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk]))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('id="copilota-run"', html)
        self.assertIn('id="copilota-card"', html)
        self.assertIn(reverse("tickets:api_copilota"), html)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketDashboardTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="dashboard-ticket-user",
            password="pass12345",
            email="dashboard-ticket@example.com",
        )
        _complete_onboarding(self.user)
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
        _complete_onboarding(self.user)
        _complete_onboarding(self.other_user)
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
        _complete_onboarding(self.user)
        _complete_onboarding(self.other_user)
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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketMaintenanceRegisterTests(TestCase):
    """Test per l'integrazione dei ticket MAN nel registro manutenzione asset (PATCH 21E)."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="test-user",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )
        _complete_onboarding(self.user)

        # Crea asset di test
        self.asset_category = AssetCategory.objects.create(
            code="CNC",
            label="Macchine CNC",
        )
        self.asset = Asset.objects.create(
            name="Macchina CNC Test",
            asset_tag="CNC-001",
            asset_type="CNC",
            asset_category=self.asset_category,
            status="IN_USE",
        )
        TicketImpostazioni.objects.create(tipo="MAN", acl_gestione=["test-user"])

    def test_new_man_ticket_form_has_no_maintenance_register_checkbox(self):
        """Il checkbox è ora nella gestione tecnica (gestione_detail), non nel form del richiedente."""
        self.client.force_login(self.user)

        response = self.client.get(reverse("tickets:nuovo") + "?tipo=MAN")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="include_in_maintenance_register"')

    def test_new_man_ticket_has_include_in_maintenance_register_true_by_default(self):
        """Verifica che un nuovo ticket MAN abbia include_in_maintenance_register=True di default."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tickets:nuovo") + "?tipo=MAN",
            {
                "tipo": "MAN",
                "titolo": "Test ticket MAN",
                "descrizione": "Descrizione test",
                "categoria": "MECCANICA",
                "priorita": "MEDIA",
                "incide_sicurezza": "0",
                "asset_id": str(self.asset.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(titolo="Test ticket MAN")
        self.assertTrue(ticket.include_in_maintenance_register)

    def test_it_ticket_not_included_in_maintenance_register(self):
        """Verifica che i ticket IT non vengano inclusi nel registro manutenzione anche se flag True."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tickets:nuovo") + "?tipo=IT",
            {
                "tipo": "IT",
                "titolo": "Test ticket IT",
                "descrizione": "Descrizione test",
                "categoria": "PC",
                "priorita": "MEDIA",
                "incide_sicurezza": "0",
                "asset_id": str(self.asset.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(titolo="Test ticket IT")
        # I ticket IT non dovrebbero comparire nel registro manutenzione
        from assets.services.maintenance_register import ticket_to_maintenance_register_row
        row = ticket_to_maintenance_register_row(ticket)
        self.assertIsNone(row)

    def test_man_ticket_without_asset_not_included_in_maintenance_register(self):
        """Verifica che un ticket MAN senza asset non venga incluso nel registro manutenzione."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tickets:nuovo") + "?tipo=MAN",
            {
                "tipo": "MAN",
                "titolo": "Test ticket MAN senza asset",
                "descrizione": "Descrizione test",
                "categoria": "MECCANICA",
                "priorita": "MEDIA",
                "incide_sicurezza": "0",
                "asset_descrizione_libera": "Asset generico",
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(titolo="Test ticket MAN senza asset")
        self.assertTrue(ticket.include_in_maintenance_register)

        # Non dovrebbe comparire nel registro manutenzione perché non ha asset
        from assets.services.maintenance_register import ticket_to_maintenance_register_row
        row = ticket_to_maintenance_register_row(ticket)
        self.assertIsNone(row)

    def test_man_ticket_with_asset_and_flag_true_appears_in_maintenance_register(self):
        """Verifica che un ticket MAN con asset e flag True compaia come riga manutenzione."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tickets:nuovo") + "?tipo=MAN",
            {
                "tipo": "MAN",
                "titolo": "Test ticket MAN con asset",
                "descrizione": "Descrizione test",
                "categoria": "MECCANICA",
                "priorita": "MEDIA",
                "incide_sicurezza": "0",
                "asset_id": str(self.asset.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(titolo="Test ticket MAN con asset")
        self.assertTrue(ticket.include_in_maintenance_register)

        # Dovrebbe comparire nel registro manutenzione
        from assets.services.maintenance_register import ticket_to_maintenance_register_row
        row = ticket_to_maintenance_register_row(ticket)
        self.assertIsNotNone(row)
        self.assertEqual(row["source"], "TICKET")
        self.assertEqual(row["maintenance_type"], "Straordinaria")
        self.assertEqual(row["ticket"], ticket)
        self.assertEqual(row["ticket_number"], ticket.numero_ticket)

    def test_man_ticket_with_asset_and_flag_false_not_in_maintenance_register(self):
        """Il tecnico può escludere dal registro manutenzione un ticket MAN via api_ticket_analytics."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("tickets:nuovo") + "?tipo=MAN",
            {
                "tipo": "MAN",
                "titolo": "Test ticket MAN escluso",
                "descrizione": "Descrizione test",
                "categoria": "MECCANICA",
                "priorita": "MEDIA",
                "incide_sicurezza": "0",
                "asset_id": str(self.asset.id),
            },
        )

        self.assertEqual(response.status_code, 302)
        ticket = Ticket.objects.get(titolo="Test ticket MAN escluso")
        self.assertTrue(ticket.include_in_maintenance_register)

        import json
        analytics_response = self.client.post(
            reverse("tickets:api_analytics"),
            data=json.dumps({
                "ticket_id": ticket.pk,
                "include_in_maintenance_register": False,
            }),
            content_type="application/json",
        )
        self.assertEqual(analytics_response.status_code, 200)
        ticket.refresh_from_db()
        self.assertFalse(ticket.include_in_maintenance_register)

        # Non dovrebbe comparire nel registro manutenzione
        from assets.services.maintenance_register import ticket_to_maintenance_register_row
        row = ticket_to_maintenance_register_row(ticket)
        self.assertIsNone(row)

    def test_collect_asset_maintenance_register_includes_tickets(self):
        """Verifica che collect_asset_maintenance_register includa i ticket MAN."""
        from assets.services.maintenance_register import collect_asset_maintenance_register

        # Crea ticket MAN incluso
        ticket_included = Ticket.objects.create(
            tipo="MAN",
            titolo="Ticket incluso",
            descrizione="Descrizione",
            categoria="MECCANICA",
            priorita="MEDIA",
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        # Crea ticket MAN escluso
        ticket_excluded = Ticket.objects.create(
            tipo="MAN",
            titolo="Ticket escluso",
            descrizione="Descrizione",
            categoria="MECCANICA",
            priorita="MEDIA",
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=False,
        )

        # Crea ticket IT (non dovrebbe comparire)
        ticket_it = Ticket.objects.create(
            tipo="IT",
            titolo="Ticket IT",
            descrizione="Descrizione",
            categoria="PC",
            priorita="MEDIA",
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        # Recupera il registro manutenzione
        register = collect_asset_maintenance_register(self.asset, include_tickets=True)

        # Verifica che solo il ticket MAN incluso sia presente
        ticket_rows = [row for row in register if row["source"] == "TICKET"]
        self.assertEqual(len(ticket_rows), 1)
        self.assertEqual(ticket_rows[0]["ticket"], ticket_included)
        self.assertEqual(ticket_rows[0]["ticket_number"], ticket_included.numero_ticket)
        # Verifica che il ticket MAN escluso e il ticket IT non siano presenti
        ticket_ids = [row["ticket"].id for row in ticket_rows]
        self.assertNotIn(ticket_excluded.id, ticket_ids)
        self.assertNotIn(ticket_it.id, ticket_ids)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketDownloadAuditTests(TestCase):
    """Verifica che i download di allegati siano tracciati in AuditLog (Patch 21H)."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="ticket-audit-user",
            password="pass12345",
            email="ticket-audit@example.com",
        )
        self.other_user = User.objects.create_user(
            username="ticket-audit-other",
            password="pass12345",
            email="ticket-audit-other@example.com",
        )
        _complete_onboarding(self.user)
        _complete_onboarding(self.other_user)
        self.ticket = Ticket.objects.create(
            tipo="IT",
            titolo="Ticket Audit",
            descrizione="Audit download allegati",
            categoria="PC",
            priorita=PrioritaTicket.MEDIA,
            richiedente_nome=self.user.username,
            richiedente_email=self.user.email,
        )

    def _make_attachment(self, media_root: Path):
        rel = Path("tickets/allegati/2026/05/audit.txt")
        full = media_root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(b"audit content")
        return TicketAllegato.objects.create(
            ticket=self.ticket,
            file=str(rel).replace("\\", "/"),
            nome_originale="audit.txt",
            tipo_mime="text/plain",
            uploaded_by_nome=self.user.username,
        )

    def test_authorized_download_creates_success_audit(self):
        from core.models import AuditLog

        test_dir = _reset_test_dir("tickets_audit_success")
        media_root = test_dir / "media"
        private_root = test_dir / "media_private"
        media_root.mkdir(parents=True, exist_ok=True)
        private_root.mkdir(parents=True, exist_ok=True)
        try:
            with override_settings(MEDIA_ROOT=media_root, TICKETS_PRIVATE_ROOT=private_root):
                allegato = self._make_attachment(media_root)
                self.client.force_login(self.user)
                # Conta solo le righe di QUESTA azione: il totale globale e' inquinabile
                # da scritture estranee alla richiesta (es. l'auto_insert del singleton
                # twofa.TwoFactorPolicy, creato pigramente alla prima richiesta).
                audit_download = AuditLog.objects.filter(
                    azione="download_allegato", modulo="tickets",
                )
                before = audit_download.count()
                response = self.client.get(reverse("tickets:download_allegato", args=[allegato.pk]))
                self.assertEqual(response.status_code, 200)
                created = audit_download.order_by("-id").first()
                self.assertIsNotNone(created)
                self.assertEqual(audit_download.count(), before + 1)
                payload = created.dettaglio or {}
                self.assertEqual(payload.get("esito"), "success")
                self.assertEqual(payload.get("allegato_id"), allegato.id)
                self.assertEqual(payload.get("ticket_id"), self.ticket.id)
                # Nessun path fisico, token o contenuto file nel payload
                serialized = repr(payload)
                self.assertNotIn(str(media_root), serialized)
                self.assertNotIn(str(private_root), serialized)
                self.assertNotIn("audit content", serialized)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)

    def test_denied_download_audits_without_sensitive_details(self):
        from core.models import AuditLog

        test_dir = _reset_test_dir("tickets_audit_denied")
        media_root = test_dir / "media"
        private_root = test_dir / "media_private"
        media_root.mkdir(parents=True, exist_ok=True)
        private_root.mkdir(parents=True, exist_ok=True)
        try:
            with override_settings(MEDIA_ROOT=media_root, TICKETS_PRIVATE_ROOT=private_root):
                allegato = self._make_attachment(media_root)
                self.client.force_login(self.other_user)
                response = self.client.get(reverse("tickets:download_allegato", args=[allegato.pk]))
                self.assertEqual(response.status_code, 403)
                created = AuditLog.objects.filter(
                    azione="download_allegato", modulo="tickets",
                ).order_by("-id").first()
                self.assertIsNotNone(created)
                payload = created.dettaglio or {}
                self.assertEqual(payload.get("esito"), "denied")
                self.assertEqual(payload.get("motivo"), "permission_denied")
                serialized = repr(payload)
                self.assertNotIn(str(media_root), serialized)
                self.assertNotIn(str(private_root), serialized)
                self.assertNotIn("audit content", serialized)
                # Nessun nome file fisico esposto su denied
                self.assertNotIn("audit.txt", serialized)
        finally:
            shutil.rmtree(test_dir, ignore_errors=True)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketApiObjectLevelAuthTests(TestCase):
    """SEC-AUDIT-004: le API di gestione interventi/componenti/workorder
    devono verificare l'accesso object-level allo specifico ticket collegato,
    non solo che l'utente sia gestore di un tipo qualsiasi.

    Scenario: ``man-manager`` è gestore solo dei ticket MAN. Il decoratore
    ``_tickets_gestione_required`` lo lascia entrare in tutte le API; il
    guard object-level deve negargli l'accesso ai ticket IT.
    """

    def setUp(self):
        super().setUp()
        from tickets.models import TicketComponenteSostituito, TicketImpostazioni

        self.man_manager = get_user_model().objects.create_user(
            username="man-manager",
            email="man@example.com",
            first_name="Man",
            last_name="Manager",
        )
        _complete_onboarding(self.man_manager)
        TicketImpostazioni.objects.create(tipo="MAN", acl_gestione=["man-manager"])
        TicketImpostazioni.objects.create(tipo="IT", acl_gestione=["it-manager"])

        self.category = AssetCategory.objects.create(code="CNC", label="Macchine CNC")
        self.asset = Asset.objects.create(
            name="CNC Test",
            asset_tag="CNC-001",
            asset_type="CNC",
            asset_category=self.category,
            status="IN_USE",
        )
        self.man_ticket = Ticket.objects.create(
            tipo="MAN", titolo="MAN ticket", descrizione="x",
            categoria="MECCANICA", priorita="MEDIA", asset=self.asset,
            richiedente_nome="R", richiedente_email="r@example.com",
        )
        self.it_ticket = Ticket.objects.create(
            tipo="IT", titolo="IT ticket", descrizione="x",
            categoria="PC", priorita="MEDIA", asset=self.asset,
            richiedente_nome="R", richiedente_email="r@example.com",
        )
        self.man_interv = TicketIntervento.objects.create(
            ticket=self.man_ticket, tecnico_nome="T",
            data_inizio=timezone.now(), esito="IN_CORSO",
        )
        self.it_interv = TicketIntervento.objects.create(
            ticket=self.it_ticket, tecnico_nome="T",
            data_inizio=timezone.now(), esito="IN_CORSO",
        )
        self.it_comp = TicketComponenteSostituito.objects.create(
            intervento=self.it_interv, nome="Cuscinetto",
        )

    def _send(self, method, urlname, payload):
        import json
        fn = getattr(self.client, method)
        return fn(
            reverse(urlname),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_authorized_manager_can_update_intervento_in_scope(self):
        """1. Il gestore MAN può modificare un intervento di un ticket MAN."""
        self.client.force_login(self.man_manager)
        resp = self._send("patch", "tickets:api_intervento",
                           {"id": self.man_interv.id, "note": "aggiornato"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("ok"))
        self.man_interv.refresh_from_db()
        self.assertEqual(self.man_interv.note, "aggiornato")

    def test_manager_forbidden_on_intervento_out_of_scope(self):
        """2. Il gestore MAN riceve 403 su un intervento di ticket IT e nulla cambia."""
        self.client.force_login(self.man_manager)
        resp = self._send("patch", "tickets:api_intervento",
                           {"id": self.it_interv.id, "note": "hack"})
        self.assertEqual(resp.status_code, 403)
        self.it_interv.refresh_from_db()
        self.assertNotEqual(self.it_interv.note, "hack")

    def test_manager_forbidden_on_componente_out_of_scope(self):
        """3. Il gestore MAN riceve 403 eliminando un componente di ticket IT."""
        from tickets.models import TicketComponenteSostituito

        self.client.force_login(self.man_manager)
        resp = self._send("delete", "tickets:api_componente", {"id": self.it_comp.id})
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(
            TicketComponenteSostituito.objects.filter(id=self.it_comp.id).exists()
        )

    def test_manager_forbidden_on_workorder_from_ticket_out_of_scope(self):
        """4. Il gestore MAN riceve 403 creando un workorder da un ticket IT."""
        from assets.models import WorkOrder

        self.client.force_login(self.man_manager)
        resp = self._send("post", "tickets:api_crea_workorder",
                           {"ticket_id": self.it_ticket.id})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(WorkOrder.objects.filter(ticket=self.it_ticket).exists())

    def test_happy_path_delete_intervento_in_scope_unchanged(self):
        """5. Happy path invariato: delete di un intervento in scope funziona."""
        self.client.force_login(self.man_manager)
        resp = self._send("delete", "tickets:api_intervento", {"id": self.man_interv.id})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(TicketIntervento.objects.filter(id=self.man_interv.id).exists())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TicketEscalationTests(TestCase):
    """#1 — escalation ticket URGENTI aperti e non assegnati."""

    def _make_ticket(self, **kwargs):
        defaults = dict(
            tipo="IT", titolo="Server giù", descrizione="x", categoria="SERVER",
            priorita=PrioritaTicket.URGENTE, stato="APERTA", assegnato_a="",
        )
        defaults.update(kwargs)
        return Ticket.objects.create(**defaults)

    def _age(self, ticket, hours):
        old = timezone.now() - timedelta(hours=hours)
        Ticket.objects.filter(pk=ticket.pk).update(created_at=old)

    def test_fetch_seleziona_solo_urgenti_aperti_non_assegnati_oltre_soglia(self):
        from tickets.tasks import _fetch_tickets_da_escalare

        target = self._make_ticket(titolo="Da escalare")
        self._age(target, 10)

        # Escluso: assegnato.
        assigned = self._make_ticket(titolo="Assegnato", assegnato_a="Tecnico")
        self._age(assigned, 10)
        # Escluso: non urgente.
        media = self._make_ticket(titolo="Media", priorita=PrioritaTicket.MEDIA)
        self._age(media, 10)
        # Escluso: troppo recente (sotto soglia 4h).
        recent = self._make_ticket(titolo="Recente")
        self._age(recent, 1)
        # Escluso: già in carico.
        incarico = self._make_ticket(titolo="In carico", stato="IN_CARICO")
        self._age(incarico, 10)

        result = list(_fetch_tickets_da_escalare(soglia_ore=4))
        self.assertEqual([t.pk for t in result], [target.pk])

    def test_run_crea_reminder_per_richiedente(self):
        from core.models import Notifica
        from tickets.tasks import run_tickets_escalation

        t = self._make_ticket(richiedente_legacy_user_id=77)
        self._age(t, 10)

        result = run_tickets_escalation.__wrapped__(force_email=False) \
            if hasattr(run_tickets_escalation, "__wrapped__") else run_tickets_escalation(force_email=False)

        self.assertEqual(result["tickets"], 1)
        self.assertGreaterEqual(result["reminders"], 1)
        self.assertFalse(result["email_sent"])  # niente finestra, niente force
        notif = Notifica.objects.filter(legacy_user_id=77, tipo="ticket_sla").first()
        self.assertIsNotNone(notif)
        self.assertIn(t.numero_ticket, notif.messaggio)
        self.assertEqual(notif.url_azione, f"/tickets/gestione/{t.pk}/")

    def test_run_reminder_idempotente(self):
        from core.models import Notifica
        from tickets.tasks import run_tickets_escalation

        t = self._make_ticket(richiedente_legacy_user_id=77)
        self._age(t, 10)

        fn = getattr(run_tickets_escalation, "__wrapped__", run_tickets_escalation)
        fn(force_email=False)
        fn(force_email=False)
        # Una sola notifica non letta per (utente, ticket).
        self.assertEqual(
            Notifica.objects.filter(legacy_user_id=77, tipo="ticket_sla", letta=False).count(), 1
        )

    def test_run_force_email_invia_resoconto_al_team(self):
        from tickets.models import TicketImpostazioni
        from tickets.tasks import run_tickets_escalation

        imp = TicketImpostazioni.get_or_create_for("IT")
        imp.team_gestori = [{"nome": "Gestore IT", "email": "it@example.com"}]
        imp.save()

        t = self._make_ticket()
        self._age(t, 10)

        fn = getattr(run_tickets_escalation, "__wrapped__", run_tickets_escalation)
        with patch("core.email_utils.send_hub_mail", return_value=1) as mock_send:
            result = fn(force_email=True)

        self.assertTrue(result["email_sent"])
        self.assertEqual(mock_send.call_count, 1)
        # destinatari = team gestori IT
        args, kwargs = mock_send.call_args
        self.assertIn("it@example.com", args[2])

    def test_escalation_config_round_trip(self):
        from tickets.escalation_config import get_escalation_config, save_escalation_config

        ok = save_escalation_config(attivo=True, soglia_ore=6, ora_invio=9)
        self.assertTrue(ok)
        cfg = get_escalation_config()
        self.assertTrue(cfg["attivo"])
        self.assertEqual(cfg["soglia_ore"], 6)
        self.assertEqual(cfg["ora_invio"], 9)

    def test_escalation_config_clamps_out_of_range(self):
        from tickets.escalation_config import get_escalation_config, save_escalation_config

        save_escalation_config(attivo=False, soglia_ore=9999, ora_invio=99)
        cfg = get_escalation_config()
        self.assertFalse(cfg["attivo"])
        self.assertEqual(cfg["soglia_ore"], 168)  # SOGLIA_MAX
        self.assertEqual(cfg["ora_invio"], 23)    # ORA_MAX
