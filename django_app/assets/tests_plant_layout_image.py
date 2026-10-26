"""Planimetria officina: ruota/ritaglia con coordinate riallineate, PDF, card della scheda."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from assets.forms import PlantLayoutForm
from assets.models import Asset, PlantLayout, PlantLayoutArea, PlantLayoutMarker
from assets.services import plant_layout_image as tools
from assets.tests import _complete_onboarding, _workspace_temporary_directory
from assets.views.asset_detail import _map_card_background_position


def _png(width: int, height: int, name: str = "pianta.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "#ffffff").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=400, height=200)
    page.draw_rect(fitz.Rect(50, 50, 350, 150), color=(0, 0, 0))
    data = doc.tobytes()
    doc.close()
    return data


class _MediaMixin:
    def setUp(self):
        super().setUp()
        self._tmp = _workspace_temporary_directory("assets-plx-")
        tmpdir = self._tmp.__enter__()
        self._media = override_settings(MEDIA_ROOT=Path(tmpdir))
        self._media.enable()

    def tearDown(self):
        self._media.disable()
        self._tmp.__exit__(None, None, None)
        super().tearDown()


class PlantLayoutImageToolsTests(_MediaMixin, TestCase):
    def _layout(self, w=200, h=100):
        layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(w, h), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-PLX-1", name="Tornio", reparto="TRN")
        marker = PlantLayoutMarker.objects.create(layout=layout, asset=asset, x_percent=10, y_percent=20)
        area = PlantLayoutArea.objects.create(
            layout=layout, name="Torni", reparto_code="TRN", x_percent=10, y_percent=20, width_percent=30, height_percent=40
        )
        return layout, marker, area

    def test_rotate_right_swaps_image_and_moves_coordinates(self):
        layout, marker, area = self._layout()
        result = tools.rotate_layout(layout, clockwise=True)
        self.assertTrue(result.ok)
        layout.refresh_from_db()
        self.assertEqual((layout.image.width, layout.image.height), (100, 200))
        marker.refresh_from_db()
        area.refresh_from_db()
        # (x, y) → (100 - y, x)
        self.assertEqual((marker.x_percent, marker.y_percent), (Decimal("80"), Decimal("10")))
        self.assertEqual(
            (area.x_percent, area.y_percent, area.width_percent, area.height_percent),
            (Decimal("40"), Decimal("10"), Decimal("40"), Decimal("30")),
        )

    def test_rotate_left_then_right_is_identity_and_keeps_unplaced(self):
        layout, marker, area = self._layout()
        other = Asset.objects.create(asset_tag="AST-PLX-2", name="Fresa")
        unplaced = PlantLayoutMarker.objects.create(layout=layout, asset=other, x_percent=50, y_percent=50)
        tools.rotate_layout(layout, clockwise=False)
        tools.rotate_layout(PlantLayout.objects.get(pk=layout.pk), clockwise=True)
        marker.refresh_from_db()
        area.refresh_from_db()
        unplaced.refresh_from_db()
        self.assertEqual((marker.x_percent, marker.y_percent), (Decimal("10"), Decimal("20")))
        self.assertEqual((area.width_percent, area.height_percent), (Decimal("30"), Decimal("40")))
        self.assertTrue(tools.marker_is_unplaced(unplaced))

    def test_crop_remaps_inside_and_resets_outside(self):
        layout, marker, area = self._layout()
        other = Asset.objects.create(asset_tag="AST-PLX-3", name="Pressa")
        inside = PlantLayoutMarker.objects.create(layout=layout, asset=other, x_percent=75, y_percent=75)
        result = tools.crop_layout(layout, x_percent=50, y_percent=50, width_percent=50, height_percent=50)
        self.assertTrue(result.ok)
        self.assertIn("da posizionare", result.message)
        layout.refresh_from_db()
        self.assertEqual((layout.image.width, layout.image.height), (100, 50))
        inside.refresh_from_db()
        marker.refresh_from_db()
        self.assertEqual((inside.x_percent, inside.y_percent), (Decimal("50"), Decimal("50")))
        self.assertTrue(tools.marker_is_unplaced(marker))
        # Il reparto (10..40 x 20..60) è fuori in X: eliminato.
        self.assertFalse(PlantLayoutArea.objects.filter(pk=area.pk).exists())

    def test_crop_refuses_tiny_box(self):
        layout, _marker, _area = self._layout()
        result = tools.crop_layout(layout, x_percent=0, y_percent=0, width_percent=2, height_percent=2)
        self.assertFalse(result.ok)

    def test_form_accepts_pdf_as_first_page_png(self):
        upload = SimpleUploadedFile("pianta.pdf", _pdf_bytes(), content_type="application/pdf")
        form = PlantLayoutForm(data={"category": "Officina", "name": "Da PDF"}, files={"image": upload})
        self.assertTrue(form.is_valid(), form.errors)
        layout = form.save()
        self.assertTrue(layout.image.name.endswith(".png"))
        self.assertGreater(layout.image.width, layout.image.height)

    def test_form_rejects_fake_pdf(self):
        upload = SimpleUploadedFile("pianta.pdf", b"non un pdf", content_type="application/pdf")
        form = PlantLayoutForm(data={"category": "Officina", "name": "Finto"}, files={"image": upload})
        self.assertFalse(form.is_valid())
        self.assertIn("PDF", str(form.errors["image"]))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PlantLayoutEditorToolTests(_MediaMixin, TestCase):
    def test_editor_saves_payload_then_rotates(self):
        admin = get_user_model().objects.create_superuser(username="plx-admin", email="plx@test.local", password="x")
        _complete_onboarding(admin)
        asset = Asset.objects.create(
            asset_tag="AST-PLX-E", name="Centro", asset_type=Asset.TYPE_WORK_MACHINE, reparto="CN5"
        )
        layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(200, 100), is_active=True)
        self.client.force_login(admin)
        with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)),                 patch("admin_portale.decorators.is_legacy_admin", return_value=True):
            response = self.client.post(reverse("assets:plant_layout_editor"), {
                "action": "save_layout",
                "layout_id": layout.id,
                "layout_mode": "edit",
                "category": "Officina",
                "name": "Pianta",
                "is_active": "on",
                "image_tool": "rotate_right",
                "areas_payload": "[]",
                "markers_payload": json.dumps([{"asset_id": asset.id, "x_percent": 10, "y_percent": 20}]),
            })
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("assets:plant_layout_editor"), response["Location"])
        marker = PlantLayoutMarker.objects.get(layout=layout, asset=asset)
        self.assertEqual((marker.x_percent, marker.y_percent), (Decimal("80"), Decimal("10")))
        layout.refresh_from_db()
        self.assertEqual((layout.image.width, layout.image.height), (100, 200))


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetDetailPlantMapCardTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username="plx-user", password="x")
        _complete_onboarding(self.user)

    def test_card_shows_zone_and_drawn_area(self):
        layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(200, 100), is_active=True)
        PlantLayoutArea.objects.create(
            layout=layout, name="Isola torni", reparto_code="TRN", x_percent=0, y_percent=0, width_percent=50, height_percent=50
        )
        asset = Asset.objects.create(asset_tag="AST-PLX-D", name="Tornio", reparto="TRN")
        PlantLayoutMarker.objects.create(layout=layout, asset=asset, x_percent=25, y_percent=25)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[asset.id]))
        self.assertEqual(resp.status_code, 200)
        card = resp.context["map_card"]
        self.assertTrue(card["placed"])
        self.assertEqual(card["area_name"], "Isola torni")
        self.assertContains(resp, "af-map-zone")
        self.assertContains(resp, "Pianta intera")
        self.assertEqual(card["editor_url"], "")  # utente senza gestione mappa

    def test_card_hidden_without_marker_for_plain_user(self):
        PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(20, 10), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-PLX-N", name="Tornio", asset_type=Asset.TYPE_WORK_MACHINE)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assets:asset_view", args=[asset.id]))
        self.assertIsNone(resp.context["map_card"])

    def test_background_position_centres_the_point(self):
        # Al centro dell'immagine il punto resta al centro qualunque sia lo zoom.
        self.assertEqual(_map_card_background_position(50, 50, 160, 100), (50.0, 50.0))
        # Agli estremi l'offset esce da 0..100: l'immagine si sposta oltre il bordo.
        x, _y = _map_card_background_position(0, 50, 160, 100)
        self.assertLess(x, 0)


class PlantLayoutManagementTests(_MediaMixin, TestCase):
    """Scelta della pianta, nuove versioni e catalogo dell'editor."""

    def _admin_post(self, data):
        admin = get_user_model().objects.create_superuser(username="plx-gest", email="plxg@test.local", password="x")
        _complete_onboarding(admin)
        self.client.force_login(admin)
        with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)), \
                patch("admin_portale.decorators.is_legacy_admin", return_value=True):
            return self.client.post(reverse("assets:plant_layout_editor"), data)

    def test_new_asset_goes_where_similar_machines_are_placed(self):
        from assets.views._helpers import _ensure_asset_plant_layout_marker, _resolve_asset_plant_layout_detail

        PlantLayout.objects.create(category="Apparecchi", name="Carroponti", image=_png(50, 50), is_active=True)
        officina = PlantLayout.objects.create(category="Officina Imm.2", name="Officina 2", image=_png(50, 50), is_active=True)
        old = Asset.objects.create(asset_tag="AST-SIM-1", name="Tornio vecchio", reparto="Torni")
        PlantLayoutMarker.objects.create(layout=officina, asset=old, x_percent=30, y_percent=40)
        new = Asset.objects.create(asset_tag="AST-SIM-2", name="Tornio nuovo", reparto="Torni")
        self.assertEqual(_resolve_asset_plant_layout_detail(new), (officina, "simili"))
        self.assertEqual(_ensure_asset_plant_layout_marker(new), "")
        self.assertEqual(PlantLayoutMarker.objects.get(asset=new).layout_id, officina.id)

    def test_no_placeholder_on_alphabetical_first_when_undecided(self):
        from assets.views._helpers import _ensure_asset_plant_layout_marker

        PlantLayout.objects.create(category="Apparecchi", name="Carroponti", image=_png(50, 50), is_active=True)
        PlantLayout.objects.create(category="Officina", name="Officina", image=_png(50, 50), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-UND-1", name="Pompa", reparto="Ignoto")
        self.assertIn("scegli", _ensure_asset_plant_layout_marker(asset))
        self.assertFalse(PlantLayoutMarker.objects.filter(asset=asset).exists())

    def test_single_active_layout_still_gets_placeholder(self):
        from assets.views._helpers import _ensure_asset_plant_layout_marker

        only = PlantLayout.objects.create(category="Officina", name="Officina", image=_png(50, 50), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-ONE-1", name="Pressa", reparto="Ignoto")
        self.assertEqual(_ensure_asset_plant_layout_marker(asset), "")
        self.assertEqual(PlantLayoutMarker.objects.get(asset=asset).layout_id, only.id)

    def test_new_version_copies_areas_and_machines(self):
        v1 = PlantLayout.objects.create(category="Officina Imm.1", name="Officina 2025", image=_png(80, 40), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-VER-1", name="Fresa", reparto="FRE")
        PlantLayoutMarker.objects.create(layout=v1, asset=asset, label="F1", x_percent=12, y_percent=34)
        PlantLayoutArea.objects.create(layout=v1, name="Frese", reparto_code="FRE", x_percent=5, y_percent=5, width_percent=20, height_percent=20)
        response = self._admin_post({
            "action": "save_layout",
            "layout_mode": "new",
            "category": "Officina Imm.1",
            "name": "Officina 2026",
            "is_active": "on",
            "copy_previous": "1",
            "image": _png(80, 40, "nuova.png"),
            "areas_payload": "[]",
            "markers_payload": "[]",
        })
        self.assertEqual(response.status_code, 302)
        v2 = PlantLayout.objects.get(name="Officina 2026")
        self.assertTrue(v2.is_active)
        marker = PlantLayoutMarker.objects.get(layout=v2, asset=asset)
        self.assertEqual((marker.label, marker.x_percent, marker.y_percent), ("F1", Decimal("12"), Decimal("34")))
        self.assertEqual(PlantLayoutArea.objects.filter(layout=v2, reparto_code="FRE").count(), 1)
        # La versione precedente resta intatta (archivio).
        self.assertTrue(PlantLayoutMarker.objects.filter(layout=v1, asset=asset).exists())

    def test_new_version_without_copy_starts_empty(self):
        v1 = PlantLayout.objects.create(category="Officina Imm.1", name="Officina 2025", image=_png(80, 40), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-VER-2", name="Fresa", reparto="FRE")
        PlantLayoutMarker.objects.create(layout=v1, asset=asset, x_percent=12, y_percent=34)
        self._admin_post({
            "action": "save_layout",
            "layout_mode": "new",
            "category": "Officina Imm.1",
            "name": "Vuota",
            "image": _png(80, 40, "vuota.png"),
            "areas_payload": "[]",
            "markers_payload": "[]",
        })
        self.assertFalse(PlantLayoutMarker.objects.filter(layout__name="Vuota").exists())

    def test_editor_catalog_knows_where_machine_is_placed(self):
        from assets.views.layout import _plant_layout_category_counts, _plant_layout_machine_catalog_for

        carro = PlantLayout.objects.create(category="Apparecchi", name="Carroponti", image=_png(50, 50), is_active=True)
        officina = PlantLayout.objects.create(category="Officina", name="Officina 1", image=_png(50, 50), is_active=True)
        asset = Asset.objects.create(asset_tag="AST-CAT-1", name="Tornio", reparto="Torni")
        PlantLayoutMarker.objects.create(layout=officina, asset=asset, x_percent=20, y_percent=20)
        PlantLayoutMarker.objects.create(layout=carro, asset=asset, x_percent=50, y_percent=50)
        row = next(r for r in _plant_layout_machine_catalog_for(carro) if r["id"] == asset.id)
        self.assertEqual(row["elsewhere"], ["Officina 1"])
        row = next(r for r in _plant_layout_machine_catalog_for(officina) if r["id"] == asset.id)
        self.assertEqual(row["elsewhere"], [])
        counts = _plant_layout_category_counts()
        self.assertEqual(counts["apparecchi"], {"placed": 0, "unplaced": 1})
        self.assertEqual(counts["officina"], {"placed": 1, "unplaced": 0})
