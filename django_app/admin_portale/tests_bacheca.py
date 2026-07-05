from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess


class AdminBachecaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="admin", password="x", email="a@a.it")
        self.user = User.objects.create_user(username="mario", password="x")

    def test_non_admin_cannot_create_category(self):
        # Invariante di sicurezza: il non-admin viene negato (403 dal decoratore o
        # redirect dal middleware) e NON crea nulla.
        self.client.force_login(self.user)
        r = self.client.post(reverse("admin_portale:api_hub_category_create"),
                             data=json.dumps({"name": "Hackerman"}), content_type="application/json")
        self.assertNotEqual(r.status_code, 200)
        self.assertFalse(HubLinkCategory.objects.filter(name="Hackerman").exists())

    def test_admin_creates_category(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:api_hub_category_create"),
                             data=json.dumps({"name": "Modulistica"}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(HubLinkCategory.objects.filter(name="Modulistica").exists())

    def test_admin_creates_url_link_with_roles(self):
        cat = HubLinkCategory.objects.create(name="Coll", slug="coll")
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:api_hub_link_create"),
                             data=json.dumps({"category_id": cat.id, "kind": "url", "title": "Gestionale",
                                              "url": "https://esempio.local", "role_ids": [5, 7]}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        link = HubLink.objects.get(title="Gestionale")
        self.assertEqual(
            set(HubLinkRoleAccess.objects.filter(link=link).values_list("legacy_role_id", flat=True)),
            {5, 7},
        )

    def test_admin_creates_internal_link(self):
        cat = HubLinkCategory.objects.create(name="Mod", slug="mod")
        self.client.force_login(self.admin)
        r = self.client.post(reverse("admin_portale:api_hub_link_create"),
                             data=json.dumps({"category_id": cat.id, "kind": "internal",
                                              "title": "Richiesta ferie", "route_name": "mie_attivita"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(HubLink.objects.filter(title="Richiesta ferie", kind="internal").exists())
