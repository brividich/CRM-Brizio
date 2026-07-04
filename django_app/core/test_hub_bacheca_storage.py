from __future__ import annotations

import os
import tempfile

from django.test import TestCase, override_settings

from core.hub_bacheca_storage import HubLinkStorage


class HubLinkStorageTests(TestCase):
    def test_url_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            HubLinkStorage().url("hub_links/2026/07/x.pdf")

    def test_location_points_to_private_root(self):
        tmp = tempfile.mkdtemp()
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=tmp):
            self.assertEqual(HubLinkStorage().location, os.path.abspath(tmp))
