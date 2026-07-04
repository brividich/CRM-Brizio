from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import HubLink, HubLinkCategory


class HubLinkModelTests(TestCase):
    def setUp(self):
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica")

    def test_clean_url_requires_url(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_URL, title="Gestionale", url="")
        with self.assertRaises(ValidationError):
            link.clean()

    def test_clean_internal_requires_route_name(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_INTERNAL, title="Ferie", route_name="")
        with self.assertRaises(ValidationError):
            link.clean()

    def test_clean_url_ok(self):
        link = HubLink(category=self.cat, kind=HubLink.KIND_URL, title="Gestionale",
                       url="https://esempio.local")
        link.clean()  # non solleva

    def test_resolve_href_url(self):
        link = HubLink.objects.create(category=self.cat, kind=HubLink.KIND_URL,
                                      title="Gestionale", url="https://esempio.local")
        self.assertEqual(link.resolve_href(), "https://esempio.local")

    def test_resolve_href_internal_unknown_route_is_hash(self):
        link = HubLink.objects.create(category=self.cat, kind=HubLink.KIND_INTERNAL,
                                      title="X", route_name="rotta_inesistente_xyz")
        self.assertEqual(link.resolve_href(), "#")
