import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from config.env_config import load_env_file_values, update_env_file_values
from core.models import ModuleCategory, NavigationItem, SiteConfig
from hub_tools.views import _sanitize_guide_icon


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
            "brand_favicon": "/media/favicon.ico",
            "brand_landing_image": "/media/landing.png",
            "brand_landing_fit_mode": "contain",
            "brand_logo_full_height": "48",
            "brand_logo_full_max_width": "220",
            "brand_logo_compact_size": "40",
            "brand_sidebar_logo_scale": "170",
            "brand_login_form_x": "72",
            "brand_login_form_y": "46",
            "brand_primary_color": "#112233",
            "brand_accent_color": "#ffaa00",
            "brand_background_color": "#f7f8fb",
        }
        with self._admin_access():
            response = self.client.post(self.url, payload)

        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.assertEqual(SiteConfig.get("portal_name"), "Portal QA")
        self.assertEqual(SiteConfig.get("portal_subtitle"), "Area test")
        self.assertEqual(SiteConfig.get("brand_logo_full"), "/media/brand-full.svg")
        self.assertEqual(SiteConfig.get("brand_logo_compact"), "/media/brand-compact.svg")
        self.assertEqual(SiteConfig.get("brand_favicon"), "/media/favicon.ico")
        self.assertEqual(SiteConfig.get("brand_landing_image"), "/media/landing.png")
        self.assertEqual(SiteConfig.get("brand_landing_fit_mode"), "contain")
        self.assertEqual(SiteConfig.get("brand_logo_full_height"), "48")
        self.assertEqual(SiteConfig.get("brand_logo_full_max_width"), "220")
        self.assertEqual(SiteConfig.get("brand_logo_compact_size"), "40")
        self.assertEqual(SiteConfig.get("brand_sidebar_logo_scale"), "170")
        self.assertEqual(SiteConfig.get("brand_login_form_x"), "72")
        self.assertEqual(SiteConfig.get("brand_login_form_y"), "46")
        self.assertEqual(SiteConfig.get("brand_primary_color"), "#112233")
        self.assertEqual(SiteConfig.get("brand_accent_color"), "#ffaa00")
        self.assertEqual(SiteConfig.get("brand_background_color"), "#f7f8fb")

    def test_categorie_branding_uploads_logo_files(self):
        media_root = Path(__file__).resolve().parents[1] / ".tmp_tests" / f"hub-branding-{uuid4().hex}"
        try:
            with (
                override_settings(MEDIA_ROOT=media_root, MEDIA_URL="/media/"),
                self._admin_access(),
                patch("hub_tools.views.validate_extension_and_mime", return_value="image/png"),
            ):
                response = self.client.post(
                    self.url,
                    {
                        "action": "branding",
                        "portal_name": "Portal Upload",
                        "portal_subtitle": "",
                        "brand_primary_color": "#1e3a5f",
                        "brand_accent_color": "#f97316",
                        "brand_background_color": "#eef0f5",
                        "brand_landing_fit_mode": "stretch",
                        "brand_logo_full_height": "40",
                        "brand_logo_full_max_width": "140",
                        "brand_logo_compact_size": "32",
                        "brand_sidebar_logo_scale": "135",
                        "brand_login_form_x": "80",
                        "brand_login_form_y": "52",
                        "brand_logo_full_file": SimpleUploadedFile(
                            "logo.png",
                            b"\x89PNG\r\n\x1a\n",
                            content_type="image/png",
                        ),
                        "brand_logo_compact_file": SimpleUploadedFile(
                            "logo-compact.png",
                            b"\x89PNG\r\n\x1a\n",
                            content_type="image/png",
                        ),
                        "brand_landing_image_file": SimpleUploadedFile(
                            "landing.png",
                            b"\x89PNG\r\n\x1a\n",
                            content_type="image/png",
                        ),
                    },
                )

            self.assertRedirects(response, self.url, fetch_redirect_response=False)
            self.assertEqual(SiteConfig.get("brand_logo_full"), "/media/portal_branding/logo_full.png")
            self.assertEqual(SiteConfig.get("brand_logo_compact"), "/media/portal_branding/logo_compact.png")
            self.assertEqual(SiteConfig.get("brand_landing_image"), "/media/portal_branding/landing.png")
            self.assertEqual(SiteConfig.get("brand_landing_fit_mode"), "stretch")
            self.assertEqual(SiteConfig.get("brand_sidebar_logo_scale"), "135")
            self.assertEqual(SiteConfig.get("brand_login_form_x"), "80")
            self.assertEqual(SiteConfig.get("brand_login_form_y"), "52")
            self.assertTrue((media_root / "portal_branding" / "logo_full.png").exists())
            self.assertTrue((media_root / "portal_branding" / "logo_compact.png").exists())
            self.assertTrue((media_root / "portal_branding" / "landing.png").exists())
        finally:
            shutil.rmtree(media_root, ignore_errors=True)

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


class HubSetupWizardEnvTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_superuser(
            username="hub-setup-admin",
            email="hub.setup@test.local",
            password="test-pass-123",
        )
        cls.legacy_admin = SimpleNamespace(id=1, ruolo="admin", ruolo_id=1)

    def setUp(self):
        self.client.force_login(self.user)
        self.temp_root = Path(__file__).resolve().parents[1] / ".tmp_tests" / f"hub-setup-env-{uuid4().hex}"
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.env_path = self.temp_root / ".env"
        self.addCleanup(lambda: shutil.rmtree(self.temp_root, ignore_errors=True))

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

    def _update_env_without_process(self, updates, dotenv_path=None, *, delete_keys=None):
        return update_env_file_values(
            updates,
            dotenv_path=dotenv_path,
            delete_keys=delete_keys,
            apply_to_process=False,
        )

    def test_setup_wizard_renders_true_false_env_booleans_correctly(self):
        self.env_path.write_text(
            "\n".join(
                [
                    "DB_TRUST_CERT=True",
                    "LDAP_ENABLED=yes",
                    "SESSION_EXPIRE_AT_BROWSER_CLOSE=True",
                    "EMAIL_USE_TLS=False",
                ]
            ),
            encoding="utf-8",
        )

        with (
            self._admin_access(),
            patch("hub_tools.views._ENV_PATH", self.env_path),
        ):
            response = self.client.get(reverse("hub_tools:hub_setup_wizard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["env"]["DB_TRUST_CERT"], "1")
        self.assertEqual(response.context["env"]["LDAP_ENABLED"], "1")
        self.assertEqual(response.context["env"]["EMAIL_USE_TLS"], "0")
        self.assertContains(response, 'id="f_db_trust_cert" checked')
        self.assertContains(response, 'id="f_ldap_enabled" checked')

    def test_reconfigure_preserves_db_trust_cert_when_field_is_missing(self):
        self.env_path.write_text(
            "\n".join(
                [
                    "INSTANCE_NAME=NOVICROM HUB",
                    "APP_VERSION=1.0.0",
                    "DJANGO_SECRET_KEY=test-secret",
                    "DB_ENGINE=sqlserver",
                    "DB_HOST=sql.test.local",
                    "DB_NAME=PortaleTest",
                    "DB_DRIVER=ODBC Driver 18 for SQL Server",
                    "DB_TRUST_CERT=True",
                    "LDAP_ENABLED=False",
                ]
            ),
            encoding="utf-8",
        )

        with (
            self._admin_access(),
            patch("hub_tools.views._ENV_PATH", self.env_path),
            patch("hub_tools.views.update_env_file_values", side_effect=self._update_env_without_process),
        ):
            response = self.client.post(
                reverse("hub_tools:hub_api_reconfigure"),
                data=json.dumps(
                    {
                        "ldap_enabled": True,
                        "ldap_server": "ldap://dc.test.local",
                        "ldap_domain": "TEST",
                    }
                ),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        updated = load_env_file_values(self.env_path)
        self.assertEqual(updated["DB_TRUST_CERT"], "1")
        self.assertEqual(updated["LDAP_ENABLED"], "1")

    def test_reconfigure_does_not_force_navigation_legacy_fallback(self):
        self.env_path.write_text(
            "\n".join(
                [
                    "INSTANCE_NAME=NOVICROM HUB",
                    "APP_VERSION=1.0.0",
                    "DJANGO_SECRET_KEY=test-secret",
                    "NAVIGATION_REGISTRY_ENABLED=1",
                    "NAVIGATION_LEGACY_FALLBACK_ENABLED=0",
                    "LDAP_ENABLED=1",
                    "LDAP_SERVER=ldap://dc.test.local",
                ]
            ),
            encoding="utf-8",
        )

        with (
            self._admin_access(),
            patch("hub_tools.views._ENV_PATH", self.env_path),
            patch("hub_tools.views.update_env_file_values", side_effect=self._update_env_without_process),
        ):
            response = self.client.post(
                reverse("hub_tools:hub_api_reconfigure"),
                data=json.dumps({"nav_registry": True}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        updated = load_env_file_values(self.env_path)
        self.assertEqual(updated["NAVIGATION_REGISTRY_ENABLED"], "1")
        self.assertEqual(updated["NAVIGATION_LEGACY_FALLBACK_ENABLED"], "0")
        self.assertEqual(updated["LDAP_ENABLED"], "1")
        self.assertEqual(updated["LDAP_SERVER"], "ldap://dc.test.local")

    def test_reconfigure_enables_legacy_fallback_only_when_registry_disabled(self):
        self.env_path.write_text(
            "\n".join(
                [
                    "DJANGO_SECRET_KEY=test-secret",
                    "NAVIGATION_REGISTRY_ENABLED=1",
                    "NAVIGATION_LEGACY_FALLBACK_ENABLED=0",
                ]
            ),
            encoding="utf-8",
        )

        with (
            self._admin_access(),
            patch("hub_tools.views._ENV_PATH", self.env_path),
            patch("hub_tools.views.update_env_file_values", side_effect=self._update_env_without_process),
        ):
            response = self.client.post(
                reverse("hub_tools:hub_api_reconfigure"),
                data=json.dumps({"nav_registry": False}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        updated = load_env_file_values(self.env_path)
        self.assertEqual(updated["NAVIGATION_REGISTRY_ENABLED"], "0")
        self.assertEqual(updated["NAVIGATION_LEGACY_FALLBACK_ENABLED"], "1")


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

    def test_sanitize_guide_icon_blanks_mojibake_sequences(self):
        self.assertEqual(_sanitize_guide_icon("\u00f0broken"), "")
        self.assertEqual(_sanitize_guide_icon("\u00e2broken"), "")
        self.assertEqual(_sanitize_guide_icon(""), "")
        self.assertEqual(_sanitize_guide_icon("DOC"), "DOC")

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
