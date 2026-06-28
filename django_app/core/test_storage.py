"""Test della ForgivingManifestStaticFilesStorage (tolleranza sourcemap .map)."""
from __future__ import annotations

import unittest.mock as mock

from django.contrib.staticfiles.storage import HashedFilesMixin
from django.test import SimpleTestCase

from core.storage import ForgivingManifestStaticFilesStorage


class ForgivingStorageTests(SimpleTestCase):
    def _converter(self, raising_exc):
        storage = ForgivingManifestStaticFilesStorage()

        def raising(_matchobj):
            raise raising_exc

        with mock.patch.object(HashedFilesMixin, "url_converter", return_value=raising):
            return storage.url_converter("name", {})

    def test_missing_sourcemap_is_tolerated(self):
        conv = self._converter(ValueError("The file 'chart.umd.js.map' could not be found"))
        m = mock.Mock()
        m.group.return_value = "//# sourceMappingURL=chart.umd.js.map"
        self.assertEqual(conv(m), "//# sourceMappingURL=chart.umd.js.map")

    def test_other_missing_asset_still_raises(self):
        conv = self._converter(ValueError("The file 'logo.png' could not be found"))
        with self.assertRaises(ValueError):
            conv(mock.Mock())
