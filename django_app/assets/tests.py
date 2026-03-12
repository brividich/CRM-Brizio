from __future__ import annotations

import configparser
import io
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from types import SimpleNamespace
from PIL import Image

from anagrafica.models import Fornitore
from core.legacy_models import Pulsante
from core.models import UserDashboardLayout
from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

from . import views as asset_views
from .models import (
    Asset,
    AssetActionButton,
    AssetCategory,
    AssetCategoryField,
    AssetCustomField,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetEndpoint,
    AssetITDetails,
    AssetLabelTemplate,
    AssetListLayout,
    AssetListOption,
    AssetReportDefinition,
    AssetReportTemplate,
    AssetSidebarButton,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    WorkMachine,
    WorkOrder,
    WorkOrderAttachment,
)

User = get_user_model()

def _valid_png_upload(name: str = "planimetria.png") -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "#ffffff").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _attach_session(request) -> None:
    middleware = SessionMiddleware(lambda req: HttpResponse("ok"))
    middleware.process_request(request)
    request.session.save()


def _ensure_legacy_pulsanti_table() -> None:
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pulsanti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codice VARCHAR(100) NOT NULL,
                    nome_visibile VARCHAR(200) NULL,
                    icona VARCHAR(20) NULL,
                    modulo VARCHAR(100) NOT NULL,
                    url VARCHAR(500) NOT NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('pulsanti', 'U') IS NULL
                CREATE TABLE pulsanti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    codice NVARCHAR(100) NOT NULL,
                    nome_visibile NVARCHAR(200) NULL,
                    icona NVARCHAR(20) NULL,
                    modulo NVARCHAR(100) NOT NULL,
                    url NVARCHAR(500) NOT NULL
                )
                """
            )


def _build_workbook(path: Path, sheet_name: str = "LAN A 203.0.113.x") -> None:
    headers = [
        "REPARTO",
        "NOME PC",
        "TIPO",
        "MODELLO",
        "ID",
        "VLAN",
        "IP",
        "SWITCH",
        "PORTA SWITCH",
        "PUNTO",
        "OS",
        "CPU",
        "RAM",
        "DISCO",
        "DOMAIN",
        "EDPR",
        "AD360",
        "2FA OFFICE",
        "PSW BIOS",
        "ULTIMA MTZ",
    ]
    row_values = [
        "IT",
        "PC-UFFICIO-01",
        "PC",
        "Dell 5520",
        "SN-123",
        23,
        "198.51.100.23",
        "SW-01",
        "Gi1/0/15",
        "A-10",
        "Windows 11",
        "i7",
        "16GB",
        "512GB SSD",
        "SI",
        "SI",
        "NO",
        "SI",
        "present",
        "2026-01-15",
    ]
    _build_workbook_custom(path, sheet_name=sheet_name, headers=headers, rows=[row_values], header_row=5)


def _build_workbook_custom(
    path: Path,
    *,
    sheet_name: str,
    headers: list[str],
    rows: list[list[object]],
    header_row: int = 5,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for col_idx, header in enumerate(headers, start=1):
        ws.cell(row=header_row, column=col_idx, value=header)
    for row_offset, row_values in enumerate(rows, start=1):
        for col_idx, value in enumerate(row_values, start=1):
            ws.cell(row=header_row + row_offset, column=col_idx, value=value)
    wb.save(path)


def _build_work_machine_workbook(path: Path, rows: list[list[object]]) -> None:
    _build_workbook_custom(
        path,
        sheet_name="Foglio1",
        headers=[
            "REPARTO",
            "Name",
            "X (mm)",
            "Y (mm)",
            "Z (mm)",
            "DIAMETER (mm)",
            "Spindle (mm)",
            "Year",
            "TMC",
            "TCR",
            "Pressure (bar)",
            "CNC",
            "5 AXES",
            "Accuracy from",
        ],
        rows=rows,
        header_row=1,
    )


def _label_template_payload(*, preview_asset_id: int | None = None, **overrides) -> dict[str, str]:
    payload = {
        "name": "Layout officina",
        "page_width_mm": "110",
        "page_height_mm": "70",
        "qr_size_mm": "28",
        "qr_position": "LEFT",
        "show_logo": "on",
        "logo_height_mm": "11",
        "logo_alignment": "CENTER",
        "title_font_size_pt": "18",
        "body_font_size_pt": "9",
        "show_border": "on",
        "border_radius_mm": "6",
        "show_field_labels": "on",
        "show_target_label": "on",
        "show_help_text": "on",
        "background_color": "#F8FAFC",
        "border_color": "#0F172A",
        "text_color": "#111827",
        "accent_color": "#2563EB",
        "title_primary_field": "asset_tag",
        "title_secondary_field": "name",
        "body_fields_payload": json.dumps(["asset_type", "reparto", "year", "cnc_controlled"]),
    }
    if preview_asset_id:
        payload["preview_asset_id"] = str(preview_asset_id)
    payload.update(overrides)
    return payload


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetsRoutingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="asset-user", password="pass12345")
        self.factory = RequestFactory()
        self._config_tmpdir = tempfile.TemporaryDirectory()
        self._config_path = Path(self._config_tmpdir.name) / "config.ini"
        self._config_path.write_text("", encoding="utf-8")
        self._config_patcher = patch("assets.views._assets_config_ini_path", return_value=self._config_path)
        self._config_patcher.start()

    def tearDown(self):
        self._config_patcher.stop()
        self._config_tmpdir.cleanup()
        super().tearDown()

    def test_assets_list_200_when_logged(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)

    def test_assets_list_200_when_logged_as_admin(self):
        admin = User.objects.create_superuser(
            username="asset-admin-list",
            email="asset-admin-list@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)

    def test_assets_list_falls_back_when_layout_table_is_unavailable(self):
        self.client.force_login(self.user)
        with patch.object(AssetListLayout.objects, "all", side_effect=DatabaseError("missing assets_assetlistlayout")):
            response = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inventario asset")
        self.assertContains(response, 'data-col-toggle="name" checked', html=False)

    def test_assets_list_persists_table_layout_server_side(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assets:asset_list"),
            data=json.dumps(
                {
                    "action": "save_asset_table_layout",
                    "context_key": "all",
                    "visible_columns": ["name", "status"],
                    "column_order": ["status", "name"],
                    "column_widths": {"name": 320},
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        saved_row = UserDashboardLayout.objects.get(legacy_user_id=-self.user.id)
        saved_layout = saved_row.layout["assets_table"]["all"]
        self.assertEqual(saved_layout["visible_columns"], ["name", "status"])
        self.assertEqual(saved_layout["column_order"], ["status", "name"])
        self.assertEqual(saved_layout["column_widths"], {"name": 320})

        page = self.client.get(reverse("assets:asset_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '"visible_columns": ["name", "status"]', html=False)
        self.assertContains(page, '"column_order": ["status", "name"]', html=False)
        self.assertContains(page, '"column_widths": {"name": 320}', html=False)

    def test_non_admin_cannot_create_custom_field(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_custom_field",
                "label": "Ubicazione Rack",
                "field_type": "TEXT",
                "is_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(AssetCustomField.objects.exists())

    def test_superuser_can_create_custom_field(self):
        admin = User.objects.create_superuser(username="asset-admin", email="asset-admin@test.local", password="pass12345")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_custom_field",
                "label": "Ubicazione Rack",
                "field_type": "TEXT",
                "is_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetCustomField.objects.filter(label="Ubicazione Rack").exists())

    def test_asset_form_renders_dynamic_custom_field(self):
        AssetCustomField.objects.create(code="ubicazione-rack", label="Ubicazione Rack", field_type="TEXT", is_active=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ubicazione Rack")

    def test_asset_list_firewall_context_shows_only_relevant_default_columns(self):
        firewall_asset = Asset.objects.create(
            asset_tag="IT-FW-001",
            name="Firewall bordo rete",
            asset_type=Asset.TYPE_FIREWALL,
            reparto="CED",
            manufacturer="Fortinet",
            model="FG-100F",
            serial_number="FGT123456",
            extra_columns={"rack_label": "ARM-12"},
        )
        AssetEndpoint.objects.create(
            asset=firewall_asset,
            endpoint_name="WAN",
            vlan=23,
            ip="192.0.2.10",
        )
        AssetCustomField.objects.create(code="rack_label", label="Rack label", field_type="TEXT", is_active=True)
        AssetCustomField.objects.create(code="x_mm", label="X (mm)", field_type="NUMBER", is_active=True)

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_list") + "?asset_type=FIREWALL")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Colonne")
        self.assertContains(response, 'assets.list.network', html=False)
        self.assertContains(response, 'data-col-toggle="vlan" checked', html=False)
        self.assertContains(response, 'data-col-toggle="ip" checked', html=False)
        self.assertContains(response, 'data-col-toggle="custom_rack_label" checked', html=False)
        self.assertNotContains(response, 'data-col-toggle="custom_x_mm" checked', html=False)
        self.assertContains(response, "192.0.2.10")
        self.assertContains(response, "23")

    def test_work_machine_list_200_when_logged(self):
        asset = Asset.objects.create(
            name="Tornio parallelo",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="OFF",
            source_key="manual-wm-test-list",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-test-list", year=2021, cnc_controlled=True)
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:work_machine_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tornio parallelo")

    def test_work_machine_dashboard_200_when_logged(self):
        asset = Asset.objects.create(
            name="Centro di lavoro officina",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-dashboard",
        )
        WorkMachine.objects.create(
            asset=asset,
            source_key="manual-wm-dashboard",
            year=2020,
            cnc_controlled=True,
            next_maintenance_date=date(2026, 3, 20),
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:work_machine_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dashboard officina")
        self.assertContains(response, "Centro di lavoro officina")
        self.assertContains(response, 'type="month"', html=False)
        self.assertContains(response, f'value="{timezone.localdate().strftime("%Y-%m")}"', html=False)

    def test_reports_dashboard_contains_month_selector(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:reports"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="month"', html=False)
        self.assertContains(response, f'value="{timezone.localdate().strftime("%Y-%m")}"', html=False)

    def test_admin_can_create_periodic_verification_with_supplier_and_assets(self):
        admin = User.objects.create_superuser(
            username="asset-periodic-admin",
            email="asset-periodic-admin@test.local",
            password="pass12345",
        )
        supplier = Fornitore.objects.create(ragione_sociale="Verifiche Industriali Srl", categoria=Fornitore.CATEGORIA_MANUTENZIONE)
        asset = Asset.objects.create(
            name="Carroponte 5T",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="OFF",
            source_key="manual-periodic-carroponte",
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:periodic_verifications"),
            {
                "action": "create_periodic_verification",
                "name": "Verifica carroponte",
                "supplier": str(supplier.id),
                "frequency_months": "3",
                "last_verification_date": timezone.localdate().strftime("%Y-%m-%d"),
                "next_verification_date": "",
                "asset_ids": [str(asset.id)],
                "is_active": "on",
                "notes": "Controllo trimestrale gru a ponte",
            },
        )

        self.assertEqual(response.status_code, 302)
        verification = PeriodicVerification.objects.get(name="Verifica carroponte")
        self.assertEqual(verification.supplier, supplier)
        self.assertTrue(verification.assets.filter(pk=asset.id).exists())
        self.assertEqual(verification.frequency_months, 3)
        self.assertIsNotNone(verification.next_verification_date)

    def test_periodic_verification_page_contains_layout_controls_and_asset_search(self):
        admin = User.objects.create_superuser(
            username="asset-periodic-layout-admin",
            email="asset-periodic-layout-admin@test.local",
            password="pass12345",
        )
        Asset.objects.create(
            name="Carroponte reparto A",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="OFF",
            source_key="manual-periodic-layout-page",
        )

        self.client.force_login(admin)
        response = self.client.get(reverse("assets:periodic_verifications"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cerca asset coinvolti per tag o nome")
        self.assertContains(response, "Compatta")
        self.assertContains(response, "Bilanciata")
        self.assertContains(response, "Ampia")
        self.assertContains(response, "Seleziona visibili")

    def test_asset_edit_can_assign_multiple_periodic_verifications(self):
        asset = Asset.objects.create(
            name="Pressa assemblaggio",
            asset_type=Asset.TYPE_HW,
            reparto="ASS",
            status=Asset.STATUS_IN_USE,
            source_key="manual-periodic-asset-edit",
        )
        verification_a = PeriodicVerification.objects.create(name="Verifica elettrica", frequency_months=12)
        verification_b = PeriodicVerification.objects.create(name="Verifica sicurezza", frequency_months=6)

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assets:asset_edit", kwargs={"id": asset.id}),
            {
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "reparto": asset.reparto,
                "manufacturer": "",
                "model": "",
                "serial_number": "",
                "status": asset.status,
                "sharepoint_folder_url": "",
                "sharepoint_folder_path": "",
                "assignment_to": "",
                "assignment_reparto": "",
                "assignment_location": "",
                "notes": "",
                "periodic_verification_ids": [str(verification_a.id), str(verification_b.id)],
            },
        )

        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.periodic_verifications.count(), 2)
        detail_response = self.client.get(reverse("assets:asset_view", kwargs={"id": asset.id}))
        self.assertContains(detail_response, "Verifica elettrica")
        self.assertContains(detail_response, "Verifica sicurezza")

    def test_work_machine_maintenance_month_dataset_filters_month_and_reparto(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        next_month_start = (month_start + timedelta(days=32)).replace(day=1)

        asset_due = Asset.objects.create(
            name="Centro filtro reparto",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-month-report-cn5",
        )
        WorkMachine.objects.create(
            asset=asset_due,
            source_key="manual-wm-month-report-cn5",
            next_maintenance_date=month_start + timedelta(days=4),
            maintenance_reminder_days=15,
        )

        asset_other_reparto = Asset.objects.create(
            name="Centro altro reparto",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="TNC",
            source_key="manual-wm-month-report-tnc",
        )
        WorkMachine.objects.create(
            asset=asset_other_reparto,
            source_key="manual-wm-month-report-tnc",
            next_maintenance_date=month_start + timedelta(days=8),
            maintenance_reminder_days=15,
        )

        asset_other_month = Asset.objects.create(
            name="Centro mese successivo",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-month-report-next",
        )
        WorkMachine.objects.create(
            asset=asset_other_month,
            source_key="manual-wm-month-report-next",
            next_maintenance_date=next_month_start + timedelta(days=3),
            maintenance_reminder_days=15,
        )

        dataset = asset_views._build_work_machine_maintenance_month_dataset(
            month_value=month_start.strftime("%Y-%m"),
            reparto_filter="CN5",
            today=today,
        )

        self.assertEqual(dataset["total_count"], 1)
        self.assertEqual(len(dataset["rows"]), 1)
        self.assertEqual(dataset["rows"][0]["asset"].name, "Centro filtro reparto")
        self.assertEqual(dataset["rows"][0]["asset"].reparto, "CN5")
        self.assertEqual(dataset["month_code"], month_start.strftime("%Y-%m"))

    def test_work_machine_maintenance_month_pdf_returns_pdf(self):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        asset = Asset.objects.create(
            name="Centro PDF manutenzione",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-month-report-pdf",
        )
        WorkMachine.objects.create(
            asset=asset,
            source_key="manual-wm-month-report-pdf",
            next_maintenance_date=month_start + timedelta(days=6),
            maintenance_reminder_days=10,
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("assets:work_machine_maintenance_month_pdf"),
            {"month": month_start.strftime("%Y-%m"), "reparto": "CN5"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/pdf"))
        self.assertIn(".pdf", response["Content-Disposition"])
        self.assertIn(month_start.strftime("%Y-%m"), response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertGreater(len(response.content), 800)

    def test_plant_layout_map_renders_active_layout(self):
        asset = Asset.objects.create(
            name="Centro mappa",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-layout-map",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-layout-map", cnc_controlled=True)
        layout = PlantLayout.objects.create(
            category="Officina",
            name="Officina principale",
            description="Versione marzo",
            image=_valid_png_upload(),
            is_active=True,
        )
        PlantLayoutArea.objects.create(
            layout=layout,
            name="Reparto CN5",
            reparto_code="CN5",
            color="#2563EB",
            x_percent=5,
            y_percent=10,
            width_percent=30,
            height_percent=22,
        )
        PlantLayoutMarker.objects.create(
            layout=layout,
            asset=asset,
            label="ML-001",
            x_percent=16,
            y_percent=21,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:plant_layout_map"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Officina principale")
        self.assertContains(response, "Reparto CN5")
        self.assertContains(response, "Centro mappa")

    def test_plant_layout_map_can_switch_active_category(self):
        PlantLayout.objects.create(
            category="Officina",
            name="Officina principale",
            description="Layout reparto produttivo",
            image=_valid_png_upload("officina.png"),
            is_active=True,
        )
        PlantLayout.objects.create(
            category="TVCC",
            name="TVCC capannone",
            description="Layout telecamere",
            image=_valid_png_upload("tvcc.png"),
            is_active=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:plant_layout_map"), {"category": "TVCC"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TVCC capannone")
        self.assertContains(response, "TVCC")
        self.assertNotContains(response, "Officina principale")

    def test_non_admin_cannot_open_plant_layout_editor(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:plant_layout_editor"))
        self.assertEqual(response.status_code, 403)

    def test_admin_can_save_plant_layout_with_areas_and_markers(self):
        admin = User.objects.create_superuser(
            username="asset-layout-admin",
            email="asset-layout-admin@test.local",
            password="pass12345",
        )
        asset = Asset.objects.create(
            name="Centro da posizionare",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-layout-editor",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-layout-editor", cnc_controlled=True)

        self.client.force_login(admin)
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                with patch("admin_portale.decorators.get_legacy_user", return_value=SimpleNamespace(id=1, ruolo_id=1)):
                    with patch("admin_portale.decorators.is_legacy_admin", return_value=True):
                        response = self.client.post(
                            reverse("assets:plant_layout_editor"),
                            {
                                "action": "save_layout",
                                "layout_mode": "new",
                                "category": "TVCC",
                                "name": "Layout officina CN5",
                                "description": "Prima planimetria",
                                "is_active": "on",
                                "areas_payload": json.dumps(
                                    [
                                        {
                                            "name": "CN5",
                                            "reparto_code": "CN5",
                                            "color": "#2563EB",
                                            "notes": "Isola 1",
                                            "x_percent": 10,
                                            "y_percent": 8,
                                            "width_percent": 35,
                                            "height_percent": 24,
                                            "sort_order": 10,
                                        }
                                    ]
                                ),
                                "markers_payload": json.dumps(
                                    [
                                        {
                                            "asset_id": asset.id,
                                            "label": "ML-CN5",
                                            "x_percent": 18,
                                            "y_percent": 17,
                                            "sort_order": 10,
                                        }
                                    ]
                                ),
                                "image": _valid_png_upload(),
                            },
                        )

        self.assertEqual(response.status_code, 302)
        layout = PlantLayout.objects.get(name="Layout officina CN5")
        self.assertEqual(layout.category, "TVCC")
        self.assertTrue(layout.is_active)
        area = PlantLayoutArea.objects.get(layout=layout)
        marker = PlantLayoutMarker.objects.get(layout=layout, asset=asset)
        self.assertEqual(area.reparto_code, "CN5")
        self.assertEqual(marker.label, "ML-CN5")

    def test_work_machine_create_form_creates_asset_and_profile(self):
        self.client.force_login(self.user)
        with tempfile.TemporaryDirectory() as tmpdir:
            manual_file = SimpleUploadedFile("manuale.pdf", b"%PDF-1.4 test", content_type="application/pdf")
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                response = self.client.post(
                    reverse("assets:work_machine_create"),
                    {
                        "name": "Centro di lavoro 5 assi",
                        "reparto": "CN5",
                        "manufacturer": "DMG Mori",
                        "model": "DMC 85",
                        "serial_number": "DMG-550",
                        "status": Asset.STATUS_IN_USE,
                        "sharepoint_folder_url": "https://contoso.sharepoint.com/sites/example/Shared%20Documents/CN5/ML-TEST",
                        "sharepoint_folder_path": "Macchine/CN5/ML-TEST",
                        "assignment_to": "Officina",
                        "assignment_reparto": "CN5",
                        "assignment_location": "Corsia A",
                        "notes": "Inserimento manuale",
                        "x_mm": "850",
                        "y_mm": "700",
                        "z_mm": "500",
                        "diameter_mm": "120",
                        "spindle_mm": "180",
                        "year": "2022",
                        "tmc": "48",
                        "tcr_enabled": "on",
                        "pressure_bar": "6.5",
                        "cnc_controlled": "on",
                        "five_axes": "on",
                        "accuracy_from": "0.010",
                        "next_maintenance_date": "2026-03-30",
                        "maintenance_reminder_days": "15",
                        "documents_specs_payload": json.dumps(
                            [{"name": "Scheda tecnica", "url": "/docs/spec.pdf", "date": "06/03/2026", "size": "PDF"}]
                        ),
                        "documents_manuals_payload": json.dumps(
                            [{"name": "Manuale operatore", "url": "/docs/manuale.pdf", "date": "06/03/2026", "size": "v1"}]
                        ),
                        "documents_interventions_payload": json.dumps([]),
                        "upload_manuals_files": manual_file,
                    },
                )
                self.assertEqual(response.status_code, 302)
                asset = Asset.objects.get(name="Centro di lavoro 5 assi")
                self.assertEqual(asset.asset_type, Asset.TYPE_WORK_MACHINE)
                machine = WorkMachine.objects.get(asset=asset)
                self.assertEqual(machine.x_mm, 850)
                self.assertEqual(machine.tmc, 48)
                self.assertTrue(machine.tcr_enabled)
                self.assertTrue(machine.cnc_controlled)
                self.assertTrue(machine.five_axes)
                self.assertEqual(str(machine.next_maintenance_date), "2026-03-30")
                self.assertEqual(machine.maintenance_reminder_days, 15)
                self.assertEqual(asset.sharepoint_folder_url, "https://contoso.sharepoint.com/sites/example/Shared%20Documents/CN5/ML-TEST")
                self.assertEqual(asset.sharepoint_folder_path, "Macchine/CN5/ML-TEST")
                documents = asset.extra_columns.get("documents", [])
                self.assertEqual(len(documents), 2)
                self.assertEqual({row["category"] for row in documents}, {"SPECIFICHE", "MANUALI"})
                upload = AssetDocument.objects.get(asset=asset, category=AssetDocument.CATEGORY_MANUALI)
                self.assertEqual(upload.original_name, "manuale.pdf")
                self.assertTrue(Path(upload.file.path).exists())

    def test_asset_detail_shows_sharepoint_actions(self):
        asset = Asset.objects.create(
            name="Centro documentato",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-sharepoint-detail",
            sharepoint_folder_url="https://contoso.sharepoint.com/sites/example/Shared%20Documents/CN5/ML-000001",
            sharepoint_folder_path="Macchine/CN5/ML-000001",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-sharepoint-detail")
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": asset.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Archivio SharePoint")
        self.assertContains(response, "Apri etichetta QR")
        self.assertContains(response, "Apri cartella")

    def test_asset_detail_shows_report_pdf_button(self):
        asset = Asset.objects.create(
            name="Macchina report",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-report-button",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-report-button")
        self.client.force_login(self.user)

        response = self.client.get(reverse("assets:asset_view", kwargs={"id": asset.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Report PDF")
        self.assertContains(response, reverse("assets:asset_report_pdf", kwargs={"id": asset.id}))

    def test_asset_report_pdf_returns_pdf(self):
        asset = Asset.objects.create(
            name="Macchina report PDF",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-report-pdf",
            manufacturer="DMG",
            model="CMX 70",
        )
        WorkMachine.objects.create(
            asset=asset,
            source_key="manual-wm-report-pdf",
            year=2024,
            cnc_controlled=True,
            next_maintenance_date=date(2026, 4, 15),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("assets:asset_report_pdf", kwargs={"id": asset.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_asset_report_pdf_skips_template_query_when_table_is_unavailable(self):
        asset = Asset.objects.create(
            name="Macchina report senza template",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-report-no-template-table",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-report-no-template-table")
        self.client.force_login(self.user)

        with patch(
            "assets.views._model_table_exists",
            side_effect=lambda model: False if model is AssetReportTemplate else True,
        ):
            with patch.object(
                AssetReportTemplate.objects,
                "filter",
                side_effect=AssertionError("AssetReportTemplate query should not run"),
            ):
                response = self.client.get(reverse("assets:asset_report_pdf", kwargs={"id": asset.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_asset_qr_label_returns_pdf(self):
        asset = Asset.objects.create(
            name="Macchina QR",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CNC",
            source_key="manual-wm-qr",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-qr")
        AssetLabelTemplate.objects.update_or_create(
            code="default",
            defaults={
                "show_logo": True,
                "logo_height_mm": 10,
                "logo_alignment": AssetLabelTemplate.LOGO_ALIGNMENT_LEFT,
            },
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_qr_label", kwargs={"id": asset.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_non_admin_cannot_open_asset_label_designer(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_label_designer"))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse("assets:asset_list"))

    def test_superuser_can_open_asset_label_designer(self):
        admin = User.objects.create_superuser(
            username="asset-label-admin",
            email="asset-label-admin@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        response = self.client.get(reverse("assets:asset_label_designer"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Designer etichetta QR")
        self.assertTrue(AssetLabelTemplate.objects.filter(code="default").exists())

    def test_superuser_can_save_asset_label_template(self):
        admin = User.objects.create_superuser(
            username="asset-label-save-admin",
            email="asset-label-save-admin@test.local",
            password="pass12345",
        )
        asset = Asset.objects.create(
            name="Centro prova label",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-label-template",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-label-template", year=2023, cnc_controlled=True)
        self.client.force_login(admin)
        response = self.client.post(reverse("assets:asset_label_designer"), _label_template_payload(preview_asset_id=asset.id))
        self.assertEqual(response.status_code, 302)
        template = AssetLabelTemplate.objects.get(code="default")
        self.assertEqual(template.name, "Layout officina")
        self.assertEqual(template.qr_position, "LEFT")
        self.assertEqual(template.page_width_mm, 110)
        self.assertEqual(template.page_height_mm, 70)
        self.assertTrue(template.show_logo)
        self.assertEqual(template.logo_alignment, "CENTER")
        self.assertEqual(template.body_fields, ["asset_type", "reparto", "year", "cnc_controlled"])

    def test_resolve_asset_label_template_prefers_asset_override_then_type_then_default(self):
        asset = Asset.objects.create(
            name="Macchina priorita template",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-template-priority",
        )
        default_template = asset_views._get_default_asset_label_template()
        default_template.name = "Template generale"
        default_template.save()

        resolved = asset_views._resolve_asset_label_template(asset)
        self.assertEqual(resolved.pk, default_template.pk)

        type_template = AssetLabelTemplate.objects.create(
            asset_type=Asset.TYPE_WORK_MACHINE,
            name="Template tipologia",
        )
        resolved = asset_views._resolve_asset_label_template(asset)
        self.assertEqual(resolved.pk, type_template.pk)

        asset_template = AssetLabelTemplate.objects.create(asset=asset, name="Template personale")
        resolved = asset_views._resolve_asset_label_template(asset)
        self.assertEqual(resolved.pk, asset_template.pk)

    def test_superuser_can_save_asset_type_label_template(self):
        admin = User.objects.create_superuser(
            username="asset-label-type-admin",
            email="asset-label-type-admin@test.local",
            password="pass12345",
        )
        asset = Asset.objects.create(
            name="Centro per template tipologia",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-label-type-template",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-label-type-template", year=2024, cnc_controlled=True)
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_label_designer"),
            _label_template_payload(
                preview_asset_id=asset.id,
                scope=AssetLabelTemplate.SCOPE_ASSET_TYPE,
                scope_asset_type=Asset.TYPE_WORK_MACHINE,
                name="Template tipologia officina",
            ),
        )
        self.assertEqual(response.status_code, 302)
        template = AssetLabelTemplate.objects.get(
            scope=AssetLabelTemplate.SCOPE_ASSET_TYPE,
            asset_type=Asset.TYPE_WORK_MACHINE,
        )
        self.assertEqual(template.code, "type-work_machine")
        self.assertIsNone(template.asset)
        self.assertEqual(template.name, "Template tipologia officina")

    def test_superuser_can_save_asset_specific_label_template(self):
        admin = User.objects.create_superuser(
            username="asset-label-asset-admin",
            email="asset-label-asset-admin@test.local",
            password="pass12345",
        )
        asset = Asset.objects.create(
            name="Centro per override asset",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-label-asset-template",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-label-asset-template", year=2025, cnc_controlled=True)
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_label_designer"),
            _label_template_payload(
                preview_asset_id=asset.id,
                scope=AssetLabelTemplate.SCOPE_ASSET,
                scope_asset_id=str(asset.id),
                name="Override macchina 1",
            ),
        )
        self.assertEqual(response.status_code, 302)
        template = AssetLabelTemplate.objects.get(
            scope=AssetLabelTemplate.SCOPE_ASSET,
            asset=asset,
        )
        self.assertEqual(template.code, f"asset-{asset.id}")
        self.assertEqual(template.name, "Override macchina 1")
        self.assertEqual(asset_views._resolve_asset_label_template(asset).pk, template.pk)

    def test_superuser_can_upload_custom_logo_for_asset_label_template(self):
        admin = User.objects.create_superuser(
            username="asset-label-logo-admin",
            email="asset-label-logo-admin@test.local",
            password="pass12345",
        )
        png_logo = SimpleUploadedFile(
            "logo.png",
            (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x8d\xb1\x87\x00\x00\x00\x00IEND\xaeB`\x82"
            ),
            content_type="image/png",
        )
        self.client.force_login(admin)
        with tempfile.TemporaryDirectory() as tmpdir:
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                response = self.client.post(
                    reverse("assets:asset_label_designer"),
                    {
                        "name": "Template con logo",
                        "page_width_mm": "100",
                        "page_height_mm": "62",
                        "qr_size_mm": "24",
                        "qr_position": "RIGHT",
                        "show_logo": "on",
                        "logo_height_mm": "10",
                        "logo_alignment": "LEFT",
                        "title_font_size_pt": "16",
                        "body_font_size_pt": "8",
                        "show_border": "on",
                        "border_radius_mm": "4",
                        "show_field_labels": "on",
                        "show_target_label": "on",
                        "show_help_text": "on",
                        "show_target_url": "on",
                        "background_color": "#FFFFFF",
                        "border_color": "#111827",
                        "text_color": "#0F172A",
                        "accent_color": "#1D4ED8",
                        "title_primary_field": "asset_tag",
                        "title_secondary_field": "name",
                        "body_fields_payload": json.dumps(["asset_type", "reparto"]),
                        "logo_file": png_logo,
                    },
                )
                self.assertEqual(response.status_code, 302)
                template = AssetLabelTemplate.objects.get(code="default")
                self.assertTrue(bool(template.logo_file))
                self.assertTrue(Path(template.logo_file.path).exists())

    def test_gestione_admin_shows_sharepoint_config_card(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text(
                "\n".join(
                    [
                        "[AZIENDA]",
                        "tenant_id = tenant-test",
                        "client_id = client-test",
                        "client_secret = secret-test",
                        "site_id = site-test",
                        "",
                        "[ASSETS]",
                        "sharepoint_asset_root_path = Asset/Inventario",
                        "sharepoint_work_machine_root_path = Macchine",
                        "sharepoint_library_url = https://contoso.sharepoint.com/sites/example-assets",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            request = self.factory.get(reverse("assets:gestione_admin"), {"tab": "config"})
            _attach_session(request)
            request.user = self.user
            request.legacy_user = None
            setattr(request, "_messages", FallbackStorage(request))

            with patch("assets.views._assets_config_ini_path", return_value=config_path):
                response = asset_views.gestione_admin.__wrapped__(request)

            self.assertEqual(response.status_code, 200)
            content = response.content.decode("utf-8")
            self.assertIn("SharePoint / Microsoft Graph", content)
            self.assertIn("Asset/Inventario", content)
            self.assertIn("Macchine", content)

    def test_gestione_admin_shows_label_type_rows_and_overrides(self):
        asset = Asset.objects.create(
            name="Macchina override visibile",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            source_key="manual-wm-config-labels",
        )
        default_template = asset_views._get_default_asset_label_template()
        default_template.name = "Template generale assets"
        default_template.save()
        AssetLabelTemplate.objects.create(asset_type=Asset.TYPE_WORK_MACHINE, name="Template macchine di lavoro")
        AssetLabelTemplate.objects.create(asset=asset, name="Template personale macchina")

        request = self.factory.get(reverse("assets:gestione_admin"), {"tab": "config"})
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Etichette QR stampabili", content)
        self.assertIn("Fallback generale", content)
        self.assertIn("Template generale assets", content)
        self.assertIn("Macchina di lavoro", content)
        self.assertIn("Template macchine di lavoro", content)
        self.assertIn(asset.asset_tag, content)
        self.assertIn("Template personale macchina", content)

    def test_gestione_admin_can_delete_non_default_label_template(self):
        template = AssetLabelTemplate.objects.create(
            asset_type=Asset.TYPE_WORK_MACHINE,
            name="Template da eliminare",
        )
        request = self.factory.post(
            reverse("assets:gestione_admin"),
            {
                "action": "delete_label_template",
                "template_id": str(template.id),
            },
        )
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(AssetLabelTemplate.objects.filter(pk=template.pk).exists())

    def test_gestione_admin_can_save_sharepoint_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.ini"
            config_path.write_text("[AZIENDA]\nclient_secret = keep-me\n", encoding="utf-8")
            request = self.factory.post(
                reverse("assets:gestione_admin"),
                {
                    "action": "save_sharepoint_config",
                    "sharepoint_tenant_id": "tenant-new",
                    "sharepoint_client_id": "client-new",
                    "sharepoint_client_secret": "",
                    "sharepoint_site_id": "site-new",
                    "sharepoint_asset_root_path": "Asset/Inventario",
                    "sharepoint_work_machine_root_path": "Macchine",
                    "sharepoint_library_url": "https://contoso.sharepoint.com/sites/example-assets",
                },
            )
            _attach_session(request)
            request.user = self.user
            request.legacy_user = None
            setattr(request, "_messages", FallbackStorage(request))

            with patch("assets.views._assets_config_ini_path", return_value=config_path):
                response = asset_views.gestione_admin.__wrapped__(request)

            self.assertEqual(response.status_code, 302)
            cfg = configparser.ConfigParser()
            cfg.read(config_path, encoding="utf-8")
            self.assertEqual(cfg.get("AZIENDA", "tenant_id"), "tenant-new")
            self.assertEqual(cfg.get("AZIENDA", "client_id"), "client-new")
            self.assertEqual(cfg.get("AZIENDA", "site_id"), "site-new")
            self.assertEqual(cfg.get("AZIENDA", "client_secret"), "keep-me")
            self.assertEqual(cfg.get("ASSETS", "sharepoint_asset_root_path"), "Asset/Inventario")
            self.assertEqual(cfg.get("ASSETS", "sharepoint_work_machine_root_path"), "Macchine")

    def test_asset_edit_redirects_to_work_machine_edit_for_work_machine(self):
        asset = Asset.objects.create(
            name="Pressa officina",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CQF",
            source_key="manual-wm-test-redirect",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-test-redirect")
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_edit", kwargs={"id": asset.id}))
        self.assertRedirects(response, reverse("assets:work_machine_edit", kwargs={"id": asset.id}))

    def test_work_machine_dashboard_shows_overdue_reminder(self):
        asset = Asset.objects.create(
            name="Fresa produzione",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CNC",
            source_key="manual-wm-overdue",
        )
        WorkMachine.objects.create(
            asset=asset,
            source_key="manual-wm-overdue",
            next_maintenance_date=timezone.localdate() - timedelta(days=2),
            maintenance_reminder_days=7,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:work_machine_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scaduta da 2 gg")

    def test_superuser_can_create_list_option(self):
        admin = User.objects.create_superuser(username="asset-lists-admin", email="asset-lists@test.local", password="pass12345")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_list_option",
                "field_key": "reparto",
                "value": "CQF",
                "sort_order": "10",
                "is_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetListOption.objects.filter(field_key="reparto", value="CQF").exists())

    def test_superuser_can_create_action_button(self):
        admin = User.objects.create_superuser(
            username="asset-buttons-admin",
            email="asset-buttons@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_action_button",
                "label": "Apri scheda",
                "zone": "HEADER",
                "action_type": "LINK",
                "target": "/assets/view/{asset_id}/",
                "style": "PRIMARY",
                "sort_order": "10",
                "is_active": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetActionButton.objects.filter(label="Apri scheda", zone="HEADER").exists())

    def test_non_admin_cannot_export_admin_snapshot(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assets:asset_list"),
            {"action": "export_admin_snapshot"},
        )
        self.assertEqual(response.status_code, 302)

    def test_superuser_can_export_admin_snapshot(self):
        admin = User.objects.create_superuser(
            username="asset-export-admin",
            email="asset-export@test.local",
            password="pass12345",
        )
        AssetCustomField.objects.create(code="rack", label="Rack", field_type="TEXT", is_active=True)
        AssetListOption.objects.create(field_key="reparto", value="IT", sort_order=10, is_active=True)
        AssetActionButton.objects.create(
            code="asset-detail",
            label="Vai dettaglio",
            zone=AssetActionButton.ZONE_HEADER,
            action_type=AssetActionButton.TYPE_LINK,
            target="/assets/view/{asset_id}/",
            style=AssetActionButton.STYLE_PRIMARY,
            sort_order=10,
            is_active=True,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {"action": "export_admin_snapshot"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["Content-Type"].startswith("application/json"))
        payload = json.loads(response.content.decode("utf-8"))
        self.assertIn("asset_categories", payload)
        self.assertIn("asset_category_fields", payload)
        self.assertIn("custom_fields", payload)
        self.assertIn("list_options", payload)
        self.assertIn("action_buttons", payload)
        self.assertIn("detail_fields", payload)
        self.assertIn("sidebar_buttons", payload)
        self.assertEqual(payload["custom_fields"][0]["label"], "Rack")

    def test_admin_can_create_asset_category(self):
        admin = User.objects.create_superuser(
            username="asset-category-admin",
            email="asset-category@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_asset_category",
                "label": "Sistema allarme",
                "base_asset_type": Asset.TYPE_OTHER,
                "description": "Impianti antintrusione",
                "detail_specs_title": "Dati impianto",
                "detail_profile_title": "Profilo allarme",
                "sort_order": "20",
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AssetCategory.objects.filter(
                label="Sistema allarme",
                base_asset_type=Asset.TYPE_OTHER,
                detail_specs_title="Dati impianto",
            ).exists()
        )

    def test_asset_create_saves_category_specific_field_values(self):
        category = AssetCategory.objects.create(
            code="sistema-allarme",
            label="Sistema allarme",
            base_asset_type=Asset.TYPE_OTHER,
            is_active=True,
        )
        category_field = AssetCategoryField.objects.create(
            category=category,
            code="matricola_centrale",
            label="Matricola centrale",
            field_type=AssetCategoryField.TYPE_TEXT,
            detail_section=AssetDetailField.SECTION_SPECS,
            detail_value_format=AssetDetailField.FORMAT_TEXT,
            is_required=True,
            show_in_form=True,
            show_in_detail=True,
            is_active=True,
        )

        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assets:asset_create"),
            {
                "asset_tag": "",
                "name": "Centrale reparto 1",
                "asset_category": str(category.id),
                "asset_type": Asset.TYPE_HW,
                "reparto": "SIC",
                "manufacturer": "Ajax",
                "model": "Hub",
                "serial_number": "",
                "status": Asset.STATUS_IN_USE,
                "sharepoint_folder_url": "",
                "sharepoint_folder_path": "",
                "assignment_to": "",
                "assignment_reparto": "",
                "assignment_location": "",
                "notes": "",
                f"category__{category_field.code}": "ALM-001",
            },
        )

        self.assertEqual(response.status_code, 302)
        asset = Asset.objects.get(name="Centrale reparto 1")
        self.assertEqual(asset.asset_category, category)
        self.assertEqual(asset.asset_type, Asset.TYPE_OTHER)
        self.assertEqual(asset.extra_columns.get("_category_fields", {}).get("matricola_centrale"), "ALM-001")

    def test_asset_detail_uses_category_titles_and_category_field_values(self):
        category = AssetCategory.objects.create(
            code="pompa-di-calore",
            label="Pompa di calore",
            base_asset_type=Asset.TYPE_OTHER,
            detail_specs_title="Scheda impianto",
            detail_profile_title="Profilo macchina termica",
            detail_assignment_title="Referente impianto",
            detail_timeline_title="Storico impianto",
            detail_maintenance_title="Registro manutenzione termica",
            is_active=True,
        )
        AssetCategoryField.objects.create(
            category=category,
            code="potenza_kw",
            label="Potenza",
            field_type=AssetCategoryField.TYPE_NUMBER,
            detail_section=AssetDetailField.SECTION_SPECS,
            detail_value_format=AssetDetailField.FORMAT_TEXT,
            show_in_form=True,
            show_in_detail=True,
            is_active=True,
        )
        asset = Asset.objects.create(
            asset_tag="AST-CAT-001",
            name="Pompa di calore uffici",
            asset_type=Asset.TYPE_OTHER,
            asset_category=category,
            extra_columns={"_category_fields": {"potenza_kw": "18"}},
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pompa di calore")
        self.assertContains(response, "Scheda impianto")
        self.assertContains(response, "Profilo macchina termica")
        self.assertContains(response, "Referente impianto")
        self.assertContains(response, "Storico impianto")
        self.assertContains(response, "Registro manutenzione termica")
        self.assertContains(response, "Potenza")
        self.assertContains(response, "18")

    def test_admin_can_create_sidebar_child_button(self):
        admin = User.objects.create_superuser(
            username="asset-sidebar-admin",
            email="asset-sidebar@test.local",
            password="pass12345",
        )
        parent = AssetSidebarButton.objects.create(
            code="impianti",
            section=AssetSidebarButton.SECTION_MAIN,
            label="Impianti",
            target_url="django:assets:plant_layout_map",
            sort_order=10,
            is_visible=True,
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_sidebar_button",
                "label": "TVCC",
                "section": AssetSidebarButton.SECTION_ANALYTICS,
                "parent_sidebar_button_id": str(parent.id),
                "target_url": "django:assets:plant_layout_map?category=TVCC",
                "sort_order": "20",
                "is_visible": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        child = AssetSidebarButton.objects.get(label="TVCC")
        self.assertEqual(child.parent, parent)
        self.assertTrue(child.is_subitem)
        self.assertEqual(child.section, parent.section)

    def test_admin_can_create_asset_detail_field(self):
        admin = User.objects.create_superuser(
            username="asset-detail-admin",
            email="asset-detail@test.local",
            password="pass12345",
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_list"),
            {
                "action": "create_detail_field",
                "label": "Centro di costo",
                "section": AssetDetailField.SECTION_SPECS,
                "asset_scope": AssetDetailField.SCOPE_ALL,
                "source_ref": "custom:centro_di_costo",
                "value_format": AssetDetailField.FORMAT_TEXT,
                "sort_order": "90",
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AssetDetailField.objects.filter(
                label="Centro di costo",
                section=AssetDetailField.SECTION_SPECS,
                source_ref="custom:centro_di_costo",
            ).exists()
        )

    def test_asset_detail_can_render_configured_custom_detail_field(self):
        asset = Asset.objects.create(
            asset_tag="AST-DETAIL-001",
            name="Asset con dettaglio custom",
            asset_type=Asset.TYPE_OTHER,
            extra_columns={"centro_di_costo": "Produzione Nord"},
        )
        AssetCustomField.objects.create(
            code="centro_di_costo",
            label="Centro di costo",
            field_type=AssetCustomField.TYPE_TEXT,
            is_active=True,
        )
        AssetDetailField.objects.create(
            code="spec-centro-di-costo",
            label="Centro di costo",
            section=AssetDetailField.SECTION_SPECS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="custom:centro_di_costo",
            value_format=AssetDetailField.FORMAT_TEXT,
            sort_order=10,
            is_active=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Centro di costo")
        self.assertContains(response, "Produzione Nord")

    def test_asset_detail_shows_linked_closed_ticket(self):
        asset = Asset.objects.create(
            asset_tag="PCLBOVA",
            name="Notebook Luca Bova",
            asset_type=Asset.TYPE_HW,
        )
        ticket = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="Notebook non si avvia",
            descrizione="Il PC resta bloccato all'avvio.",
            categoria="PC",
            priorita=PrioritaTicket.MEDIA,
            stato=StatoTicket.CHIUSO,
            asset=asset,
            richiedente_nome=self.user.get_username(),
            richiedente_email="asset-user@test.local",
            closed_at=timezone.now(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ticket collegati")
        self.assertContains(response, ticket.numero_ticket)
        self.assertContains(response, "Notebook non si avvia")
        self.assertContains(response, "Chiuso")
        self.assertContains(response, reverse("tickets:detail", kwargs={"pk": ticket.pk}))

    def test_superuser_can_access_asset_detail_layout_admin_page(self):
        admin = User.objects.create_superuser(
            username="asset-layout-admin",
            email="asset-layout@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("assets:asset_detail_layout_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configura dettaglio asset")
        self.assertContains(response, "Riquadri fissi")

    def test_superuser_can_access_report_template_admin_page(self):
        admin = User.objects.create_superuser(
            username="asset-report-admin-page",
            email="asset-report-admin-page@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("assets:report_template_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gestione template report")
        self.assertContains(response, "Nuovo template")
        self.assertContains(response, "Report gestiti")

    def test_superuser_can_create_custom_report_definition(self):
        admin = User.objects.create_superuser(
            username="asset-report-definition-admin",
            email="asset-report-definition@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assets:report_template_admin"),
            {
                "action": "create_report_definition",
                "code": "asset-collaudo",
                "label": "Report collaudo asset",
                "description": "Report tecnico di collaudo",
                "sort_order": "30",
            },
        )

        self.assertEqual(response.status_code, 302)
        definition = AssetReportDefinition.objects.get(code="asset-collaudo")
        self.assertEqual(definition.label, "Report collaudo asset")

    def test_superuser_can_upload_report_template(self):
        admin = User.objects.create_superuser(
            username="asset-report-template-admin",
            email="asset-report-template@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        upload = SimpleUploadedFile(
            "scheda_asset.docx",
            b"fake-docx-template",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("assets:report_template_admin"),
                {
                    "action": "upload_report_template",
                    "report_code": AssetReportTemplate.REPORT_ASSET_DETAIL,
                    "name": "Scheda asset standard",
                    "version": "v1",
                    "description": "Template base per report asset",
                    "is_active": "1",
                    "template_file": upload,
                },
            )

            self.assertEqual(response.status_code, 302)
            template = AssetReportTemplate.objects.get(report_code=AssetReportTemplate.REPORT_ASSET_DETAIL)
            self.assertEqual(template.name, "Scheda asset standard")
            self.assertTrue(template.is_active)
            self.assertTrue(Path(template.file.path).exists())

    def test_superuser_can_upload_report_template_for_custom_report(self):
        admin = User.objects.create_superuser(
            username="asset-report-template-custom-admin",
            email="asset-report-template-custom@test.local",
            password="pass12345",
        )
        AssetReportDefinition.objects.create(
            code="asset-collaudo",
            label="Report collaudo asset",
            description="Report tecnico di collaudo",
            sort_order=30,
        )
        self.client.force_login(admin)
        upload = SimpleUploadedFile(
            "collaudo.xlsx",
            b"fake-xlsx-template",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("assets:report_template_admin"),
                {
                    "action": "upload_report_template",
                    "report_code": "asset-collaudo",
                    "name": "Template collaudo",
                    "version": "v2",
                    "description": "Formato officina",
                    "is_active": "1",
                    "template_file": upload,
                },
            )

            self.assertEqual(response.status_code, 302)
            template = AssetReportTemplate.objects.get(report_code="asset-collaudo")
            self.assertEqual(template.name, "Template collaudo")

    def test_delegated_user_can_access_asset_detail_layout_admin_page(self):
        self.client.force_login(self.user)
        with patch("assets.views.user_can_modulo_action", return_value=True):
            response = self.client.get(reverse("assets:asset_detail_layout_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Campi categoria")

    def test_asset_detail_layout_admin_shows_bulk_controls_for_fixed_sections(self):
        admin = User.objects.create_superuser(
            username="asset-layout-bulk-ui-admin",
            email="asset-layout-bulk-ui@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("assets:asset_detail_layout_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modifica massiva")
        self.assertContains(response, "Applica parametro")
        self.assertContains(response, 'name="selected_layout_ids"', html=False)

    def test_asset_detail_layout_admin_can_apply_bulk_size_to_all_sections(self):
        admin = User.objects.create_superuser(
            username="asset-layout-bulk-size-admin",
            email="asset-layout-bulk-size@test.local",
            password="pass12345",
        )
        asset_views._ensure_default_asset_detail_section_layouts()
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "update_detail_section_layout_bulk",
                "bulk_field": "grid_size",
                "bulk_grid_size": AssetDetailSectionLayout.SIZE_FULL,
                "apply_scope": "all",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AssetDetailSectionLayout.objects.exclude(grid_size=AssetDetailSectionLayout.SIZE_FULL).exists()
        )

    def test_asset_detail_layout_admin_can_apply_bulk_visibility_to_selected_sections(self):
        admin = User.objects.create_superuser(
            username="asset-layout-bulk-visible-admin",
            email="asset-layout-bulk-visible@test.local",
            password="pass12345",
        )
        section_layouts = asset_views._ensure_default_asset_detail_section_layouts()
        AssetDetailSectionLayout.objects.update(is_visible=True)
        selected_ids = [section_layouts[0].id, section_layouts[1].id]
        untouched_id = section_layouts[2].id
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "update_detail_section_layout_bulk",
                "bulk_field": "is_visible",
                "bulk_is_visible": "hidden",
                "apply_scope": "selected",
                "selected_layout_ids": [str(row_id) for row_id in selected_ids],
            },
        )

        self.assertEqual(response.status_code, 302)
        hidden_rows = set(
            AssetDetailSectionLayout.objects.filter(is_visible=False).values_list("id", flat=True)
        )
        self.assertEqual(hidden_rows, set(selected_ids))
        self.assertTrue(AssetDetailSectionLayout.objects.get(pk=untouched_id).is_visible)

    def test_asset_detail_shows_layout_button_for_layout_manager(self):
        asset = Asset.objects.create(
            asset_tag="AST-LAYOUT-001",
            name="Asset layout",
            asset_type=Asset.TYPE_OTHER,
        )
        self.client.force_login(self.user)

        with patch("assets.views.user_can_modulo_action", return_value=True):
            response = self.client.get(reverse("assets:asset_view", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Configura layout")

    def test_asset_detail_uses_layout_visibility_and_metric_sizes(self):
        admin = User.objects.create_superuser(
            username="asset-layout-render-admin",
            email="asset-layout-render@test.local",
            password="pass12345",
        )
        asset = Asset.objects.create(
            asset_tag="AST-LAYOUT-002",
            name="Asset render layout",
            asset_type=Asset.TYPE_OTHER,
            extra_columns={"uptime": "99.8%"},
        )
        AssetCustomField.objects.create(
            code="uptime",
            label="Uptime",
            field_type=AssetCustomField.TYPE_TEXT,
            is_active=True,
        )
        AssetDetailField.objects.create(
            code="metric-uptime",
            label="Uptime",
            section=AssetDetailField.SECTION_METRICS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="custom:uptime",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_FULL,
            sort_order=10,
            is_active=True,
        )
        AssetDetailSectionLayout.objects.update_or_create(
            code=AssetDetailSectionLayout.SECTION_QR,
            defaults={
                "grid_size": AssetDetailSectionLayout.SIZE_HALF,
                "sort_order": 240,
                "is_visible": False,
            },
        )

        self.client.force_login(admin)
        response = self.client.get(reverse("assets:asset_view", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'af-metric af-span-full', html=False)
        self.assertContains(response, "Uptime")
        self.assertNotContains(response, "QR asset")

    def test_layout_admin_can_hide_category_field_from_asset_detail(self):
        admin = User.objects.create_superuser(
            username="asset-layout-category-admin",
            email="asset-layout-category@test.local",
            password="pass12345",
        )
        category = AssetCategory.objects.create(
            code="caldaia",
            label="Caldaia",
            base_asset_type=Asset.TYPE_OTHER,
            is_active=True,
        )
        category_field = AssetCategoryField.objects.create(
            category=category,
            code="potenza_termica",
            label="Potenza termica",
            field_type=AssetCategoryField.TYPE_TEXT,
            detail_section=AssetDetailField.SECTION_SPECS,
            detail_value_format=AssetDetailField.FORMAT_TEXT,
            detail_card_size=AssetDetailField.CARD_HALF,
            show_in_form=True,
            show_in_detail=True,
            is_active=True,
        )
        asset = Asset.objects.create(
            asset_tag="AST-CAT-LAYOUT-001",
            name="Caldaia test",
            asset_type=Asset.TYPE_OTHER,
            asset_category=category,
            extra_columns={"_category_fields": {"potenza_termica": "120 kW"}},
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "update_asset_category_field",
                "category_field_id": str(category_field.id),
                "category_id": str(category.id),
                "label": category_field.label,
                "field_type": category_field.field_type,
                "detail_section": category_field.detail_section,
                "detail_value_format": category_field.detail_value_format,
                "detail_card_size": category_field.detail_card_size,
                "placeholder": category_field.placeholder,
                "help_text": category_field.help_text,
                "sort_order": str(category_field.sort_order),
                "show_in_form": "1",
                "is_active": "1",
            },
        )

        self.assertEqual(response.status_code, 302)
        category_field.refresh_from_db()
        self.assertFalse(category_field.show_in_detail)

        self.client.get(reverse("assets:asset_detail_layout_admin"))
        response = self.client.get(reverse("assets:asset_view", args=[asset.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Potenza termica")


class SeedAssetsACLTests(TestCase):
    def setUp(self):
        _ensure_legacy_pulsanti_table()

    def test_seed_acl_is_idempotent(self):
        call_command("seed_assets_acl")
        first_count = Pulsante.objects.filter(modulo="assets").count()
        self.assertGreaterEqual(first_count, 10)
        self.assertTrue(Pulsante.objects.filter(modulo="assets", codice="asset_detail_layout").exists())

        call_command("seed_assets_acl")
        second_count = Pulsante.objects.filter(modulo="assets").count()
        self.assertEqual(first_count, second_count)


class ImportAssetsExcelTests(TestCase):
    def test_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "assets.xlsx"
            _build_workbook(file_path)
            before_assets = Asset.objects.count()
            call_command(
                "import_assets_excel",
                file=str(file_path),
                sheets="LAN A 203.0.113.x",
                dry_run=True,
            )
            self.assertEqual(Asset.objects.count(), before_assets)

    def test_import_creates_asset_endpoint_and_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "assets.xlsx"
            _build_workbook(file_path)
            call_command(
                "import_assets_excel",
                file=str(file_path),
                sheets="LAN A 203.0.113.x",
            )
            self.assertEqual(Asset.objects.count(), 1)
            asset = Asset.objects.first()
            self.assertIsNotNone(asset)
            self.assertEqual(asset.name, "PC-UFFICIO-01")
            self.assertEqual(asset.asset_type, Asset.TYPE_PC)

            self.assertEqual(AssetEndpoint.objects.filter(asset=asset).count(), 1)
            endpoint = AssetEndpoint.objects.get(asset=asset)
            self.assertEqual(endpoint.vlan, 23)
            self.assertEqual(endpoint.ip, "198.51.100.23")

            self.assertTrue(AssetITDetails.objects.filter(asset=asset).exists())
            details = AssetITDetails.objects.get(asset=asset)
            self.assertTrue(details.domain_joined)
            self.assertTrue(details.edr_enabled)
            self.assertTrue(details.office_2fa_enabled)
            self.assertTrue(details.bios_pwd_set)

    def test_import_creates_custom_fields_for_unknown_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "assets-extra.xlsx"
            _build_workbook_custom(
                file_path,
                sheet_name="Macchine Officina",
                headers=["REPARTO", "NOME", "TIPO", "ID", "CENTRO COSTO", "CODICE INTERNO"],
                rows=[["CQF", "TORNIO-01", "CNC", "MAC-900", "OFFICINA-A", "INT-001"]],
                header_row=5,
            )
            call_command(
                "import_assets_excel",
                file=str(file_path),
                sheets="Macchine Officina",
            )
            asset = Asset.objects.get()
            self.assertEqual(asset.name, "TORNIO-01")
            self.assertEqual(asset.asset_type, Asset.TYPE_CNC)
            centro_field = AssetCustomField.objects.get(label="CENTRO COSTO")
            codice_field = AssetCustomField.objects.get(label="CODICE INTERNO")
            self.assertEqual(asset.extra_columns.get(centro_field.code), "OFFICINA-A")
            self.assertEqual(asset.extra_columns.get(codice_field.code), "INT-001")

    def test_import_sensitive_columns_store_presence_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "assets-sensitive.xlsx"
            _build_workbook_custom(
                file_path,
                sheet_name="Telefonia",
                headers=["NOME", "TIPO", "ID", "PIN SIM"],
                rows=[["SIM-DATA-01", "SIM", "ICCID-9988", "1234"]],
                header_row=5,
            )
            call_command(
                "import_assets_excel",
                file=str(file_path),
                sheets="Telefonia",
            )
            asset = Asset.objects.get()
            pin_field = AssetCustomField.objects.get(label="PIN SIM (presente)")
            self.assertEqual(pin_field.field_type, AssetCustomField.TYPE_BOOL)
            self.assertIs(asset.extra_columns.get(pin_field.code), True)
            self.assertNotIn("1234", [str(v) for v in asset.extra_columns.values()])

    def test_import_fuzzy_sheet_name_matching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "assets-sim.xlsx"
            _build_workbook_custom(
                file_path,
                sheet_name="sim telefonica",
                headers=["NOME", "TIPO", "ID"],
                rows=[["SIM-VOICE-01", "SIM", "ICCID-0001"]],
                header_row=1,
            )
            call_command(
                "import_assets_excel",
                file=str(file_path),
                sheets="SIM Telefonica",
            )
            asset = Asset.objects.get()
            self.assertEqual(asset.name, "SIM-VOICE-01")
            self.assertEqual(asset.serial_number, "ICCID-0001")


class ImportWorkMachinesExcelTests(TestCase):
    def test_import_creates_assets_and_work_machines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "macchine.xlsx"
            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["CN5", "DMG Mori DMC 160U", 1600, 1600, 1100, "-", "-", 2019, 183, "✓", "-", "✓", "-", "-"],
                    ["CN5", "DMG Mori DMC 160U", 1600, 1600, 1100, "-", "-", 2023, 243, "✓", "-", "✓", "✓", "0.010"],
                ],
            )

            call_command("import_work_machines_excel", file=str(file_path))

            self.assertEqual(Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).count(), 2)
            self.assertEqual(WorkMachine.objects.count(), 2)

            newer_asset = Asset.objects.get(source_key=WorkMachine.objects.get(year=2023).source_key)
            self.assertEqual(newer_asset.reparto, "CN5")
            self.assertEqual(newer_asset.manufacturer, "DMG Mori")
            self.assertEqual(newer_asset.model, "DMC 160U")

            newer_machine = WorkMachine.objects.get(asset=newer_asset)
            self.assertEqual(newer_machine.tmc, 243)
            self.assertTrue(newer_machine.tcr_enabled)
            self.assertTrue(newer_machine.cnc_controlled)
            self.assertTrue(newer_machine.five_axes)
            self.assertEqual(str(newer_machine.pressure_bar or ""), "")
            self.assertEqual(newer_machine.accuracy_from, "0.010")

    def test_import_updates_existing_machine_without_duplicate_assets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "macchine.xlsx"
            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["TNC", "DMG Ecturn 650", "-", "-", "-", "-", "-", 2019, "-", "✓", 6, "✓", "-", "-"],
                ],
            )
            call_command("import_work_machines_excel", file=str(file_path))

            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["TNC", "DMG Ecturn 650", "-", "-", "-", "-", "-", 2019, 12, "-", 8, "✓", "✓", "0.005"],
                ],
            )
            call_command("import_work_machines_excel", file=str(file_path))

            self.assertEqual(Asset.objects.filter(asset_type=Asset.TYPE_WORK_MACHINE).count(), 1)
            machine = WorkMachine.objects.get()
            self.assertEqual(machine.tmc, 12)
            self.assertFalse(machine.tcr_enabled)
            self.assertEqual(str(machine.pressure_bar), "8.00")
            self.assertTrue(machine.five_axes)
            self.assertEqual(machine.accuracy_from, "0.005")


class WorkOrderFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="wo.user",
            email="wo.user@example.com",
            password="secret123",
        )
        self.asset = Asset.objects.create(
            asset_tag="IT-000124",
            name="Server test",
            asset_type=Asset.TYPE_SERVER,
            status=Asset.STATUS_IN_USE,
        )

    def test_preventive_workorder_uses_periodic_verification_supplier_and_attachment(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Manutenzione Srl",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        verification = PeriodicVerification.objects.create(
            name="Controllo trimestrale",
            supplier=supplier,
            frequency_months=3,
            is_active=True,
        )
        verification.assets.add(self.asset)
        self.client.force_login(self.user)

        upload = SimpleUploadedFile("report.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(
                reverse("assets:wo_create", args=[self.asset.id]),
                {
                    "periodic_verification": str(verification.id),
                    "supplier": "",
                    "kind": WorkOrder.KIND_PREVENTIVE,
                    "status": WorkOrder.STATUS_OPEN,
                    "title": "Intervento programmato",
                    "description": "Controllo periodico",
                    "resolution": "",
                    "downtime_minutes": "0",
                    "cost_eur": "",
                    "attachments": upload,
                },
            )

        self.assertEqual(response.status_code, 302)
        workorder = WorkOrder.objects.get()
        self.assertEqual(workorder.periodic_verification, verification)
        self.assertEqual(workorder.supplier, supplier)
        self.assertEqual(WorkOrderAttachment.objects.filter(work_order=workorder).count(), 1)

    def test_non_programmed_workorder_allows_manual_supplier(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Assistenza Rapida Spa",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:wo_create", args=[self.asset.id]),
            {
                "periodic_verification": "",
                "supplier": str(supplier.id),
                "kind": WorkOrder.KIND_CORRECTIVE,
                "status": WorkOrder.STATUS_OPEN,
                "title": "Intervento urgente",
                "description": "Guasto improvviso",
                "resolution": "",
                "downtime_minutes": "15",
                "cost_eur": "120.00",
            },
        )

        self.assertEqual(response.status_code, 302)
        workorder = WorkOrder.objects.get(title="Intervento urgente")
        self.assertIsNone(workorder.periodic_verification)
        self.assertEqual(workorder.supplier, supplier)
