from __future__ import annotations

from django.test import TestCase

from core.hub_bacheca import link_visible_to_role, visible_bacheca
from core.models import HubLink, HubLinkCategory, HubLinkRoleAccess


def _url_link(cat, title, order=100, visible=True):
    return HubLink.objects.create(category=cat, kind=HubLink.KIND_URL, title=title,
                                  url="https://esempio.local", order=order, is_visible=visible)


class HubBachecaServiceTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Collegamenti", slug="coll", order=10)

    def test_no_access_rows_visible_to_all(self):
        link = _url_link(self.cat, "Aperto")
        self.assertTrue(link_visible_to_role(link, legacy_role_id=None, is_admin=False))
        self.assertTrue(link_visible_to_role(link, legacy_role_id=7, is_admin=False))

    def test_access_rows_restrict(self):
        link = _url_link(self.cat, "Riservato")
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=5, can_view=True)
        self.assertTrue(link_visible_to_role(link, legacy_role_id=5, is_admin=False))
        self.assertFalse(link_visible_to_role(link, legacy_role_id=9, is_admin=False))
        self.assertFalse(link_visible_to_role(link, legacy_role_id=None, is_admin=False))

    def test_admin_bypasses_role_but_not_hidden(self):
        link = _url_link(self.cat, "Riservato")
        HubLinkRoleAccess.objects.create(link=link, legacy_role_id=5, can_view=True)
        self.assertTrue(link_visible_to_role(link, legacy_role_id=None, is_admin=True))
        hidden = _url_link(self.cat, "Nascosto", visible=False)
        self.assertFalse(link_visible_to_role(hidden, legacy_role_id=None, is_admin=True))

    def test_visible_bacheca_hidden_category_excluded(self):
        cat2 = HubLinkCategory.objects.create(name="Nascosta", slug="nasc", is_visible=False)
        _url_link(cat2, "X")
        _url_link(self.cat, "Y")
        groups = visible_bacheca(legacy_role_id=None, is_admin=False)
        slugs = [g["category"].slug for g in groups]
        self.assertIn("coll", slugs)
        self.assertNotIn("nasc", slugs)

    def test_visible_bacheca_empty_category_excluded(self):
        # setUp crea la categoria "coll" senza voci; ne aggiungiamo un'altra vuota.
        HubLinkCategory.objects.create(name="Vuota", slug="vuota")
        groups = visible_bacheca(legacy_role_id=None, is_admin=False)
        self.assertEqual(groups, [])  # nessuna voce in nessuna categoria -> nessun gruppo

    def test_preview_limit_and_more(self):
        for i in range(6):
            _url_link(self.cat, f"L{i}", order=i)
        groups = visible_bacheca(legacy_role_id=None, is_admin=False, preview_limit=4)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]["items"]), 4)
        self.assertEqual(groups[0]["total"], 6)
        self.assertEqual(groups[0]["more"], 2)
