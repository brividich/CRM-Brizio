"""Import cedolini da SharePoint: link di condivisione, task mensile, pulsante."""
from __future__ import annotations

import io
from datetime import date, datetime
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import SiteConfig

from .models import ImportazioneCedolini, SaldoCedolino
from .services import cedolini_sharepoint as sp

SHARE_URL = "https://contoso.sharepoint.com/:x:/g/ABCdef123?e=xyz"


def _xlsx_cedolini(cf: str = "RSSMRA80A01H501U", mese: int = 9, anno: int = 2026) -> bytes:
    import calendar

    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Dati"
    ws.append([f"H{i}" for i in range(32)])
    riga = [None] * 32
    riga[0] = cf
    riga[3] = "settembre"
    riga[4] = anno
    riga[5] = datetime(anno, mese, calendar.monthrange(anno, mese)[1])
    riga[19] = 42.5  # FERIE - Residui
    ws.append(riga)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _response(status: int = 200, json_data: dict | None = None, content: bytes = b""):
    resp = mock.Mock()
    resp.ok = 200 <= status < 300
    resp.status_code = status
    resp.json.return_value = json_data or {}
    resp.content = content
    return resp


class ShareIdTests(TestCase):
    def test_encode_share_id_base64url_senza_padding(self):
        share_id = sp.encode_share_id("https://onedrive.live.com/redir?resid=1231244193912!12&authKey=1201919!12921!1")
        self.assertTrue(share_id.startswith("u!"))
        self.assertNotIn("=", share_id)
        self.assertNotIn("/", share_id)
        self.assertNotIn("+", share_id)

    def test_candidati_senza_query(self):
        self.assertEqual(
            sp._candidati(SHARE_URL),
            [SHARE_URL, "https://contoso.sharepoint.com/:x:/g/ABCdef123"],
        )


@mock.patch("anagrafica.services.cedolini_sharepoint._graph_headers", return_value={"Authorization": "Bearer t"})
class ImportaDaSharepointTests(TestCase):
    def test_import_crea_saldi_e_storico(self, _headers):
        risposte = [
            _response(json_data={"name": "Cedolini.xlsx"}),
            _response(content=_xlsx_cedolini()),
        ]
        with mock.patch("requests.get", side_effect=risposte) as get:
            imp = sp.importa_da_sharepoint(user=None, url=SHARE_URL)

        self.assertIn("/shares/u!", get.call_args_list[0].args[0])
        self.assertTrue(get.call_args_list[1].args[0].endswith("/driveItem/content"))
        self.assertEqual(imp.data_competenza, date(2026, 9, 30))
        self.assertEqual(imp.file_nome, "SharePoint · Cedolini.xlsx")
        self.assertIsNone(imp.importato_da)
        saldo = SaldoCedolino.objects.get(tax_code="RSSMRA80A01H501U")
        self.assertEqual(float(saldo.ferie_residui), 42.5)

    def test_ritenta_senza_query_string(self, _headers):
        risposte = [
            _response(status=400),
            _response(json_data={"name": "Cedolini.xlsx"}),
            _response(content=_xlsx_cedolini()),
        ]
        with mock.patch("requests.get", side_effect=risposte):
            imp = sp.importa_da_sharepoint(url=SHARE_URL)
        self.assertEqual(imp.righe_ok, 1)

    def test_link_non_accessibile_solleva_errore_leggibile(self, _headers):
        with mock.patch("requests.get", return_value=_response(status=403)):
            with self.assertRaisesMessage(ValueError, "non è accessibile"):
                sp.importa_da_sharepoint(url=SHARE_URL)
        self.assertFalse(ImportazioneCedolini.objects.exists())

    def test_link_vuoto(self, _headers):
        with self.assertRaisesMessage(ValueError, "non configurato"):
            sp.importa_da_sharepoint(url="")


class TaskImportCedoliniTests(TestCase):
    def test_noop_senza_link(self):
        from anagrafica.tasks import run_import_cedolini_sharepoint

        with mock.patch("anagrafica.services.cedolini_sharepoint.importa_da_sharepoint") as imp:
            esito = run_import_cedolini_sharepoint()
        imp.assert_not_called()
        self.assertTrue(esito["ok"])
        self.assertIn("skipped", esito)

    def test_errore_non_solleva(self):
        from anagrafica.tasks import run_import_cedolini_sharepoint

        sp.set_share_url(SHARE_URL)
        with mock.patch(
            "anagrafica.services.cedolini_sharepoint.importa_da_sharepoint",
            side_effect=ValueError("Graph giù"),
        ):
            esito = run_import_cedolini_sharepoint()
        self.assertEqual(esito, {"ok": False, "errore": "Graph giù"})

    def test_schedule_primo_del_mese_mezzanotte(self):
        from automazioni.schedules import spec_by_name

        spec = spec_by_name("import_cedolini_sharepoint")
        self.assertEqual(spec["func"], "anagrafica.tasks.run_import_cedolini_sharepoint")
        self.assertEqual(spec["schedule_type"], "C")
        self.assertEqual(spec["cron"], "0 0 1 * *")


@mock.patch("anagrafica.views._is_anagrafica_admin", return_value=True)
class CedoliniImportViewSharepointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("hr_admin", "hr@example.test", "x")
        self.client.force_login(self.user)
        self.url = reverse("anagrafica:cedolini_import")

    def test_salva_link(self, _admin):
        resp = self.client.post(self.url, {"azione": "sharepoint_link", "sharepoint_url": SHARE_URL})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SiteConfig.get(sp.CONFIG_KEY), SHARE_URL)

    def test_rifiuta_link_non_https(self, _admin):
        self.client.post(self.url, {"azione": "sharepoint_link", "sharepoint_url": "http://x/y"})
        self.assertEqual(SiteConfig.get(sp.CONFIG_KEY, ""), "")

    def test_pulsante_importa_usa_utente_corrente(self, _admin):
        sp.set_share_url(SHARE_URL)
        with mock.patch("anagrafica.services.cedolini_sharepoint.importa_da_sharepoint") as imp:
            imp.return_value = mock.Mock(
                data_competenza=date(2026, 9, 30), righe_ok=3, righe_errore=0, righe_non_trovate=0,
            )
            resp = self.client.post(self.url, {"azione": "sharepoint_import"})
        self.assertEqual(resp.status_code, 302)
        imp.assert_called_once_with(user=self.user)
