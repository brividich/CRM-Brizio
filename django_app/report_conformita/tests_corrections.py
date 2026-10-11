from io import BytesIO
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory, Client
from django.urls import reverse
from openpyxl import load_workbook

from assets.models import Asset
from .acl_bootstrap import PERM_VIEW, PERM_AREA, PERM_EDIT, _bootstrap_canonical
from .corrections import CorrectionData, corrected_result
from .models import ReportCorrection
from .registry import all_reports, get_report, ReportParams
from .sources import COLUMN_SOURCES
from .tests import _params


class ReportCorrectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(username="report_editor", is_superuser=True, is_staff=True)
        cls.asset = Asset.objects.create(asset_tag="QA-IT-01", name="PC sintetico", asset_type=Asset.TYPE_PC,
                                        serial_number="QA-SERIAL", assignment_to="Ufficio QA")

    def setUp(self):
        self.client.force_login(self.admin)
        self.definition = get_report("inventario-it")
        self.params = _params()
        self.url = reverse("report_conformita:dati", args=[self.definition.slug])

    def data(self):
        return CorrectionData(self.definition, self.params, self.definition.build(self.params))

    def save_cell(self, data=None, cell=None, value="Rettifica QA", action="correct"):
        data = data or self.data()
        cell = cell or data.rows[0][1]
        return self.client.post(self.url, {"target": cell.target, "token": data.token(cell),
                                        "value": value, "reason": "Verifica sintetica", "action": action})

    def test_all_reports_have_sources_and_data_page(self):
        for definition in all_reports():
            with self.subTest(report=definition.slug):
                result = definition.build(self.params)
                self.assertEqual(len(COLUMN_SOURCES[definition.slug]), len(result.columns))
                self.assertEqual(len(result.rows), len(result.row_keys))
                self.assertTrue(all(result.row_keys))
                response = self.client.get(reverse("report_conformita:dati", args=[definition.slug]))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Dati e fonti")
                report = self.client.get(reverse("report_conformita:report", args=[definition.slug]))
                self.assertContains(report, reverse("report_conformita:dati", args=[definition.slug]))

    def test_save_restore_history_and_source_untouched(self):
        self.assertEqual(self.save_cell().status_code, 302)
        self.asset.refresh_from_db()
        self.assertEqual(self.asset.name, "PC sintetico")
        result = corrected_result(self.definition, self.params)
        self.assertEqual(result.rows[0][1], "Rettifica QA")
        self.assertTrue(any("RETTIFICHE" in note for note in result.notes))
        self.assertEqual(self.save_cell(action="restore").status_code, 302)
        self.assertEqual(corrected_result(self.definition, self.params).rows[0][1], "PC sintetico")
        self.assertEqual(ReportCorrection.objects.count(), 2)
        self.assertTrue(ReportCorrection.objects.first().restored)

    def test_reordering_does_not_move_correction(self):
        self.save_cell()
        Asset.objects.create(asset_tag="AA-FIRST", name="Altro PC", asset_type=Asset.TYPE_PC)
        result = corrected_result(self.definition, self.params)
        names = {row[0]: row[1] for row in result.rows}
        self.assertEqual(names["QA-IT-01"], "Rettifica QA")
        self.assertEqual(names["AA-FIRST"], "Altro PC")

    def test_source_change_suspends_correction(self):
        self.save_cell()
        Asset.objects.filter(pk=self.asset.pk).update(name="Nome aggiornato")
        result = corrected_result(self.definition, self.params)
        self.assertEqual(result.rows[0][1], "Nome aggiornato")
        self.assertTrue(self.data().rows[0][1].stale)
        self.assertTrue(any("sospesa" in note for note in result.notes))

    def test_stale_form_rejected_for_source_or_revision_change(self):
        old = self.data()
        self.save_cell()
        self.assertEqual(self.save_cell(data=old).status_code, 409)
        current = self.data()
        Asset.objects.filter(pk=self.asset.pk).update(name="Altra modifica")
        self.assertEqual(self.save_cell(data=current).status_code, 409)
        self.assertEqual(ReportCorrection.objects.count(), 1)

    def test_unknown_target_and_forged_token_rejected(self):
        response = self.client.post(self.url, {"target": "not-a-target"})
        self.assertEqual(response.status_code, 404)
        cell = self.data().rows[0][1]
        response = self.client.post(self.url, {"target": cell.target, "token": "forged", "reason": "QA", "action": "correct"})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ReportCorrection.objects.exists())

    def test_view_permission_cannot_write_or_cross_area(self):
        allowed = {PERM_VIEW, *PERM_AREA.values()}
        with patch("report_conformita.views._has_perm", side_effect=lambda req, code: code in allowed):
            self.assertEqual(self.client.get(self.url).status_code, 200)
            self.assertEqual(self.save_cell().status_code, 403)
        with patch("report_conformita.views._has_perm", side_effect=lambda req, code: code in {PERM_VIEW, PERM_EDIT}):
            self.assertEqual(self.client.get(self.url).status_code, 403)
            self.assertEqual(self.save_cell().status_code, 403)
        self.assertFalse(ReportCorrection.objects.exists())

    def test_empty_value_preserved_and_reason_required(self):
        self.save_cell(value="")
        self.assertEqual(corrected_result(self.definition, self.params).rows[0][1], "")
        cell = self.data().rows[0][1]
        response = self.client.post(self.url, {"target": cell.target, "token": self.data().token(cell),
                                             "value": "X", "reason": "  ", "action": "correct"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ReportCorrection.objects.count(), 1)

    def test_source_editor_link_and_acl_filter(self):
        edit_url = reverse("assets:asset_edit", args=[self.asset.pk])
        self.assertContains(self.client.get(self.url), edit_url)
        with patch("core.middleware.acl_allows_path", return_value=False):
            self.assertNotContains(self.client.get(self.url), edit_url)

    def test_correction_exported_and_audited(self):
        from core.models import AuditLog
        from .exports import report_pdf
        self.save_cell(value="=1+1")
        url = reverse("report_conformita:report", args=[self.definition.slug])
        response = self.client.get(url, {"formato": "xlsx"})
        wb = load_workbook(BytesIO(response.content))
        matches = [c for row in wb["Dati"] for c in row if "=1+1" in str(c.value)]
        self.assertEqual(len(matches), 1)
        self.assertNotEqual(matches[0].data_type, "f")
        result = corrected_result(self.definition, self.params)
        self.assertTrue(report_pdf(self.definition, self.params, result).startswith(b"%PDF"))
        self.assertTrue(AuditLog.objects.filter(azione="report_conformita_rettifica").exists())

    def test_kpi_override_reaches_riesame_without_row_notes(self):
        data = self.data()
        self.save_cell(data=data, cell=data.kpis[0], value="99")
        self.save_cell(value="Nominativo sintetico riservato")
        result = corrected_result(self.definition, self.params)
        self.assertEqual(result.kpis[0].value, "99")
        self.assertTrue(result.riesame_notes)
        self.assertFalse(any("riservato" in note for note in result.riesame_notes))
        response = self.client.get(reverse("report_conformita:riesame"))
        self.assertContains(response, "99")
        self.assertNotContains(response, "Nominativo sintetico riservato")

    def test_scopes_follow_report_filters_and_period_semantics(self):
        other = ReportParams(date(2020, 1, 1), date(2020, 12, 31), self.params.today)
        self.save_cell()
        self.assertEqual(corrected_result(self.definition, other).rows[0][1], "Rettifica QA")
        period_definition = get_report("registro-nc-ofi")
        result = period_definition.build(self.params)
        data = CorrectionData(period_definition, self.params, result)
        request = RequestFactory().post("/")
        request.user = self.admin
        cell = data.kpis[0]
        data.save(request, cell, {"token": data.token(cell), "value": "99", "reason": "QA", "action": "correct"})
        self.assertNotEqual(corrected_result(period_definition, other).kpis[0].value, "99")
        filtered = _params(norma="45001")
        self.assertNotEqual(corrected_result(period_definition, filtered).kpis[0].value, "99")

    def test_csrf_and_anonymous_access(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.admin)
        protected.get(self.url, {"target": self.data().rows[0][1].target})
        self.assertEqual(protected.post(self.url, {}).status_code, 403)
        self.assertFalse(ReportCorrection.objects.exists())

    def test_acl_bootstrap_binds_new_page_and_edit_permission(self):
        from core.models import PermissionDefinition, RoutePermissionBinding
        _bootstrap_canonical()
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_EDIT).exists())
        self.assertTrue(RoutePermissionBinding.objects.filter(route_name="report_conformita:dati", permission_id=PERM_VIEW).exists())

    def test_html_is_escaped(self):
        self.save_cell(value="<script>test_synthetic()</script>")
        response = self.client.get(self.url)
        self.assertNotContains(response, "<script>test_synthetic()</script>")
        self.assertContains(response, "&lt;script&gt;test_synthetic()&lt;/script&gt;")

    def test_parallel_revisions_do_not_overwrite(self):
        before = self.data()
        other = self.data()
        cell = before.rows[0][1]
        request = RequestFactory().post("/")
        request.user = self.admin
        payload = {"token": before.token(cell), "value": "Prima", "reason": "QA", "action": "correct"}
        before.save(request, cell, payload)
        with self.assertRaisesMessage(ValueError, "Un altro utente"):
            other.save(request, other.cells[cell.target], payload)
        self.assertEqual(ReportCorrection.objects.count(), 1)

    def test_report_link_preserves_period_and_filter(self):
        url = reverse("report_conformita:report", args=["registro-nc-ofi"])
        response = self.client.get(url, {"da": "2026-01-01", "a": "2026-03-31", "norma": "45001"})
        self.assertContains(response, "da=2026-01-01&amp;a=2026-03-31&amp;norma=45001")

    def test_removed_source_not_reapplied_but_history_kept(self):
        self.save_cell()
        Asset.objects.filter(pk=self.asset.pk).update(status="RETIRED")
        self.assertEqual(corrected_result(self.definition, self.params).rows, [])
        self.assertContains(self.client.get(self.url), "Verifica sintetica")

    def test_invalid_export_characters_and_excessive_values_rejected(self):
        for value in ("X" * 251, "Bad\x01cell"):
            with self.subTest(value_length=len(value)):
                self.assertEqual(self.save_cell(value=value).status_code, 400)
        data = self.data()
        self.assertEqual(self.save_cell(data=data, cell=data.kpis[0], value="9" * 81).status_code, 400)
        self.assertFalse(ReportCorrection.objects.exists())

    def test_restore_ignores_replacement_validation(self):
        self.save_cell()
        self.assertEqual(self.save_cell(value="X" * 1000, action="restore").status_code, 302)
        self.assertEqual(corrected_result(self.definition, self.params).rows[0][1], "PC sintetico")
