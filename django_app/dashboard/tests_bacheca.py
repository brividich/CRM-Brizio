from __future__ import annotations

from types import SimpleNamespace

from django.test import TestCase

from core.models import HubLink, HubLinkCategory
from dashboard import views_home_portale as hp


class DocumentiCollegamentiHelperTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica", order=1)
        HubLink.objects.create(category=self.cat, kind=HubLink.KIND_URL,
                               title="Gestionale", url="https://esempio.local")

    def _admin_request(self):
        # is_superuser=True ⇒ is_admin True ⇒ nessuna dipendenza da tabelle legacy
        return SimpleNamespace(
            user=SimpleNamespace(is_superuser=True, get_username=lambda: "admin",
                                 first_name="", email=""),
            legacy_user=SimpleNamespace(id=1, ruolo="AMMINISTRAZIONE", ruolo_id=1, nome="Admin"),
        )

    def test_documenti_collegamenti_shape(self):
        groups = hp._documenti_collegamenti(self._admin_request())
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertEqual(g["name"], "Modulistica")
        self.assertEqual(g["items"][0]["title"], "Gestionale")
        self.assertEqual(g["items"][0]["kind_label"], "Link")
        self.assertEqual(g["items"][0]["href"], "https://esempio.local")
        self.assertTrue(g["items"][0]["open_in_new_tab"])
