"""QR asset (PROMPT 06 - A): destinazione, link pubblico opt-in, immagine, etichette, upload.

Dati sintetici. Copre il finding B3 (nessun token pubblico implicito) e A9
(niente SVG/HTML negli upload immagine del modulo).
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, UserOnboarding

from .models import Asset, AssetLabelTemplate
from .services import asset_qr

User = get_user_model()

_SVG = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
    return buf.getvalue()


def _user(username: str, *, superuser: bool = False):
    user = User.objects.create_user(username=username, password="x", is_superuser=superuser, is_staff=superuser)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()}
    )
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="")
class QrDestinationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = _user("qr.admin", superuser=True)
        self.user = _user("qr.user")
        self.asset = Asset.objects.create(asset_tag="AST-QR-T1", name="Tornio QR")

    def test_new_asset_has_no_implicit_public_token(self):
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.public_qr_token)
        self.assertFalse(self.asset.public_qr_enabled)
        # Neanche un salvataggio successivo lo crea.
        self.asset.name = "Tornio QR 2"
        self.asset.save()
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.public_qr_token)

    def test_label_points_to_internal_landing_until_enabled(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch("assets.views._draw_asset_label_pdf") as draw:
            response = self.client.get(reverse("assets:asset_qr_label", kwargs={"id": self.asset.id}))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(draw.call_args.kwargs["target_url"].endswith(f"/assets/qr/{self.asset.asset_tag}/"))
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.public_qr_token)

    def test_admin_enables_public_link_then_label_points_to_public_landing(self):
        from unittest.mock import patch

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assets:asset_qr_public_link", kwargs={"id": self.asset.id}), {"azione": "abilita"}
        )
        self.assertEqual(response.status_code, 302)
        self.asset.refresh_from_db()
        self.assertTrue(self.asset.public_qr_enabled)
        self.assertTrue(self.asset.public_qr_token)
        with patch("assets.views._draw_asset_label_pdf") as draw:
            self.client.get(reverse("assets:asset_qr_label", kwargs={"id": self.asset.id}))
        self.assertIn(f"/assets/qr/pub/{self.asset.public_qr_token}/", draw.call_args.kwargs["target_url"])
        log = AuditLog.objects.filter(azione="asset_qr_pubblico_abilita").first()
        self.assertIsNotNone(log)
        self.assertNotIn(self.asset.public_qr_token, str(log.dettaglio))

    def test_user_without_permission_cannot_enable_public_link(self):
        self.client.force_login(self.user)
        url = reverse("assets:asset_qr_public_link", kwargs={"id": self.asset.id})
        self.assertEqual(self.client.post(url, {"azione": "abilita"}).status_code, 403)
        ajax = self.client.post(url, {"azione": "abilita"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(ajax.status_code, 403)
        self.assertEqual(ajax.json()["ok"], False)
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.public_qr_token)

    def test_get_requests_never_create_token(self):
        self.client.force_login(self.admin)
        for name in ("asset_qr_image", "asset_qr_panel", "asset_qr_label", "asset_view"):
            self.client.get(reverse(f"assets:{name}", kwargs={"id": self.asset.id}))
        self.asset.refresh_from_db()
        self.assertIsNone(self.asset.public_qr_token)

    def test_revoke_and_regenerate(self):
        asset_qr.abilita_link_pubblico(self.asset)
        old = self.asset.public_qr_token
        self.client.force_login(self.admin)
        url = reverse("assets:asset_qr_public_link", kwargs={"id": self.asset.id})
        self.client.post(url, {"azione": "revoca"})
        public = reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": old})
        self.client.logout()
        self.assertEqual(self.client.get(public).status_code, 404)
        self.client.force_login(self.admin)
        self.client.post(url, {"azione": "abilita"})
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.public_qr_token, old)  # riattivare non cambia le etichette stampate
        self.client.post(url, {"azione": "rigenera"})
        self.asset.refresh_from_db()
        self.assertNotEqual(self.asset.public_qr_token, old)
        self.client.logout()
        self.assertEqual(self.client.get(public).status_code, 404)

    def test_next_redirect_is_same_host_only(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assets:asset_qr_public_link", kwargs={"id": self.asset.id}),
            {"azione": "revoca", "next": "https://evil.example/x"},
        )
        self.assertEqual(response["Location"], reverse("assets:asset_view", kwargs={"id": self.asset.id}))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False, SITE_URL="")
class QrImageAndPanelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = _user("qr.admin2", superuser=True)
        self.user = _user("qr.user2")
        self.asset = Asset.objects.create(asset_tag="AST-QR-IMG", name="Fresa QR")

    def test_image_is_png_generated_server_side(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_qr_image", kwargs={"id": self.asset.id}) + "?size=l&download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_cache_key_changes_with_tag_and_token(self):
        class _Req:
            def build_absolute_uri(self, path):
                return f"http://testserver{path}"

        req = _Req()
        first = asset_qr.destinazione(req, self.asset)
        self.asset.asset_tag = "AST-QR-IMG-2"
        second = asset_qr.destinazione(req, self.asset)
        asset_qr.abilita_link_pubblico(self.asset)
        third = asset_qr.destinazione(req, self.asset)
        keys = {asset_qr._cache_key(self.asset.id, d, "m") for d in (first, second, third)}
        self.assertEqual(len(keys), 3)
        self.assertEqual(third.kind, asset_qr.DEST_PUBLIC)

    def test_panel_shows_public_controls_only_with_permission(self):
        url = reverse("assets:asset_qr_panel", kwargs={"id": self.asset.id})
        self.client.force_login(self.user)
        body = self.client.get(url).content.decode()
        self.assertIn("Stampa etichetta", body)
        self.assertIn("Landing interna", body)
        self.assertNotIn("Abilita link pubblico", body)
        self.client.force_login(self.admin)
        self.assertIn("Abilita link pubblico", self.client.get(url).content.decode())

    def test_detail_and_list_render_qr_component(self):
        self.client.force_login(self.admin)
        detail = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id})).content.decode()
        self.assertIn(reverse("assets:asset_qr_panel", kwargs={"id": self.asset.id}), detail)
        listing = self.client.get(reverse("assets:asset_list")).content.decode()
        self.assertIn('data-col-toggle="qr"', listing)
        self.assertIn(reverse("assets:asset_qr_labels_bulk"), listing)

    def test_bulk_labels_pdf_has_one_page_per_asset(self):
        AssetLabelTemplate.objects.update_or_create(code="default", defaults={"show_logo": False})
        other = Asset.objects.create(asset_tag="AST-QR-IMG-B", name="Pressa QR")
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_qr_labels_bulk") + f"?ids={self.asset.id},{other.id},999999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content.count(b"/Type /Page\n") + response.content.count(b"/Type /Page "), 2)
        too_many = ",".join(str(i) for i in range(1, 202))
        self.assertEqual(self.client.get(reverse("assets:asset_qr_labels_bulk") + f"?ids={too_many}").status_code, 400)
        self.assertEqual(self.client.get(reverse("assets:asset_qr_labels_bulk")).status_code, 400)
        # Cifre Unicode e valori enormi: ignorati, nessun 500.
        self.assertEqual(self.client.get(reverse("assets:asset_qr_labels_bulk") + "?ids=²,99999999999999").status_code, 400)

    def test_anonymous_ajax_gets_json_401(self):
        response = self.client.get(
            reverse("assets:asset_qr_panel", kwargs={"id": self.asset.id}), HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["ok"], False)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetImageUploadHardeningTests(TestCase):
    def setUp(self):
        root = Path.cwd() / "django_app" / ".tmp_tests"
        root.mkdir(parents=True, exist_ok=True)
        self.media_root = root / f"assets-qr-{uuid4().hex}"
        self.media_root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.admin = _user("qr.upload.admin", superuser=True)

    def test_validate_asset_image_rejects_svg_renamed_png(self):
        from .views import _validate_asset_image

        error = _validate_asset_image(SimpleUploadedFile("finta.png", _SVG, content_type="image/png"))
        self.assertTrue(error)
        self.assertEqual(_validate_asset_image(SimpleUploadedFile("vera.png", _png_bytes(), content_type="image/png")), "")

    def test_form_cleaners_reject_svg_and_html(self):
        from django import forms as dj_forms

        from .upload_rules import clean_document_upload, clean_image_upload

        with self.assertRaises(dj_forms.ValidationError):
            clean_image_upload(SimpleUploadedFile("logo.png", _SVG), max_bytes=2_000_000, label="Logo")
        with self.assertRaises(dj_forms.ValidationError):
            clean_document_upload(SimpleUploadedFile("rapporto.pdf", b"<html><script>x</script></html>"), label="Rapporto")
        ok = SimpleUploadedFile("logo.png", _png_bytes())
        self.assertIs(clean_image_upload(ok, max_bytes=2_000_000, label="Logo"), ok)

    def test_report_template_rejects_html(self):
        from .views import REPORT_TEMPLATE_ALLOWED_EXTENSIONS

        self.assertNotIn(".html", REPORT_TEMPLATE_ALLOWED_EXTENSIONS)
        self.assertNotIn(".htm", REPORT_TEMPLATE_ALLOWED_EXTENSIONS)
