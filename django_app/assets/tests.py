from __future__ import annotations

import io
import json
import shutil
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook
from types import SimpleNamespace
from PIL import Image

from anagrafica.models import Fornitore, FornitoreDocumento
from core.legacy_models import AnagraficaDipendente, Pulsante, UtenteLegacy
from core.models import UserDashboardLayout, UserOnboarding
from core.upload_mime import UploadMimeValidationError
from tickets.models import PrioritaTicket, StatoTicket, Ticket, TipoTicket

from . import views as asset_views
from .forms import (
    AssetAdministrativeDeadlineForm,
    AssetComponentForm,
    MaintenanceRuleAssetOverrideForm,
    MaintenanceRuleForm,
)
from .maintenance import build_day_based_maintenance_schedule_rows, resolve_asset_maintenance_rules
from .models import (
    Asset,
    AssetActionButton,
    AssetAdministrativeDeadline,
    AssetAdministrativeDeadlineCompletion,
    AssetAdministrativeDeadlineCompletionAttachment,
    AssetCategory,
    AssetCategoryField,
    AssetComponent,
    AssetCustomField,
    AssetDetailField,
    AssetDetailSectionLayout,
    AssetDocument,
    AssetEndpoint,
    AssetITDetails,
    AssetLabelTemplate,
    AssetListLayout,
    AssetListOption,
    AssetMaintenanceRuleState,
    AssetCalendarEvent,
    MaintenanceInterventionTemplate,
    MaintenanceRule,
    MaintenanceRuleAssetOverride,
    AssistanceContract,
    AssetReportDefinition,
    AssetReportTemplate,
    AssetSidebarButton,
    PeriodicVerification,
    PlantLayout,
    PlantLayoutArea,
    PlantLayoutMarker,
    SoftwareLicense,
    WorkMachine,
    WorkOrder,
    WorkOrderAttachment,
)

User = get_user_model()


def _make_workspace_tempdir(prefix: str) -> Path:
    root = Path.cwd() / "django_app" / ".tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{prefix}{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=False)
    return target


@contextmanager
def _workspace_temporary_directory(prefix: str):
    target = _make_workspace_tempdir(prefix)
    try:
        yield str(target)
    finally:
        shutil.rmtree(target, ignore_errors=True)


def _complete_onboarding(user) -> None:
    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={
            "completed": True,
            "skipped": False,
            "completed_at": timezone.now(),
        },
    )


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


