"""Reparti a forma libera («L») sulla planimetria: geometria, editor, ruota/ritaglia, mappa."""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset, PlantLayout, PlantLayoutArea, PlantLayoutMarker
from assets.services import plant_layout_image as tools
from assets.tests import _complete_onboarding
from assets.tests_plant_layout_image import _MediaMixin, _png

# «L»: braccio orizzontale in alto (10..60 x 10..30) e verticale a sinistra (10..30 x 10..70)
ELLE = [[10, 10], [60, 10], [60, 30], [30, 30], [30, 70], [10, 70]]


class GeometriaTests(TestCase):
    def _area(self, punti=None, **kw):
        a = PlantLayoutArea(name="L", **kw)
        if punti:
            a.imposta_punti(punti)
        return a

    def test_imposta_punti_calcola_il_riquadro(self):
        a = self._area(ELLE)
        self.assertTrue(a.e_poligono)
        self.assertEqual((a.x_percent, a.y_percent, a.width_percent, a.height_percent),
                         (Decimal("10.0"), Decimal("10.0"), Decimal("50.0"), Decimal("60.0")))

    def test_contiene_solo_dentro_la_elle(self):
        a = self._area(ELLE)
        self.assertTrue(a.contiene(20, 50))   # braccio verticale
        self.assertTrue(a.contiene(50, 20))   # braccio orizzontale
        self.assertFalse(a.contiene(50, 50))  # angolo vuoto, dentro il riquadro
        self.assertTrue(a.contiene(10, 40))   # sul bordo

    def test_superficie_e_punto_interno(self):
        a = self._area(ELLE)
        self.assertAlmostEqual(a.superficie(), 50 * 20 + 20 * 40)
        px, py = a.punto_interno()
        self.assertTrue(a.contiene(px, py))

    def test_rettangolo_senza_punti(self):
        a = self._area(x_percent=Decimal("10"), y_percent=Decimal("10"), width_percent=Decimal("20"),
                       height_percent=Decimal("20"))
        self.assertFalse(a.e_poligono)
        self.assertTrue(a.contiene(15, 15))
        self.assertFalse(a.contiene(35, 15))
        self.assertIn("polygon(0.00% 0.00%", a.clip_path())

    def test_area_al_punto_preferisce_la_forma_che_lo_contiene(self):
        grande = self._area(x_percent=Decimal("0"), y_percent=Decimal("0"), width_percent=Decimal("100"),
                            height_percent=Decimal("100"))
        elle = self._area(ELLE)
        self.assertIs(tools.area_at_point([grande, elle], 20, 50), elle)
        self.assertIs(tools.area_at_point([grande, elle], 50, 50), grande)


