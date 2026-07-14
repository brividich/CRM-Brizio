"""Test di sicurezza del modulo assets: documenti, allegati OdL, scritture di massa.

Coperti qui:
  * i file di ``assets_documents/`` e ``assets_workorders/`` non sono mai linkati
    da /media/ (che IIS serve in anonimo): l'accesso passa sempre da una view;
  * il token QR e' una vera chiave d'accesso — vale solo per i documenti del SUO
    asset, e solo se il QR pubblico e' abilitato;
  * il download autenticato di un documento non e' enumerabile da chiunque (IDOR);
  * import Excel e bulk update sono scritture di massa: solo admin asset, con audit.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, UserOnboarding

from .models import Asset, AssetDocument, WorkOrder, WorkOrderAttachment

User = get_user_model()


def _complete_onboarding(user) -> None:
    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
    )


class _MediaRootMixin:
    """MEDIA_ROOT isolata per test: i file caricati non finiscono nella media reale."""

    def setUp(self):
        super().setUp()
        root = Path.cwd() / "django_app" / ".tmp_tests"
        root.mkdir(parents=True, exist_ok=True)
        self.media_root = root / f"assets-security-{uuid4().hex}"
        self.media_root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        self._media_override = override_settings(MEDIA_ROOT=self.media_root)
        self._media_override.enable()
        self.addCleanup(self._media_override.disable)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetDocumentQrAccessTests(_MediaRootMixin, TestCase):
    """PARTE 1 — i documenti passano dal token QR, mai da /media/."""

    def setUp(self):
        super().setUp()
        self.asset = Asset.objects.create(asset_tag="AST-SEC-QR-1", name="Pressa QR")
        self.other_asset = Asset.objects.create(asset_tag="AST-SEC-QR-2", name="Forno QR")
        self.document = AssetDocument.objects.create(
            asset=self.asset,
            category=AssetDocument.CATEGORY_MANUALI,
            file=SimpleUploadedFile("manuale.pdf", b"%PDF-1.4 manuale pressa", content_type="application/pdf"),
            original_name="manuale.pdf",
        )
        self.other_document = AssetDocument.objects.create(
            asset=self.other_asset,
            category=AssetDocument.CATEGORY_SPECIFICHE,
            file=SimpleUploadedFile("specifiche.pdf", b"%PDF-1.4 specifiche forno", content_type="application/pdf"),
            original_name="specifiche.pdf",
        )

    def _qr_url(self, token: str, document_id: int) -> str:
        return reverse(
            "assets:asset_document_qr_download",
            kwargs={"public_qr_token": token, "document_id": document_id},
        )

    def test_token_valido_scarica_i_documenti_del_suo_asset_senza_login(self):
        response = self.client.get(self._qr_url(self.asset.public_qr_token, self.document.id))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 manuale pressa")
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(
            AuditLog.objects.filter(azione="download_asset_document_qr", modulo="assets").exists()
        )

    def test_token_di_un_asset_non_scarica_i_documenti_di_un_altro(self):
        response = self.client.get(self._qr_url(self.asset.public_qr_token, self.other_document.id))

        self.assertEqual(response.status_code, 404)
        denied = AuditLog.objects.filter(azione="download_asset_document_qr").order_by("-id").first()
        self.assertIsNotNone(denied)
        self.assertEqual(denied.dettaglio.get("esito"), "denied")
        self.assertEqual(denied.dettaglio.get("motivo"), "document_not_in_asset")

    def test_token_disabilitato_o_inesistente_negato(self):
        token = self.asset.public_qr_token
        Asset.objects.filter(pk=self.asset.pk).update(public_qr_enabled=False)

        disabilitato = self.client.get(self._qr_url(token, self.document.id))
        inesistente = self.client.get(self._qr_url("token-che-non-esiste", self.document.id))

        self.assertEqual(disabilitato.status_code, 404)
        self.assertEqual(inesistente.status_code, 404)

    def test_landing_qr_pubblica_mostra_i_documenti_via_token_e_mai_via_media(self):
        response = self.client.get(
            reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": self.asset.public_qr_token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "manuale.pdf")
        self.assertContains(response, self._qr_url(self.asset.public_qr_token, self.document.id))
        self.assertNotContains(response, "/media/assets_documents/")
        # Nessun documento dell'altro asset nella landing.
        self.assertNotContains(response, "specifiche.pdf")

    def test_landing_qr_autenticata_usa_la_view_di_download_non_media(self):
        admin = User.objects.create_superuser(
            username="asset-sec-admin-landing",
            email="asset-sec-admin-landing@test.local",
            password="pass12345",
        )
        _complete_onboarding(admin)
        self.client.force_login(admin)

        response = self.client.get(
            reverse("assets:asset_qr_landing", kwargs={"asset_tag": self.asset.asset_tag})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("assets:asset_document_download", kwargs={"document_id": self.document.id}),
        )
        self.assertNotContains(response, "/media/assets_documents/")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetDocumentDownloadGateTests(_MediaRootMixin, TestCase):
    """PARTE 2 — IDOR: il download autenticato non e' enumerabile da chiunque."""

    def setUp(self):
        super().setUp()
        self.asset = Asset.objects.create(asset_tag="AST-SEC-DOC", name="Macchina documenti")
        self.document = AssetDocument.objects.create(
            asset=self.asset,
            category=AssetDocument.CATEGORY_MANUALI,
            file=SimpleUploadedFile("riservato.pdf", b"%PDF-1.4 riservato", content_type="application/pdf"),
            original_name="riservato.pdf",
        )
        self.url = reverse("assets:asset_document_download", kwargs={"document_id": self.document.id})

    def test_anonimo_redirect_al_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_utente_autenticato_non_admin_negato_e_diniego_loggato(self):
        user = User.objects.create_user(username="asset-sec-user", password="pass12345")
        _complete_onboarding(user)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 403)
        denied = (
            AuditLog.objects.filter(azione="download_asset_document", modulo="assets")
            .order_by("-id")
            .first()
        )
        self.assertIsNotNone(denied)
        self.assertEqual(denied.dettaglio.get("esito"), "denied")

    def test_admin_scarica(self):
        admin = User.objects.create_superuser(
            username="asset-sec-admin-doc",
            email="asset-sec-admin-doc@test.local",
            password="pass12345",
        )
        _complete_onboarding(admin)
        self.client.force_login(admin)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 riservato")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class WorkOrderAttachmentDownloadTests(_MediaRootMixin, TestCase):
    """PARTE 1 — gli allegati OdL passano da una view autenticata, non da /media/."""

    def setUp(self):
        super().setUp()
        self.asset = Asset.objects.create(asset_tag="AST-SEC-WO", name="Macchina OdL")
        self.workorder = WorkOrder.objects.create(asset=self.asset, title="Intervento con allegato")
        self.attachment = WorkOrderAttachment.objects.create(
            work_order=self.workorder,
            file=SimpleUploadedFile("rapporto.pdf", b"%PDF-1.4 rapporto", content_type="application/pdf"),
            original_name="rapporto.pdf",
        )
        self.url = reverse(
            "assets:workorder_attachment_download", kwargs={"attachment_id": self.attachment.id}
        )

    def test_anonimo_redirect_al_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_autenticato_scarica_e_laccesso_e_loggato(self):
        user = User.objects.create_user(username="asset-sec-wo-user", password="pass12345")
        _complete_onboarding(user)
        self.client.force_login(user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), b"%PDF-1.4 rapporto")
        self.assertTrue(
            AuditLog.objects.filter(azione="download_workorder_attachment", modulo="assets").exists()
        )

    def test_dettaglio_odl_linka_la_view_non_lurl_media(self):
        user = User.objects.create_user(username="asset-sec-wo-view", password="pass12345")
        _complete_onboarding(user)
        self.client.force_login(user)

        response = self.client.get(reverse("assets:wo_view", kwargs={"id": self.workorder.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)
        self.assertNotContains(response, "/media/assets_workorders/")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetsMassWriteGateTests(TestCase):
    """PARTE 3 — import Excel e bulk update: scritture di massa riservate agli admin."""

    def setUp(self):
        self.asset = Asset.objects.create(
            asset_tag="AST-SEC-BULK",
            name="Macchina bulk",
            status=Asset.STATUS_IN_USE,
        )
        self.user = User.objects.create_user(username="asset-sec-bulk-user", password="pass12345")
        _complete_onboarding(self.user)
        self.admin = User.objects.create_superuser(
            username="asset-sec-bulk-admin",
            email="asset-sec-bulk-admin@test.local",
            password="pass12345",
        )
        _complete_onboarding(self.admin)

    def test_import_excel_negato_ai_non_admin_e_nessun_asset_creato(self):
        self.client.force_login(self.user)
        prima = Asset.objects.count()

        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "import_excel",
                "excel_file": SimpleUploadedFile(
                    "assets.xlsx",
                    b"non-verra-mai-letto",
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Asset.objects.count(), prima)
        denied = AuditLog.objects.filter(azione="import_assets_excel").order_by("-id").first()
        self.assertIsNotNone(denied)
        self.assertEqual(denied.dettaglio.get("esito"), "denied")

    def test_bulk_update_negato_ai_non_admin_e_nessuna_modifica(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:asset_bulk_update"),
            data={"ids": [self.asset.id], "fields": {"status": Asset.STATUS_RETIRED}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json().get("ok"))
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.STATUS_IN_USE)

    def test_bulk_update_admin_aggiorna_e_scrive_audit(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:asset_bulk_update"),
            data={"ids": [self.asset.id], "fields": {"status": Asset.STATUS_RETIRED}},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("updated"), 1)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.STATUS_RETIRED)
        logged = AuditLog.objects.filter(azione="asset_bulk_update", modulo="assets").order_by("-id").first()
        self.assertIsNotNone(logged)
        self.assertEqual(logged.dettaglio.get("esito"), "success")
        self.assertEqual(logged.dettaglio.get("aggiornati"), 1)


class MediaDenyWebConfigTests(SimpleTestCase):
    """PARTE 1 — IIS non deve servire i file: /media/assets_documents/... deve 404.

    IIS serve MEDIA_ROOT in anonimo, quindi il gate applicativo non basta: senza
    il deny, l'URL diretto resta raggiungibile a chiunque (l'asset_tag e' nel path
    ed e' prevedibile). Il web.config e' scritto da configure-iis-site.ps1, NON da
    deploy-release.ps1: su un sito gia' in esercizio il deny va applicato a mano.
    """

    TEMPLATES = (
        "web.config.httpplatform.template",
        "web.config.wfastcgi.template",
    )
    DENIED_LOCATIONS = (
        'location path="media/assets_documents"',
        'location path="media/assets_workorders"',
    )

    def test_i_template_iis_negano_le_cartelle_documenti_asset(self):
        config_dir = Path(settings.BASE_DIR).parent / "deployment" / "config"
        for template_name in self.TEMPLATES:
            template = config_dir / template_name
            self.assertTrue(template.exists(), f"template mancante: {template}")
            content = template.read_text(encoding="utf-8")
            for location in self.DENIED_LOCATIONS:
                self.assertIn(location, content, f"{template_name}: manca il deny {location}")
