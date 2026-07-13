"""Test dell'endpoint unico di export delle liste di anagrafica (PDF/Excel)."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import Mansione
from core.models import AuditLog

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExportEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser("admin_export", "admin@example.invalid", "x")
        cls.plain = User.objects.create_user("utente_export", "u@example.invalid", "x")
        # NB: LIVELLO_RISCHIO_CHOICES reali = B/M/A (non ALTO/BASSO come nel brief).
        Mansione.objects.create(
            nome="Addetto verniciatura",
            livello_rischio=Mansione.RISCHIO_ALTO,
            categoria=Mansione.CAT_OPERAIO,
            descrizione="Cabina di verniciatura",
        )
        Mansione.objects.create(
            nome="Impiegato ufficio",
            livello_rischio=Mansione.RISCHIO_BASSO,
            categoria=Mansione.CAT_IMPIEGATO,
        )

    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def test_xlsx_export_returns_spreadsheet(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        self.assertIn("mansioni", resp["Content-Disposition"])

    def test_pdf_export_returns_pdf(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="pdf"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_filtered_scope_respects_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            self._url("mansioni", format="xlsx", scope="filtered", q="verniciatura")
        )
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 1)
        self.assertEqual(log.dettaglio.get("scope"), "filtered")
        self.assertIn("verniciatura", log.dettaglio.get("filtri", ""))

    def test_filtered_scope_respects_rischio(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("mansioni", format="xlsx", rischio="A"))
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 1)

    def test_full_scope_ignores_querystring(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            self._url("mansioni", format="xlsx", scope="full", q="verniciatura")
        )
        self.assertEqual(resp.status_code, 200)
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), 2)
        self.assertEqual(log.dettaglio.get("scope"), "full")

    def test_audit_row_written(self):
        self.client.force_login(self.admin)
        self.client.get(self._url("mansioni", format="pdf"))
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.modulo, "anagrafica")
        self.assertEqual(log.dettaglio.get("lista"), "mansioni")
        self.assertEqual(log.dettaglio.get("formato"), "pdf")

    def test_unknown_key_is_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url("non-esiste", format="xlsx"))
        self.assertEqual(resp.status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        resp = self.client.get(self._url("mansioni", format="xlsx"))
        self.assertIn(resp.status_code, (302, 403))


class ExportSpecRegistryTests(TestCase):
    def test_mansioni_spec_columns_match_page(self):
        from anagrafica.exports import EXPORT_SPECS

        spec = EXPORT_SPECS["mansioni"]
        labels = [label for label, _key in spec.columns]
        self.assertEqual(
            labels,
            ["Mansione", "Categoria", "Livello di rischio", "Descrizione",
             "DPI richiesti", "Visite richieste", "Attiva"],
        )

    def test_acl_binding_registered_for_export_route(self):
        from anagrafica.acl_bootstrap import _EXPORT_ROUTE_BINDINGS, PERM_EXPORT

        self.assertEqual(_EXPORT_ROUTE_BINDINGS["anagrafica:export"], PERM_EXPORT)
