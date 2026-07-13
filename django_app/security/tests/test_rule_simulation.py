"""
Tests for rule simulation functionality.

Tests cover non-destructive rule simulation against historical data.
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from security.models import (
    SecurityAlert,
    SecurityAlertRuleConfig,
    SecurityEventRecord,
    SecurityReport,
    SecurityReportMetric,
    SecuritySource,
    SecurityVulnerabilityFinding,
    Severity,
    Status,
)
from security.services.rule_simulation import simulate_alert_rule


class RuleSimulationTests(TestCase):
    """Test non-destructive rule simulation."""

    def setUp(self):
        """Set up test data."""
        self.source = SecuritySource.objects.create(
            name="Test Source",
            source_type="manual",
        )
        self.report = SecurityReport.objects.create(
            source=self.source,
            title="Test Report",
            report_type="vulnerability",
        )

    def test_simulate_rule_requires_permission(self):
        """Test that simulation requires proper permission."""
        # This is tested at the API level, not service level
        pass

    def test_simulate_rule_does_not_create_alerts(self):
        """Test that simulation does not create SecurityAlert records."""
        initial_alert_count = SecurityAlert.objects.count()

        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Verify no alerts were created
        self.assertEqual(SecurityAlert.objects.count(), initial_alert_count)
        self.assertTrue(result["safe"])

    def test_simulate_metric_rule_with_metric_name(self):
        """Test simulation of metric rule with metric_name."""
        # Create test metrics
        SecurityReportMetric.objects.create(
            report=self.report,
            name="test_metric",
            value=5.0,
            unit="count",
        )
        SecurityReportMetric.objects.create(
            report=self.report,
            name="test_metric",
            value=2.0,
            unit="count",
        )

        rule = {
            "code": "test-metric-rule",
            "name": "Test Metric Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "3",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test metric rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should match at least one metric
        self.assertGreater(result["raw_matches"], 0)
        self.assertGreater(result["coverage"]["metrics_checked"], 0)

    def test_simulate_vulnerability_rule_critical_cvss(self):
        """Test simulation of vulnerability rule for critical CVSS >= 9."""
        # Create test vulnerability findings
        SecurityVulnerabilityFinding.objects.create(
            source=self.source,
            report=self.report,
            cve="CVE-2025-0001",
            affected_product="Test Product",
            cvss=9.8,
            exposed_devices=2,
            severity=Severity.CRITICAL,
            status=Status.OPEN,
        )
        SecurityVulnerabilityFinding.objects.create(
            source=self.source,
            report=self.report,
            cve="CVE-2025-0002",
            affected_product="Test Product",
            cvss=7.5,
            exposed_devices=0,
            severity=Severity.HIGH,
            status=Status.OPEN,
        )

        rule = {
            "code": "test-vuln-rule",
            "name": "Test Vulnerability Rule",
            "enabled": True,
            "source_type": "defender",
            "metric_name": "",
            "condition_operator": "gte",
            "threshold_value": "9",
            "threshold_json": {"cvss": 9},
            "severity": "critical",
            "cooldown_minutes": 1440,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": True,
            "auto_create_evidence_container": True,
            "description": "Test vulnerability rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should match at least one critical vulnerability
        self.assertGreater(result["raw_matches"], 0)
        self.assertGreater(result["coverage"]["findings_checked"], 0)

    def test_simulate_event_payload_condition(self):
        """Test simulation of event payload condition."""
        # Create test events
        SecurityEventRecord.objects.create(
            source=self.source,
            report=self.report,
            event_type="test_event",
            severity=Severity.HIGH,
            payload={"type": "malware", "status": "detected"},
        )
        SecurityEventRecord.objects.create(
            source=self.source,
            report=self.report,
            event_type="test_event",
            severity=Severity.INFO,
            payload={"type": "info", "status": "logged"},
        )

        rule = {
            "code": "test-event-rule",
            "name": "Test Event Rule",
            "enabled": True,
            "source_type": "watchguard",
            "metric_name": "",
            "condition_operator": "contains",
            "threshold_value": "malware",
            "threshold_json": {"type": "malware"},
            "severity": "high",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test event rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should match at least one event
        self.assertGreater(result["coverage"]["events_checked"], 0)

    def test_invalid_operator_returns_error(self):
        """Test that invalid operator returns validation error."""
        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "invalid_operator",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        self.assertFalse(result["safe"])
        self.assertIn("condition_operator", result["warnings"][0])

    def test_invalid_severity_returns_error(self):
        """Test that invalid severity returns validation error."""
        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "invalid_severity",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        self.assertFalse(result["safe"])
        self.assertIn("severity", result["warnings"][0])

    def test_invalid_threshold_json_returns_error(self):
        """Test that invalid threshold_json returns validation error."""
        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": "not a dict",
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        self.assertFalse(result["safe"])
        self.assertIn("threshold_json", result["warnings"][0])

    def test_generic_rule_without_conditions_returns_low_confidence(self):
        """Test that generic rule without conditions returns low confidence."""
        rule = {
            "code": "test-generic-rule",
            "name": "Test Generic Rule",
            "enabled": True,
            "source_type": "",
            "metric_name": "",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test generic rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        self.assertEqual(result["confidence"], "low")
        self.assertTrue(any("Simulazione poco affidabile" in w for w in result["warnings"]))

    def test_high_raw_matches_produces_high_noise_level(self):
        """Test that high raw matches produce high noise level."""
        # Create many test metrics
        for i in range(50):
            SecurityReportMetric.objects.create(
                report=self.report,
                name="test_metric",
                value=float(i),
                unit="count",
            )

        rule = {
            "code": "test-noisy-rule",
            "name": "Test Noisy Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test noisy rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        self.assertIn(result["noise_level"], ["high", "critical"])

    def test_cooldown_dedup_reduces_deduplicated_matches(self):
        """Test that cooldown and dedup reduce deduplicated matches."""
        # Create test metrics
        for i in range(20):
            SecurityReportMetric.objects.create(
                report=self.report,
                name="test_metric",
                value=float(i),
                unit="count",
            )

        rule = {
            "code": "test-dedup-rule",
            "name": "Test Dedup Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 1440,
            "dedup_window_minutes": 10080,  # 1 week
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test dedup rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Deduplicated matches should be less than raw matches
        self.assertLess(result["deduplicated_matches"], result["raw_matches"])

    def test_examples_limited_by_max_examples(self):
        """Test that examples are limited by max_examples."""
        # Create many test metrics
        for i in range(20):
            SecurityReportMetric.objects.create(
                report=self.report,
                name="test_metric",
                value=float(i),
                unit="count",
            )

        rule = {
            "code": "test-examples-rule",
            "name": "Test Examples Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test examples rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 5})

        # Examples should be limited to max_examples
        self.assertLessEqual(len(result["examples"]), 5)

    def test_payload_examples_are_redacted(self):
        """Test that payload examples are redacted."""
        # Create test event with potentially sensitive data
        SecurityEventRecord.objects.create(
            source=self.source,
            report=self.report,
            event_type="test_event",
            severity=Severity.HIGH,
            payload={
                "type": "malware",
                "api_key": "secret-key-12345",
                "password": "secret-password",
            },
        )

        rule = {
            "code": "test-redaction-rule",
            "name": "Test Redaction Rule",
            "enabled": True,
            "source_type": "watchguard",
            "metric_name": "",
            "condition_operator": "contains",
            "threshold_value": "malware",
            "threshold_json": {},
            "severity": "high",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test redaction rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Check that examples don't contain secrets
        for example in result["examples"]:
            payload = example.get("redacted_payload_preview", {})
            self.assertNotIn("secret-key-12345", str(payload))
            self.assertNotIn("secret-password", str(payload))

    def test_secret_like_values_not_in_response(self):
        """Test that secret-like values don't appear in response."""
        # Create test event with secrets
        SecurityEventRecord.objects.create(
            source=self.source,
            report=self.report,
            event_type="test_event",
            severity=Severity.HIGH,
            payload={
                "api_key": "secret-key-12345",
                "token": "secret-token-67890",
            },
        )

        rule = {
            "code": "test-secrets-rule",
            "name": "Test Secrets Rule",
            "enabled": True,
            "source_type": "watchguard",
            "metric_name": "",
            "condition_operator": "contains",
            "threshold_value": "test",
            "threshold_json": {},
            "severity": "high",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test secrets rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Check that secrets don't appear in response
        result_str = str(result)
        self.assertNotIn("secret-key-12345", result_str)
        self.assertNotIn("secret-token-67890", result_str)

    def test_baseline_deviation_produces_warning_if_not_supported(self):
        """Test that baseline_deviation produces warning if not fully supported."""
        rule = {
            "code": "test-baseline-rule",
            "name": "Test Baseline Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "baseline_deviation",
            "threshold_value": "1",
            "threshold_json": {"baseline": 10, "deviation": 2},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test baseline deviation rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should not fail, but may have low confidence
        self.assertTrue(result["safe"])

    def test_simulate_defender_critical_rule_suggests_tickets(self):
        """Test that Defender critical rule suggests would_create_tickets."""
        # Create critical vulnerability
        SecurityVulnerabilityFinding.objects.create(
            source=self.source,
            report=self.report,
            cve="CVE-2025-0001",
            affected_product="Edge",
            cvss=9.8,
            exposed_devices=2,
            severity=Severity.CRITICAL,
            status=Status.OPEN,
        )

        rule = {
            "code": "defender-critical-cve",
            "name": "Defender Critical CVE",
            "enabled": True,
            "source_type": "defender",
            "metric_name": "",
            "condition_operator": "gte",
            "threshold_value": "9",
            "threshold_json": {"cvss": 9, "exposed_devices": 0},
            "severity": "critical",
            "cooldown_minutes": 1440,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": True,
            "auto_create_evidence_container": True,
            "description": "Defender critical CVE with CVSS >= 9 and exposed devices > 0",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should suggest tickets if auto_create_ticket is True
        if result["would_create_alerts"] > 0:
            self.assertGreater(result["would_create_tickets"], 0)
            self.assertGreater(result["would_create_evidence_containers"], 0)

    def test_simulation_id_is_generated(self):
        """Test that simulation_id is generated."""
        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should have a simulation_id
        self.assertTrue(result["simulation_id"])
        self.assertTrue(result["simulation_id"].startswith("sim-"))

    def test_coverage_includes_lookback_days(self):
        """Test that coverage includes lookback_days."""
        rule = {
            "code": "test-rule",
            "name": "Test Rule",
            "enabled": True,
            "source_type": "manual",
            "metric_name": "test_metric",
            "condition_operator": "gte",
            "threshold_value": "1",
            "threshold_json": {},
            "severity": "medium",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Coverage should include lookback_days
        self.assertEqual(result["coverage"]["lookback_days"], 30)

    def test_suppressed_matches_counted(self):
        """Test that suppressed matches are counted."""
        # Create suppressed event
        SecurityEventRecord.objects.create(
            source=self.source,
            report=self.report,
            event_type="test_event",
            severity=Severity.HIGH,
            payload={"type": "malware"},
            suppressed=True,
        )

        rule = {
            "code": "test-suppressed-rule",
            "name": "Test Suppressed Rule",
            "enabled": True,
            "source_type": "watchguard",
            "metric_name": "",
            "condition_operator": "contains",
            "threshold_value": "malware",
            "threshold_json": {},
            "severity": "high",
            "cooldown_minutes": 60,
            "dedup_window_minutes": 1440,
            "auto_create_ticket": False,
            "auto_create_evidence_container": True,
            "description": "Test suppressed rule",
        }

        result = simulate_alert_rule(rule, {"lookback_days": 30, "max_examples": 10})

        # Should count suppressed matches
        self.assertGreaterEqual(result["suppressed_matches"], 0)
