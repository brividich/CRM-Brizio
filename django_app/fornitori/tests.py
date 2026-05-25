from django.test import SimpleTestCase

from .acl_bootstrap import _PULSANTI_DEFINITIONS


class FornitoriAclBootstrapTests(SimpleTestCase):
    def test_bootstrap_exposes_assignable_fornitori_actions(self):
        by_code = {item["codice"]: item for item in _PULSANTI_DEFINITIONS}

        self.assertEqual(by_code["fornitori_index"]["modulo"], "fornitori")
        self.assertTrue(by_code["fornitori_index"]["visible_topbar"])
        self.assertFalse(by_code["fornitore_documento_delete"]["visible_topbar"])
        self.assertIn("fornitore_asset_remove", by_code)
        self.assertEqual(
            by_code["fornitore_asset_remove"]["url"],
            "route:fornitori:fornitore_asset_remove",
        )
