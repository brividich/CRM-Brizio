"""Diagnostica DB/audit (BUILD_SPEC R0.5), doctor e tuning su ambiente non SQL Server."""
from __future__ import annotations

import io
import json
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core import db_diagnostics as dd
from core.models import AuditLog


class SoglieTests(SimpleTestCase):
    def test_limite_per_edizione(self):
        self.assertEqual(dd.edition_limit_mb("Express Edition (64-bit)", "16.0.4135.4"), 10240)
        self.assertEqual(dd.edition_limit_mb("Express Edition (64-bit)", "15.0.2000.5"), 10240)
        self.assertEqual(dd.edition_limit_mb("Express Edition (64-bit)", "17.0.1000.7"), 51200)
        self.assertIsNone(dd.edition_limit_mb("Standard Edition (64-bit)", "16.0.1"))

    def test_previsione_saturazione(self):
        cap = {"limit_mb": 10240, "data_used_mb": 7000}
        self.assertEqual(dd.saturation_forecast(cap, {"daily_mb": 81})["days_to_limit"], 40)
        self.assertIsNone(dd.saturation_forecast({"limit_mb": None}, {"daily_mb": 5})["days_to_limit"])

    def test_stato_crescita(self):
        cap = {"limit_mb": 10240, "data_used_mb": 7000}
        self.assertEqual(dd.audit_growth_status(cap, {"daily_mb": 81, "monthly_projection_mb": 2430})[0], "critical")
        self.assertEqual(dd.audit_growth_status(cap, {"daily_mb": 20, "monthly_projection_mb": 600})[0], "warning")
        self.assertEqual(dd.audit_growth_status(cap, {"daily_mb": 1, "monthly_projection_mb": 30})[0], "ok")
        # senza limite di edizione conta solo la crescita mensile
        self.assertEqual(dd.audit_growth_status({}, {"daily_mb": 20, "monthly_projection_mb": 600})[0], "warning")


class DiagnosticaTests(TestCase):
    def setUp(self):
        cache.delete("monitoring:audit-growth:result")
        AuditLog.objects.create(azione="auto_insert", modulo="automazioni", dettaglio={"model": "AutomationRule", "pk": "1"})
        AuditLog.objects.create(azione="auto_insert", modulo="security", dettaglio={"model": "SecuritySourceFile", "pk": "2"})

    def test_audit_growth_e_top_modelli(self):
        g = dd.audit_growth(days=7)
        self.assertGreaterEqual(g["recent_rows"], 2)
        self.assertEqual(g["policy_version"], 1)
        modelli = {t["modello"]: t["classe"] for t in g["top_models"]}
        self.assertEqual(modelli.get("SecuritySourceFile"), "metadata_only")
        self.assertEqual(modelli.get("AutomationRule"), "full")

    def test_doctor_testo_e_json(self):
        out = io.StringIO()
        call_command("hub_backup_doctor", stdout=out)
        self.assertIn("Audit (politica v1)", out.getvalue())
        out = io.StringIO()
        call_command("hub_backup_doctor", "--json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertIn("audit", data)
        self.assertFalse(data["capacity"]["supported"])

    def test_tuning_no_op_fuori_da_sql_server(self):
        out = io.StringIO()
        call_command("hub_db_tuning", "--apply", stdout=out)
        self.assertIn("Nessuna azione", out.getvalue())

    def test_check_audit_growth_mai_critical(self):
        from monitoring import health

        with mock.patch.object(dd, "server_capacity", return_value={"limit_mb": 10240, "data_used_mb": 10000, "used_pct": 97}), \
                mock.patch.object(dd, "audit_growth", return_value={"daily_mb": 80, "monthly_projection_mb": 2400, "policy_version": 1}):
            res = health.check_audit_growth()
        self.assertEqual(res.status, health.STATUS_FAIL)
        self.assertFalse(res.critical)
        self.assertEqual(res.details["days_to_limit"], 3)
        self.assertIn("audit_growth", health.available_checks())
        # memoizzato
        self.assertEqual(health.check_audit_growth().details["days_to_limit"], 3)
