from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings

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


class ProcedureGroupInBachecaTests(TestCase):
    """Il gruppo virtuale «Procedure SGI» compare in bacheca, esclusi i sensibili."""

    def _admin_request(self):
        return SimpleNamespace(
            user=SimpleNamespace(is_superuser=True, get_username=lambda: "admin",
                                 first_name="", email=""),
            legacy_user=SimpleNamespace(id=1, ruolo="AMMINISTRAZIONE", ruolo_id=1, nome="Admin"),
        )

    def _proc_doc(self, code, sensibile=False):
        from datetime import date

        from procedure_refresh.models import ProcedureDocument, ProcedureRevision, SourceType

        doc = ProcedureDocument.objects.create(
            code=code, title="Titolo " + code, is_active=True, escludi_dal_rag=sensibile,
        )
        ProcedureRevision.objects.create(
            document=doc, revision_code="1", revision_date=date(2026, 1, 1),
            effective_date=date(2026, 1, 1), source_type=SourceType.SHAREPOINT,
            source_url="https://sp/" + code, file_name=code + ".pdf", is_current=True,
        )
        return doc

    def test_gruppo_procedure_in_bacheca(self):
        self._proc_doc("MT CN 30")
        self._proc_doc("MT CN 31", sensibile=True)
        groups = hp._documenti_collegamenti(self._admin_request(), preview=False)
        proc = [g for g in groups if g["name"] == "Procedure SGI"]
        self.assertEqual(len(proc), 1)
        titles = " ".join(i["title"] for i in proc[0]["items"])
        self.assertIn("MT CN 30", titles)
        self.assertNotIn("MT CN 31", titles)


class HubLinkDownloadViewTests(TestCase):
    """Testa la view di download direttamente (RequestFactory) per isolare la
    logica di visibilità/serving dal middleware ACL/onboarding del portale.
    La logica di ruolo è coperta anche in core.test_hub_bacheca_service."""

    def setUp(self):
        import tempfile
        self.User = get_user_model()
        self.user = self.User.objects.create_user(username="mario", password="x")
        self.cat = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica-dl")
        self.tmp = tempfile.mkdtemp()
        self.factory = RequestFactory()

    def _file_link(self, title="Doc", roles=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import HubLinkRoleAccess
        link = HubLink.objects.create(
            category=self.cat, kind=HubLink.KIND_FILE, title=title,
            file=SimpleUploadedFile("m187.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
            original_filename="m187.pdf",
        )
        for rid in (roles or []):
            HubLinkRoleAccess.objects.create(link=link, legacy_role_id=rid)
        return link

    def _req(self, pk, user):
        req = self.factory.get(f"/dashboard/bacheca/doc/{pk}/")
        req.user = user
        return req

    def test_view_serves_public_file(self):
        from dashboard.views_bacheca import hub_link_download
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=self.tmp):
            link = self._file_link()
            resp = hub_link_download(self._req(link.pk, self.user), link.pk)
            self.assertEqual(resp.status_code, 200)

    def test_view_denies_restricted_file(self):
        from django.http import Http404
        from dashboard.views_bacheca import hub_link_download
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=self.tmp):
            link = self._file_link(roles=[5])  # utente test senza ruolo legacy → None
            with self.assertRaises(Http404):
                hub_link_download(self._req(link.pk, self.user), link.pk)

    def test_view_requires_login(self):
        from django.contrib.auth.models import AnonymousUser
        from dashboard.views_bacheca import hub_link_download
        with override_settings(HUB_BACHECA_PRIVATE_ROOT=self.tmp):
            link = self._file_link()
            resp = hub_link_download(self._req(link.pk, AnonymousUser()), link.pk)
            self.assertEqual(resp.status_code, 302)  # login_required redirect


class HomeRenderSmokeTests(TestCase):
    """La home riscritta (layout Bacheca) deve renderizzare senza errori."""

    def test_home_renders_for_admin(self):
        from django.urls import reverse
        admin = get_user_model().objects.create_superuser(
            username="adm", email="a@a.it", password="x")
        cat = HubLinkCategory.objects.create(name="Modulistica", slug="mod-smoke")
        HubLink.objects.create(category=cat, kind=HubLink.KIND_URL, title="Gestionale",
                               url="https://esempio.local")
        self.client.force_login(admin)
        resp = self.client.get(reverse("home_portale:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Documenti")
