"""Config SOC: le righe si modificano, si attivano/disattivano, si eliminano; gli errori si vedono."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from security.models import BackupExpectedJobConfig, SecurityAlertRuleConfig, SecurityConfigurationAuditLog, SecurityNotificationChannel, SecuritySourceConfig
from security.services.autoconfig import apply_autoconfig


class ConfigCrudTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create(username="cfg_admin", is_staff=True, is_superuser=True))
        apply_autoconfig(None)
        self.rule = SecurityAlertRuleConfig.objects.order_by("code").first()
        self.url = reverse("security:admin_config_alert_rules")

    def _rule_data(self, **overrides):
        data = {
            "code": self.rule.code, "name": self.rule.name, "enabled": "on", "source_type": self.rule.source_type,
            "metric_name": self.rule.metric_name, "condition_operator": self.rule.condition_operator,
            "threshold_value": self.rule.threshold_value or "1", "threshold_json": "{}", "severity": self.rule.severity,
            "cooldown_minutes": 60, "dedup_window_minutes": 60, "description": "",
        }
        data.update(overrides)
        return data

    def test_every_row_has_edit_toggle_delete(self):
        response = self.client.get(self.url)
        self.assertContains(response, f"?edit={self.rule.pk}")
        self.assertContains(response, 'value="toggle"')
        self.assertContains(response, 'value="delete"')

    def test_edit_form_is_prefilled_and_saves_the_existing_row(self):
        response = self.client.get(self.url, {"edit": self.rule.pk})
        self.assertContains(response, f"Modifica «{self.rule}»")
        self.assertContains(response, f'name="object_id" value="{self.rule.pk}"')
        self.client.post(self.url, {**self._rule_data(name="Nome corretto"), "object_id": self.rule.pk})
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.name, "Nome corretto")
        self.assertEqual(SecurityAlertRuleConfig.objects.filter(code=self.rule.code).count(), 1)

    def test_toggle_and_delete_are_audited(self):
        was = self.rule.enabled
        self.client.post(self.url, {"action": "toggle", "object_id": self.rule.pk})
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.enabled, not was)
        pk = self.rule.pk
        self.client.post(self.url, {"action": "delete", "object_id": pk})
        self.assertFalse(SecurityAlertRuleConfig.objects.filter(pk=pk).exists())
        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(action="delete", object_id=str(pk)).exists())

    def test_invalid_save_shows_which_field_is_wrong(self):
        response = self.client.post(self.url, {**self._rule_data(), "cooldown_minutes": "non-un-numero", "object_id": self.rule.pk})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Non salvato", status_code=400)
        self.assertContains(response, "Cooldown minuti", status_code=400)

    def test_backup_expected_job_missing_field_is_explained(self):
        url = reverse("security:admin_config_backups")
        response = self.client.post(url, {"job_name": "J1", "device_name": "D", "nas_name": "N", "enabled": "on", "expected_days_of_week": "[]", "missing_after_hours": 26})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Durata massima minuti", status_code=400)
        ok = self.client.post(url, {"job_name": "J1", "device_name": "D", "nas_name": "N", "enabled": "on", "expected_days_of_week": "[]", "missing_after_hours": 26, "max_duration_minutes": 0})
        self.assertEqual(ok.status_code, 302)
        self.assertTrue(BackupExpectedJobConfig.objects.filter(job_name="J1").exists())

    def test_sources_edit_and_test_match_still_work(self):
        source = SecuritySourceConfig.objects.order_by("name").first()
        url = reverse("security:admin_config_sources")
        self.client.post(url, {"object_id": source.pk, "name": source.name, "source_type": source.source_type, "vendor": source.vendor, "enabled": "on",
                               "description": "", "expected_frequency": "daily", "mailbox_sender_patterns": "*x*", "mailbox_subject_patterns": "",
                               "parser_name": source.parser_name, "severity_mapping_json": "{}", "metadata_json": "{}"})
        source.refresh_from_db()
        self.assertEqual(source.mailbox_sender_patterns, ["*x*"])
        response = self.client.post(url, {"action": "test-match", "source_id": source.pk, "sender": "a@x.test", "subject": "s"})
        self.assertContains(response, "corrispondenza")

    def test_notification_secret_is_replaced_only_when_given(self):
        channel = SecurityNotificationChannel.objects.first()
        url = reverse("security:admin_config_notifications")
        data = {"object_id": channel.pk, "name": channel.name, "channel_type": channel.channel_type, "enabled": "on", "severity_min": channel.severity_min,
                "recipients": "", "cooldown_minutes": 5}
        self.client.post(url, {**data, "replace_webhook_secret": "https://hook.example.test/x"})
        channel.refresh_from_db()
        self.assertEqual(channel.webhook_url_secret_ref, "https://hook.example.test/x")
        self.client.post(url, data)
        channel.refresh_from_db()
        self.assertEqual(channel.webhook_url_secret_ref, "https://hook.example.test/x")

    def test_ticketing_cannot_be_deleted(self):
        self.assertNotContains(self.client.get(reverse("security:admin_config_ticketing")), 'value="delete"')
