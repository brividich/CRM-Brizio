"""Destinazione dell'audit sigillato dal link di una cartella SharePoint (Graph simulato)."""
from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import TestCase

from core import sharepoint_upload as sp
from core.models import SiteConfig

LINK = "https://contoso.sharepoint.com/sites/Qualita/Documenti%20condivisi/Audit/Portale"


def _risposta(status, data=None):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = data or {}
    return r


CARTELLA = {
    "name": "Portale",
    "folder": {"childCount": 0},
    "webUrl": LINK,
    "parentReference": {"driveId": "b!drive-sintetico", "path": "/drives/b!drive-sintetico/root:/Audit"},
}


@patch.object(sp, "_token", return_value="tok")
class LinkSharePointTests(TestCase):
    def test_link_della_barra_indirizzi_diventa_diretto(self, _t):
        link = ("https://contoso.sharepoint.com/sites/Qualita/Documenti%20condivisi/Forms/AllItems.aspx"
                "?id=%2Fsites%2FQualita%2FDocumenti%20condivisi%2FAudit&viewid=abc")
        self.assertEqual(sp._link_diretto(link),
                         "https://contoso.sharepoint.com/sites/Qualita/Documenti condivisi/Audit")

    def test_risolve_raccolta_e_cartella(self, _t):
        with patch("requests.get", return_value=_risposta(200, CARTELLA)) as get:
            drive, cartella, url = sp.risolvi_link(LINK)
        self.assertEqual((drive, cartella), ("b!drive-sintetico", "Audit/Portale"))
        self.assertIn("/shares/u!", get.call_args.args[0])

    def test_link_non_sharepoint_rifiutato(self, _t):
        with self.assertRaises(sp.SharePointUploadError):
            sp.risolvi_link("https://esempio.it/cartella")

    def test_file_o_raccolta_intera_rifiutati(self, _t):
        with patch("requests.get", return_value=_risposta(200, {"name": "x.pdf", "file": {}})):
            with self.assertRaisesMessage(sp.SharePointUploadError, "non porta a una cartella"):
                sp.risolvi_link(LINK)
        with patch("requests.get", return_value=_risposta(200, {"name": "root", "folder": {}, "root": {}})):
            with self.assertRaisesMessage(sp.SharePointUploadError, "raccolta intera"):
                sp.risolvi_link(LINK)

    def test_configura_scrive_leggimi_poi_salva(self, _t):
        with patch("requests.get", return_value=_risposta(200, CARTELLA)), \
             patch.object(sp, "carica", return_value="https://x") as carica:
            esito = sp.configura_da_link(LINK)
        self.assertEqual(carica.call_args.args[0], sp.LEGGIMI)
        self.assertEqual(esito["leggimi"], "creato")
        self.assertEqual(sp.destinazione(), ("b!drive-sintetico", "Audit/Portale"))

    def test_leggimi_gia_presente_va_bene(self, _t):
        with patch("requests.get", return_value=_risposta(200, CARTELLA)), \
             patch.object(sp, "carica", side_effect=sp.SharePointUploadError("Il file esiste già nella cartella")):
            self.assertEqual(sp.configura_da_link(LINK)["leggimi"], "già presente")

    def test_senza_permesso_di_scrittura_non_salva(self, _t):
        with patch("requests.get", return_value=_risposta(200, CARTELLA)), \
             patch.object(sp, "carica", side_effect=sp.SharePointUploadError("SharePoint ha risposto 403")):
            with self.assertRaises(sp.SharePointUploadError):
                sp.configura_da_link(LINK)
        self.assertEqual(SiteConfig.get("audit_export_sp_drive_id", ""), "")

    def test_comando(self, _t):
        out = StringIO()
        with patch("requests.get", return_value=_risposta(200, CARTELLA)), \
             patch.object(sp, "carica", return_value="https://x"):
            call_command("audit_sigilli", "--cartella-sharepoint", LINK, stdout=out)
        self.assertIn("Cartella impostata: Audit/Portale", out.getvalue())
        with patch("requests.get", return_value=_risposta(404)):
            with self.assertRaises(CommandError):
                call_command("audit_sigilli", "--cartella-sharepoint", LINK, stdout=StringIO())
