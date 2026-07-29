"""Test dell'autoconfigurazione SOC (servizio + pagina /soc/admin/autoconfig/).

Il servizio e' la fonte unica dei default: qui si verifica che il piano sia
onesto (dice davvero cosa manca), che l'apply sia idempotente e non distruttivo,
che i fix chiudano il check diagnostico da cui nascono e che tutto finisca nel
registro audit.
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from security.models import (
    SecurityAlertRuleConfig,
    SecurityAlertSuppressionRule,
    SecurityCenterSetting,
    SecurityConfigurationAuditLog,
    SecurityNotificationChannel,
    SecurityParserConfig,
    SecuritySourceConfig,
    SecurityTicketConfig,
    Severity,
)
from security.services.autoconfig import (
    apply_autoconfig,
    apply_fix,
    available_fixes,
    plan_autoconfig,
    plan_summary,
)
from security.services.diagnostics import run_security_center_diagnostics


class AutoconfigPlanTest(TestCase):
    def test_plan_su_db_vuoto_segnala_tutto_da_creare(self):
        plan = plan_autoconfig()
        summary = plan_summary(plan)
        self.assertGreater(summary["to_create"], 0)
        self.assertEqual(summary["aligned"], 0)
        self.assertTrue(all(row["status"] == "missing" for row in plan))

    def test_plan_non_scrive_nulla(self):
        plan_autoconfig()
        self.assertEqual(SecurityCenterSetting.objects.count(), 0)
        self.assertEqual(SecuritySourceConfig.objects.count(), 0)

    def test_sezione_sconosciuta_rifiutata(self):
        with self.assertRaises(ValueError):
            plan_autoconfig(["non_esiste"])


class AutoconfigApplyTest(TestCase):
    def test_apply_crea_la_configurazione_e_poi_e_idempotente(self):
        first = apply_autoconfig()
        self.assertGreater(first["created"], 0)
        self.assertTrue(SecurityCenterSetting.objects.exists())
        self.assertTrue(SecuritySourceConfig.objects.exists())
        self.assertTrue(SecurityParserConfig.objects.exists())
        self.assertTrue(SecurityAlertRuleConfig.objects.exists())
        self.assertTrue(SecurityTicketConfig.objects.exists())

        second = apply_autoconfig()
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 0)

        self.assertEqual(plan_summary(plan_autoconfig())["to_create"], 0)

    def test_apply_non_sovrascrive_le_personalizzazioni(self):
        apply_autoconfig()
        rule = SecurityAlertRuleConfig.objects.get(code="defender_critical_cve_cvss_gte_9")
        rule.threshold_value = "7"
        rule.save(update_fields=["threshold_value"])

        result = apply_autoconfig()
        rule.refresh_from_db()
        self.assertEqual(rule.threshold_value, "7")
        skipped = {row["key"]: row["skipped"] for row in result["sections"]}
        self.assertIn("defender_critical_cve_cvss_gte_9", skipped["alert_rules"])

    def test_overwrite_riallinea_ai_default(self):
        apply_autoconfig()
        rule = SecurityAlertRuleConfig.objects.get(code="defender_critical_cve_cvss_gte_9")
        rule.threshold_value = "7"
        rule.save(update_fields=["threshold_value"])

        apply_autoconfig(overwrite=True)
        rule.refresh_from_db()
        self.assertEqual(rule.threshold_value, "9")

    def test_apply_di_una_sola_sezione(self):
        apply_autoconfig(["ticketing"])
        self.assertTrue(SecurityTicketConfig.objects.exists())
        self.assertFalse(SecuritySourceConfig.objects.exists())

    def test_apply_scrive_l_audit_con_l_attore(self):
        user = get_user_model().objects.create_user("soc_autoconfig_actor", password="x")
        apply_autoconfig(["ticketing"], actor=user)
        log = SecurityConfigurationAuditLog.objects.filter(action="autoconfig_create").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.actor, user)


class SeedCommandTest(TestCase):
    """Il comando storico resta il wrapper CLI dello stesso servizio."""

    def test_dry_run_non_scrive(self):
        out = StringIO()
        call_command("seed_security_center_config", "--dry-run", stdout=out)
        self.assertIn("da creare", out.getvalue())
        self.assertEqual(SecuritySourceConfig.objects.count(), 0)

    def test_seed_e_riallineamento(self):
        call_command("seed_security_center_config", stdout=StringIO())
        self.assertTrue(SecuritySourceConfig.objects.exists())

        rule = SecurityAlertRuleConfig.objects.get(code="defender_critical_cve_cvss_gte_9")
        rule.threshold_value = "7"
        rule.save(update_fields=["threshold_value"])

        # comportamento storico: il comando riallinea ai default...
        call_command("seed_security_center_config", stdout=StringIO())
        rule.refresh_from_db()
        self.assertEqual(rule.threshold_value, "9")

        # ...salvo chiedere esplicitamente di non farlo.
        rule.threshold_value = "7"
        rule.save(update_fields=["threshold_value"])
        call_command("seed_security_center_config", "--no-overwrite", stdout=StringIO())
        rule.refresh_from_db()
        self.assertEqual(rule.threshold_value, "7")

    def test_only_seziona(self):
        call_command("seed_security_center_config", "--only", "ticketing", stdout=StringIO())
        self.assertTrue(SecurityTicketConfig.objects.exists())
        self.assertFalse(SecuritySourceConfig.objects.exists())

    def test_reset_svuota_la_sezione(self):
        call_command("seed_security_center_config", "--only", "sources", stdout=StringIO())
        self.assertTrue(SecuritySourceConfig.objects.exists())
        call_command("seed_security_center_config", "--only", "sources", "--reset", stdout=StringIO())
        # il reset elimina e riseleziona i default: la sezione resta popolata
        self.assertTrue(SecuritySourceConfig.objects.exists())


class AutoconfigFixTest(TestCase):
    def test_fix_disponibili_solo_per_check_non_ok(self):
        codes = {fix["code"] for fix in available_fixes()}
        self.assertIn("seed_config", codes)

        apply_autoconfig()
        codes_after = {fix["code"] for fix in available_fixes()}
        self.assertNotIn("seed_config", codes_after)

    def test_fix_seed_config_chiude_il_check(self):
        apply_fix("seed_config")
        checks = {c["code"]: c for c in run_security_center_diagnostics()["checks"]}
        self.assertEqual(checks["security_config_seeded"]["status"], "ok")

    def test_fix_ticketing_e_notifiche(self):
        apply_fix("create_ticket_config")
        apply_fix("create_dashboard_channel")
        self.assertTrue(SecurityTicketConfig.objects.exists())
        self.assertTrue(SecurityNotificationChannel.objects.filter(channel_type="dashboard").exists())

    def test_fix_riattiva_le_sorgenti_disattivate(self):
        apply_autoconfig(["sources"])
        SecuritySourceConfig.objects.update(enabled=False)
        result = apply_fix("enable_sources")
        self.assertEqual(SecuritySourceConfig.objects.filter(enabled=False).count(), 0)
        self.assertIn("attivate", result["message"])

    def test_fix_disattiva_le_soppressioni_scadute(self):
        rule = SecurityAlertSuppressionRule.objects.create(
            name="Soppressione scaduta",
            reason="test",
            is_active=True,
            expires_at=timezone.now() - timezone.timedelta(days=1),
        )
        apply_fix("expire_suppressions")
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

    def test_fix_defender_ticket_automatici(self):
        apply_autoconfig(["alert_rules"])
        SecurityAlertRuleConfig.objects.filter(severity=Severity.CRITICAL).update(auto_create_ticket=False)
        apply_fix("defender_critical_tickets")
        self.assertFalse(
            SecurityAlertRuleConfig.objects.filter(
                enabled=True, severity=Severity.CRITICAL, source_type__icontains="defender", auto_create_ticket=False
            ).exists()
        )

    def test_fix_sconosciuto_rifiutato(self):
        with self.assertRaises(ValueError):
            apply_fix("non_esiste")


class MigrationsDiagnosticTest(TestCase):
    def test_check_migrazioni_non_e_un_falso_positivo(self):
        # Il DB di test e' migrato: il check deve dire "ok" (prima chiamava
        # migrate --dry-run, opzione inesistente, e restava sempre in warning).
        checks = {c["code"]: c for c in run_security_center_diagnostics()["checks"]}
        self.assertEqual(checks["migrations"]["status"], "ok")


@override_settings(LEGACY_AUTH_ENABLED=False)
class AutoconfigViewTest(TestCase):
    def setUp(self):
        super().setUp()
        U = get_user_model()
        self.admin = U.objects.create_user("soc_autoconfig_admin", password="x", is_staff=True, is_superuser=True)
        self.plain = U.objects.create_user("soc_autoconfig_plain", password="x")

    def test_pagina_visibile_a_chi_gestisce_la_configurazione(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("security:admin_autoconfig"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Piano di configurazione")

    def test_pagina_negata_a_utente_senza_permessi(self):
        # Il diniego puo' arrivare dal gate della view (403) o prima dall'ACL
        # di piattaforma (redirect): quello che conta e' che non si apra.
        self.client.force_login(self.plain)
        response = self.client.get(reverse("security:admin_autoconfig"))
        self.assertIn(response.status_code, (302, 403))

    def test_apply_htmx_ritorna_il_partial_e_configura(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("security:admin_autoconfig_apply"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SecuritySourceConfig.objects.exists())
        self.assertTrue(SecurityConfigurationAuditLog.objects.filter(action="autoconfig_create").exists())

    def test_apply_negato_a_utente_senza_permessi(self):
        self.client.force_login(self.plain)
        response = self.client.post(reverse("security:admin_autoconfig_apply"))
        self.assertIn(response.status_code, (302, 403))
        self.assertFalse(SecuritySourceConfig.objects.exists())

    def test_apply_richiede_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("security:admin_autoconfig_apply")).status_code, 405)

    def test_fix_sconosciuto_404(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("security:admin_autoconfig_fix", args=["non-esiste"]))
        self.assertEqual(response.status_code, 404)

    def test_fix_applicato_dalla_pagina(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("security:admin_autoconfig_fix", args=["create_ticket_config"]), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(SecurityTicketConfig.objects.exists())
