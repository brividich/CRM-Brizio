"""Test di regressione dell'innesto SOC IT - CN (modulo security nell'HUB).

Copre SOLO ciò che è stato wired nelle fasi B1-B3 (dashboard, alert/ticket/KPI,
pipeline sincrona, Configuration Studio). NON è la suite completa di SC-AI (che
testa anche funzioni non ancora montate — API DRF, AI, mailbox): quella verrà
riportata separatamente. Le viste sono dietro `ACLMiddleware`; qui si autentica un
superuser (che bypassa l'ACL) per verificare rendering e assenza di regressioni.
"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse


class _AuthedSuperuserMixin:
    """Login come superuser: nell'HUB ogni vista /soc/ è dietro ACLMiddleware."""

    def setUp(self):
        super().setUp()
        U = get_user_model()
        u, _ = U.objects.get_or_create(
            username="soc_test_admin",
            defaults={"is_staff": True, "is_superuser": True},
        )
        u.is_staff = True
        u.is_superuser = True
        u.save()
        self.client.force_login(u)


class SocPagesRenderTest(_AuthedSuperuserMixin, TestCase):
    def test_dashboard(self):
        self.assertEqual(self.client.get(reverse("security:dashboard")).status_code, 200)

    def test_alerts_list(self):
        self.assertEqual(self.client.get(reverse("security:alerts_list")).status_code, 200)

    def test_tickets_list(self):
        self.assertEqual(self.client.get(reverse("security:tickets_list")).status_code, 200)

    def test_kpis(self):
        self.assertEqual(self.client.get(reverse("security:kpis")).status_code, 200)

    def test_pipeline_page(self):
        self.assertEqual(self.client.get(reverse("security:pipeline")).status_code, 200)

    def test_pipeline_run_sync(self):
        # La pipeline gira in modo sincrono (parser+regole+KPI) senza Celery/coda.
        r = self.client.post(reverse("security:pipeline_run", args=["full"]), HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)

    def test_inbox(self):
        self.assertEqual(self.client.get(reverse("security:inbox")).status_code, 200)

    def test_admin_config_dashboard(self):
        self.assertEqual(self.client.get(reverse("security:admin_config")).status_code, 200)

    def test_admin_config_subpages(self):
        for name in [
            "admin_config_general", "admin_config_sources", "admin_config_parsers",
            "admin_config_alert_rules", "admin_config_suppressions", "admin_config_backups",
            "admin_config_notifications", "admin_config_ticketing", "admin_config_audit",
        ]:
            self.assertEqual(self.client.get(reverse(f"security:{name}")).status_code, 200, name)

    def test_diagnostics(self):
        self.assertEqual(self.client.get(reverse("security:admin_diagnostics")).status_code, 200)

    def test_addons(self):
        self.assertEqual(self.client.get(reverse("security:admin_addons")).status_code, 200)


class SocTasksTest(TestCase):
    def test_background_tasks_import_and_run(self):
        # Celery rimosso: i 2 task sono funzioni pure (django-q2). Su DB vuoto ritornano 0.
        from security import tasks
        self.assertEqual(tasks.run_security_parsers_task(), 0)
        self.assertEqual(tasks.evaluate_security_rules_task(), 0)


class SocAiToolTest(TestCase):
    """Sotto-progetto C: tool live 'soc_summary' nell'assistente AI (aggregati security)."""

    def test_wants_soc_only_it_security(self):
        from ai_assistant.tools import _wants_soc_context
        self.assertTrue(_wants_soc_context("quanti alert di sicurezza aperti e critici?"))
        self.assertTrue(_wants_soc_context("ci sono CVE critiche o vulnerabilita da rimediare?"))
        # NON deve attivarsi su altri domini (DPI) o sulla sicurezza SUL LAVORO:
        self.assertFalse(_wants_soc_context("quali DPI sono in scadenza?"))
        self.assertFalse(_wants_soc_context("mostra i rischi della mansione saldatore"))

    def test_soc_tool_registered_and_routed(self):
        from ai_assistant.tools import _soc_context, RUNTIME_TOOLS, _DOMAIN_ROUTING_SEEDS
        self.assertIn(_soc_context, RUNTIME_TOOLS)
        self.assertIn("soc", _DOMAIN_ROUTING_SEEDS)

    def test_soc_context_superuser_aggregati(self):
        from django.test import RequestFactory
        from ai_assistant.tools import _soc_context
        U = get_user_model()
        u = U.objects.create(username="soc_ai_test", is_superuser=True, is_staff=True)
        req = RequestFactory().get("/")
        req.user = u
        ctx = _soc_context(req, "quanti alert di sicurezza aperti?")
        self.assertIn("SECURITY CENTER", ctx.text)
        self.assertTrue(ctx.audit["allowed"])
        # privacy: nessun campo nominativo/host negli aggregati (DB vuoto)
        self.assertEqual(ctx.audit.get("row_count", 0), 0)


class SecurityAssetLinkTest(TestCase):
    """Sotto-progetto D2: collegamento SecurityAsset↔Asset dell'HUB."""

    def test_hub_asset_fk_nullable(self):
        from security.models import SecurityAsset
        sa = SecurityAsset.objects.create(hostname="HOST-D2")
        self.assertIsNone(sa.hub_asset)

    def test_command_dryrun_non_fallisce(self):
        from io import StringIO
        out = StringIO()
        call_command("collega_asset_security", stdout=out)
        self.assertIn("match trovati", out.getvalue())

    def test_match_per_hostname(self):
        from io import StringIO
        from assets.models import Asset
        from security.models import SecurityAsset
        Asset.objects.create(asset_tag="D2-TAG", name="FIREWALL-01")
        sa = SecurityAsset.objects.create(hostname="FIREWALL-01")
        out = StringIO()
        call_command("collega_asset_security", "--apply", stdout=out)
        sa.refresh_from_db()
        self.assertIsNotNone(sa.hub_asset)
        self.assertEqual(sa.hub_asset.name, "FIREWALL-01")
