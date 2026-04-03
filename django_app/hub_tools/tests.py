import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import ModuleCategory, NavigationItem, SiteConfig


class HubCategorieViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            username="hub-categorie-admin",
            email="hub.categorie@test.local",
            password="test-pass-123",
        )
        cls.legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("hub_tools:hub_categorie")

    def _admin_access(self):
        stack = ExitStack()
        stack.enter_context(
            patch("admin_portale.decorators.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("admin_portale.decorators.is_legacy_admin", return_value=True)
        )
        stack.enter_context(
            patch("core.context_processors.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("core.context_processors.is_legacy_admin", return_value=True)
        )
        return stack

    def test_categorie_get_and_branding_post(self):
        with self._admin_access():
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        payload = {
            "action": "branding",
            "portal_name": "Portal QA",
            "portal_subtitle": "Area test",
            "brand_logo_full": "/media/brand-full.svg",
            "brand_logo_compact": "/media/brand-compact.svg",
        }
        with self._admin_access():
            response = self.client.post(self.url, payload)

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(SiteConfig.get("portal_name"), "Portal QA")
        self.assertEqual(SiteConfig.get("portal_subtitle"), "Area test")
        self.assertEqual(SiteConfig.get("brand_logo_full"), "/media/brand-full.svg")
        self.assertEqual(SiteConfig.get("brand_logo_compact"), "/media/brand-compact.svg")

    def test_categorie_create_edit_assign_and_item_icon_post(self):
        nav_item = NavigationItem.objects.create(
            code="qa-dashboard",
            label="QA Dashboard",
            section="topbar",
            order=10,
        )

        with self._admin_access():
            response = self.client.post(
                self.url,
                {
                    "action": "create",
                    "key": "quality",
                    "label": "QUALITY",
                    "icon": "QA",
                    "topbar_color": "#112233",
                    "order": "7",
                },
            )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)

        category = ModuleCategory.objects.get(key="quality")
        self.assertEqual(category.label, "QUALITY")
        self.assertEqual(category.icon, "QA")
        self.assertEqual(category.topbar_color, "#112233")
        self.assertEqual(category.order, 7)

        with self._admin_access():
            response = self.client.post(
                self.url,
                {
                    "action": "item_icon",
                    "nav_item_id": str(nav_item.id),
                    "icon": "DB",
                },
            )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        nav_item.refresh_from_db()
        self.assertEqual(nav_item.icon, "DB")

        with self._admin_access():
            response = self.client.post(
                self.url,
                {
                    "action": "assign",
                    "nav_item_id": str(nav_item.id),
                    "category_id": str(category.id),
                },
            )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        nav_item.refresh_from_db()
        self.assertEqual(nav_item.category_id, category.id)

        with self._admin_access():
            response = self.client.post(
                self.url,
                {
                    "action": "edit",
                    "id": str(category.id),
                    "label": "Quality Ops",
                    "icon": "QO",
                    "topbar_color": "#334455",
                    "order": "9",
                },
            )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        category.refresh_from_db()
        self.assertEqual(category.label, "Quality Ops")
        self.assertEqual(category.icon, "QO")
        self.assertEqual(category.topbar_color, "#334455")
        self.assertEqual(category.order, 9)


class HubDatabaseRestoreSecurityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            username="hub-restore-admin",
            email="hub.restore@test.local",
            password="test-pass-123",
        )
        cls.legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("hub_tools:hub_db_restore")

    def _admin_access(self):
        stack = ExitStack()
        stack.enter_context(
            patch("admin_portale.decorators.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("admin_portale.decorators.is_legacy_admin", return_value=True)
        )
        return stack

    def test_restore_rejects_path_traversal_backup_name(self):
        with (
            self._admin_access(),
            patch("hub_tools.views._get_db_engine", return_value="sqlite"),
        ):
            response = self.client.post(
                self.url,
                data=json.dumps({"backup_name": "../../django_app/config/settings/prod.py"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {"ok": False, "error": "Nome backup non valido"})


class HubApiErrorLeakHardeningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            username="hub-errors-admin",
            email="hub.errors@test.local",
            password="test-pass-123",
        )
        cls.legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def setUp(self):
        self.client.force_login(self.user)

    def _admin_access(self):
        stack = ExitStack()
        stack.enter_context(
            patch("admin_portale.decorators.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("admin_portale.decorators.is_legacy_admin", return_value=True)
        )
        return stack

    def test_toggle_module_returns_generic_error_when_internal_exception_occurs(self):
        with (
            self._admin_access(),
            patch("hub_tools.views._set_module_state", side_effect=RuntimeError("sqlserver01 login failed")),
        ):
            response = self.client.post(
                reverse("hub_tools:hub_moduli_toggle"),
                data=json.dumps({"key": "tickets", "enabled": True}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Operazione fallita. Controlla i log.")

    def test_notifica_invia_hides_raw_backend_exception(self):
        with (
            self._admin_access(),
            patch("core.legacy_anagrafica.fetch_anagrafica_rows", side_effect=RuntimeError("ODBC Driver 18 sqlserver01")),
        ):
            response = self.client.post(
                reverse("hub_tools:hub_notifica_invia"),
                data=json.dumps(
                    {
                        "destinatario": "reparto",
                        "reparto": "IT",
                        "tipo": "generico",
                        "messaggio": "Test hardening",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "Operazione fallita. Controlla i log.")


class HubGuideCatalogTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            username="hub-guides-admin",
            email="hub.guides@test.local",
            password="test-pass-123",
        )
        cls.legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def setUp(self):
        self.client.force_login(self.user)
        temp_root = Path(__file__).resolve().parents[2] / ".tmp_tests"
        temp_root.mkdir(parents=True, exist_ok=True)
        base = temp_root / f"hub-guides-{uuid4().hex}"
        base.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(base, ignore_errors=True))
        self.tools_dir = base / "tools"
        self.doc_dir = base / "doc"
        self.deployment_dir = base / "deployment"
        self.assets_dir = base / "assets"
        for directory in (self.tools_dir, self.doc_dir, self.deployment_dir, self.assets_dir):
            directory.mkdir(parents=True, exist_ok=True)

        (self.tools_dir / "GUIDA_ALPHA.html").write_text("<html><body>Alpha HTML</body></html>", encoding="utf-8")
        (self.doc_dir / "GUIDA_ALPHA.md").write_text("# Alpha MD\nfallback", encoding="utf-8")
        (self.doc_dir / "GUIDA_BETA.md").write_text("# Beta Guide\ncontenuto markdown", encoding="utf-8")
        (self.deployment_dir / "MANUALE_RELEASE.pdf").write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
        (self.assets_dir / "README.md").write_text("# Assets\nnote modulo", encoding="utf-8")

    def _admin_access(self):
        stack = ExitStack()
        stack.enter_context(
            patch("admin_portale.decorators.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("admin_portale.decorators.is_legacy_admin", return_value=True)
        )
        stack.enter_context(
            patch("core.context_processors.get_legacy_user", return_value=self.legacy_admin)
        )
        stack.enter_context(
            patch("core.context_processors.is_legacy_admin", return_value=True)
        )
        stack.enter_context(
            patch(
                "hub_tools.views._GUIDE_DISCOVERY_RULES",
                (
                    ("tools", self.tools_dir, "*"),
                    ("doc", self.doc_dir, "*"),
                    ("deployment", self.deployment_dir, "*"),
                    ("assets", self.assets_dir, "README.md"),
                ),
            )
        )
        stack.enter_context(patch("hub_tools.views._GUIDE_METADATA", {}))
        return stack

    def test_guide_list_discovers_all_sources_and_deduplicates_by_best_format(self):
        with self._admin_access():
            response = self.client.get(reverse("hub_tools:hub_guide_list"))

        self.assertEqual(response.status_code, 200)
        guides = response.context["guides"]
        self.assertEqual(response.context["guide_count"], 4)
        relative_paths = {guide["relative_path"] for guide in guides}
        self.assertTrue(any(path.endswith("tools/GUIDA_ALPHA.html") for path in relative_paths))
        self.assertFalse(any(path.endswith("doc/GUIDA_ALPHA.md") for path in relative_paths))
        self.assertTrue(any(path.endswith("doc/GUIDA_BETA.md") for path in relative_paths))
        self.assertTrue(any(path.endswith("deployment/MANUALE_RELEASE.pdf") for path in relative_paths))
        self.assertTrue(any(path.endswith("assets/README.md") for path in relative_paths))

    def test_guide_serve_renders_markdown_and_pdf_from_catalog(self):
        with self._admin_access():
            response = self.client.get(reverse("hub_tools:hub_guide_list"))
            guides = response.context["guides"]

        beta_guide = next(guide for guide in guides if guide["relative_path"].endswith("doc/GUIDA_BETA.md"))
        pdf_guide = next(
            guide for guide in guides if guide["relative_path"].endswith("deployment/MANUALE_RELEASE.pdf")
        )

        with self._admin_access():
            markdown_response = self.client.get(
                reverse("hub_tools:hub_guide_serve", args=[beta_guide["slug"]])
            )
        self.assertEqual(markdown_response.status_code, 200)
        self.assertEqual(markdown_response["Content-Type"], "text/html; charset=utf-8")
        self.assertContains(markdown_response, "Beta Guide")
        self.assertContains(markdown_response, "doc/GUIDA_BETA.md")

        with self._admin_access():
            pdf_response = self.client.get(
                reverse("hub_tools:hub_guide_serve", args=[pdf_guide["slug"]])
            )
        self.assertEqual(pdf_response.status_code, 200)
        self.assertEqual(pdf_response["Content-Type"], "application/pdf")
