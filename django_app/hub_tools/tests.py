from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

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
