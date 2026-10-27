"""Mappa officina: segnaposti nascosti, avvisi di legge, quadro CNC, stato JSON, stampa, storico posizioni."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import (
    Asset,
    AssetTimelineEntry,
    CollegamentoMTConnect,
    MaintenanceInterventionTemplate,
    MaintenanceOccurrence,
    PeriodicVerification,
    PeriodoStatoMacchina,
    PlantLayout,
    PlantLayoutMarker,
)
from assets.tests import _complete_onboarding
from assets.tests_plant_layout_image import _MediaMixin, _png
from assets.views._helpers_c import _plant_layout_machine_catalog, _plant_layout_public_payload


class PlantMapPayloadTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.layout = PlantLayout.objects.create(category="Officina", name="Officina", image=_png(80, 40), is_active=True)

    def _place(self, asset, x=20, y=30, layout=None):
        return PlantLayoutMarker.objects.create(layout=layout or self.layout, asset=asset, x_percent=x, y_percent=y)

    def test_unplaced_and_retired_are_hidden_and_counted(self):
        placed = Asset.objects.create(asset_tag="MAP-1", name="Tornio", reparto="TRN")
        stray = Asset.objects.create(asset_tag="MAP-2", name="Mai collocata", reparto="TRN")
        retired = Asset.objects.create(asset_tag="MAP-3", name="Dismessa", reparto="TRN", status=Asset.STATUS_RETIRED)
        self._place(placed)
        self._place(stray, 50, 50)
        self._place(retired)
        payload = _plant_layout_public_payload(self.layout)
        self.assertEqual([m["asset_id"] for m in payload["markers"]], [placed.id])
        self.assertEqual(payload["unplaced_count"], 1)
        self.assertEqual(payload["retired_hidden"], 1)

    def test_chemicals_are_not_placeable(self):
        chem = Asset.objects.create(asset_tag="MAP-CH", name="Solvente", asset_type=Asset.TYPE_CHEMICAL)
        machine = Asset.objects.create(asset_tag="MAP-WM", name="Fresa", asset_type=Asset.TYPE_WORK_MACHINE)
        ids = {row["id"] for row in _plant_layout_machine_catalog()}
        self.assertIn(machine.id, ids)
        self.assertNotIn(chem.id, ids)

    def test_old_overdue_legal_and_admin_deadlines(self):
        today = timezone.localdate()
        plan = MaintenanceInterventionTemplate.objects.create(code="map-old", label="Controllo")
        old = Asset.objects.create(asset_tag="MAP-OLD", name="Pressa", reparto="PRS")
        crane = Asset.objects.create(asset_tag="MAP-CR", name="Carroponte", reparto="PRS", asset_type=Asset.TYPE_CARROPONTE)
        soon = Asset.objects.create(asset_tag="MAP-SOON", name="Gru a bandiera", reparto="PRS")
        MaintenanceOccurrence.objects.create(plan=plan, asset=old, due_date=today - timedelta(days=45))
        verifica = PeriodicVerification.objects.create(name="Verifica INAIL", next_verification_date=today - timedelta(days=2))
        verifica.assets.add(crane)
        prossima = PeriodicVerification.objects.create(name="Verifica funi", next_verification_date=today + timedelta(days=10))
        prossima.assets.add(soon)
        for i, asset in enumerate((old, crane, soon)):
            self._place(asset, 10 + i * 10, 20)
        payload = _plant_layout_public_payload(self.layout)
        by_asset = {m["asset_id"]: m for m in payload["markers"]}
        self.assertEqual(by_asset[old.id]["alert"], "overdue")
        self.assertEqual(by_asset[old.id]["machine"]["overdue_days"], 45)
        self.assertEqual(by_asset[crane.id]["alert"], "legal")
        self.assertTrue(by_asset[crane.id]["machine"]["legal"][0]["scaduta"])
        self.assertEqual(by_asset[soon.id]["alert"], "due_soon")
        self.assertEqual(payload["reparti"][0]["name"], "PRS")
        self.assertEqual(payload["reparti"][0]["alerts"], 3)

    def test_elsewhere_index_lists_other_active_plans_only(self):
        other = PlantLayout.objects.create(category="Carroponti", name="Carroponti", image=_png(40, 40), is_active=True)
        draft = PlantLayout.objects.create(category="Bozze", name="Bozza", image=_png(40, 40), is_active=False)
        here = Asset.objects.create(asset_tag="MAP-H", name="Qui")
        there = Asset.objects.create(asset_tag="MAP-T", name="Là")
        hidden = Asset.objects.create(asset_tag="MAP-D", name="In bozza")
        self._place(here)
        self._place(there, layout=other)
        self._place(hidden, layout=draft)
        rows = _plant_layout_public_payload(self.layout)["elsewhere"]
        self.assertEqual([r["asset_id"] for r in rows], [there.id])
        self.assertIn("asset=%d" % there.id, rows[0]["url"])
        self.assertEqual(rows[0]["layout"], "Carroponti")

    def test_cnc_live_day_timeline_and_board(self):
        cnc = Asset.objects.create(asset_tag="MAP-CNC", name="DMU 65", asset_type=Asset.TYPE_CNC)
        self._place(cnc)
        now = timezone.now()
        coll = CollegamentoMTConnect.objects.create(
            asset=cnc, url_agent="http://10.0.5.30:5000", codice="DM6", stato="in_lavoro",
            stato_dal=now - timedelta(minutes=30), controllato_il=now - timedelta(minutes=1), programma="O1234",
        )
        start = max(timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0), now - timedelta(hours=2))
        PeriodoStatoMacchina.objects.create(collegamento=coll, stato="ferma", dal=start, al=now - timedelta(minutes=30))
        PeriodoStatoMacchina.objects.create(collegamento=coll, stato="in_lavoro", dal=now - timedelta(minutes=30))
        payload = _plant_layout_public_payload(self.layout)
        live = payload["markers"][0]["machine"]["live"]
        self.assertEqual(live["codice"], "DM6")
        self.assertEqual([s["stato"] for s in live["giornata"]], ["ferma", "in_lavoro"])
        self.assertGreater(live["utilizzo"], 0)
        self.assertEqual(live["da_quanto"], "30 min")
        self.assertEqual(payload["cnc"], {"total": 1, "in_lavoro": 1, "setup": 0, "ferma": 0, "allarme": 0, "spenta": 0})


class PlantMapViewTests(_MediaMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.layout = PlantLayout.objects.create(category="Officina", name="Officina", image=_png(80, 40), is_active=True)
        self.asset = Asset.objects.create(asset_tag="MAPV-1", name="Tornio", reparto="TRN", internal_number="T01")
        PlantLayoutMarker.objects.create(layout=self.layout, asset=self.asset, x_percent=20, y_percent=30)
        self.admin = get_user_model().objects.create_superuser(username="mapv", email="mapv@test.local", password="x")
        _complete_onboarding(self.admin)

    def test_json_state_needs_login_and_returns_payload(self):
        url = reverse("assets:plant_layout_map") + "?format=json"
        anon = self.client.get(url, HTTP_ACCEPT="application/json")
        self.assertEqual(anon.status_code, 401)
        self.assertEqual(anon["Content-Type"], "application/json")
        self.client.force_login(self.admin)
        data = self.client.get(url).json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["layout_id"], self.layout.id)
        self.assertEqual(data["payload"]["markers"][0]["asset_id"], self.asset.id)

    def test_print_sheet_numbers_machines(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:plant_layout_map") + "?stampa=1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@page{size:A3 landscape")
        self.assertContains(response, 'class="pp-n"')
        self.assertContains(response, "Reparto TRN")
        self.assertContains(response, "T01")

    def test_map_page_renders_new_controls(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:plant_layout_map"))
        self.assertContains(response, "Stampa A3")
        self.assertContains(response, "data-pl-fresh")
        self.assertNotContains(response, "{#")


class PlantPositionHistoryTests(_MediaMixin, TestCase):
    def test_changes_are_classified(self):
        from assets.forms import _plant_marker_position_changes

        before = {1: (50.0, 50.0), 2: (10.0, 10.0), 3: (20.0, 20.0), 4: (30.0, 30.0)}
        after = {1: (12.0, 40.0), 2: (10.5, 10.5), 3: (40.0, 20.0), 5: (60.0, 10.0)}
        self.assertEqual(
            _plant_marker_position_changes(before, after),
            [(1, "collocata"), (3, "spostata"), (4, "tolta"), (5, "collocata")],
        )

    def test_editor_save_writes_asset_timeline_and_deactivate(self):
        layout = PlantLayout.objects.create(category="Officina", name="Officina A", image=_png(80, 40), is_active=True)
        asset = Asset.objects.create(asset_tag="HIST-1", name="Tornio")
        marker = PlantLayoutMarker.objects.create(layout=layout, asset=asset, x_percent=50, y_percent=50)
        admin = get_user_model().objects.create_superuser(username="plx-hist", email="plxh@test.local", password="x")
        _complete_onboarding(admin)
        self.client.force_login(admin)
        markers = [{"id": marker.id, "asset_id": asset.id, "label": "", "x_percent": 22, "y_percent": 33, "sort_order": 10}]
        with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)), \
                patch("admin_portale.decorators.is_legacy_admin", return_value=True):
            self.client.post(reverse("assets:plant_layout_editor"), {
                "layout_id": layout.id, "category": "Officina", "name": "Officina A", "description": "",
                "is_active": "on", "areas_payload": "[]", "markers_payload": __import__("json").dumps(markers),
            })
            entry = AssetTimelineEntry.objects.get(asset=asset)
            self.assertEqual(entry.title, "Collocata sulla planimetria")
            self.assertEqual(entry.tag, "PLANIMETRIA")
            self.assertEqual(entry.created_by, admin)
            self.client.post(reverse("assets:plant_layout_editor"), {"action": "deactivate_layout", "layout_id": layout.id})
        layout.refresh_from_db()
        self.assertFalse(layout.is_active)
