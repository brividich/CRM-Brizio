from django.test import SimpleTestCase

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