class TrasformazioniTests(_MediaMixin, TestCase):
    def test_ruota_e_ritaglia_portano_i_punti(self):
        layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(200, 200), is_active=True)
        area = PlantLayoutArea(layout=layout, name="L")
        area.imposta_punti(ELLE)
        area.save()
        tools.rotate_layout(layout, clockwise=True)
        area.refresh_from_db()
        self.assertEqual(area.punti[0], [90.0, 10.0])  # (x, y) → (100 - y, x)
        self.assertTrue(area.contiene(100 - 50, 20))  # era (20, 50) nel braccio verticale
        tools.crop_layout(layout, x_percent=0, y_percent=0, width_percent=100, height_percent=50)
        area.refresh_from_db()
        self.assertTrue(area.e_poligono)
        self.assertTrue(all(0 <= x <= 100 and 0 <= y <= 100 for x, y in area.punti))

    def test_nuova_versione_copia_la_forma(self):
        src = PlantLayout.objects.create(category="Officina", name="V1", image=_png(100, 100), is_active=True)
        dst = PlantLayout.objects.create(category="Officina", name="V2", image=_png(100, 100))
        area = PlantLayoutArea(layout=src, name="L")
        area.imposta_punti(ELLE)
        area.save()
        tools.copy_layout_content(src, dst)
        self.assertEqual(PlantLayoutArea.objects.get(layout=dst).punti, area.punti)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class EditorEMappaTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="poly-admin", email="poly@test.local", password="x")
        _complete_onboarding(self.admin)
        self.client.force_login(self.admin)
        self.layout = PlantLayout.objects.create(category="Officina", name="Pianta", image=_png(200, 100), is_active=True)
        self.asset = Asset.objects.create(asset_tag="WM-L", name="Centro", asset_type=Asset.TYPE_WORK_MACHINE, reparto="CN5")

    def _salva(self, punti):
        with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)), \
                patch("admin_portale.decorators.is_legacy_admin", return_value=True):
            return self.client.post(reverse("assets:plant_layout_editor"), {
                "action": "save_layout", "layout_id": self.layout.id, "layout_mode": "edit",
                "category": "Officina", "name": "Pianta", "is_active": "on",
                "areas_payload": json.dumps([{"name": "CN5", "reparto_code": "CN5", "color": "#2563EB",
                                              "x_percent": 1, "y_percent": 1, "width_percent": 5, "height_percent": 5,
                                              "punti": punti}]),
                "markers_payload": json.dumps([{"asset_id": self.asset.id, "x_percent": 20, "y_percent": 50}]),
            })

    def test_editor_salva_la_forma_e_ricalcola_il_riquadro(self):
        resp = self._salva(ELLE)
        self.assertEqual(resp.status_code, 302)
        area = PlantLayoutArea.objects.get(layout=self.layout)
        self.assertEqual(area.punti, [[float(x), float(y)] for x, y in ELLE])
        self.assertEqual((area.x_percent, area.width_percent), (Decimal("10.00"), Decimal("50.00")))

    def test_editor_rifiuta_forme_non_valide(self):
        self._salva([[10, 10], [20, 20]])
        self.assertFalse(PlantLayoutArea.objects.filter(layout=self.layout).exists())

    def test_rettangolo_resta_rettangolo(self):
        self._salva([])
        area = PlantLayoutArea.objects.get(layout=self.layout)
        self.assertEqual(area.punti, [])
        self.assertEqual(area.width_percent, Decimal("5.00"))

    def test_mappa_disegna_la_forma(self):
        area = PlantLayoutArea(layout=self.layout, name="CN5", reparto_code="CN5")
        area.imposta_punti(ELLE)
        area.save()
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.asset, x_percent=20, y_percent=50)
        with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)), \
                patch("admin_portale.decorators.is_legacy_admin", return_value=True):
            resp = self.client.get(reverse("assets:plant_layout_map"))
            editor = self.client.get(reverse("assets:plant_layout_editor") + f"?layout={self.layout.id}")
        self.assertContains(resp, "pl-area is-poly")
        self.assertContains(resp, "clip-path:polygon(")
        self.assertContains(editor, '"punti": [[10.0, 10.0]')

    def test_ticket_area_mia_con_la_forma(self):
        from assets.services.mappa_ticket import MODALITA_AREE, mappe

        area = PlantLayoutArea(layout=self.layout, name="CN5", reparto_code="CN5")
        area.imposta_punti(ELLE)
        area.save()
        dentro = Asset.objects.create(asset_tag="WM-IN", name="Dentro", asset_type=Asset.TYPE_WORK_MACHINE)
        angolo = Asset.objects.create(asset_tag="WM-OUT", name="Angolo", asset_type=Asset.TYPE_WORK_MACHINE)
        PlantLayoutMarker.objects.create(layout=self.layout, asset=dentro, x_percent=20, y_percent=50)
        PlantLayoutMarker.objects.create(layout=self.layout, asset=angolo, x_percent=50, y_percent=50)
        (pianta,) = mappe("CN5", modalita=MODALITA_AREE)
        mie = {m["asset_id"] for m in pianta["markers"] if m["mio"]}
        self.assertEqual(mie, {dentro.pk})
        self.assertEqual(len(pianta["aree"][0]["punti"]), 6)
        self.assertNotIn("_area", pianta["aree"][0])
