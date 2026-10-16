"""Scheda asset: upload video .avi, cartelle con file scartati, «Dismetti» ed «Elimina»."""
from __future__ import annotations

import importlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from core.legacy_models import Ruolo
from core.models import AuditLog, PermissionDefinition, RolePermissionGrant

from .models import Asset, AssetDocument, WorkOrder
from .services.ciclo_vita_asset import blocchi_eliminazione
from .tests import _complete_onboarding, _workspace_temporary_directory

User = get_user_model()


def _avi_bytes() -> bytes:
    # Intestazione RIFF/AVI sintetica: basta a libmagic per riconoscere il contenitore.
    return b"RIFF" + struct.pack("<I", 4000) + b"AVI LIST" + struct.pack("<I", 200) + b"hdrlavih" + b"\x00" * 3000


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetDocumentUploadTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="asset-upl-admin", email="upl@test.local", password="pass12345")
        _complete_onboarding(self.user)
        self.client.force_login(self.user)
        self.asset = Asset.objects.create(asset_tag="AST-UPL-001", name="Pressa upload")
        self.url = reverse("assets:asset_view", args=[self.asset.id])

    def test_avi_video_is_accepted_with_real_mime_check(self):
        video = SimpleUploadedFile("collaudo.avi", _avi_bytes(), content_type="video/x-msvideo")
        with _workspace_temporary_directory("assets-avi-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            response = self.client.post(self.url, {"action": "upload_asset_documents", "upload_specs_files": video})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetDocument.objects.filter(asset=self.asset, original_name="collaudo.avi").exists())

    def test_renamed_non_video_with_avi_extension_is_rejected(self):
        fake = SimpleUploadedFile("finto.avi", b"<html><script>x</script></html>", content_type="video/x-msvideo")
        with _workspace_temporary_directory("assets-avi-fake-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            self.client.post(self.url, {"action": "upload_asset_documents", "upload_specs_files": fake})
        self.assertFalse(AssetDocument.objects.filter(asset=self.asset).exists())

    def _folder_post(self, extra_headers=None):
        good = SimpleUploadedFile("specifica.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        bad = SimpleUploadedFile("setup.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        with _workspace_temporary_directory("assets-folder-mixed-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            return self.client.post(
                self.url,
                {
                    "action": "upload_asset_documents",
                    "upload_specs_files": [good, bad],
                    "upload_specs_files_relative_path": ["Macchina/Docs/specifica.pdf", "Macchina/Docs/setup.exe"],
                },
                **(extra_headers or {}),
            )

    def test_folder_upload_keeps_valid_files_when_some_are_rejected(self):
        response = self._folder_post()
        self.assertEqual(response.status_code, 302)
        document = AssetDocument.objects.get(asset=self.asset)
        self.assertEqual(document.original_name, "specifica.pdf")
        self.assertEqual(document.relative_folder, "Macchina/Docs")

    def test_batched_upload_answers_json_with_saved_and_errors(self):
        response = self._folder_post({"HTTP_ACCEPT": "application/json"})
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["saved"], 1)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("setup.exe", payload["errors"][0])

    def test_upload_form_accepts_avi_and_announces_folders(self):
        body = self.client.get(self.url).content.decode("utf-8")
        self.assertIn(".avi", body)
        self.assertIn("anche con sottocartelle", body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetRetireDeleteTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="AST-CV-001", name="Trapano creato per errore")
        self.url = reverse("assets:asset_view", args=[self.asset.id])
        self.tech = User.objects.create_user(username="asset-cv-manutentore", password="pass12345")
        _complete_onboarding(self.tech)
        self.viewer = User.objects.create_user(username="asset-cv-viewer", password="pass12345")
        _complete_onboarding(self.viewer)

    def _as_maintenance(self):
        """Il ruolo della manutenzione ha i permessi assets/asset_retire e assets/asset_delete."""
        return patch(
            "assets.views._helpers.user_can_modulo_action",
            side_effect=lambda request, modulo, azione: azione in {"asset_retire", "asset_delete"},
        )

    def test_maintenance_role_sees_buttons_and_retires_then_reactivates(self):
        self.client.force_login(self.tech)
        with self._as_maintenance():
            body = self.client.get(self.url).content.decode("utf-8")
            self.assertIn('value="retire_asset"', body)
            self.assertIn('value="delete_asset"', body)
            self.client.post(self.url, {"action": "retire_asset"})
            self.asset.refresh_from_db()
            self.assertEqual(self.asset.status, Asset.STATUS_RETIRED)
            self.client.post(self.url, {"action": "reactivate_asset"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.STATUS_IN_USE)
        self.assertTrue(AuditLog.objects.filter(azione="retire_asset").exists())

    def test_user_without_permission_cannot_retire_or_delete(self):
        self.client.force_login(self.viewer)
        body = self.client.get(self.url).content.decode("utf-8")
        self.assertNotIn('value="retire_asset"', body)
        self.assertNotIn('value="delete_asset"', body)
        self.client.post(self.url, {"action": "retire_asset"})
        self.client.post(self.url, {"action": "delete_asset"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.status, Asset.STATUS_IN_USE)

    def test_delete_without_history_removes_asset_and_audits(self):
        self.client.force_login(self.tech)
        with self._as_maintenance():
            response = self.client.post(self.url, {"action": "delete_asset"})
        self.assertRedirects(response, reverse("assets:asset_list"), fetch_redirect_response=False)
        self.assertFalse(Asset.objects.filter(pk=self.asset.pk).exists())
        log = AuditLog.objects.filter(azione="delete_asset").latest("id")
        self.assertIn("AST-CV-001", json.dumps(log.dettaglio, default=str))

    def test_delete_is_blocked_when_asset_has_history(self):
        WorkOrder.objects.create(asset=self.asset, title="Sostituzione mandrino")
        self.assertEqual(blocchi_eliminazione(self.asset), ["1 ordini di lavoro"])
        self.client.force_login(self.tech)
        with self._as_maintenance():
            body = self.client.get(self.url).content.decode("utf-8")
            self.assertIn("Elimina (non disponibile: ha storico)", body)
            self.client.post(self.url, {"action": "delete_asset"})
        self.assertTrue(Asset.objects.filter(pk=self.asset.pk).exists())


class AssetLifecycleMigrationTests(TestCase):
    def test_grants_are_active_for_maintenance_roles_only(self):
        manutenzione = Ruolo.objects.create(nome="Manutenzione")
        utente = Ruolo.objects.create(nome="utente base")
        migration = importlib.import_module("assets.migrations.0133_permessi_dismetti_elimina_asset")
        migration.forwards(django_apps, SimpleNamespace(connection=connection))

        self.assertTrue(PermissionDefinition.objects.filter(code="legacy.assets.asset_retire", is_active=True).exists())
        granted = set(
            RolePermissionGrant.objects.filter(enabled=True, permission__code__startswith="legacy.assets.asset_")
            .values_list("legacy_role_id", "permission_id")
        )
        self.assertEqual(
            granted,
            {
                (manutenzione.id, "legacy.assets.asset_retire"),
                (manutenzione.id, "legacy.assets.asset_delete"),
            },
        )
        self.assertFalse(RolePermissionGrant.objects.filter(legacy_role_id=utente.id).exists())
