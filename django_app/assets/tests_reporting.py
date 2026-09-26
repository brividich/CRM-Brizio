from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from assets.models import Asset, AssetReportRun, AssetReportSchedule
from assets.reporting_forms import AssetReportScheduleForm
from assets.services import reporting
from assets.services.reporting_exports import export_excel


class ReportingTests(TestCase):
    def setUp(self):
        self.asset = Asset.objects.create(asset_tag="REPORT-QA-01", name="=1+1", reparto="QA", status="IN_USE")
        self.plan = AssetReportSchedule.objects.create(name="Inventario QA", next_run=timezone.now() - timedelta(minutes=2), anchor_day=31)

    def run_report(self):
        run = reporting.create_run(self.plan, timezone.now())
        reporting.generate_run(run.pk)
        run.refresh_from_db()
        return run

    def test_generation_archives_matching_pdf_excel_and_snapshot(self):
        run = self.run_report()
        self.assertEqual(run.status, "DONE")
        self.assertTrue(bytes(run.pdf_content).startswith(b"%PDF"))
        self.assertEqual(run.snapshot["metrics"]["assets"], 1)
        wb = load_workbook(BytesIO(bytes(run.excel_content)))
        self.assertEqual(wb["Asset"]["B4"].value, "=1+1")
        self.assertEqual(wb["Asset"]["B4"].data_type, "s")
        self.assertEqual(wb["Riepilogo"]["B4"].value, 1)

    def test_snapshot_and_files_do_not_change_after_asset_or_plan_changes(self):
        run = self.run_report()
        pdf = bytes(run.pdf_content)
        self.asset.name = "Nuovo nome"
        self.asset.save()
        self.plan.name = "Nuovo titolo"
        self.plan.save()
        reporting.generate_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.snapshot["assets"][0]["nome"], "=1+1")
        self.assertEqual(run.configuration["name"], "Inventario QA")
        self.assertEqual(bytes(run.pdf_content), pdf)

    def test_filters_and_only_same_scope_trend(self):
        self.run_report()
        Asset.objects.create(asset_tag="REPORT-QA-02", name="Secondo", reparto="ALTRO")
        second = self.run_report()
        self.assertEqual([r["assets"] for r in second.snapshot["trend"]], [1, 2])
        self.plan.reparto = "QA"
        self.plan.save()
        changed = self.run_report()
        self.assertEqual(len(changed.snapshot["trend"]), 1)
        self.assertEqual(changed.snapshot["metrics"]["assets"], 1)

    def test_mfc_and_snmp_linked_information_in_snapshot(self):
        from contatori.models import Macchina, LetturaMensileContatori, DispositivoSNMP
        mfc = Macchina.objects.create(matricola="QA-MFC-REPORT", reparto="QA", asset=self.asset)
        LetturaMensileContatori.objects.create(macchina=mfc, mese=timezone.localdate().replace(day=1), a4_bn=15, a3_bn=2, a4_col=3, a3_col=4)
        DispositivoSNMP.objects.create(nome="QA reader", host="192.0.2.19", asset=self.asset, snmp_stato="ERROR")
        snap = reporting.build_snapshot(reporting.configuration(self.plan))
        self.assertEqual(snap["mfc"][0]["a4_bn"], 15)
        self.assertEqual(snap["metrics"]["snmp_errors"], 1)

    def test_month_end_and_dst_keep_local_time(self):
        rome = ZoneInfo("Europe/Rome")
        self.plan.next_run = datetime(2026, 1, 31, 8, tzinfo=rome)
        feb = reporting.next_deadline(self.plan, self.plan.next_run)
        self.assertEqual((feb.month, feb.day, feb.hour), (2, 28, 8))
        self.plan.next_run = feb
        march = reporting.next_deadline(self.plan, feb)
        self.assertEqual((march.month, march.day, march.hour), (3, 31, 8))
        self.assertEqual(march.utcoffset(), timedelta(hours=2))

    @patch("assets.services.reporting.async_task")
    def test_dispatch_idempotent_and_once_disables_plan(self, task):
        self.plan.frequency = "ONCE"
        self.plan.save()
        reporting.dispatch_due_reports()
        reporting.dispatch_due_reports()
        self.assertEqual(AssetReportRun.objects.count(), 1)
        task.assert_called_once()
        self.plan.refresh_from_db()
        self.assertFalse(self.plan.enabled)

    @patch("assets.services.reporting.async_task")
    def test_disabled_and_future_schedules_do_not_run(self, task):
        self.plan.enabled = False
        self.plan.save()
        AssetReportSchedule.objects.create(name="Futuro", next_run=timezone.now() + timedelta(days=2))
        reporting.dispatch_due_reports()
        task.assert_not_called()

    def test_failed_render_keeps_snapshot_for_retry(self):
        run = reporting.create_run(self.plan, timezone.now())
        with patch("assets.services.reporting_exports.export_pdf", side_effect=RuntimeError("QA failure")):
            with self.assertRaises(RuntimeError):
                reporting.generate_run(run.pk)
        self.asset.name = "Modificato dopo fallimento"
        self.asset.save()
        reporting.generate_run(run.pk)
        run.refresh_from_db()
        self.assertEqual(run.status, "DONE")
        self.assertEqual(run.snapshot["assets"][0]["nome"], "=1+1")
        self.assertEqual(run.attempts, 2)

    def test_worker_respects_retry_limit(self):
        run = reporting.create_run(self.plan, timezone.now())
        run.status, run.attempts = "ERROR", 3
        run.save()
        with patch("assets.services.reporting.build_snapshot") as build:
            self.assertEqual(reporting.generate_run(run.pk), {"saltato": True})
            build.assert_not_called()

    def test_display_dates_are_local_without_mutating_archive(self):
        run = self.run_report()
        shown = reporting.display_snapshot(run.snapshot)
        self.assertIn("/", shown["captured_at"])
        self.assertIn("T", run.snapshot["captured_at"])

    @patch("assets.services.reporting.async_task")
    def test_third_timeout_becomes_retryable_error(self, task):
        self.plan.enabled = False
        self.plan.save()
        run = reporting.create_run(self.plan, timezone.now())
        run.status, run.attempts = "RUNNING", 3
        run.started_at = timezone.now() - timedelta(minutes=11)
        run.save()
        reporting.dispatch_due_reports()
        run.refresh_from_db()
        self.assertEqual(run.status, "ERROR")
        task.assert_not_called()

    def test_empty_scope_generates_valid_files(self):
        self.plan.reparto = "INESISTENTE"
        self.plan.save()
        run = self.run_report()
        self.assertEqual(run.snapshot["metrics"]["assets"], 0)

    def test_form_rejects_no_output_format(self):
        form = AssetReportScheduleForm({"name": "QA", "frequency": "ONCE", "next_run": "2026-12-01T08:00"})
        self.assertFalse(form.is_valid())
        self.assertIn("formato", str(form.non_field_errors()))


class ReportingViewsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("report-admin", "report@example.test", "qa-password")
        self.plan = AssetReportSchedule.objects.create(name="QA report", next_run=timezone.now())
        self.run = reporting.create_run(self.plan, timezone.now())
        reporting.generate_run(self.run.pk)

    def test_anonymous_cannot_read_or_download(self):
        for name, args in [("reporting_archive", []), ("reporting_detail", [self.run.pk]), ("reporting_download", [self.run.pk, "pdf"]), ("reporting_settings", [])]:
            response = self.client.get(reverse("assets:" + name, args=args))
            self.assertIn(response.status_code, (302, 403))

    def test_authenticated_without_permission_cannot_read(self):
        user = get_user_model().objects.create_user("report-denied", password="qa-password")
        self.client.force_login(user)
        for name, args in [("reporting_settings", []), ("reporting_download", [self.run.pk, "xlsx"])]:
            response = self.client.get(reverse("assets:" + name, args=args))
            self.assertIn(response.status_code, (302, 403))

    def test_admin_pages_downloads_and_post_only_actions(self):
        self.client.force_login(self.admin)
        for name, args in [("reporting_settings", []), ("reporting_archive", []), ("reporting_detail", [self.run.pk])]:
            self.assertEqual(self.client.get(reverse("assets:" + name, args=args)).status_code, 200)
        response = self.client.get(reverse("assets:reporting_download", args=[self.run.pk, "xlsx"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(self.client.get(reverse("assets:reporting_run", args=[self.plan.pk])).status_code, 405)

    def test_canonical_bindings_separate_settings_and_reading(self):
        from core.models import RoutePermissionBinding
        self.assertEqual(RoutePermissionBinding.objects.get(path_pattern="/assets/impostazioni/reportistica").permission_id, "legacy.assets.admin_assets")
        self.assertEqual(RoutePermissionBinding.objects.get(path_pattern="/assets/reports/archivio").permission_id, "legacy.assets.assets_reports")

    def test_save_schedule_from_settings(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("assets:reporting_settings"), {
            "name": "Mensile giorno 31", "frequency": "MONTHLY", "next_run": "2026-10-31T09:30",
            "export_pdf": "on", "export_excel": "on", "enabled": "on",
        })
        self.assertEqual(response.status_code, 302)
        plan = AssetReportSchedule.objects.get(name="Mensile giorno 31")
        self.assertEqual(plan.anchor_day, 31)
        self.assertEqual(plan.created_by, self.admin)

    @patch("assets.services.reporting.async_task")
    def test_manual_double_click_queues_once_without_changing_deadline(self, task):
        self.client.force_login(self.admin)
        deadline = self.plan.next_run
        for _ in range(2):
            response = self.client.post(reverse("assets:reporting_run", args=[self.plan.pk]))
            self.assertEqual(response.status_code, 302)
        self.assertEqual(self.plan.runs.filter(status="PENDING").count(), 1)
        task.assert_called_once()
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.next_run, deadline)
