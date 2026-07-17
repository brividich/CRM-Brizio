from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from security import docs_render as dr

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class DocDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("soc_admin", "soc@example.org", "pw-Test-12345")

    def test_anonymous_redirected(self):
        url = reverse("security:doc_detail", args=[dr.slug_for(dr.DOC_FILES[0])])
        resp = self.client.get(url)
        self.assertIn(resp.status_code, (301, 302))

    def test_unknown_slug_404(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security:doc_detail", args=["nope"]))
        self.assertEqual(resp.status_code, 404)

    def test_known_slug_renders(self):
        self.client.force_login(self.admin)
        url = reverse("security:doc_detail", args=[dr.slug_for(dr.DOC_FILES[0])])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "security/doc_detail.html")

    def test_docs_have_slug(self):
        from security.views import SECURITY_CENTER_DOCS
        for d in SECURITY_CENTER_DOCS:
            self.assertIn("slug", d)
            self.assertEqual(dr.filename_for(d["slug"]), d["file"])


@override_settings(LEGACY_AUTH_ENABLED=False)
class DocsIndexTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("soc_admin2", "soc2@example.org", "pw-Test-12345")

    def test_admin_docs_rows_link_to_detail(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security:admin_docs"))
        self.assertEqual(resp.status_code, 200)
        first = reverse("security:doc_detail", args=[dr.slug_for(dr.DOC_FILES[0])])
        self.assertContains(resp, f'href="{first}"')

    def test_help_links_to_detail(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("security:help"))
        self.assertContains(resp, reverse("security:doc_detail", args=[dr.slug_for(dr.DOC_FILES[0])]))
