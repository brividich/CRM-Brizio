from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import SiteConfig
from core.reminder_recipients import resolve_reminder_recipients

User = get_user_model()


@override_settings(ADMINS=())
class ResolveReminderRecipientsTests(TestCase):
    """(c) Cascata destinatario unica: override → setting → SiteConfig → ADMINS → superuser."""

    def test_override_vince_e_pulisce(self):
        self.assertEqual(
            resolve_reminder_recipients(config_key="x", override=[" a@b.it ", "", "c@d.it"]),
            ["a@b.it", "c@d.it"],
        )

    def test_siteconfig(self):
        SiteConfig.set("test_reminder_emails", "a@b.it, c@d.it", "test")
        self.assertEqual(
            resolve_reminder_recipients(config_key="test_reminder_emails"),
            ["a@b.it", "c@d.it"],
        )

    def test_setting_key_prima_del_siteconfig(self):
        SiteConfig.set("test_reminder_emails", "site@x.it", "test")
        with override_settings(MONITORING_ADMIN_EMAILS="setting@x.it"):
            res = resolve_reminder_recipients(
                config_key="test_reminder_emails", setting_emails_key="MONITORING_ADMIN_EMAILS"
            )
        self.assertEqual(res, ["setting@x.it"])  # il setting vince sul SiteConfig

    def test_fallback_superuser(self):
        User.objects.create_user(
            "su", email="su@x.it", password="pw", is_superuser=True, is_active=True
        )
        res = resolve_reminder_recipients(config_key="chiave_assente_xyz")
        self.assertIn("su@x.it", res)

    def test_admins_prima_del_superuser(self):
        User.objects.create_user("su2", email="su2@x.it", password="pw", is_superuser=True)
        with override_settings(ADMINS=[("Admin", "admin@x.it")]):
            res = resolve_reminder_recipients(config_key="chiave_assente_xyz")
        self.assertEqual(res, ["admin@x.it"])

    def test_wrapper_anagrafica_delega(self):
        from anagrafica.services.reminders import get_reminder_recipients

        self.assertEqual(get_reminder_recipients("x", override=["a@b.it"]), ["a@b.it"])

    def test_wrapper_monitoring_delega(self):
        from monitoring.services import _admin_recipients

        with override_settings(MONITORING_ADMIN_EMAILS="mon@x.it"):
            self.assertEqual(_admin_recipients(), ["mon@x.it"])
