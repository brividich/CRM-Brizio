from __future__ import annotations

from django.contrib.admin.sites import site

from django.test import TestCase

from suggestion_corner.models import (
    SuggestionCorner, SuggestionCornerConfig, SuggestionCornerProcessoMapping,
)


class SuggestionCornerAdminTest(TestCase):
    def test_modelli_registrati(self):
        self.assertIn(SuggestionCorner, site._registry)
        self.assertIn(SuggestionCornerConfig, site._registry)
        self.assertIn(SuggestionCornerProcessoMapping, site._registry)

    def test_stato_readonly(self):
        admin_obj = site._registry[SuggestionCorner]
        self.assertIn("stato", admin_obj.get_readonly_fields(request=None))
