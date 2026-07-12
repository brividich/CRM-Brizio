"""Test di regressione dell'innesto SOC IT - CN (modulo security nell'HUB).

Copre SOLO ciò che è stato wired nelle fasi B1-B3 (dashboard, alert/ticket/KPI,
pipeline sincrona, Configuration Studio). NON è la suite completa di SC-AI (che
testa anche funzioni non ancora montate — API DRF, AI, mailbox): quella verrà
riportata separatamente. Le viste sono dietro `ACLMiddleware`; qui si autentica un
superuser (che bypassa l'ACL) per verificare rendering e assenza di regressioni.
"""
from django.contrib.auth import get_user_model
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