def _ensure_anagrafica_table() -> None:
    from core.legacy_anagrafica import ensure_anagrafica_schema

    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute("DROP TABLE IF EXISTS anagrafica_dipendenti")
            cursor.execute(
                """
                CREATE TABLE anagrafica_dipendenti (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    aliasusername VARCHAR(200) NULL,
                    nome VARCHAR(200) NULL,
                    cognome VARCHAR(200) NULL,
                    mansione VARCHAR(200) NULL,
                    reparto VARCHAR(200) NULL,
                    ruolo VARCHAR(200) NULL,
                    matricola VARCHAR(100) NULL,
                    attivo INTEGER NULL,
                    email VARCHAR(200) NULL,
                    email_notifica VARCHAR(200) NULL,
                    utente_id INTEGER NULL
                )
                """
            )
        else:
            cursor.execute(
                """
                IF OBJECT_ID('anagrafica_dipendenti', 'U') IS NOT NULL
                    DROP TABLE anagrafica_dipendenti
                CREATE TABLE anagrafica_dipendenti (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    aliasusername NVARCHAR(200) NULL,
                    nome NVARCHAR(200) NULL,
                    cognome NVARCHAR(200) NULL,
                    mansione NVARCHAR(200) NULL,
                    reparto NVARCHAR(200) NULL,
                    ruolo NVARCHAR(200) NULL,
                    matricola NVARCHAR(100) NULL,
                    attivo BIT NULL,
                    email NVARCHAR(200) NULL,
                    email_notifica NVARCHAR(200) NULL,
                    utente_id INT NULL
                )
                """
            )
    ensure_anagrafica_schema()


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
        _complete_onboarding(self.user)
        self.factory = RequestFactory()
        self._config_tmpdir = _make_workspace_tempdir("assets-config-")
        self._config_path = self._config_tmpdir / ".env"
        self._config_path.write_text("", encoding="utf-8")
        self._config_patcher = patch("config.env_config.default_env_path", return_value=self._config_path)
        self._config_patcher.start()

    def tearDown(self):
        self._config_patcher.stop()
        shutil.rmtree(self._config_tmpdir, ignore_errors=True)
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

    def test_dashboard_open_workorder_alert_rows_returns_empty_on_database_error(self):
        with patch.object(asset_views.WorkOrder.objects, "select_related", side_effect=DatabaseError("schema mismatch")):
            rows = asset_views._dashboard_open_workorder_alert_rows(limit=4)
        self.assertEqual(rows, [])

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

    def test_asset_list_firewall_context_uses_common_default_columns(self):
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
        self.assertContains(response, "Vista")
        self.assertContains(response, 'assets.list.network', html=False)
        self.assertContains(response, 'data-col-toggle="assignment_location" checked', html=False)
        self.assertContains(response, 'data-col-toggle="serial_number" checked', html=False)
        self.assertNotContains(response, 'data-col-toggle="vlan"', html=False)
        self.assertNotContains(response, 'data-col-toggle="ip"', html=False)
        self.assertNotContains(response, 'data-col-toggle="custom_rack_label"', html=False)
        self.assertContains(response, "Firewall bordo rete")
        self.assertContains(response, "FGT123456")
        self.assertNotContains(response, "192.0.2.10")

    def test_asset_dashboard_redirects_legacy_filtered_list_urls(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("assets:asset_dashboard"),
            {"asset_type": Asset.TYPE_FIREWALL, "rows": 25},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('assets:asset_list')}?asset_type={Asset.TYPE_FIREWALL}&rows=25",
        )

    def test_default_sidebar_seed_rows_use_canonical_asset_list_routes(self):
        targets_by_code = {
            row["code"]: row["target_url"]
            for row in asset_views._default_sidebar_seed_rows()
        }

        self.assertEqual(
            targets_by_code["dashboard"],
            "django:assets:asset_list?rows={rows}",
        )
        self.assertEqual(
            targets_by_code["networking"],
            "django:assets:asset_list?asset_type=FIREWALL&rows={rows}",
        )

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
        self.assertContains(response, 'class="wm-table"', html=False)
        self.assertContains(response, "Responsabile")
        self.assertContains(response, "Collocazione")
        self.assertContains(response, "Tornio parallelo")

    def test_device_list_uses_common_asset_table_columns(self):
        Asset.objects.create(
            asset_tag="IT-PC-001",
            name="Notebook amministrazione",
            asset_type=Asset.TYPE_PC,
            reparto="CED",
            assignment_to="Mario Rossi",
            assignment_location="Ufficio IT",
            manufacturer="Lenovo",
            model="T14",
            serial_number="SN-PC-001",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:device_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="dv-table"', html=False)
        self.assertContains(response, "Responsabile")
        self.assertContains(response, "Collocazione")
        self.assertContains(response, "Notebook amministrazione")
        self.assertContains(response, "SN-PC-001")

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
        response = self.client.get(reverse("assets:reports") + "?scope=production")
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
        response = self.client.get(reverse("assets:periodic_verifications") + "?scope=production")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cerca asset coinvolti per tag o nome")
        self.assertContains(response, "Compatta")
        self.assertContains(response, "Bilanciata")
        self.assertContains(response, "Ampia")
        self.assertContains(response, "Seleziona visibili")

    def test_legacy_periodic_verification_url_redirects_to_maintenance_route(self):
        admin = User.objects.create_superuser(
            username="asset-periodic-legacy-admin",
            email="asset-periodic-legacy-admin@test.local",
            password="pass12345",
        )
        self.client.force_login(admin)
        response = self.client.get("/assets/verifiche-periodiche/")
        self.assertRedirects(
            response,
            reverse("assets:periodic_verifications"),
            fetch_redirect_response=False,
        )

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
        with _workspace_temporary_directory("assets-layout-") as tmpdir:
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
        with _workspace_temporary_directory("assets-work-machine-form-") as tmpdir:
            manual_file = SimpleUploadedFile("manuale.pdf", b"%PDF-1.4 test", content_type="application/pdf")
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                with patch("assets.views.validate_extension_and_mime", return_value="application/pdf"):
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
                documents = asset.extra_columns.get("documents", [])
                self.assertEqual(len(documents), 2)
                self.assertEqual({row["category"] for row in documents}, {"SPECIFICHE", "MANUALI"})
                upload = AssetDocument.objects.get(asset=asset, category=AssetDocument.CATEGORY_MANUALI)
                self.assertEqual(upload.original_name, "manuale.pdf")
                self.assertTrue(Path(upload.file.path).exists())

    def test_work_machine_upload_sanitizes_name_and_uses_authenticated_download(self):
        self.client.force_login(self.user)
        with _workspace_temporary_directory("assets-work-machine-upload-") as tmpdir:
            manual_file = SimpleUploadedFile("../manuale rischio.pdf", b"%PDF-1.4 test", content_type="application/pdf")
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                with patch("assets.views.validate_extension_and_mime", return_value="application/pdf"):
                    response = self.client.post(
                        reverse("assets:work_machine_create"),
                        {
                            "name": "Centro upload locale",
                            "reparto": "CN5",
                            "status": Asset.STATUS_IN_USE,
                            "documents_specs_payload": json.dumps([]),
                            "documents_manuals_payload": json.dumps([]),
                            "documents_interventions_payload": json.dumps([]),
                            "upload_manuals_files": manual_file,
                        },
                    )
                self.assertEqual(response.status_code, 302)
                asset = Asset.objects.get(name="Centro upload locale")
                upload = AssetDocument.objects.get(asset=asset, category=AssetDocument.CATEGORY_MANUALI)
                self.assertEqual(upload.original_name, "manuale rischio.pdf")
                self.assertNotIn("..", upload.file.name)
                self.assertNotIn("\\", upload.file.name)

                edit_page = self.client.get(reverse("assets:work_machine_edit", args=[asset.id]))
                self.assertContains(edit_page, reverse("assets:asset_document_download", args=[upload.id]))
                self.assertNotContains(edit_page, "/media/assets_documents/")

                download = self.client.get(reverse("assets:asset_document_download", args=[upload.id]))
                self.assertEqual(download.status_code, 200)
                self.assertEqual(download["Content-Type"], "application/pdf")
                self.assertEqual(b"".join(download.streaming_content), b"%PDF-1.4 test")

    def test_sharepoint_remote_filename_is_unique_and_safe(self):
        asset = Asset.objects.create(
            name="Centro SharePoint filename",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CN5",
            sharepoint_folder_path="Macchine/CN5/ML-000099",
            source_key="manual-wm-sp-filename",
        )
        with _workspace_temporary_directory("assets-sp-filename-") as tmpdir, override_settings(MEDIA_ROOT=Path(tmpdir)):
            document = AssetDocument.objects.create(
                asset=asset,
                category=AssetDocument.CATEGORY_MANUALI,
                file=SimpleUploadedFile("manuale rischio.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                original_name='manuale: rischio?.pdf',
            )
            remote_name = asset_views._sharepoint_document_remote_filename(document)

        self.assertIn(str(document.id), remote_name)
        self.assertTrue(remote_name.endswith("manuale- rischio-.pdf"))
        self.assertNotIn(":", remote_name)
        self.assertNotIn("?", remote_name)

    def test_default_sharepoint_path_sanitizes_folder_segments(self):
        asset = Asset.objects.create(
            name="Centro path sicuro",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto='CN5/Linea?#%{}~&',
            source_key="manual-wm-sp-path-safe",
        )

        path = asset_views._default_asset_sharepoint_path(asset)

        self.assertIn(f"/CN5-Linea-/{asset.id}", path)
        for char in '\\:*?"<>|#%{}~&':
            self.assertNotIn(char, path)

    def test_asset_edit_assignment_from_anagrafica_autofills_department_and_location(self):
        self.client.force_login(self.user)
        legacy_user = UtenteLegacy.objects.create(
            nome="Bova Luca",
            email="l.bova@example.local",
            password="x",
            attivo=True,
        )
        anagrafica = AnagraficaDipendente.objects.create(
            nome="Luca",
            cognome="Bova",
            reparto="CED",
            mansione="IT",
            email="l.bova@example.local",
            email_notifica="l.bova@example.com",
            utente=legacy_user,
        )
        asset = Asset.objects.create(
            asset_tag="IT-AUTOASSIGN",
            name="Firewall assegnazione",
            asset_type=Asset.TYPE_FIREWALL,
            reparto="CED",
            status=Asset.STATUS_IN_USE,
            source_key="asset-autoassign",
        )

        response = self.client.post(
            reverse("assets:asset_edit", args=[asset.id]),
            {
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "reparto": asset.reparto,
                "manufacturer": "",
                "model": "M270",
                "serial_number": "FW-1",
                "status": Asset.STATUS_IN_USE,
                "assignment_mode": "employee",
                "assignment_employee_id": str(anagrafica.id),
                "assignment_to": "",
                "assignment_reparto": "",
                "assignment_location": "",
                "sharepoint_auto_folder": "on",
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        asset.refresh_from_db()
        self.assertEqual(asset.assignment_to, "Bova Luca")
        self.assertEqual(asset.assignment_reparto, "CED")
        self.assertEqual(asset.assignment_location, "CED")
        self.assertEqual(asset.assigned_legacy_user_id, legacy_user.id)

    def test_asset_assignment_payload_does_not_expose_employee_email(self):
        self.client.force_login(self.user)
        legacy_user = UtenteLegacy.objects.create(
            nome="Privacy Test",
            email="privacy@example.local",
            password="x",
            attivo=True,
        )
        AnagraficaDipendente.objects.create(
            nome="Privacy",
            cognome="Test",
            reparto="CED",
            mansione="IT",
            email="privacy@example.local",
            email_notifica="privacy@example.com",
            utente=legacy_user,
        )
        asset = Asset.objects.create(
            asset_tag="IT-PRIVACY",
            name="Asset privacy",
            asset_type=Asset.TYPE_FIREWALL,
            reparto="CED",
            status=Asset.STATUS_IN_USE,
            source_key="asset-privacy",
        )

        response = self.client.get(reverse("assets:asset_edit", args=[asset.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Privacy")
        self.assertNotContains(response, "privacy@example.local")
        self.assertNotContains(response, "privacy@example.com")

    def test_asset_edit_rejects_unknown_assignment_employee_id(self):
        self.client.force_login(self.user)
        asset = Asset.objects.create(
            asset_tag="IT-BADASSIGN",
            name="Firewall assegnazione invalida",
            asset_type=Asset.TYPE_FIREWALL,
            reparto="CED",
            status=Asset.STATUS_IN_USE,
            source_key="asset-badassign",
        )

        response = self.client.post(
            reverse("assets:asset_edit", args=[asset.id]),
            {
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "reparto": asset.reparto,
                "manufacturer": "",
                "model": "",
                "serial_number": "",
                "status": Asset.STATUS_IN_USE,
                "assignment_mode": "employee",
                "assignment_employee_id": "999999",
                "assignment_to": "",
                "assignment_reparto": "",
                "assignment_location": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seleziona un dipendente valido dall&#x27;anagrafica.")
        asset.refresh_from_db()
        self.assertEqual(asset.assigned_legacy_user_id, None)
        self.assertEqual(asset.assignment_to, "")

    def test_asset_edit_rejects_department_assignment_without_department(self):
        self.client.force_login(self.user)
        legacy_user = UtenteLegacy.objects.create(
            nome="Mario Rossi",
            email="m.rossi@example.local",
            password="x",
            attivo=True,
        )
        asset = Asset.objects.create(
            asset_tag="IT-DEPTEMPTY",
            name="Asset reparto vuoto",
            asset_type=Asset.TYPE_FIREWALL,
            reparto="CED",
            status=Asset.STATUS_IN_USE,
            assigned_legacy_user_id=legacy_user.id,
            assignment_to="Mario Rossi",
            assignment_reparto="CED",
            source_key="asset-dept-empty",
        )

        response = self.client.post(
            reverse("assets:asset_edit", args=[asset.id]),
            {
                "asset_tag": asset.asset_tag,
                "name": asset.name,
                "asset_type": asset.asset_type,
                "reparto": asset.reparto,
                "manufacturer": "",
                "model": "",
                "serial_number": "",
                "status": Asset.STATUS_IN_USE,
                "assignment_mode": "department",
                "assignment_employee_id": "",
                "assignment_department_value": "",
                "assignment_to": asset.assignment_to,
                "assignment_reparto": asset.assignment_reparto,
                "assignment_location": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Indica il reparto da assegnare.")
        asset.refresh_from_db()
        self.assertEqual(asset.assigned_legacy_user_id, legacy_user.id)
        self.assertEqual(asset.assignment_to, "Mario Rossi")

    def test_work_machine_department_assignment_creates_marker_and_auto_sharepoint_path(self):
        self.client.force_login(self.user)
        with _workspace_temporary_directory("assets-layout-upload-") as tmpdir:
            with override_settings(MEDIA_ROOT=Path(tmpdir)):
                layout = PlantLayout.objects.create(
                    category="Officina",
                    name="Layout officina",
                    image=_valid_png_upload(),
                    is_active=True,
                )
                response = self.client.post(
                    reverse("assets:work_machine_create"),
                    {
                        "asset_tag": "ML-AUTODEPT",
                        "name": "Totem reparto",
                        "asset_category": "",
                        "reparto": "CN5",
                        "manufacturer": "",
                        "model": "",
                        "serial_number": "TOTEM-1",
                        "status": Asset.STATUS_IN_USE,
                        "assignment_mode": "department",
                        "assignment_employee_id": "",
                        "assignment_department_value": "CN5",
                        "assignment_to": "",
                        "assignment_reparto": "",
                        "assignment_location": "",
                        "sharepoint_auto_folder": "on",
                        "include_in_plant_layout": "on",
                        "notes": "",
                        "documents_specs_payload": json.dumps([]),
                        "documents_manuals_payload": json.dumps([]),
                        "documents_interventions_payload": json.dumps([]),
                    },
                )
        self.assertEqual(response.status_code, 302)
        asset = Asset.objects.get(asset_tag="ML-AUTODEPT")
        self.assertEqual(asset.assignment_to, "Reparto CN5")
        self.assertEqual(asset.assignment_reparto, "CN5")
        self.assertEqual(asset.assignment_location, "CN5")
        self.assertEqual(asset.sharepoint_folder_path, f"Macchine/CN5/{asset.id}")
        self.assertTrue(PlantLayoutMarker.objects.filter(layout=layout, asset=asset, is_visible=True).exists())

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

    def test_asset_qr_label_defaults_to_sharepoint_folder_when_available(self):
        asset = Asset.objects.create(
            name="Macchina QR SharePoint",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CNC",
            sharepoint_folder_url="https://contoso.sharepoint.com/sites/assets/Shared%20Documents/ASSET%20CN/ML-QR",
            source_key="manual-wm-qr-sharepoint",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-qr-sharepoint")
        self.client.force_login(self.user)

        with patch("assets.views._draw_asset_label_pdf") as draw_label:
            response = self.client.get(reverse("assets:asset_qr_label", kwargs={"id": asset.id}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(draw_label.call_args.kwargs["target_url"], asset.sharepoint_folder_url)
        self.assertEqual(draw_label.call_args.kwargs["target_label"], "Cartella SharePoint")

    def test_asset_qr_label_detail_target_still_points_to_asset_detail(self):
        asset = Asset.objects.create(
            name="Macchina QR dettaglio",
            asset_type=Asset.TYPE_WORK_MACHINE,
            reparto="CNC",
            sharepoint_folder_url="https://contoso.sharepoint.com/sites/assets/Shared%20Documents/ASSET%20CN/ML-DET",
            source_key="manual-wm-qr-detail",
        )
        WorkMachine.objects.create(asset=asset, source_key="manual-wm-qr-detail")
        self.client.force_login(self.user)

        with patch("assets.views._draw_asset_label_pdf") as draw_label:
            response = self.client.get(f"{reverse('assets:asset_qr_label', kwargs={'id': asset.id})}?target=detail")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            draw_label.call_args.kwargs["target_url"],
            response.wsgi_request.build_absolute_uri(reverse("assets:asset_view", kwargs={"id": asset.id})),
        )
        self.assertEqual(draw_label.call_args.kwargs["target_label"], "Scheda asset")

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
        with _workspace_temporary_directory("assets-label-logo-") as tmpdir:
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
        tmpdir = _make_workspace_tempdir("assets-sharepoint-card-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text(
                "\n".join(
                    [
                        "GRAPH_TENANT_ID=tenant-test",
                        "GRAPH_CLIENT_ID=client-test",
                        "GRAPH_CLIENT_SECRET=secret-test",
                        "GRAPH_SITE_ID=site-test",
                        "ASSETS_SHAREPOINT_ASSET_ROOT_PATH=Asset/Inventario",
                        "ASSETS_SHAREPOINT_WORK_MACHINE_ROOT_PATH=Macchine",
                        "ASSETS_SHAREPOINT_LIBRARY_URL=https://contoso.sharepoint.com/sites/example-assets",
                    ]
                ),
                encoding="utf-8",
            )
            request = self.factory.get(reverse("assets:gestione_admin"), {"tab": "config"})
            _attach_session(request)
            request.user = self.user
            request.legacy_user = None
            setattr(request, "_messages", FallbackStorage(request))

            with patch("config.env_config.default_env_path", return_value=env_path), patch.dict(
                "assets.views.os.environ",
                {},
                clear=True,
            ):
                response = asset_views.gestione_admin.__wrapped__(request)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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

    def test_gestione_admin_shows_sidebar_management_card(self):
        AssetSidebarButton.objects.create(
            code="impianti",
            section=AssetSidebarButton.SECTION_MAIN,
            label="Impianti",
            target_url="django:assets:plant_layout_map",
            sort_order=10,
            is_visible=True,
        )

        request = self.factory.get(reverse("assets:gestione_admin"), {"tab": "config"})
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Menu laterale inventario", content)
        self.assertIn("Nuova voce sidebar", content)
        self.assertIn("Impianti", content)
        self.assertIn("assets-sidebar-target-options", content)
        self.assertIn("assets-sidebar-active-match-options", content)
        self.assertIn("django:assets:reports", content)
        self.assertIn("asset_type=SERVER", content)

    def test_gestione_admin_shows_asset_category_management_tab(self):
        category = AssetCategory.objects.create(
            code="sistema-allarme",
            label="Sistema allarme",
            base_asset_type=Asset.TYPE_OTHER,
            is_active=True,
        )
        Asset.objects.create(
            asset_tag="ALM-001",
            name="Centrale allarme reparto 1",
            asset_type=Asset.TYPE_OTHER,
            asset_category=category,
            status=Asset.STATUS_IN_USE,
            reparto="SIC",
        )
        AssetCategoryField.objects.create(
            category=category,
            code="matricola_centrale",
            label="Matricola centrale",
            field_type=AssetCategoryField.TYPE_TEXT,
            detail_section=AssetDetailField.SECTION_SPECS,
            detail_value_format=AssetDetailField.FORMAT_TEXT,
            show_in_form=True,
            show_in_detail=True,
            is_active=True,
        )

        request = self.factory.get(reverse("assets:gestione_admin"), {"tab": "categorie"})
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode("utf-8")
        self.assertIn("Nuova categoria", content)
        self.assertIn("Asset collegati", content)
        self.assertIn(f"asset_category={category.id}", content)
        self.assertIn(f"category-preview-{category.id}", content)
        self.assertIn("Campi dinamici di categoria", content)
        self.assertIn("Sistema allarme", content)
        self.assertIn("Centrale allarme reparto 1", content)
        self.assertIn("Matricola centrale", content)

    def test_gestione_admin_can_create_asset_category_from_categories_tab(self):
        request = self.factory.post(
            reverse("assets:gestione_admin"),
            {
                "action": "create_asset_category",
                "label": "Pompa di calore",
                "base_asset_type": Asset.TYPE_OTHER,
                "description": "Impianto termico",
                "detail_specs_title": "Scheda impianto",
                "sort_order": "15",
                "is_active": "1",
            },
        )
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('assets:gestione_admin')}?tab=categorie")
        self.assertTrue(
            AssetCategory.objects.filter(
                label="Pompa di calore",
                detail_specs_title="Scheda impianto",
            ).exists()
        )

    def test_gestione_admin_can_create_asset_category_field_from_categories_tab(self):
        category = AssetCategory.objects.create(
            code="tvcc",
            label="TVCC",
            base_asset_type=Asset.TYPE_OTHER,
            is_active=True,
        )
        request = self.factory.post(
            reverse("assets:gestione_admin"),
            {
                "action": "create_asset_category_field",
                "category_id": str(category.id),
                "label": "NVR principale",
                "field_type": AssetCategoryField.TYPE_TEXT,
                "detail_section": AssetDetailField.SECTION_SPECS,
                "detail_value_format": AssetDetailField.FORMAT_TEXT,
                "sort_order": "20",
                "show_in_form": "1",
                "show_in_detail": "1",
                "is_active": "1",
            },
        )
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('assets:gestione_admin')}?tab=categorie")
        self.assertTrue(
            AssetCategoryField.objects.filter(
                category=category,
                label="NVR principale",
            ).exists()
        )

    def test_gestione_admin_can_create_sidebar_button_for_asset_category(self):
        AssetSidebarButton.objects.all().delete()
        category = AssetCategory.objects.create(
            code="tvcc",
            label="TVCC",
            base_asset_type=Asset.TYPE_CCTV,
            is_active=True,
        )
        request = self.factory.post(
            reverse("assets:gestione_admin"),
            {
                "action": "create_sidebar_button_for_category",
                "category_id": str(category.id),
                "sidebar_label": "TVCC impianti",
                "section": AssetSidebarButton.SECTION_MAIN,
                "sort_order": "90",
            },
        )
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{reverse('assets:gestione_admin')}?tab=categorie")
        self.assertTrue(AssetSidebarButton.objects.filter(code="dashboard").exists())
        sidebar_item = AssetSidebarButton.objects.get(label="TVCC impianti")
        self.assertEqual(
            sidebar_item.target_url,
            f"django:assets:asset_list?asset_category={category.id}&rows={{rows}}",
        )
        self.assertEqual(sidebar_item.active_match, f"asset_category={category.id}")

    def test_asset_list_filters_by_asset_category(self):
        category = AssetCategory.objects.create(
            code="allarmi",
            label="Allarmi",
            base_asset_type=Asset.TYPE_OTHER,
            is_active=True,
        )
        other_category = AssetCategory.objects.create(
            code="tvcc",
            label="TVCC",
            base_asset_type=Asset.TYPE_CCTV,
            is_active=True,
        )
        Asset.objects.create(
            asset_tag="ALM-100",
            name="Centrale allarme",
            asset_type=Asset.TYPE_OTHER,
            asset_category=category,
        )
        Asset.objects.create(
            asset_tag="CAM-100",
            name="Telecamera ingresso",
            asset_type=Asset.TYPE_CCTV,
            asset_category=other_category,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_list"), {"asset_category": category.id})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Centrale allarme")
        self.assertContains(response, "Allarmi (1)")
        self.assertNotContains(response, "Telecamera ingresso")

    def test_gestione_admin_can_seed_sidebar_buttons(self):
        AssetSidebarButton.objects.all().delete()

        request = self.factory.post(
            reverse("assets:gestione_admin"),
            {
                "action": "seed_sidebar_buttons",
            },
        )
        _attach_session(request)
        request.user = self.user
        request.legacy_user = None
        setattr(request, "_messages", FallbackStorage(request))

        response = asset_views.gestione_admin.__wrapped__(request)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetSidebarButton.objects.filter(code="dashboard").exists())
        self.assertTrue(AssetSidebarButton.objects.filter(code="software_licenses").exists())

    def test_sidebar_input_suggestions_include_routes_and_filters(self):
        target_suggestions, active_match_suggestions = asset_views._sidebar_input_suggestions()

        target_values = {row["value"] for row in target_suggestions}
        active_values = {row["value"] for row in active_match_suggestions}

        self.assertIn("django:assets:reports", target_values)
        self.assertIn("django:assets:asset_list?asset_type=SERVER&rows={rows}", target_values)
        self.assertIn("/assets/reports/", active_values)
        self.assertIn("asset_type=SERVER", active_values)
        self.assertIn("reparto=", active_values)

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
        tmpdir = _make_workspace_tempdir("assets-sharepoint-save-")
        try:
            env_path = tmpdir / ".env"
            env_path.write_text("GRAPH_CLIENT_SECRET=keep-me\n", encoding="utf-8")
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

            with patch("config.env_config.default_env_path", return_value=env_path), patch.dict(
                "assets.views.os.environ",
                {},
                clear=True,
            ):
                response = asset_views.gestione_admin.__wrapped__(request)

            self.assertEqual(response.status_code, 302)
            content = env_path.read_text(encoding="utf-8")
            self.assertIn("GRAPH_TENANT_ID=tenant-new", content)
            self.assertIn("GRAPH_CLIENT_ID=client-new", content)
            self.assertIn("GRAPH_SITE_ID=site-new", content)
            self.assertIn("GRAPH_CLIENT_SECRET=keep-me", content)
            self.assertIn("ASSETS_SHAREPOINT_ASSET_ROOT_PATH=Asset/Inventario", content)
            self.assertIn("ASSETS_SHAREPOINT_WORK_MACHINE_ROOT_PATH=Macchine", content)
            self.assertIn("ASSETS_SHAREPOINT_LIBRARY_URL=https://contoso.sharepoint.com/sites/example-assets", content)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

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
        child = AssetSidebarButton.objects.get(label="TVCC", parent=parent)
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

        with _workspace_temporary_directory("assets-report-template-") as media_root, override_settings(MEDIA_ROOT=media_root):
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

        with _workspace_temporary_directory("assets-report-template-custom-") as media_root, override_settings(MEDIA_ROOT=media_root):
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

    def test_asset_detail_layout_admin_can_move_fixed_sections(self):
        admin = User.objects.create_superuser(
            username="asset-layout-move-admin",
            email="asset-layout-move@test.local",
            password="pass12345",
        )
        asset_views._ensure_default_asset_detail_section_layouts()
        self.client.force_login(admin)

        timeline_layout = AssetDetailSectionLayout.objects.get(code=AssetDetailSectionLayout.SECTION_TIMELINE)
        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "move_detail_section_layout",
                "layout_id": str(timeline_layout.id),
                "direction": "up",
            },
        )

        self.assertEqual(response.status_code, 302)
        ordered_codes = list(
            AssetDetailSectionLayout.objects.order_by("sort_order", "id").values_list("code", flat=True)
        )
        self.assertEqual(
            ordered_codes[:3],
            [
                AssetDetailSectionLayout.SECTION_TIMELINE,
                AssetDetailSectionLayout.SECTION_SPECS,
                AssetDetailSectionLayout.SECTION_MAINTENANCE,
            ],
        )

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

    def test_asset_detail_layout_admin_shows_bulk_controls_for_detail_fields(self):
        admin = User.objects.create_superuser(
            username="asset-layout-detail-bulk-ui-admin",
            email="asset-layout-detail-bulk-ui@test.local",
            password="pass12345",
        )
        AssetDetailField.objects.create(
            code="bulk-ui-detail-field",
            label="Seriale",
            section=AssetDetailField.SECTION_SPECS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:serial_number",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_THIRD,
            sort_order=10,
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("assets:asset_detail_layout_admin"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Modifica massiva campi")
        self.assertContains(response, 'value="update_detail_field_bulk"', html=False)
        self.assertContains(response, 'name="selected_detail_field_ids"', html=False)

    def test_asset_detail_layout_admin_can_apply_bulk_card_size_to_all_detail_fields(self):
        admin = User.objects.create_superuser(
            username="asset-layout-detail-bulk-size-admin",
            email="asset-layout-detail-bulk-size@test.local",
            password="pass12345",
        )
        field_a = AssetDetailField.objects.create(
            code="bulk-size-field-a",
            label="Produttore",
            section=AssetDetailField.SECTION_SPECS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:manufacturer",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_THIRD,
            sort_order=10,
            is_active=True,
        )
        field_b = AssetDetailField.objects.create(
            code="bulk-size-field-b",
            label="Modello",
            section=AssetDetailField.SECTION_SPECS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:model",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_HALF,
            sort_order=20,
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "update_detail_field_bulk",
                "bulk_field": "card_size",
                "bulk_card_size": AssetDetailField.CARD_FULL,
                "apply_scope": "all",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            set(
                AssetDetailField.objects.filter(pk__in=[field_a.id, field_b.id]).values_list("card_size", flat=True)
            ),
            {AssetDetailField.CARD_FULL},
        )

    def test_asset_detail_layout_admin_can_apply_bulk_active_state_to_selected_detail_fields(self):
        admin = User.objects.create_superuser(
            username="asset-layout-detail-bulk-active-admin",
            email="asset-layout-detail-bulk-active@test.local",
            password="pass12345",
        )
        field_a = AssetDetailField.objects.create(
            code="bulk-active-field-a",
            label="Produttore",
            section=AssetDetailField.SECTION_SPECS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:manufacturer",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_THIRD,
            sort_order=10,
            is_active=True,
        )
        field_b = AssetDetailField.objects.create(
            code="bulk-active-field-b",
            label="Modello",
            section=AssetDetailField.SECTION_METRICS,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:model",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_HALF,
            sort_order=20,
            is_active=True,
        )
        field_c = AssetDetailField.objects.create(
            code="bulk-active-field-c",
            label="Reparto",
            section=AssetDetailField.SECTION_PROFILE,
            asset_scope=AssetDetailField.SCOPE_ALL,
            source_ref="asset:reparto",
            value_format=AssetDetailField.FORMAT_TEXT,
            card_size=AssetDetailField.CARD_HALF,
            sort_order=30,
            is_active=True,
        )
        selected_ids = [field_a.id, field_b.id]
        self.client.force_login(admin)

        response = self.client.post(
            reverse("assets:asset_detail_layout_admin"),
            {
                "action": "update_detail_field_bulk",
                "bulk_field": "is_active",
                "bulk_is_active": "inactive",
                "apply_scope": "selected",
                "selected_detail_field_ids": [str(row_id) for row_id in selected_ids],
            },
        )

        self.assertEqual(response.status_code, 302)
        inactive_ids = set(
            AssetDetailField.objects.filter(pk__in=[field_a.id, field_b.id, field_c.id], is_active=False).values_list(
                "id", flat=True
            )
        )
        self.assertEqual(inactive_ids, set(selected_ids))
        self.assertTrue(AssetDetailField.objects.get(pk=field_c.id).is_active)

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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SoftwareLicenseTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="asset-license-admin",
            email="asset-license-admin@test.local",
            password="pass12345",
        )
        self.category = AssetCategory.objects.create(
            code="license-category",
            label="Categoria Licenze",
            base_asset_type=Asset.TYPE_PC,
            sort_order=10,
        )
        self.asset = Asset.objects.create(
            name="PC Licenze",
            asset_type=Asset.TYPE_PC,
            asset_category=self.category,
            reparto="IT",
            source_key="asset-license-main",
        )

    def test_software_license_list_renders(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("assets:software_license_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Licenze software")

    def test_software_license_list_creates_for_asset(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assets:software_license_list") + f"?asset={self.asset.id}",
            {
                "asset_id": str(self.asset.id),
                "action": "create_software_license",
                "category": SoftwareLicense.CATEGORY_SOFTWARE,
                "vendor": "Microsoft",
                "product_name": "Office 365",
                "edition": "Business Standard",
                "license_reference": "MS-001",
                "account_email": "it@example.local",
                "seats_total": "10",
                "seats_used": "5",
                "purchase_date": "2026-01-01",
                "renewal_date": "2026-12-01",
                "expiry_date": "2026-12-31",
                "auto_renew": "on",
                "is_active": "on",
                "notes": "Licenza asset",
                "assigned_employee_id": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        license_row = SoftwareLicense.objects.get(license_reference="MS-001")
        self.assertEqual(license_row.asset, self.asset)

    def test_software_license_list_creates_for_employee(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO anagrafica_dipendenti
                    (aliasusername, nome, cognome, reparto, email, attivo)
                VALUES
                    (%s, %s, %s, %s, %s, %s)
                """,
                ["a.rossi", "Alessia", "Rossi", "IT", "a.rossi@example.local", 1],
            )
            cursor.execute(
                """
                SELECT id
                FROM anagrafica_dipendenti
                WHERE aliasusername = %s
                """,
                ["a.rossi"],
            )
            row = cursor.fetchone()

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("assets:software_license_list") + f"?anagrafica={int(row[0])}",
            {
                "anagrafica_id": str(int(row[0])),
                "action": "create_software_license",
                "category": SoftwareLicense.CATEGORY_ANTIVIRUS,
                "vendor": "Eset",
                "product_name": "Endpoint Security",
                "edition": "",
                "license_reference": "AV-200",
                "account_email": "security@example.local",
                "seats_total": "1",
                "seats_used": "1",
                "purchase_date": "",
                "renewal_date": "",
                "expiry_date": "",
                "auto_renew": "",
                "is_active": "on",
                "notes": "",
                "assigned_employee_id": str(int(row[0])),
            },
        )

        self.assertEqual(response.status_code, 302)
        license_row = SoftwareLicense.objects.get(license_reference="AV-200")
        self.assertEqual(license_row.assigned_anagrafica_id, int(row[0]))
        self.assertIn("Rossi", license_row.assigned_to_display)

    def test_asset_detail_shows_software_license(self):
        SoftwareLicense.objects.create(
            category=SoftwareLicense.CATEGORY_OFFICE,
            vendor="Microsoft",
            product_name="Office 365",
            asset=self.asset,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Office 365")


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
        with _workspace_temporary_directory("assets-import-") as tmpdir:
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
        with _workspace_temporary_directory("assets-import-") as tmpdir:
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
        with _workspace_temporary_directory("assets-import-extra-") as tmpdir:
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
        with _workspace_temporary_directory("assets-import-sensitive-") as tmpdir:
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
        with _workspace_temporary_directory("assets-import-fuzzy-") as tmpdir:
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


class ImportAssetsCatalogTests(TestCase):
    def _write_catalog_csv(self, path: Path, rows: list[list[str]]) -> None:
        lines = ["asset_id;famiglia;sottocategoria;descrizione;nome;ubicazione;matricola;stato"]
        lines.extend(";".join(row) for row in rows)
        path.write_text("\n".join(lines), encoding="utf-8")

    def test_creates_parent_category_from_famiglia(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "", "Reparto A", "M-2286", "In uso"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)

            self.assertTrue(AssetCategory.objects.filter(label="Sollevamento", parent__isnull=True).exists())

    def test_creates_subcategory_under_parent(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "", "Reparto A", "M-2286", "In uso"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)

            parent = AssetCategory.objects.get(label="Sollevamento", parent__isnull=True)
            subcategory = AssetCategory.objects.get(label="Carroponte", parent=parent)
            self.assertEqual(subcategory.base_asset_type, Asset.TYPE_CARROPONTE)

    def test_creates_asset_with_explicit_asset_id(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "CP 142", "Reparto A", "M-2286", "In uso"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)

            asset = Asset.objects.get(asset_tag="APLCP142-MATR.PI-I-2286")
            self.assertEqual(asset.name, "CP 142")
            self.assertEqual(asset.serial_number, "M-2286")
            self.assertEqual(asset.asset_category.label, "Carroponte")

    def test_double_import_is_idempotent(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "CP 142", "Reparto A", "M-2286", "In uso"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)
            call_command("import_assets_catalog", str(file_path), commit=True)

            self.assertEqual(Asset.objects.filter(asset_tag="APLCP142-MATR.PI-I-2286").count(), 1)
            self.assertEqual(AssetCategory.objects.filter(label="Sollevamento", parent__isnull=True).count(), 1)
            self.assertEqual(AssetCategory.objects.filter(label="Carroponte").count(), 1)

    def test_dry_run_does_not_write(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "CP 142", "Reparto A", "M-2286", "In uso"]],
            )

            call_command("import_assets_catalog", str(file_path), dry_run=True)

            self.assertEqual(Asset.objects.count(), 0)
            self.assertEqual(AssetCategory.objects.count(), 0)

    def test_missing_famiglia_is_blocking_error(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "", "Carroponte", "Linea A", "CP 142", "Reparto A", "M-2286", "In uso"]],
            )

            with self.assertRaisesMessage(CommandError, "Import annullato"):
                call_command("import_assets_catalog", str(file_path), commit=True)

            self.assertEqual(Asset.objects.count(), 0)

    def test_missing_sottocategoria_is_blocking_error(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "", "Linea A", "CP 142", "Reparto A", "M-2286", "In uso"]],
            )

            with self.assertRaisesMessage(CommandError, "Import annullato"):
                call_command("import_assets_catalog", str(file_path), commit=True)

            self.assertEqual(Asset.objects.count(), 0)

    def test_updates_existing_asset_without_duplicate(self):
        Asset.objects.create(asset_tag="APLCP142-MATR.PI-I-2286", name="Vecchio nome", asset_type=Asset.TYPE_OTHER)
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["APLCP142-MATR.PI-I-2286", "Sollevamento", "Carroponte", "Linea A", "CP aggiornato", "Reparto B", "M-2286", "In riparazione"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)

            self.assertEqual(Asset.objects.filter(asset_tag="APLCP142-MATR.PI-I-2286").count(), 1)
            asset = Asset.objects.get(asset_tag="APLCP142-MATR.PI-I-2286")
            self.assertEqual(asset.name, "CP aggiornato")
            self.assertEqual(asset.reparto, "Reparto B")
            self.assertEqual(asset.status, Asset.STATUS_IN_REPAIR)

    def test_generic_cn_asset_is_imported_as_real_asset(self):
        with _workspace_temporary_directory("assets-catalog-") as tmpdir:
            file_path = Path(tmpdir) / "catalogo.csv"
            self._write_catalog_csv(
                file_path,
                [["CN-ANT", "Generici CN", "Asset generico", "Antincendio generale", "", "Stabilimento", "", "Attivo"]],
            )

            call_command("import_assets_catalog", str(file_path), commit=True)

            asset = Asset.objects.get(asset_tag="CN-ANT")
            self.assertEqual(asset.notes, "Asset generico CN")
            self.assertIs(asset.extra_columns.get("is_generic_asset"), True)


class ImportWorkMachinesExcelTests(TestCase):
    def test_import_creates_assets_and_work_machines(self):
        with _workspace_temporary_directory("assets-work-machines-import-") as tmpdir:
            file_path = Path(tmpdir) / "macchine.xlsx"
            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["CN5", "DMG Mori DMC 160U", 1600, 1600, 1100, "-", "-", 2019, 183, "âœ“", "-", "âœ“", "-", "-"],
                    ["CN5", "DMG Mori DMC 160U", 1600, 1600, 1100, "-", "-", 2023, 243, "âœ“", "-", "âœ“", "âœ“", "0.010"],
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
        with _workspace_temporary_directory("assets-work-machines-import-") as tmpdir:
            file_path = Path(tmpdir) / "macchine.xlsx"
            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["TNC", "DMG Ecturn 650", "-", "-", "-", "-", "-", 2019, "-", "âœ“", 6, "âœ“", "-", "-"],
                ],
            )
            call_command("import_work_machines_excel", file=str(file_path))

            _build_work_machine_workbook(
                file_path,
                rows=[
                    ["TNC", "DMG Ecturn 650", "-", "-", "-", "-", "-", 2019, 12, "-", 8, "âœ“", "âœ“", "0.005"],
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
        with _workspace_temporary_directory("assets-wo-attachments-") as media_root, override_settings(MEDIA_ROOT=media_root):
            with patch("assets.views.validate_extension_and_mime", return_value="application/pdf"):
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

    def test_workorder_attachment_rejects_spoofed_mime(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("report.pdf", b"MZ...", content_type="application/pdf")
        with patch(
            "assets.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("report.pdf: tipo MIME non consentito (application/x-msdownload)."),
        ):
            response = self.client.post(
                reverse("assets:wo_create", args=[self.asset.id]),
                {
                    "periodic_verification": "",
                    "supplier": "",
                    "kind": WorkOrder.KIND_CORRECTIVE,
                    "status": WorkOrder.STATUS_OPEN,
                    "title": "Intervento con allegato non valido",
                    "description": "Verifica MIME",
                    "attachments": upload,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tipo MIME non consentito")
        self.assertEqual(WorkOrder.objects.count(), 0)

    def test_workorder_attachment_fails_closed_when_mime_engine_missing(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("report.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        with patch(
            "assets.views.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("Validazione MIME non disponibile sul server. Upload bloccato."),
        ):
            response = self.client.post(
                reverse("assets:wo_create", args=[self.asset.id]),
                {
                    "periodic_verification": "",
                    "supplier": "",
                    "kind": WorkOrder.KIND_CORRECTIVE,
                    "status": WorkOrder.STATUS_OPEN,
                    "title": "Intervento con validazione bloccata",
                    "description": "Fail closed",
                    "attachments": upload,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Validazione MIME non disponibile")
        self.assertEqual(WorkOrder.objects.count(), 0)

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

    def test_workorder_with_rule_and_contract_syncs_execution_state_only_on_close(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Service Integrato Srl",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        category = AssetCategory.objects.create(
            code="wo-flow-category",
            label="Categoria WO Flow",
            base_asset_type=Asset.TYPE_SERVER,
        )
        self.asset.asset_category = category
        self.asset.save(update_fields=["asset_category"])
        template = MaintenanceInterventionTemplate.objects.create(
            code="wo-flow-template",
            label="Check semestrale server",
            asset_category=category,
        )
        rule = MaintenanceRule.objects.create(
            intervention_template=template,
            asset_category=category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=180,
            warning_days=20,
        )
        contract = AssistanceContract.objects.create(
            supplier=supplier,
            asset=self.asset,
            title="Contratto server mission critical",
            contract_type=AssistanceContract.TYPE_FULL_SERVICE,
            start_date=timezone.localdate() - timedelta(days=10),
            coverage_summary="Copertura full service H24",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:wo_create", args=[self.asset.id]),
            {
                "periodic_verification": "",
                "maintenance_rule": str(rule.id),
                "supplier": "",
                "assistance_contract": str(contract.id),
                "covered_by_contract": "on",
                "kind": WorkOrder.KIND_PREVENTIVE,
                "status": WorkOrder.STATUS_DONE,
                "title": "Check server completato",
                "description": "Intervento eseguito e chiuso nello stesso momento.",
                "resolution": "Server verificato",
                "downtime_minutes": "5",
                "cost_eur": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        workorder = WorkOrder.objects.get(title="Check server completato")
        self.assertEqual(workorder.maintenance_rule, rule)
        self.assertEqual(workorder.assistance_contract, contract)
        self.assertTrue(workorder.covered_by_contract)
        self.assertEqual(workorder.supplier, supplier)
        self.assertEqual(workorder.status, WorkOrder.STATUS_OPEN)
        self.assertIsNone(workorder.closed_at)
        self.assertFalse(
            AssetMaintenanceRuleState.objects.filter(asset=self.asset, base_rule=rule).exists()
        )

        close_response = self.client.post(
            reverse("assets:wo_close", args=[workorder.id]),
            {
                "status": WorkOrder.STATUS_DONE,
                "resolution": "Server verificato",
                "assistance_contract": str(contract.id),
                "covered_by_contract": "on",
            },
        )

        self.assertEqual(close_response.status_code, 302)
        workorder.refresh_from_db()
        self.assertEqual(workorder.status, WorkOrder.STATUS_DONE)
        state = AssetMaintenanceRuleState.objects.get(asset=self.asset, base_rule=rule)
        self.assertEqual(state.last_work_order, workorder)
        self.assertEqual(state.last_execution_date, timezone.localdate())

    def test_create_workorder_rejects_contract_coverage_without_contract(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:wo_create", args=[self.asset.id]),
            {
                "periodic_verification": "",
                "supplier": "",
                "kind": WorkOrder.KIND_CORRECTIVE,
                "status": WorkOrder.STATUS_DONE,
                "covered_by_contract": "on",
                "title": "Intervento senza contratto",
                "description": "Verifica copertura non coerente",
                "resolution": "",
                "downtime_minutes": "0",
                "cost_eur": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Seleziona un contratto per indicare la copertura.")
        self.assertFalse(WorkOrder.objects.filter(title="Intervento senza contratto").exists())

    def test_workorder_form_prefills_from_schedule_context(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Prefill Service Srl",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        category = AssetCategory.objects.create(
            code="wo-prefill-category",
            label="Categoria WO Prefill",
            base_asset_type=Asset.TYPE_SERVER,
        )
        self.asset.asset_category = category
        self.asset.save(update_fields=["asset_category"])
        template = MaintenanceInterventionTemplate.objects.create(
            code="wo-prefill-template",
            label="Controllo annuale server",
            description="Esegui checklist annuale e verifica parametri di backup.",
            asset_category=category,
        )
        rule = MaintenanceRule.objects.create(
            intervention_template=template,
            asset_category=category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=365,
            warning_days=30,
            notes="Verificare anche lo stato dei dischi.",
        )
        AssistanceContract.objects.create(
            supplier=supplier,
            asset=self.asset,
            title="Contratto server enterprise",
            contract_type=AssistanceContract.TYPE_FULL_SERVICE,
            start_date=timezone.localdate() - timedelta(days=5),
        )
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("assets:wo_create", args=[self.asset.id]) + f"?rule={rule.id}&source=maintenance_schedule"
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["maintenance_rule"], rule.id)
        self.assertEqual(form.initial["kind"], WorkOrder.KIND_PREVENTIVE)
        self.assertEqual(form.initial["title"], "Controllo annuale server")
        self.assertIn("checklist annuale", form.initial["description"].lower())
        self.assertIn("stato dei dischi", form.initial["description"].lower())
        self.assertTrue(form.initial["covered_by_contract"])
        self.assertContains(response, "Prossime manutenzioni")
        self.assertContains(response, "Contratto suggerito")
        self.assertNotContains(response, "Stato iniziale")

    def test_close_workorder_rejects_incompatible_contract(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Supplier Originario",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        other_supplier = Fornitore.objects.create(
            ragione_sociale="Supplier Incompatibile",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        category = AssetCategory.objects.create(
            code="wo-close-category",
            label="Categoria WO Close",
            base_asset_type=Asset.TYPE_SERVER,
        )
        self.asset.asset_category = category
        self.asset.save(update_fields=["asset_category"])
        template = MaintenanceInterventionTemplate.objects.create(
            code="wo-close-template",
            label="Controllo chiusura",
            asset_category=category,
        )
        rule = MaintenanceRule.objects.create(
            intervention_template=template,
            asset_category=category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=90,
        )
        invalid_contract = AssistanceContract.objects.create(
            supplier=other_supplier,
            asset=self.asset,
            title="Contratto incompatibile",
            contract_type=AssistanceContract.TYPE_ON_CALL,
            start_date=timezone.localdate() - timedelta(days=2),
        )
        workorder = WorkOrder.objects.create(
            asset=self.asset,
            maintenance_rule=rule,
            supplier=supplier,
            kind=WorkOrder.KIND_PREVENTIVE,
            status=WorkOrder.STATUS_OPEN,
            title="WO da chiudere",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:wo_close", args=[workorder.id]),
            {
                "status": WorkOrder.STATUS_DONE,
                "resolution": "Chiusura di test",
                "assistance_contract": str(invalid_contract.id),
                "covered_by_contract": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        workorder.refresh_from_db()
        self.assertEqual(workorder.status, WorkOrder.STATUS_OPEN)
        self.assertContains(response, "fornitore diverso")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetAdministrativeStepOneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="asset-step-one", password="pass12345")
        _complete_onboarding(self.user)
        self.asset = Asset.objects.create(
            name="Carroponte reparto A",
            asset_type=Asset.TYPE_HW,
            reparto="OFF",
            source_key="manual-step-one-asset-a",
        )
        self.other_asset = Asset.objects.create(
            name="Compressore reparto B",
            asset_type=Asset.TYPE_HW,
            reparto="MAN",
            source_key="manual-step-one-asset-b",
        )

    def test_asset_component_form_prevents_duplicate_code_per_asset(self):
        AssetComponent.objects.create(
            asset=self.asset,
            code="FILTRO-001",
            name="Filtro aspirazione",
        )

        form = AssetComponentForm(
            data={
                "asset": str(self.asset.id),
                "code": "FILTRO-001",
                "name": "Filtro ricambio",
                "component_type": "Filtro",
                "serial_number": "",
                "manufacturer": "",
                "model": "",
                "installed_on": "",
                "notes": "",
                "is_active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("code", form.errors)

    def test_component_create_view_creates_component(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:asset_component_create") + f"?asset={self.asset.id}",
            {
                "asset": str(self.asset.id),
                "code": "POMPA-01",
                "name": "Pompa olio",
                "component_type": "Pompa",
                "serial_number": "SN-POMPA-01",
                "manufacturer": "SKF",
                "model": "PO-200",
                "installed_on": "2026-03-01",
                "notes": "Componente test step 1",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        component = AssetComponent.objects.get(code="POMPA-01")
        self.assertEqual(component.asset, self.asset)
        self.assertTrue(component.is_active)

    def test_deadline_create_view_links_component(self):
        component = AssetComponent.objects.create(
            asset=self.asset,
            code="CERT-01",
            name="Quadro elettrico",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:asset_administrative_deadline_create") + f"?asset={self.asset.id}&component={component.id}",
            {
                "asset": str(self.asset.id),
                "component": str(component.id),
                "deadline_type": AssetAdministrativeDeadline.TYPE_CERTIFICATE,
                "title": "Certificato CE quadro elettrico",
                "reference_code": "CE-2026-001",
                "issuer": "Ente Certificatore",
                "issued_on": "2026-03-01",
                "due_date": "2026-06-30",
                "warning_days": "15",
                "notes": "Scadenza collegata al componente",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        deadline = AssetAdministrativeDeadline.objects.get(reference_code="CE-2026-001")
        self.assertEqual(deadline.asset, self.asset)
        self.assertEqual(deadline.component, component)

    def test_deadline_form_rejects_component_from_other_asset(self):
        foreign_component = AssetComponent.objects.create(
            asset=self.other_asset,
            code="ALTRO-01",
            name="Valvola esterna",
        )

        form = AssetAdministrativeDeadlineForm(
            data={
                "asset": str(self.asset.id),
                "component": str(foreign_component.id),
                "deadline_type": AssetAdministrativeDeadline.TYPE_TECHNICAL,
                "title": "Scadenza test",
                "reference_code": "REF-001",
                "issuer": "Officina interna",
                "issued_on": "2026-03-01",
                "due_date": "2026-05-31",
                "warning_days": "10",
                "notes": "",
                "is_active": "on",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("component", form.errors)

    def test_step_one_routes_render_and_asset_detail_contains_links(self):
        component = AssetComponent.objects.create(
            asset=self.asset,
            code="RID-01",
            name="Riduttore",
        )
        AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            component=component,
            deadline_type=AssetAdministrativeDeadline.TYPE_REVISION,
            title="Revisione riduttore",
            due_date=date(2026, 4, 15),
            warning_days=20,
        )

        self.client.force_login(self.user)

        response = self.client.get(reverse("assets:asset_component_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Elenco componenti")

        asset_components_page = self.client.get(
            reverse("assets:asset_component_list_for_asset", kwargs={"asset_id": self.asset.id})
        )
        self.assertEqual(asset_components_page.status_code, 200)
        self.assertContains(asset_components_page, self.asset.asset_tag)
        self.assertContains(asset_components_page, "Riduttore")

        deadline_page = self.client.get(reverse("assets:asset_administrative_deadline_list"))
        self.assertEqual(deadline_page.status_code, 200)
        self.assertContains(deadline_page, "Elenco scadenze")

        detail_page = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))
        self.assertEqual(detail_page.status_code, 200)
        self.assertContains(detail_page, "Crea intervento")
        self.assertContains(detail_page, "Apri scadenze")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetMaintenanceStepTwoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="asset-step-two-admin",
            email="asset-step-two-admin@test.local",
            password="pass12345",
        )
        self.category = AssetCategory.objects.create(
            code="macchine-step-two",
            label="Macchine Step Two",
            base_asset_type=Asset.TYPE_WORK_MACHINE,
            sort_order=10,
        )
        self.other_category = AssetCategory.objects.create(
            code="impianti-step-two",
            label="Impianti Step Two",
            base_asset_type=Asset.TYPE_HW,
            sort_order=20,
        )

    def test_maintenance_template_create_view_creates_template(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:maintenance_template_create") + f"?category={self.category.id}",
            {
                "code": "cambio-olio-step-two",
                "label": "Cambio olio",
                "description": "Template standard per cambio olio",
                "asset_category": str(self.category.id),
                "sort_order": "15",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        template = MaintenanceInterventionTemplate.objects.get(code="cambio-olio-step-two")
        self.assertEqual(template.asset_category, self.category)
        self.assertEqual(template.label, "Cambio olio")
        self.assertTrue(template.is_active)

    def test_maintenance_rule_create_view_creates_category_rule(self):
        template = MaintenanceInterventionTemplate.objects.create(
            code="lubrificazione-step-two",
            label="Lubrificazione",
            asset_category=self.category,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:maintenance_rule_create") + f"?category={self.category.id}&template={template.id}",
            {
                "intervention_template": str(template.id),
                "asset_category": str(self.category.id),
                "threshold_type": MaintenanceRule.THRESHOLD_DAYS,
                "threshold_value": "90",
                "sort_order": "30",
                "is_active": "on",
                "notes": "Intervento periodico standard",
            },
        )

        self.assertEqual(response.status_code, 302)
        rule = MaintenanceRule.objects.get(intervention_template=template, asset_category=self.category)
        self.assertEqual(rule.threshold_type, MaintenanceRule.THRESHOLD_DAYS)
        self.assertEqual(rule.threshold_value, 90)
        self.assertTrue(rule.is_active)

    def test_maintenance_rule_create_view_shows_template_management_when_templates_missing(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("assets:maintenance_rule_create") + f"?category={self.category.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Non ci sono template manutenzione attivi.")
        self.assertContains(response, reverse("assets:maintenance_template_list") + f"?category={self.category.id}")
        self.assertContains(response, reverse("assets:maintenance_template_create") + f"?category={self.category.id}")
        self.assertContains(response, reverse("assets:gestione_admin") + "?tab=categorie")
        self.assertContains(response, 'aria-disabled="true"', html=False)

    def test_maintenance_rule_create_view_warns_when_selected_category_has_no_compatible_templates(self):
        MaintenanceInterventionTemplate.objects.create(
            code="step-two-template-altro",
            label="Template altra categoria",
            asset_category=self.other_category,
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("assets:maintenance_rule_create") + f"?category={self.category.id}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nessun template compatibile con la categoria")
        self.assertContains(response, self.category.label)

    def test_maintenance_rule_form_rejects_mismatched_template_category(self):
        foreign_template = MaintenanceInterventionTemplate.objects.create(
            code="controllo-elettrico-step-two",
            label="Controllo elettrico",
            asset_category=self.other_category,
        )

        form = MaintenanceRuleForm(
            data={
                "intervention_template": str(foreign_template.id),
                "asset_category": str(self.category.id),
                "threshold_type": MaintenanceRule.THRESHOLD_DAYS,
                "threshold_value": "45",
                "sort_order": "10",
                "is_active": "on",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("intervention_template", form.errors)

    def test_maintenance_templates_and_rules_routes_render(self):
        general_template = MaintenanceInterventionTemplate.objects.create(
            code="verifica-sicurezza-step-two",
            label="Verifica sicurezza",
            sort_order=5,
        )
        category_template = MaintenanceInterventionTemplate.objects.create(
            code="revisione-gruppo-step-two",
            label="Revisione gruppo",
            asset_category=self.category,
            sort_order=10,
        )
        MaintenanceRule.objects.create(
            intervention_template=category_template,
            asset_category=self.category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=180,
            sort_order=10,
            notes="Regola standard di test",
        )

        self.client.force_login(self.admin)

        template_list_response = self.client.get(reverse("assets:maintenance_template_list"))
        self.assertEqual(template_list_response.status_code, 200)
        self.assertContains(template_list_response, "Template manutenzione")
        self.assertContains(template_list_response, general_template.label)
        self.assertContains(template_list_response, category_template.label)

        rule_list_response = self.client.get(reverse("assets:maintenance_rule_list"))
        self.assertEqual(rule_list_response.status_code, 200)
        self.assertContains(rule_list_response, "Regole manutenzione")
        self.assertContains(rule_list_response, category_template.label)
        self.assertContains(rule_list_response, self.category.label)

    def test_maintenance_form_accepts_global_template_for_category_rule(self):
        template = MaintenanceInterventionTemplate.objects.create(
            code="controllo-filtri-step-two",
            label="Controllo filtri",
        )

        form = MaintenanceRuleForm(
            data={
                "intervention_template": str(template.id),
                "asset_category": str(self.category.id),
                "threshold_type": MaintenanceRule.THRESHOLD_HOURS,
                "threshold_value": "250",
                "sort_order": "40",
                "is_active": "on",
                "notes": "Template generale applicato a categoria specifica",
            }
        )

        self.assertTrue(form.is_valid(), form.errors.as_json())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetMaintenanceStepThreeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="asset-step-three-admin",
            email="asset-step-three-admin@test.local",
            password="pass12345",
        )
        self.category = AssetCategory.objects.create(
            code="step-three-category",
            label="Categoria Step Three",
            base_asset_type=Asset.TYPE_WORK_MACHINE,
            sort_order=10,
        )
        self.other_category = AssetCategory.objects.create(
            code="step-three-other-category",
            label="Categoria Step Three Altro",
            base_asset_type=Asset.TYPE_HW,
            sort_order=20,
        )
        self.asset = Asset.objects.create(
            name="Centro di lavoro ST3",
            asset_type=Asset.TYPE_WORK_MACHINE,
            asset_category=self.category,
            reparto="OFF",
            source_key="asset-step-three-main",
        )
        self.general_template = MaintenanceInterventionTemplate.objects.create(
            code="step-three-general-template",
            label="Verifica sicurezza generale",
        )
        self.category_template = MaintenanceInterventionTemplate.objects.create(
            code="step-three-category-template",
            label="Lubrificazione guidata",
            asset_category=self.category,
        )
        self.other_category_template = MaintenanceInterventionTemplate.objects.create(
            code="step-three-other-template",
            label="Template altra categoria",
            asset_category=self.other_category,
        )
        self.base_rule = MaintenanceRule.objects.create(
            intervention_template=self.category_template,
            asset_category=self.category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=90,
            sort_order=10,
            notes="Regola standard di categoria",
        )
        self.foreign_rule = MaintenanceRule.objects.create(
            intervention_template=self.other_category_template,
            asset_category=self.other_category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=120,
            sort_order=20,
            notes="Regola altra categoria",
        )

    def test_override_create_view_creates_valid_override(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse(
                "assets:asset_maintenance_rule_override_create",
                kwargs={"asset_id": self.asset.id, "rule_id": self.base_rule.id},
            ),
            {
                "asset": str(self.asset.id),
                "base_rule": str(self.base_rule.id),
                "override_threshold_type": MaintenanceRule.THRESHOLD_DAYS,
                "override_threshold_value": "120",
                "override_intervention_template": str(self.general_template.id),
                "is_disabled": "",
                "notes": "Intervallo aumentato per questo asset",
            },
        )

        self.assertEqual(response.status_code, 302)
        override = MaintenanceRuleAssetOverride.objects.get(asset=self.asset, base_rule=self.base_rule)
        self.assertEqual(override.override_threshold_type, MaintenanceRule.THRESHOLD_DAYS)
        self.assertEqual(override.override_threshold_value, 120)
        self.assertEqual(override.override_intervention_template, self.general_template)

    def test_override_form_rejects_rule_from_other_category(self):
        form = MaintenanceRuleAssetOverrideForm(
            data={
                "asset": str(self.asset.id),
                "base_rule": str(self.foreign_rule.id),
                "override_threshold_type": "",
                "override_threshold_value": "45",
                "override_intervention_template": "",
                "is_disabled": "",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("base_rule", form.errors)

    def test_override_form_rejects_override_template_from_other_category(self):
        form = MaintenanceRuleAssetOverrideForm(
            data={
                "asset": str(self.asset.id),
                "base_rule": str(self.base_rule.id),
                "override_threshold_type": MaintenanceRule.THRESHOLD_DAYS,
                "override_threshold_value": "45",
                "override_intervention_template": str(self.other_category_template.id),
                "is_disabled": "",
                "notes": "",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("override_intervention_template", form.errors)

    def test_resolve_asset_maintenance_rules_returns_inherited_status(self):
        rows = resolve_asset_maintenance_rules(self.asset)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "inherited")
        self.assertEqual(rows[0]["effective_threshold_type"], self.base_rule.threshold_type)
        self.assertEqual(rows[0]["effective_threshold_value"], self.base_rule.threshold_value)
        self.assertEqual(rows[0]["effective_intervention_template"], self.base_rule.intervention_template)

    def test_resolve_asset_maintenance_rules_returns_overridden_status(self):
        MaintenanceRuleAssetOverride.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            override_threshold_value=150,
            override_intervention_template=self.general_template,
            notes="Override asset-specifico",
        )

        rows = resolve_asset_maintenance_rules(self.asset)

        self.assertEqual(rows[0]["status"], "overridden")
        self.assertEqual(rows[0]["effective_threshold_type"], self.base_rule.threshold_type)
        self.assertEqual(rows[0]["effective_threshold_value"], 150)
        self.assertEqual(rows[0]["effective_intervention_template"], self.general_template)
        self.assertEqual(rows[0]["effective_notes"], "Override asset-specifico")

    def test_resolve_asset_maintenance_rules_returns_disabled_status(self):
        MaintenanceRuleAssetOverride.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            is_disabled=True,
            notes="Regola non applicabile a questo asset",
        )

        rows = resolve_asset_maintenance_rules(self.asset)

        self.assertEqual(rows[0]["status"], "disabled")
        self.assertTrue(rows[0]["is_disabled"])

    def test_asset_maintenance_routes_render_and_reset_override(self):
        override = MaintenanceRuleAssetOverride.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            override_threshold_value=110,
            notes="Override da resettare",
        )
        self.client.force_login(self.admin)

        list_response = self.client.get(
            reverse("assets:asset_maintenance_rule_list", kwargs={"asset_id": self.asset.id})
        )
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "Regole manutenzione asset")
        self.assertContains(list_response, self.base_rule.intervention_template.label)
        self.assertContains(list_response, "Personalizzata")

        detail_response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Regole manutenzione")

        reset_response = self.client.post(
            reverse(
                "assets:asset_maintenance_rule_override_reset",
                kwargs={"asset_id": self.asset.id, "id": override.id},
            )
        )
        self.assertEqual(reset_response.status_code, 302)
        self.assertFalse(MaintenanceRuleAssetOverride.objects.filter(pk=override.id).exists())

    def test_day_based_schedule_uses_manual_execution_state(self):
        today = timezone.localdate()
        AssetMaintenanceRuleState.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            last_execution_date=today - timedelta(days=80),
            notes="Baseline manuale",
        )

        rows = build_day_based_maintenance_schedule_rows(
            asset_queryset=Asset.objects.filter(pk=self.asset.id).select_related("asset_category"),
            today=today,
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["schedule_status"], "warning")
        self.assertEqual(rows[0]["due_date"], today + timedelta(days=10))
        self.assertEqual(rows[0]["last_execution_notes"], "Baseline manuale")

    def test_asset_maintenance_rule_list_updates_execution_state(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:asset_maintenance_rule_list", kwargs={"asset_id": self.asset.id}),
            {
                "action": "update_rule_execution",
                "base_rule_id": str(self.base_rule.id),
                "last_execution_date": "2026-03-01",
                "last_execution_notes": "Manutenzione straordinaria registrata a mano",
            },
        )

        self.assertEqual(response.status_code, 302)
        state = AssetMaintenanceRuleState.objects.get(asset=self.asset, base_rule=self.base_rule)
        self.assertEqual(str(state.last_execution_date), "2026-03-01")
        self.assertEqual(state.notes, "Manutenzione straordinaria registrata a mano")

    def test_maintenance_schedule_creates_outlook_event_for_selected_legacy_user(self):
        target_user = UtenteLegacy.objects.create(
            nome="Mario Rossi",
            email="m.rossi@example.local",
            password="hash-test",
            attivo=True,
        )
        AssetMaintenanceRuleState.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            last_execution_date=date(2026, 1, 1),
            notes="Storico per calendario",
        )
        self.client.force_login(self.admin)

        with patch.object(
            asset_views,
            "_outlook_calendar_create_event",
            return_value={"id": "evt-123", "webLink": "https://outlook.office.com/calendar/item/evt-123"},
        ) as mocked_create:
            response = self.client.post(
                reverse("assets:maintenance_schedule"),
                {
                    "action": "create_outlook_calendar_event",
                    "asset_id": str(self.asset.id),
                    "base_rule_id": str(self.base_rule.id),
                    "target_legacy_user_id": str(target_user.id),
                    "filter_asset": str(self.asset.id),
                    "filter_status": "all",
                    "filter_category": "",
                    "filter_reparto": "",
                    "filter_coverage": "all",
                    "filter_q": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"asset={self.asset.id}", response["Location"])
        mocked_create.assert_called_once()
        self.assertEqual(mocked_create.call_args.kwargs["target_email"], "m.rossi@example.local")
        payload = mocked_create.call_args.kwargs["payload"]
        self.assertIn(self.asset.asset_tag, payload["subject"])
        self.assertIn(self.category_template.label, payload["subject"])
        self.assertEqual(payload["start"]["timeZone"], asset_views.OUTLOOK_CALENDAR_TIMEZONE)

        calendar_event = AssetCalendarEvent.objects.get(
            asset=self.asset,
            event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
            maintenance_rule=self.base_rule,
            target_legacy_user_id=target_user.id,
        )
        self.assertEqual(calendar_event.target_email, "m.rossi@example.local")
        self.assertEqual(str(calendar_event.due_date), "2026-04-01")
        self.assertEqual(calendar_event.graph_event_id, "evt-123")

        with patch.object(asset_views, "_outlook_calendar_graph_ready", return_value=True):
            page_response = self.client.get(reverse("assets:maintenance_schedule") + f"?asset={self.asset.id}")
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Crea evento Outlook")
        self.assertContains(page_response, "Evento Outlook")
        self.assertContains(page_response, "Mario Rossi")

    def test_maintenance_schedule_does_not_duplicate_existing_outlook_event(self):
        target_user = UtenteLegacy.objects.create(
            nome="Laura Bianchi",
            email="l.bianchi@example.local",
            password="hash-test",
            attivo=True,
        )
        AssetMaintenanceRuleState.objects.create(
            asset=self.asset,
            base_rule=self.base_rule,
            last_execution_date=date(2026, 1, 1),
        )
        source_key = asset_views._asset_calendar_source_key(
            event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
            asset_id=self.asset.id,
            source_id=self.base_rule.id,
            due_date=date(2026, 4, 1),
            target_legacy_user_id=target_user.id,
        )
        AssetCalendarEvent.objects.create(
            asset=self.asset,
            event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
            source_key=source_key,
            maintenance_rule=self.base_rule,
            due_date=date(2026, 4, 1),
            target_legacy_user_id=target_user.id,
            target_display_name="Laura Bianchi",
            target_email="l.bianchi@example.local",
            subject="Manutenzione esistente",
            transaction_id="existing-transaction",
            graph_event_id="evt-existing",
            graph_event_web_link="https://outlook.office.com/calendar/item/evt-existing",
            created_by=self.admin,
        )
        self.client.force_login(self.admin)

        with patch.object(asset_views, "_outlook_calendar_create_event") as mocked_create:
            response = self.client.post(
                reverse("assets:maintenance_schedule"),
                {
                    "action": "create_outlook_calendar_event",
                    "asset_id": str(self.asset.id),
                    "base_rule_id": str(self.base_rule.id),
                    "target_legacy_user_id": str(target_user.id),
                    "filter_asset": str(self.asset.id),
                    "filter_status": "all",
                    "filter_category": "",
                    "filter_reparto": "",
                    "filter_coverage": "all",
                    "filter_q": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        mocked_create.assert_not_called()
        self.assertEqual(
            AssetCalendarEvent.objects.filter(
                asset=self.asset,
                event_kind=AssetCalendarEvent.KIND_MAINTENANCE,
                maintenance_rule=self.base_rule,
                target_legacy_user_id=target_user.id,
                due_date=date(2026, 4, 1),
            ).count(),
            1,
        )

    def test_administrative_deadline_list_creates_outlook_event_for_selected_legacy_user(self):
        target_user = UtenteLegacy.objects.create(
            nome="Giulia Verdi",
            email="g.verdi@example.local",
            password="hash-test",
            attivo=True,
        )
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_TECHNICAL,
            title="Revisione impianto",
            reference_code="REV-2026",
            issuer="INAIL",
            due_date=date(2026, 5, 20),
            warning_days=20,
        )
        self.client.force_login(self.admin)

        with patch.object(
            asset_views,
            "_outlook_calendar_create_event",
            return_value={"id": "evt-deadline", "webLink": "https://outlook.office.com/calendar/item/evt-deadline"},
        ) as mocked_create:
            response = self.client.post(
                reverse("assets:asset_administrative_deadline_list"),
                {
                    "action": "create_outlook_calendar_event",
                    "deadline_id": str(deadline.id),
                    "target_legacy_user_id": str(target_user.id),
                    "filter_asset": str(self.asset.id),
                    "filter_component": "",
                    "filter_deadline_type": "",
                    "filter_status": "all",
                    "filter_q": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"asset={self.asset.id}", response["Location"])
        mocked_create.assert_called_once()
        self.assertEqual(mocked_create.call_args.kwargs["target_email"], "g.verdi@example.local")
        payload = mocked_create.call_args.kwargs["payload"]
        self.assertIn(deadline.title, payload["subject"])

        calendar_event = AssetCalendarEvent.objects.get(
            asset=self.asset,
            event_kind=AssetCalendarEvent.KIND_ADMINISTRATIVE_DEADLINE,
            administrative_deadline=deadline,
            target_legacy_user_id=target_user.id,
        )
        self.assertEqual(calendar_event.target_email, "g.verdi@example.local")
        self.assertEqual(calendar_event.graph_event_id, "evt-deadline")

        with patch.object(asset_views, "_outlook_calendar_graph_ready", return_value=True):
            page_response = self.client.get(
                reverse("assets:asset_administrative_deadline_list") + f"?asset={self.asset.id}"
            )
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Crea evento Outlook")
        self.assertContains(page_response, "Evento Outlook")
        self.assertContains(page_response, "Giulia Verdi")

    def test_periodic_verification_list_creates_outlook_event_for_selected_asset_context(self):
        target_user = UtenteLegacy.objects.create(
            nome="Paolo Neri",
            email="p.neri@example.local",
            password="hash-test",
            attivo=True,
        )
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Verifiche",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        verification = PeriodicVerification.objects.create(
            name="Taratura annuale",
            supplier=supplier,
            frequency_months=12,
            next_verification_date=date(2026, 6, 15),
            created_by=self.admin,
        )
        verification.assets.add(self.asset)
        self.client.force_login(self.admin)

        with patch.object(
            asset_views,
            "_outlook_calendar_create_event",
            return_value={"id": "evt-periodic", "webLink": "https://outlook.office.com/calendar/item/evt-periodic"},
        ) as mocked_create:
            response = self.client.post(
                reverse("assets:periodic_verifications"),
                {
                    "action": "create_outlook_calendar_event",
                    "verification_id": str(verification.id),
                    "asset_id": str(self.asset.id),
                    "target_legacy_user_id": str(target_user.id),
                    "filter_asset": str(self.asset.id),
                    "filter_edit": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"asset={self.asset.id}", response["Location"])
        mocked_create.assert_called_once()
        self.assertEqual(mocked_create.call_args.kwargs["target_email"], "p.neri@example.local")
        payload = mocked_create.call_args.kwargs["payload"]
        self.assertIn(verification.name, payload["subject"])

        calendar_event = AssetCalendarEvent.objects.get(
            asset=self.asset,
            event_kind=AssetCalendarEvent.KIND_PERIODIC_VERIFICATION,
            periodic_verification=verification,
            target_legacy_user_id=target_user.id,
        )
        self.assertEqual(calendar_event.target_email, "p.neri@example.local")
        self.assertEqual(str(calendar_event.due_date), "2026-06-15")
        self.assertEqual(calendar_event.graph_event_id, "evt-periodic")

        with patch.object(asset_views, "_outlook_calendar_graph_ready", return_value=True):
            page_response = self.client.get(reverse("assets:periodic_verifications") + f"?asset={self.asset.id}&scope=production")
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Crea evento Outlook")
        self.assertContains(page_response, "Evento Outlook")
        self.assertContains(page_response, "Paolo Neri")

    def test_assistance_contract_list_creates_outlook_event_for_selected_asset_context(self):
        target_user = UtenteLegacy.objects.create(
            nome="Sara Blu",
            email="s.blu@example.local",
            password="hash-test",
            attivo=True,
        )
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Contratto Calendario",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        contract = AssistanceContract.objects.create(
            supplier=supplier,
            asset=self.asset,
            code="CTR-CAL",
            title="Contratto con promemoria",
            contract_type=AssistanceContract.TYPE_FULL_SERVICE,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            is_active=True,
            coverage_summary="Copertura standard",
        )
        self.client.force_login(self.admin)

        with patch.object(
            asset_views,
            "_outlook_calendar_create_event",
            return_value={"id": "evt-contract", "webLink": "https://outlook.office.com/calendar/item/evt-contract"},
        ) as mocked_create:
            response = self.client.post(
                reverse("assets:assistance_contract_list"),
                {
                    "action": "create_outlook_calendar_event",
                    "contract_id": str(contract.id),
                    "asset_id": str(self.asset.id),
                    "target_legacy_user_id": str(target_user.id),
                    "filter_asset": str(self.asset.id),
                    "filter_supplier": "",
                    "filter_state": "all",
                    "filter_scope": "all",
                    "filter_q": "",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"asset={self.asset.id}", response["Location"])
        mocked_create.assert_called_once()
        self.assertEqual(mocked_create.call_args.kwargs["target_email"], "s.blu@example.local")
        payload = mocked_create.call_args.kwargs["payload"]
        self.assertIn(contract.title, payload["subject"])

        calendar_event = AssetCalendarEvent.objects.get(
            asset=self.asset,
            event_kind=AssetCalendarEvent.KIND_ASSISTANCE_CONTRACT,
            assistance_contract=contract,
            target_legacy_user_id=target_user.id,
        )
        self.assertEqual(calendar_event.target_email, "s.blu@example.local")
        self.assertEqual(str(calendar_event.due_date), "2026-12-31")
        self.assertEqual(calendar_event.graph_event_id, "evt-contract")

        with patch.object(asset_views, "_outlook_calendar_graph_ready", return_value=True):
            page_response = self.client.get(reverse("assets:assistance_contract_list") + f"?asset={self.asset.id}")
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, "Crea evento Outlook")
        self.assertContains(page_response, "Evento Outlook")
        self.assertContains(page_response, "Sara Blu")

    def test_assistance_contract_list_creates_contract_for_selected_asset(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Contratti Step 3",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:assistance_contract_list") + f"?asset={self.asset.id}",
            {
                "asset_id": str(self.asset.id),
                "action": "create_assistance_contract",
                "supplier": str(supplier.id),
                "asset_category": "",
                "code": "CTR-001",
                "title": "Contratto officina asset specifico",
                "contract_type": AssistanceContract.TYPE_FULL_SERVICE,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "is_active": "on",
                "sla_description": "4h onsite",
                "coverage_summary": "Ricambi inclusi",
                "periodic_cost_eur": "450.00",
                "notes": "Contratto di prova",
                "document": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        contract = AssistanceContract.objects.get(code="CTR-001")
        self.assertEqual(contract.asset, self.asset)
        self.assertEqual(contract.supplier, supplier)

    def test_assistance_contract_list_preserves_filters_after_post(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Redirect Filtri",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:assistance_contract_list")
            + f"?asset={self.asset.id}&state=active&scope=asset&q=ricambi",
            {
                "asset_id": str(self.asset.id),
                "action": "create_assistance_contract",
                "supplier": str(supplier.id),
                "asset_category": "",
                "code": "CTR-FILTER",
                "title": "Contratto con redirect filtrato",
                "contract_type": AssistanceContract.TYPE_FULL_SERVICE,
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "is_active": "on",
                "sla_description": "",
                "coverage_summary": "Ricambi inclusi",
                "periodic_cost_eur": "",
                "notes": "",
                "document": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"asset={self.asset.id}", response["Location"])
        self.assertIn("state=active", response["Location"])
        self.assertIn("scope=asset", response["Location"])
        self.assertIn("q=ricambi", response["Location"])

    def test_assistance_contract_list_shows_selected_asset_context_and_document_name(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Documento",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        self.client.force_login(self.admin)

        media_root = _make_workspace_tempdir("assets-contract-doc-")
        try:
            with override_settings(MEDIA_ROOT=media_root):
                document = FornitoreDocumento.objects.create(
                    fornitore=supplier,
                    nome="Contratto officina firmato",
                    tipo=FornitoreDocumento.TIPO_CONTRATTO,
                    file=SimpleUploadedFile("contratto.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                )
                AssistanceContract.objects.create(
                    supplier=supplier,
                    asset=self.asset,
                    title="Contratto con documento",
                    contract_type=AssistanceContract.TYPE_FULL_SERVICE,
                    start_date=timezone.localdate() - timedelta(days=5),
                    document=document,
                )

                response = self.client.get(reverse("assets:assistance_contract_list") + f"?asset={self.asset.id}")
        finally:
            shutil.rmtree(media_root, ignore_errors=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stai creando un contratto per questo asset")
        self.assertContains(response, document.nome)

    def test_new_schedule_and_contract_pages_render(self):
        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Render",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        AssistanceContract.objects.create(
            supplier=supplier,
            asset_category=self.category,
            title="Contratto categoria render",
            contract_type=AssistanceContract.TYPE_ON_CALL,
            start_date=timezone.localdate() - timedelta(days=5),
        )
        self.client.force_login(self.admin)

        schedule_response = self.client.get(reverse("assets:maintenance_schedule"))
        self.assertEqual(schedule_response.status_code, 200)
        self.assertContains(schedule_response, "Prossime manutenzioni")

        contracts_response = self.client.get(reverse("assets:assistance_contract_list"))
        self.assertEqual(contracts_response.status_code, 200)
        self.assertContains(contracts_response, "Contratti assistenza")

    def test_schedule_and_asset_detail_show_contextual_suggestions(self):
        self.client.force_login(self.admin)

        schedule_response = self.client.get(reverse("assets:maintenance_schedule") + f"?asset={self.asset.id}")
        self.assertEqual(schedule_response.status_code, 200)
        self.assertContains(schedule_response, "Imposta prima esecuzione")
        self.assertContains(schedule_response, "Verifica copertura")
        self.assertContains(schedule_response, "Prima esecuzione da pianificare")

        detail_response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Suggerimenti operativi")
        self.assertContains(detail_response, "Imposta prima esecuzione")
        self.assertContains(detail_response, "Verifica copertura")

    def test_reports_dashboard_links_all_open_workorders_and_missing_baseline_action(self):
        WorkOrder.objects.create(
            asset=self.asset,
            maintenance_rule=self.base_rule,
            kind=WorkOrder.KIND_PREVENTIVE,
            status=WorkOrder.STATUS_OPEN,
            title="WO report aperto",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("assets:reports") + "?scope=production")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Apri tutti gli aperti")
        self.assertContains(response, "?status=OPEN")
        self.assertContains(response, "Interventi aperti")
        self.assertContains(response, "Imposta prima esecuzione")

    def test_record_periodic_verification_execution_creates_workorder_and_advances_plan(self):
        from anagrafica.models import Fornitore

        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Cambio Olio",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        plan = PeriodicVerification.objects.create(
            name="Cambio olio",
            supplier=supplier,
            frequency_months=3,
            last_verification_date=date(2025, 11, 1),
            next_verification_date=date(2026, 2, 1),
            created_by=self.admin,
        )
        plan.assets.add(self.asset)
        self.client.force_login(self.admin)

        execution_date = date(2026, 4, 28)
        response = self.client.post(
            reverse("assets:periodic_verifications"),
            {
                "action": "record_periodic_verification_execution",
                "verification_id": str(plan.id),
                "execution_asset_id": str(self.asset.id),
                "execution_date": execution_date.isoformat(),
                "execution_duration_minutes": "45",
                "execution_cost_eur": "120,50",
                "execution_notes": "Sostituito olio idraulico, controllato livelli",
                "filter_asset": str(self.asset.id),
                "filter_scope": "production",
                "filter_window": "12",
            },
        )

        self.assertEqual(response.status_code, 302, response.content[:400])
        plan.refresh_from_db()
        self.assertEqual(plan.last_verification_date, execution_date)
        self.assertEqual(plan.next_verification_date, date(2026, 7, 28))

        wo = WorkOrder.objects.get(periodic_verification=plan, asset=self.asset)
        self.assertEqual(wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(wo.kind, WorkOrder.KIND_PREVENTIVE)
        self.assertEqual(wo.intervention_duration_minutes, 45)
        self.assertEqual(str(wo.cost_eur), "120.50")
        self.assertIn("olio idraulico", wo.resolution)
        self.assertEqual(wo.supplier_id, supplier.id)

    def test_record_maintenance_rule_execution_creates_workorder_and_updates_state(self):
        self.client.force_login(self.admin)

        execution_date = date(2026, 4, 20)
        response = self.client.post(
            reverse("assets:maintenance_schedule"),
            {
                "action": "record_maintenance_rule_execution",
                "asset_id": str(self.asset.id),
                "base_rule_id": str(self.base_rule.id),
                "execution_date": execution_date.isoformat(),
                "execution_duration_minutes": "30",
                "execution_cost_eur": "75",
                "execution_notes": "Lubrificazione completa guide e mandrino",
                "filter_asset": str(self.asset.id),
                "filter_status": "all",
            },
        )

        self.assertEqual(response.status_code, 302, response.content[:400])

        wo = WorkOrder.objects.get(maintenance_rule=self.base_rule, asset=self.asset)
        self.assertEqual(wo.status, WorkOrder.STATUS_DONE)
        self.assertEqual(wo.kind, WorkOrder.KIND_PREVENTIVE)
        self.assertEqual(wo.intervention_duration_minutes, 30)
        self.assertEqual(str(wo.cost_eur), "75.00")
        self.assertIn("Lubrificazione", wo.resolution)

        state = AssetMaintenanceRuleState.objects.get(asset=self.asset, base_rule=self.base_rule)
        self.assertEqual(state.last_execution_date, execution_date)
        self.assertEqual(state.last_work_order_id, wo.id)

        page = self.client.get(reverse("assets:maintenance_schedule"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Esecuzioni recenti")
        self.assertContains(page, "Registra esecuzione")

    def test_record_periodic_verification_execution_supports_multi_asset_and_attachments(self):
        from anagrafica.models import Fornitore
        from django.core.files.uploadedfile import SimpleUploadedFile
        from .models import WorkOrderAttachment

        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Multi",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        second_asset = Asset.objects.create(
            name="Centro di lavoro ST3 Secondo",
            asset_type=Asset.TYPE_WORK_MACHINE,
            asset_category=self.category,
            reparto="OFF",
            source_key="asset-step-three-second",
        )
        plan = PeriodicVerification.objects.create(
            name="Taratura mandrino",
            supplier=supplier,
            frequency_months=6,
            last_verification_date=date(2025, 11, 1),
            next_verification_date=date(2026, 5, 1),
            created_by=self.admin,
        )
        plan.assets.add(self.asset, second_asset)
        self.client.force_login(self.admin)

        execution_date = date(2026, 5, 3)
        attachment_file = SimpleUploadedFile(
            "verbale.pdf",
            b"%PDF-1.4 fake",
            content_type="application/pdf",
        )
        with patch("assets.views.validate_extension_and_mime", return_value="application/pdf"):
            response = self.client.post(
                reverse("assets:periodic_verifications"),
                {
                    "action": "record_periodic_verification_execution",
                    "verification_id": str(plan.id),
                    "execution_asset_ids": [str(self.asset.id), str(second_asset.id)],
                    "execution_date": execution_date.isoformat(),
                    "execution_duration_minutes": "60",
                    "execution_cost_eur": "200.00",
                    "execution_notes": "Taratura completata su entrambe le macchine",
                    "execution_files": [attachment_file],
                    "filter_asset": str(self.asset.id),
                    "filter_scope": "production",
                    "filter_window": "12",
                },
            )
        self.assertEqual(response.status_code, 302, response.content[:400])

        plan.refresh_from_db()
        self.assertEqual(plan.last_verification_date, execution_date)

        workorders = WorkOrder.objects.filter(periodic_verification=plan, asset__in=[self.asset, second_asset])
        self.assertEqual(workorders.count(), 2)
        for wo in workorders:
            self.assertEqual(wo.status, WorkOrder.STATUS_DONE)
            self.assertEqual(wo.attachments.count(), 1)
            attachment = wo.attachments.first()
            self.assertEqual(attachment.original_name, "verbale.pdf")

        total_attachments = WorkOrderAttachment.objects.filter(work_order__in=workorders).count()
        self.assertEqual(total_attachments, 2)

    def test_maintenance_schedule_lists_periodic_verifications(self):
        from anagrafica.models import Fornitore

        supplier = Fornitore.objects.create(
            ragione_sociale="Fornitore Tarature",
            categoria=Fornitore.CATEGORIA_MANUTENZIONE,
        )
        plan = PeriodicVerification.objects.create(
            name="Verifica manometri",
            supplier=supplier,
            frequency_months=12,
            last_verification_date=date(2025, 6, 1),
            next_verification_date=date(2026, 6, 1),
            created_by=self.admin,
        )
        plan.assets.add(self.asset)
        self.client.force_login(self.admin)

        page = self.client.get(reverse("assets:maintenance_schedule") + f"?asset={self.asset.id}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Verifiche periodiche pianificate")
        self.assertContains(page, "Verifica manometri")
        self.assertContains(page, "Apri piano")

    def test_complete_administrative_deadline_with_next_due_renews_record(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_REVISION,
            title="Revisione carroponte",
            due_date=date(2026, 4, 30),
            warning_days=30,
            is_active=True,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:asset_administrative_deadline_list"),
            {
                "action": "complete_administrative_deadline",
                "deadline_id": str(deadline.id),
                "execution_date": "2026-04-28",
                "execution_next_due": "2027-04-28",
                "execution_duration_minutes": "60",
                "execution_cost_eur": "350.00",
                "execution_notes": "Revisione completata, nuovo verbale archiviato",
            },
        )

        self.assertEqual(response.status_code, 302, response.content[:400])
        deadline.refresh_from_db()
        self.assertEqual(deadline.due_date, date(2027, 4, 28))
        self.assertTrue(deadline.is_active)

        completion = deadline.completions.get()
        self.assertEqual(completion.completed_on, date(2026, 4, 28))
        self.assertEqual(completion.next_due_date, date(2027, 4, 28))
        self.assertEqual(str(completion.cost_eur), "350.00")
        self.assertEqual(completion.duration_minutes, 60)
        self.assertEqual(completion.completed_by_id, self.admin.id)
        self.assertIn("verbale", completion.notes)

        page = self.client.get(reverse("assets:asset_administrative_deadline_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Storico completamenti")
        self.assertContains(page, "Revisione carroponte")

    def test_complete_administrative_deadline_without_next_due_closes_record(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Certificato CE provvisorio",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("assets:asset_administrative_deadline_list"),
            {
                "action": "complete_administrative_deadline",
                "deadline_id": str(deadline.id),
                "execution_date": "2026-04-15",
                "execution_cost_eur": "0",
                "execution_notes": "Sostituito da nuovo certificato CE2",
            },
        )

        self.assertEqual(response.status_code, 302)
        deadline.refresh_from_db()
        self.assertFalse(deadline.is_active)
        self.assertEqual(deadline.completions.count(), 1)

    def test_admin_deadline_completion_attachment_uses_private_download_route(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale ISPESL",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        upload = SimpleUploadedFile("verbale.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        self.client.force_login(self.admin)

        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
            patch("assets.views.validate_extension_and_mime", return_value="application/pdf"),
        ):
            response = self.client.post(
                reverse("assets:asset_administrative_deadline_list"),
                {
                    "action": "complete_administrative_deadline",
                    "deadline_id": str(deadline.id),
                    "execution_date": "2026-04-15",
                    "execution_notes": "Verbale allegato",
                    "completion_files": upload,
                },
            )
            self.assertEqual(response.status_code, 302)
            attachment = AssetAdministrativeDeadlineCompletionAttachment.objects.get()
            self.assertTrue((Path(private_root) / attachment.file.name).exists())
            self.assertFalse((Path(media_root) / attachment.file.name).exists())

            page = self.client.get(reverse("assets:asset_administrative_deadline_list"))
            self.assertContains(
                page,
                reverse("assets:admin_deadline_attachment_download", args=[attachment.id]),
            )

            download = self.client.get(reverse("assets:admin_deadline_attachment_download", args=[attachment.id]))
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download["Content-Type"], "application/pdf")
            self.assertEqual(b"".join(download.streaming_content), b"%PDF-1.4 test")
            self.assertNotContains(page, "/media/assets_admin_deadlines/")
            direct_media = self.client.get(settings.MEDIA_URL + attachment.file.name)
            self.assertIn(direct_media.status_code, {404, 302})

    def test_admin_deadline_attachment_download_requires_assets_admin(self):
        user = User.objects.create_user(username="asset-basic", password="pass12345")
        UserOnboarding.objects.update_or_create(
            user=user,
            defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
        )
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale riservato",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        completion = AssetAdministrativeDeadlineCompletion.objects.create(
            deadline=deadline,
            completed_on=date(2026, 4, 15),
        )
        with _workspace_temporary_directory("assets-private-") as private_root, override_settings(ASSETS_PRIVATE_ROOT=private_root):
            attachment = AssetAdministrativeDeadlineCompletionAttachment.objects.create(
                completion=completion,
                file=SimpleUploadedFile("verbale.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
                original_name="verbale.pdf",
            )
            self.client.force_login(user)
            response = self.client.get(reverse("assets:admin_deadline_attachment_download", args=[attachment.id]))
            self.assertEqual(response.status_code, 403)

    def test_admin_deadline_attachment_malicious_name_cannot_escape_private_root(self):
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale nome anomalo",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        completion = AssetAdministrativeDeadlineCompletion.objects.create(
            deadline=deadline,
            completed_on=date(2026, 4, 15),
        )
        self.client.force_login(self.admin)
        with _workspace_temporary_directory("assets-private-") as private_root, override_settings(ASSETS_PRIVATE_ROOT=private_root):
            attachment = AssetAdministrativeDeadlineCompletionAttachment.objects.create(
                completion=completion,
                file=SimpleUploadedFile("safe.pdf", b"safe", content_type="application/pdf"),
                original_name="safe.pdf",
            )
            attachment.file.name = "../escape.pdf"
            attachment.save(update_fields=["file"])
            outside = Path(private_root).parent / "escape.pdf"
            outside.write_bytes(b"outside")

            response = self.client.get(reverse("assets:admin_deadline_attachment_download", args=[attachment.id]))

            self.assertEqual(response.status_code, 404)
            self.assertTrue(outside.exists())

    def test_admin_deadline_attachment_download_creates_audit_log(self):
        from core.models import AuditLog

        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale audit",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        completion = AssetAdministrativeDeadlineCompletion.objects.create(
            deadline=deadline,
            completed_on=date(2026, 4, 15),
        )
        with _workspace_temporary_directory("assets-private-") as private_root, override_settings(ASSETS_PRIVATE_ROOT=private_root):
            attachment = AssetAdministrativeDeadlineCompletionAttachment.objects.create(
                completion=completion,
                file=SimpleUploadedFile("verbale-audit.pdf", b"%PDF-AUDIT", content_type="application/pdf"),
                original_name="verbale-audit.pdf",
            )
            self.client.force_login(self.admin)
            before = AuditLog.objects.count()
            response = self.client.get(reverse("assets:admin_deadline_attachment_download", args=[attachment.id]))
            self.assertEqual(response.status_code, 200)
            created = AuditLog.objects.filter(
                azione="download_admin_deadline_attachment", modulo="assets",
            ).order_by("-id").first()
            self.assertIsNotNone(created)
            self.assertEqual(AuditLog.objects.count(), before + 1)
            payload = created.dettaglio or {}
            self.assertEqual(payload.get("esito"), "success")
            self.assertEqual(payload.get("attachment_id"), attachment.id)
            self.assertEqual(payload.get("asset_id"), self.asset.id)
            serialized = repr(payload)
            self.assertNotIn(str(private_root), serialized)
            self.assertNotIn("%PDF-AUDIT", serialized)

    def test_admin_deadline_attachment_denied_creates_audit_without_path(self):
        from core.models import AuditLog

        user = User.objects.create_user(username="asset-audit-basic", password="pass12345")
        UserOnboarding.objects.update_or_create(
            user=user,
            defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
        )
        deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale audit denied",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        completion = AssetAdministrativeDeadlineCompletion.objects.create(
            deadline=deadline,
            completed_on=date(2026, 4, 15),
        )
        with _workspace_temporary_directory("assets-private-") as private_root, override_settings(ASSETS_PRIVATE_ROOT=private_root):
            attachment = AssetAdministrativeDeadlineCompletionAttachment.objects.create(
                completion=completion,
                file=SimpleUploadedFile("riservato.pdf", b"%PDF-RISERVATO", content_type="application/pdf"),
                original_name="riservato.pdf",
            )
            self.client.force_login(user)
            response = self.client.get(reverse("assets:admin_deadline_attachment_download", args=[attachment.id]))
            self.assertEqual(response.status_code, 403)
            created = AuditLog.objects.filter(
                azione="download_admin_deadline_attachment", modulo="assets",
            ).order_by("-id").first()
            self.assertIsNotNone(created)
            payload = created.dettaglio or {}
            self.assertEqual(payload.get("esito"), "denied")
            self.assertEqual(payload.get("motivo"), "permission_denied")
            serialized = repr(payload)
            self.assertNotIn(str(private_root), serialized)
            self.assertNotIn("%PDF-RISERVATO", serialized)
            self.assertNotIn("riservato.pdf", serialized)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetAdminDeadlineAttachmentMigrationCommandTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="asset-migrate-admin",
            email="asset-migrate-admin@test.local",
            password="pass12345",
        )
        self.asset = Asset.objects.create(
            name="Centro migrazione",
            asset_type=Asset.TYPE_WORK_MACHINE,
            asset_tag="MIG-001",
            source_key="asset-migrate-main",
        )
        self.deadline = AssetAdministrativeDeadline.objects.create(
            asset=self.asset,
            deadline_type=AssetAdministrativeDeadline.TYPE_CERTIFICATE,
            title="Verbale migrazione",
            due_date=date(2026, 5, 15),
            is_active=True,
        )
        self.completion = AssetAdministrativeDeadlineCompletion.objects.create(
            deadline=self.deadline,
            completed_on=date(2026, 4, 15),
            completed_by=self.admin,
        )

    def _attachment(self, name: str) -> AssetAdministrativeDeadlineCompletionAttachment:
        return AssetAdministrativeDeadlineCompletionAttachment.objects.create(
            completion=self.completion,
            file=name,
            original_name=Path(name).name,
            uploaded_by=self.admin,
        )

    def _run_command(self, *args: str) -> str:
        stdout = io.StringIO()
        call_command("migrate_admin_deadline_attachments_private", *args, stdout=stdout)
        return stdout.getvalue()

    def test_migration_command_dry_run_does_not_copy_or_delete(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment("assets_admin_deadlines/MIG-001/1/legacy.pdf")
            source = Path(media_root) / attachment.file.name
            source.parent.mkdir(parents=True)
            source.write_bytes(b"legacy")

            output = self._run_command()

            attachment.refresh_from_db()
            self.assertIn("DRY-RUN", output)
            self.assertTrue(source.exists())
            self.assertFalse((Path(private_root) / attachment.file.name).exists())
            self.assertEqual(attachment.file.name, "assets_admin_deadlines/MIG-001/1/legacy.pdf")

    def test_migration_command_apply_copies_to_private_root_and_normalizes_reference(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment(r"assets_admin_deadlines\MIG-001\1\legacy.pdf")
            source = Path(media_root) / "assets_admin_deadlines" / "MIG-001" / "1" / "legacy.pdf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"legacy")

            output = self._run_command("--apply")

            attachment.refresh_from_db()
            self.assertIn("APPLY", output)
            self.assertEqual(attachment.file.name, "assets_admin_deadlines/MIG-001/1/legacy.pdf")
            self.assertEqual((Path(private_root) / attachment.file.name).read_bytes(), b"legacy")
            self.assertTrue(source.exists())

    def test_migration_command_delete_source_only_after_successful_copy(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment("assets_admin_deadlines/MIG-001/1/delete.pdf")
            source = Path(media_root) / attachment.file.name
            source.parent.mkdir(parents=True)
            source.write_bytes(b"legacy")

            output = self._run_command("--apply", "--delete-source")

            self.assertIn("deleted=1", output)
            self.assertFalse(source.exists())
            self.assertEqual((Path(private_root) / attachment.file.name).read_bytes(), b"legacy")

    def test_migration_command_missing_source_warns_without_crashing(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment("assets_admin_deadlines/MIG-001/1/missing.pdf")

            output = self._run_command("--apply")

            self.assertIn("sorgente mancante", output)
            self.assertIn("missing=1", output)
            self.assertFalse((Path(private_root) / attachment.file.name).exists())

    def test_migration_command_is_idempotent_when_target_already_exists(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment("assets_admin_deadlines/MIG-001/1/done.pdf")
            source = Path(media_root) / attachment.file.name
            target = Path(private_root) / attachment.file.name
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"same")
            target.write_bytes(b"same")

            output = self._run_command("--apply", "--delete-source")

            self.assertIn("skipped=1", output)
            self.assertIn("deleted=1", output)
            self.assertFalse(source.exists())
            self.assertEqual(target.read_bytes(), b"same")

    def test_migration_command_collision_keeps_source_and_target_unchanged(self):
        with (
            _workspace_temporary_directory("assets-media-") as media_root,
            _workspace_temporary_directory("assets-private-") as private_root,
            override_settings(MEDIA_ROOT=media_root, ASSETS_PRIVATE_ROOT=private_root),
        ):
            attachment = self._attachment("assets_admin_deadlines/MIG-001/1/collision.pdf")
            source = Path(media_root) / attachment.file.name
            target = Path(private_root) / attachment.file.name
            source.parent.mkdir(parents=True)
            target.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            target.write_bytes(b"target")

            output = self._run_command("--apply", "--delete-source")

            self.assertIn("collisione target", output)
            self.assertIn("collisions=1", output)
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(target.read_bytes(), b"target")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AssetMaintenanceRegisterTicketTests(TestCase):
    """Test per l'integrazione dei ticket MAN nel registro manutenzione asset (PATCH 21E)."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            username="test-user",
            email="test@example.com",
            first_name="Test",
            last_name="User",
        )
        UserOnboarding.objects.update_or_create(
            user=self.user,
            defaults={
                "completed": True,
                "skipped": False,
                "completed_at": timezone.now(),
            },
        )

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

    def test_asset_detail_shows_man_ticket_in_maintenance_register(self):
        """Verifica che il dettaglio asset mostri i ticket MAN inclusi come manutenzione straordinaria."""
        # Crea ticket MAN incluso
        ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN test",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))

        self.assertEqual(response.status_code, 200)
        # Verifica che il ticket appaia nel registro manutenzione
        self.assertContains(response, ticket.numero_ticket)
        self.assertContains(response, ticket.titolo)

    def test_asset_detail_does_not_show_excluded_man_ticket(self):
        """Verifica che il dettaglio asset non mostri i ticket MAN esclusi nel registro manutenzione."""
        # Crea ticket MAN escluso
        ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN escluso",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=False,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))

        self.assertEqual(response.status_code, 200)
        # Verifica che il ticket non appaia nel registro manutenzione (sezione MANUTENZIONE)
        # Il ticket puÃ² comunque apparire nella sezione "Ticket collegati"
        from assets.services.maintenance_register import collect_asset_maintenance_register
        register = collect_asset_maintenance_register(self.asset, include_tickets=True)
        ticket_rows = [row for row in register if row["source"] == "TICKET"]
        self.assertEqual(len(ticket_rows), 0)

    def test_asset_detail_maintenance_register_preserves_workorders(self):
        """Verifica che il registro manutenzione mantenga anche le righe WorkOrder esistenti."""
        from .models import WorkOrder

        # Crea WorkOrder
        wo = WorkOrder.objects.create(
            asset=self.asset,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="WorkOrder test",
            description="Descrizione WorkOrder",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))

        self.assertEqual(response.status_code, 200)
        # Verifica che il WorkOrder appaia nel registro manutenzione
        self.assertContains(response, wo.title)

    def test_asset_detail_maintenance_register_shows_both_workorders_and_tickets(self):
        """Verifica che il registro manutenzione mostri sia WorkOrder che ticket MAN."""
        from .models import WorkOrder

        # Crea WorkOrder
        wo = WorkOrder.objects.create(
            asset=self.asset,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="WorkOrder test",
            description="Descrizione WorkOrder",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        # Crea ticket MAN incluso
        ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN test",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset.id}))
        self.assertEqual(response.status_code, 200)
        # Verifica che entrambi appaiano nel registro manutenzione
        self.assertContains(response, wo.title)
        self.assertContains(response, ticket.numero_ticket)


class AssetMaintenanceRegisterUnifiedTests(TestCase):
    """Test per il registro manutenzione unificato e generazione massiva (PATCH 21A-FINAL)."""

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser(
            username="maintenance-user",
            email="maintenance@example.com",
            password="secret123",
        )
        UserOnboarding.objects.update_or_create(
            user=self.user,
            defaults={
                "completed": True,
                "skipped": False,
                "completed_at": timezone.now(),
            },
        )

        # Crea categoria e asset di test
        self.category = AssetCategory.objects.create(
            code="CNC-TEST",
            label="Macchine CNC Test",
        )
        self.asset1 = Asset.objects.create(
            name="Macchina CNC 1",
            asset_tag="CNC-001",
            asset_type="CNC",
            asset_category=self.category,
            status="IN_USE",
        )
        self.asset2 = Asset.objects.create(
            name="Macchina CNC 2",
            asset_tag="CNC-002",
            asset_type="CNC",
            asset_category=self.category,
            status="IN_USE",
        )
        self.asset3 = Asset.objects.create(
            name="Macchina CNC 3",
            asset_tag="CNC-003",
            asset_type="CNC",
            asset_category=self.category,
            status="IN_USE",
        )

        # Crea template e regola di manutenzione
        self.template = MaintenanceInterventionTemplate.objects.create(
            code="cambio-olio-test",
            label="Cambio olio test",
            description="Template per cambio olio",
            asset_category=self.category,
        )
        self.rule = MaintenanceRule.objects.create(
            intervention_template=self.template,
            asset_category=self.category,
            threshold_type=MaintenanceRule.THRESHOLD_DAYS,
            threshold_value=90,
            warning_days=15,
        )

    def test_manual_workorder_can_be_created_for_single_asset(self):
        """Verifica che sia possibile creare un WorkOrder manuale per un singolo asset."""
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assets:wo_create", args=[self.asset1.id]),
            {
                "periodic_verification": "",
                "supplier": "",
                "kind": WorkOrder.KIND_CORRECTIVE,
                "status": WorkOrder.STATUS_OPEN,
                "origin": WorkOrder.ORIGIN_MANUAL,
                "title": "Manutenzione manuale test",
                "description": "Descrizione manutenzione manuale",
                "resolution": "",
                "downtime_minutes": "0",
                "cost_eur": "",
            },
        )

        self.assertEqual(response.status_code, 302)  # Redirect dopo creazione
        wo = WorkOrder.objects.filter(asset=self.asset1, origin=WorkOrder.ORIGIN_MANUAL).first()
        self.assertIsNotNone(wo)
        self.assertEqual(wo.title, "Manutenzione manuale test")
        self.assertEqual(wo.kind, WorkOrder.KIND_CORRECTIVE)
        self.assertEqual(wo.status, WorkOrder.STATUS_OPEN)

    def test_manual_workorder_appears_in_asset_maintenance_register(self):
        """Verifica che un WorkOrder manuale appaia nel registro manutenzione dell'asset."""
        # Crea WorkOrder manuale
        wo = WorkOrder.objects.create(
            asset=self.asset1,
            kind=WorkOrder.KIND_CORRECTIVE,
            origin=WorkOrder.ORIGIN_MANUAL,
            title="Manutenzione manuale",
            description="Test",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset1.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, wo.title)

    def test_periodic_rule_generation_creates_workorder_per_asset(self):
        """Verifica che la generazione da regola crei un WorkOrder per ogni asset."""
        from assets.services import generate_workorders_for_rule

        created = generate_workorders_for_rule(self.rule, user=self.user)

        self.assertEqual(len(created), 3)  # 3 asset nella categoria

        # Verifica che ogni asset abbia un WorkOrder
        for asset in [self.asset1, self.asset2, self.asset3]:
            wo = WorkOrder.objects.filter(
                asset=asset,
                maintenance_rule=self.rule,
                origin=WorkOrder.ORIGIN_PERIODIC,
            ).first()
            self.assertIsNotNone(wo)
            self.assertEqual(wo.kind, WorkOrder.KIND_PREVENTIVE)
            self.assertEqual(wo.status, WorkOrder.STATUS_OPEN)

    def test_periodic_rule_generation_uses_reference_batch(self):
        """Verifica che la generazione da regola usi un reference_batch comune."""
        from assets.services import generate_workorders_for_rule

        created = generate_workorders_for_rule(self.rule, user=self.user)

        self.assertEqual(len(created), 3)

        # Tutti i WorkOrder devono avere lo stesso reference_batch
        reference_batches = {wo.reference_batch for wo in created}
        self.assertEqual(len(reference_batches), 1)
        batch = reference_batches.pop()
        self.assertTrue(batch.startswith("BATCH_"))
        self.assertIn(str(self.rule.id), batch)

    def test_periodic_rule_generation_does_not_create_cross_asset_single_record(self):
        """Verifica che la generazione non crei un singolo record cross-asset."""
        from assets.services import generate_workorders_for_rule

        created = generate_workorders_for_rule(self.rule, user=self.user)

        self.assertEqual(len(created), 3)

        # Ogni WorkOrder deve essere associato a un asset specifico
        asset_ids = {wo.asset_id for wo in created}
        self.assertEqual(len(asset_ids), 3)
        self.assertIn(self.asset1.id, asset_ids)
        self.assertIn(self.asset2.id, asset_ids)
        self.assertIn(self.asset3.id, asset_ids)

    def test_workorder_report_attachment_upload(self):
        """Verifica che sia possibile caricare un allegato rapportino a un WorkOrder."""
        wo = WorkOrder.objects.create(
            asset=self.asset1,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="Intervento con allegato",
            status=WorkOrder.STATUS_OPEN,
        )

        upload = SimpleUploadedFile("report.pdf", b"%PDF-1.4 test", content_type="application/pdf")

        self.client.force_login(self.user)
        with _workspace_temporary_directory("assets-wo-attachments-") as media_root, override_settings(MEDIA_ROOT=media_root):
            with patch("assets.views.validate_extension_and_mime", return_value="application/pdf"):
                response = self.client.post(
                    reverse("assets:wo_create", args=[self.asset1.id]),
                    {
                        "periodic_verification": "",
                        "supplier": "",
                        "kind": WorkOrder.KIND_CORRECTIVE,
                        "status": WorkOrder.STATUS_OPEN,
                        "title": "Intervento con allegato",
                        "description": "Test",
                        "downtime_minutes": "0",
                        "attachments": upload,
                    },
                )

        self.assertEqual(response.status_code, 302)
        # Verifica che l'allegato sia stato creato
        attachment = WorkOrderAttachment.objects.filter(work_order__asset=self.asset1).first()
        self.assertIsNotNone(attachment)
        self.assertTrue(attachment.file.name.endswith(".pdf"))

    def test_workorder_report_attachment_visible_on_asset_detail(self):
        """Verifica che gli allegati WorkOrder siano visibili nel dettaglio asset."""
        wo = WorkOrder.objects.create(
            asset=self.asset1,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="Intervento con allegato",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        # Crea allegato
        attachment = WorkOrderAttachment.objects.create(
            work_order=wo,
            file=SimpleUploadedFile("report.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            original_name="report.pdf",
            uploaded_by=self.user,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("assets:asset_view", kwargs={"id": self.asset1.id}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, wo.title)

    def test_unified_register_contains_periodic_manual_and_ticket_rows(self):
        """Verifica che il registro unificato contenga righe PERIODIC, MANUAL e TICKET."""
        from assets.services import collect_asset_maintenance_register

        # Crea WorkOrder periodico
        wo_periodic = WorkOrder.objects.create(
            asset=self.asset1,
            maintenance_rule=self.rule,
            origin=WorkOrder.ORIGIN_PERIODIC,
            kind=WorkOrder.KIND_PREVENTIVE,
            title="Manutenzione periodica",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        # Crea WorkOrder manuale
        wo_manual = WorkOrder.objects.create(
            asset=self.asset1,
            origin=WorkOrder.ORIGIN_MANUAL,
            kind=WorkOrder.KIND_CORRECTIVE,
            title="Manutenzione manuale",
            status=WorkOrder.STATUS_DONE,
            closed_at=timezone.now(),
        )

        # Crea ticket MAN incluso
        ticket = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN test",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset1,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
            stato=StatoTicket.CHIUSO,
            closed_at=timezone.now(),
        )

        # Raccogli registro
        register = collect_asset_maintenance_register(self.asset1, include_tickets=True)

        self.assertEqual(len(register), 3)

        sources = {row["source"] for row in register}
        self.assertIn("WORKORDER", sources)
        self.assertIn("TICKET", sources)

        # Verifica che ci siano entrambi i WorkOrder
        wo_rows = [row for row in register if row["source"] == "WORKORDER"]
        self.assertEqual(len(wo_rows), 2)

        # Verifica che ci sia il ticket
        ticket_rows = [row for row in register if row["source"] == "TICKET"]
        self.assertEqual(len(ticket_rows), 1)

    def test_ticket_it_not_in_unified_register(self):
        """Verifica che i ticket IT non siano inclusi nel registro unificato."""
        from assets.services import collect_asset_maintenance_register

        # Crea ticket IT
        ticket_it = Ticket.objects.create(
            tipo=TipoTicket.IT,
            titolo="Ticket IT test",
            descrizione="Descrizione test",
            categoria="SOFTWARE",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset1,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        # Crea ticket MAN
        ticket_man = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN test",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset1,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        register = collect_asset_maintenance_register(self.asset1, include_tickets=True)

        # Solo il ticket MAN deve essere presente
        self.assertEqual(len(register), 1)
        self.assertEqual(register[0]["source"], "TICKET")
        self.assertEqual(register[0]["ticket"].id, ticket_man.id)

    def test_ticket_man_excluded_flag_not_in_unified_register(self):
        """Verifica che i ticket MAN con flag exclude non siano nel registro unificato."""
        from assets.services import collect_asset_maintenance_register

        # Crea ticket MAN incluso
        ticket_included = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN incluso",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset1,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=True,
        )

        # Crea ticket MAN escluso
        ticket_excluded = Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo="Ticket MAN escluso",
            descrizione="Descrizione test",
            categoria="MECCANICA",
            priorita=PrioritaTicket.MEDIA,
            asset=self.asset1,
            richiedente_nome="Test User",
            richiedente_email="test@example.com",
            include_in_maintenance_register=False,
        )

        register = collect_asset_maintenance_register(self.asset1, include_tickets=True)

        # Solo il ticket incluso deve essere presente
        self.assertEqual(len(register), 1)
        self.assertEqual(register[0]["ticket"].id, ticket_included.id)
