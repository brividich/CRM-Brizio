from django.test import SimpleTestCase
from django.urls import reverse

from security import docs_render as dr


class SlugTests(SimpleTestCase):
    def test_slug_for_filename(self):
        self.assertEqual(dr.slug_for("00_START_HERE.md"), "00-start-here")
        self.assertEqual(dr.slug_for("MAILBOX_INGESTION.md"), "mailbox-ingestion")

    def test_filename_for_roundtrip(self):
        for f in dr.DOC_FILES:
            self.assertEqual(dr.filename_for(dr.slug_for(f)), f)

    def test_filename_for_unknown_is_none(self):
        self.assertIsNone(dr.filename_for("../../etc/passwd"))
        self.assertIsNone(dr.filename_for("does-not-exist"))


class RenderTests(SimpleTestCase):
    def test_heading_has_slug_id(self):
        html = dr.render_markdown("# Titolo Uno\n\n## Sotto Due")
        self.assertIn('<h1 id="titolo-uno">Titolo Uno</h1>', html)
        self.assertIn('<h2 id="sotto-due">Sotto Due</h2>', html)

    def test_paragraph_and_inline(self):
        html = dr.render_markdown("Testo **grassetto** e *corsivo* e `code`.")
        self.assertIn("<strong>grassetto</strong>", html)
        self.assertIn("<em>corsivo</em>", html)
        self.assertIn("<code>code</code>", html)

    def test_unordered_list(self):
        html = dr.render_markdown("- uno\n- due\n")
        self.assertIn("<ul>", html)
        self.assertIn("<li>uno</li>", html)
        self.assertIn("<li>due</li>", html)

    def test_ordered_list(self):
        html = dr.render_markdown("1. primo\n2. secondo\n")
        self.assertIn("<ol>", html)
        self.assertIn("<li>primo</li>", html)

    def test_fenced_code_escapes_html(self):
        html = dr.render_markdown("```\n<script>alert(1)</script>\n```")
        self.assertIn("<pre><code>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_table(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |\n"
        html = dr.render_markdown(md)
        self.assertIn("<table", html)
        self.assertIn("<th>A</th>", html)
        self.assertIn("<td>1</td>", html)

    def test_link_safe_scheme(self):
        html = dr.render_markdown("[ok](https://example.org)")
        self.assertIn('href="https://example.org"', html)

    def test_link_unsafe_scheme_dropped(self):
        html = dr.render_markdown("[x](javascript:alert(1))")
        self.assertNotIn("javascript:", html)
        self.assertNotIn("<a ", html)

    def test_raw_html_is_escaped(self):
        html = dr.render_markdown("Testo <img src=x onerror=alert(1)>")
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)


class TocTests(SimpleTestCase):
    def test_build_toc_skips_code(self):
        md = "# Uno\n\n```\n# non-heading\n```\n\n## Due"
        toc = dr.build_toc(md)
        self.assertEqual([t["slug"] for t in toc], ["uno", "due"])


class LoadDocTests(SimpleTestCase):
    def test_unknown_slug_returns_none(self):
        self.assertIsNone(dr.load_doc("nope"))
        self.assertIsNone(dr.load_doc("../../secret"))

    def test_load_known_slug_returns_dict(self):
        doc = dr.load_doc(dr.slug_for(dr.DOC_FILES[0]))
        self.assertIsNotNone(doc)
        self.assertIn("html", doc)
        self.assertIn("toc", doc)
        self.assertTrue(doc["title"])


class AllGuideFilesRenderTests(SimpleTestCase):
    def test_all_indexed_docs_present_and_render(self):
        for f in dr.DOC_FILES:
            path = dr.GUIDE_DIR / f
            self.assertTrue(path.exists(), f"manca {f}")
            doc = dr.load_doc(dr.slug_for(f))
            self.assertNotIn("non e' ancora stato scritto", doc["html"])
            self.assertGreater(len(doc["html"]), 200, f)


class AutomationGuideTests(SimpleTestCase):
    """Le pagine SOC puntano a queste ancore: se cambia un titolo, il link si rompe."""

    def test_anchors_linked_from_pages_exist(self):
        doc = dr.load_doc("12-automatismi-e-vulnerabilita")
        slugs = {entry["slug"] for entry in doc["toc"]}
        for anchor in ("soppressione-appresa", "automatismi-di-rientro", "impatto-cve-sugli-asset",
                       "importare-un-inventario", "collegare-i-software-alle-cve-cpe"):
            self.assertIn(anchor, slugs)


class PageHelpLinksTests(SimpleTestCase):
    """Il pulsante «?» del menu SOC punta a un capitolo e a un'ancora che esistono."""

    def test_every_page_help_points_to_existing_doc_and_anchor(self):
        from security import urls_hub
        from security.templatetags.security_help import PAGE_HELP

        route_names = {pattern.name for pattern in urls_hub.urlpatterns}
        for url_name, (slug, anchor) in PAGE_HELP.items():
            self.assertIn(url_name, route_names)
            doc = dr.load_doc(slug)
            self.assertIsNotNone(doc, slug)
            if anchor:
                self.assertIn(anchor, {entry["slug"] for entry in doc["toc"]}, f"{url_name} -> {slug}#{anchor}")

    def test_fallbacks(self):
        from security.templatetags.security_help import soc_page_help_url

        self.assertIn("08-configuration-guide", soc_page_help_url("admin_config_sources"))
        self.assertEqual(soc_page_help_url("nome-sconosciuto"), reverse("security:help"))
        self.assertTrue(soc_page_help_url("alerts_list").endswith("/13-lavoro-quotidiano/#alert"))
