# SOC IT — Guida configurazione in-app + rifiniture UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere realmente esistente e consultabile in-app la documentazione del Security Center IT (SOC), con la guida di configurazione al centro, e rifinire la UX delle 9 sezioni della Configuration Studio — senza toccare il motore alert/dedup.

**Architecture:** Un renderer Markdown interno zero-dipendenze (`docs_render.py`) trasforma i `.md` di `django_app/security/guide/` in HTML sicuro; una view `doc_detail` gated ACL li serve nel tema SOC; gli indici esistenti (`help`, `admin/docs`) diventano clickabili; le sezioni di configurazione ricevono un pannello di help contestuale con link a guida e diagnostica.

**Tech Stack:** Django 5.2 (SSR templates), Python 3.11+, nessuna nuova dipendenza pip. Test con `manage.py test django_app.security --settings=config.settings.test --keepdb`.

## Global Constraints

- **Nessuna modifica** a: motore regole/dedup, parser, ingestione, notifiche, heartbeat, modelli, migrazioni. Solo presentation-layer.
- **Nessuna dipendenza pip nuova** (renderer interno).
- **Posizione guida = `django_app/security/guide/`** (NON `docs/`/`doc/`): il packager (`deployment/scripts/package-release.ps1`) passa a robocopy `/XD doc` e `/XD docs`, che scartano qualsiasi cartella con quel nome; `guide` è sicuro e i `.md` non sono esclusi.
- **Contenuto solo sintetico**: nessun dato reale, segreto, credenziale, mailbox o report di sicurezza reale nei doc (Security Boundaries).
- **Lingua doc e UI: italiano.**
- Comandi reali del modulo da citare correttamente: `seed_security_center_config`, `security_center_diagnostics`, `ingest_security_mailbox`, `run_security_parsers`, `evaluate_security_rules`, `build_daily_kpi_snapshots`, `check_security_source_heartbeat`, `send_security_test_notification`, `collega_asset_security`, `security_db_check`, `security_uat_smoke_check`.
- Permessi reali: canonico ACL v2 `security.config.view`; Django perm `security.manage_security_configuration`; fallback `is_staff`. Helper esistenti in `views.py`: `can_view_security_center(user)`, `can_manage_security_config(user)`, `_security_config_denied(request)`.
- **Test auth:** usare superuser + `force_login` e `@override_settings(LEGACY_AUTH_ENABLED=False)` per non farsi negare dall'ACL middleware. Nel worktree può mancare `.env` (non è regressione).
- **Ogni commit** nel worktree `C:\Dev\pn-soc-guide` (branch `feature/soc-config-guide`). Trailer commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` e `Claude-Session: https://claude.ai/code/session_01M5Z3ySvQbf1dn2bjVQnxGY`.

---

## File Structure

**Nuovi:**
- `django_app/security/docs_render.py` — renderer Markdown + loader whitelist. Unica responsabilità: testo→HTML sicuro e caricamento doc.
- `django_app/security/guide/*.md` — 13 documenti (contenuto).
- `django_app/security/templates/security/doc_detail.html` — pagina singolo doc.
- `django_app/security/templates/security/admin_config/_section_help.html` — partial help sezione.
- `django_app/security/tests/test_docs_render.py` — unit test renderer/loader.
- `django_app/security/tests/test_docs_views.py` — test view/route/ACL + help sezione.

**Modificati:**
- `django_app/security/views.py` — `SECURITY_CENTER_DOCS` con `slug`; view `doc_detail`; dict `CONFIG_SECTION_HELP`; `section_help` nel context delle 9 view `admin_config_*`.
- `django_app/security/urls.py` — route `doc_detail`.
- `django_app/security/templates/security/admin_docs.html`, `help.html` — righe clickabili; nota percorso aggiornata.
- `django_app/security/templates/security/_base_soc.html` — voce nav "Guida".
- Le 9 `django_app/security/templates/security/admin_config/*.html` — include `_section_help`; `alert_rules.html` fix test-regola/empty-state.
- `CHANGELOG.md`, `README.md`.

---

### Task 1: Renderer Markdown e loader doc (`docs_render.py`)

**Files:**
- Create: `django_app/security/docs_render.py`
- Test: `django_app/security/tests/test_docs_render.py`

**Interfaces:**
- Produces:
  - `DOC_FILES: list[str]` — 13 filename in ordine indice.
  - `slug_for(filename: str) -> str`
  - `filename_for(slug: str) -> str | None`
  - `render_markdown(text: str) -> str` (HTML `mark_safe`)
  - `build_toc(text: str) -> list[dict]` con chiavi `level,text,slug`
  - `load_doc(slug: str) -> dict | None` con chiavi `slug,filename,title,html,toc`
  - `GUIDE_DIR: Path`

- [ ] **Step 1: Scrivi il test che fallisce** — `django_app/security/tests/test_docs_render.py`

```python
from pathlib import Path

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
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_render --settings=config.settings.test`
Expected: FAIL (ModuleNotFoundError: `docs_render`).

- [ ] **Step 3: Implementa `docs_render.py`**

```python
"""Renderer Markdown a zero dipendenze per la guida in-app del Security Center (SOC IT).

Contenuto attendibile (file del repo) reso su pagina admin/SOC, ma il renderer resta
difensivo: fa html.escape del testo prima del markup inline e ammette solo schemi di
link sicuri. Supporta il sottoinsieme Markdown usato dalla guida: heading ATX,
paragrafi, liste ordinate/non ordinate (nesting via indentazione), code fence,
blockquote, tabelle GFM, regola orizzontale; inline bold/italic/code/link/hard-break.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from django.utils.safestring import mark_safe

GUIDE_DIR = Path(__file__).resolve().parent / "guide"

DOC_FILES = [
    "00_START_HERE.md",
    "01_ARCHITECTURE.md",
    "02_ADMIN_GUIDE.md",
    "03_ADDONS.md",
    "04_WATCHGUARD_ADDON.md",
    "05_DEFENDER_ADDON.md",
    "06_BACKUP_ADDON.md",
    "07_ALERT_LIFECYCLE.md",
    "08_CONFIGURATION_GUIDE.md",
    "09_TROUBLESHOOTING.md",
    "10_DEVELOPER_GUIDE.md",
    "11_OPERATIONS_RUNBOOK.md",
    "MAILBOX_INGESTION.md",
]

PLACEHOLDER = "# Documento non disponibile\n\n_Questo documento non e' ancora stato scritto._"


def slug_for(filename: str) -> str:
    base = filename[:-3] if filename.endswith(".md") else filename
    return base.lower().replace("_", "-")


_SLUG_TO_FILE = {slug_for(f): f for f in DOC_FILES}


def filename_for(slug: str) -> str | None:
    return _SLUG_TO_FILE.get(slug)


def _heading_slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s or "section"


_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")
_SAFE_SCHEME = re.compile(r"^(https?:|mailto:|/|#|\.\.?/)", re.IGNORECASE)


def _render_inline(text: str) -> str:
    tokens: list[str] = []

    def stash(fragment: str) -> str:
        tokens.append(fragment)
        return f"\x00{len(tokens) - 1}\x00"

    def code_sub(m: re.Match) -> str:
        return stash(f"<code>{html.escape(m.group(1))}</code>")

    text = _CODE_RE.sub(code_sub, text)

    def link_sub(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if not _SAFE_SCHEME.match(url):
            return html.escape(m.group(0))
        external = not url.startswith(("#", "/", ".", "mailto:"))
        attrs = ' target="_blank" rel="noopener"' if external else ""
        return stash(f'<a href="{html.escape(url, quote=True)}"{attrs}>{html.escape(label)}</a>')

    text = _LINK_RE.sub(link_sub, text)
    text = html.escape(text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: tokens[int(m.group(1))], text)
    return text


_LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")


def _split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _render_table(lines: list[str], i: int) -> tuple[str, int]:
    header = _split_row(lines[i])
    j = i + 2
    rows = []
    while j < len(lines) and "|" in lines[j] and lines[j].strip():
        rows.append(_split_row(lines[j]))
        j += 1
    thead = "".join(f"<th>{_render_inline(c)}</th>" for c in header)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{_render_inline(c)}</td>" for c in r) + "</tr>"
    return f'<table class="sec-table"><thead><tr>{thead}</tr></thead><tbody>{body}</tbody></table>', j


def _consume_list(lines: list[str], i: int, n: int) -> tuple[str, int]:
    m0 = _LIST_ITEM_RE.match(lines[i])
    base_indent = len(m0.group(1))
    tag = "ol" if m0.group(2).endswith(".") else "ul"
    items: list[list] = []
    while i < n:
        m = _LIST_ITEM_RE.match(lines[i])
        if not m or not lines[i].strip():
            break
        indent = len(m.group(1))
        if indent < base_indent:
            break
        if indent > base_indent:
            sub_html, i = _consume_list(lines, i, n)
            if items:
                items[-1][1] = sub_html
            continue
        items.append([m.group(3).strip(), ""])
        i += 1
    out = f"<{tag}>"
    for content, sub in items:
        out += "<li>" + _render_inline(content) + sub + "</li>"
    out += f"</{tag}>"
    return out, i


def render_markdown(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = len(lines)
    parts: list[str] = []
    para: list[str] = []
    i = 0

    def flush_para() -> None:
        if para:
            parts.append("<p>" + _render_inline(" ".join(para).strip()) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("```"):
            flush_para()
            lang = stripped[3:].strip()
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            parts.append(f"<pre><code{cls}>{html.escape(chr(10).join(code_lines))}</code></pre>")
            continue

        if not stripped:
            flush_para()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            content = m.group(2).strip()
            parts.append(f'<h{level} id="{_heading_slug(content)}">{_render_inline(content)}</h{level}>')
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            parts.append("<hr>")
            i += 1
            continue

        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            parts.append("<blockquote>" + _render_inline(" ".join(quote)) + "</blockquote>")
            continue

        if "|" in stripped and i + 1 < n and "-" in lines[i + 1] and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            flush_para()
            table_html, i = _render_table(lines, i)
            parts.append(table_html)
            continue

        if _LIST_ITEM_RE.match(line):
            flush_para()
            block, i = _consume_list(lines, i, n)
            parts.append(block)
            continue

        para.append(stripped)
        i += 1

    flush_para()
    return mark_safe("\n".join(parts))


def build_toc(text: str) -> list[dict]:
    toc = []
    in_code = False
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            content = m.group(2).strip()
            toc.append({"level": len(m.group(1)), "text": content, "slug": _heading_slug(content)})
    return toc


def load_doc(slug: str) -> dict | None:
    filename = filename_for(slug)
    if not filename:
        return None
    path = GUIDE_DIR / filename
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        text = PLACEHOLDER
    title = slug
    for line in text.splitlines():
        hm = re.match(r"^#\s+(.*)$", line.strip())
        if hm:
            title = hm.group(1).strip()
            break
    return {"slug": slug, "filename": filename, "title": title, "html": render_markdown(text), "toc": build_toc(text)}
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_render --settings=config.settings.test`
Expected: PASS (tutti). Nota: `test_load_known_slug_returns_dict` passa anche senza `.md` reali (fail-soft PLACEHOLDER).

- [ ] **Step 5: Commit**

```bash
git add django_app/security/docs_render.py django_app/security/tests/test_docs_render.py
git commit -m "feat(security): renderer Markdown interno + loader whitelist per la guida SOC"
```

---

### Task 2: View `doc_detail`, route e template

**Files:**
- Modify: `django_app/security/views.py` (import + view `doc_detail`; `slug` in `SECURITY_CENTER_DOCS`)
- Modify: `django_app/security/urls.py`
- Create: `django_app/security/templates/security/doc_detail.html`
- Test: `django_app/security/tests/test_docs_views.py`

**Interfaces:**
- Consumes: `docs_render.load_doc`, `docs_render.slug_for`, `docs_render.DOC_FILES`, helper `can_view_security_center`, `_security_config_denied`.
- Produces: url name `security:doc_detail` (arg `slug`); `SECURITY_CENTER_DOCS[i]["slug"]`.

- [ ] **Step 1: Scrivi il test che fallisce** — `django_app/security/tests/test_docs_views.py`

```python
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
```

- [ ] **Step 2: Verifica il fallimento**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views --settings=config.settings.test`
Expected: FAIL (NoReverseMatch per `doc_detail`).

- [ ] **Step 3a: `SECURITY_CENTER_DOCS` con slug + view `doc_detail`** in `views.py`

In cima al file, tra gli import locali, aggiungi:
```python
from .docs_render import DOC_FILES as _DOC_FILES, load_doc, slug_for
```

Sostituisci il blocco `SECURITY_CENTER_DOCS = [ ... ]` (attorno a riga 830) con la costruzione derivata (mantiene titoli/summary italiani gia' presenti, aggiunge `slug`):
```python
_DOC_META = {
    "00_START_HERE.md": ("Da qui", "Ambito MVP, checklist primo setup e primi 30 minuti."),
    "01_ARCHITECTURE.md": ("Architettura", "Motore core, parser, regole, evidenze, KPI, configurazione admin, diagnostica e moduli."),
    "02_ADMIN_GUIDE.md": ("Guida admin", "Sorgenti, parser, regole alert, soppressioni, backup, notifiche, ticketing e registro audit."),
    "03_ADDONS.md": ("Moduli", "Modello core rispetto ai moduli e architettura target dei moduli."),
    "04_WATCHGUARD_ADDON.md": ("Modulo WatchGuard", "Input WatchGuard supportati, metriche, regole, riduzione rumore e limiti."),
    "05_DEFENDER_ADDON.md": ("Modulo Microsoft Defender", "Email vulnerabilita, evidenze CVE, deduplica ticket e ricorrenze."),
    "06_BACKUP_ADDON.md": ("Modulo Backup/NAS", "Sorgente Synology Active Backup, job attesi, logica backup mancanti e salute backup."),
    "07_ALERT_LIFECYCLE.md": ("Ciclo vita alert", "Stati alert e differenze tra presa in carico, posticipo, silenziamento, soppressione, risoluzione, falso positivo e chiusura."),
    "08_CONFIGURATION_GUIDE.md": ("Guida configurazione", "Configurazione seed e impostazioni DB per sorgenti, parser, regole, soppressioni, backup, notifiche e ticketing."),
    "09_TROUBLESHOOTING.md": ("Risoluzione problemi", "Problemi comuni su parser, sorgenti, alert, ticket, backup, notifiche, seed e permessi."),
    "10_DEVELOPER_GUIDE.md": ("Guida sviluppo", "Purezza parser, struttura output, avvisi, test, configurazione seed, regole alert e visibilita dashboard."),
    "11_OPERATIONS_RUNBOOK.md": ("Runbook operativo", "Checklist operative giornaliere, settimanali e mensili."),
    "MAILBOX_INGESTION.md": ("Mailbox Ingestion", "Ingestion schedulata da mailbox, provider, deduplicazione, configurazione e troubleshooting."),
}
SECURITY_CENTER_DOCS = [
    {"file": f, "slug": slug_for(f), "title": _DOC_META[f][0], "summary": _DOC_META[f][1]}
    for f in _DOC_FILES
]
```

Aggiungi la view (accanto a `help_page`/`admin_docs`):
```python
@ensure_csrf_cookie
def doc_detail(request, slug):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path(), login_url="/admin/login/")
    if not can_view_security_center(request.user):
        return _security_config_denied(request)
    doc = load_doc(slug)
    if doc is None:
        raise Http404("Documento sconosciuto.")
    return render(request, "security/doc_detail.html", {"doc": doc, "docs": SECURITY_CENTER_DOCS})
```
(Verifica che `Http404`, `redirect_to_login`, `ensure_csrf_cookie` siano gia' importati in `views.py`; lo sono per le view vicine.)

- [ ] **Step 3b: Route** in `urls.py`

Dopo `path("security/help/", views.help_page, name="help"),` aggiungi:
```python
    path("security/docs/<slug:slug>/", views.doc_detail, name="doc_detail"),
```

- [ ] **Step 3c: Template** `django_app/security/templates/security/doc_detail.html`

```django
{% extends "security/_base_soc.html" %}
{% block title %}{{ doc.title }} - Guida Security Center{% endblock %}
{% block page_marker %}Guida Security Center{% endblock %}
{% block page_title %}{{ doc.title }}{% endblock %}
{% block page_icon %}i{% endblock %}
{% block soc_content %}
<div class="sec-grid sec-two-col">
  <aside class="sec-panel sec-doc-toc">
    <div class="sec-section-head"><h2>Indice</h2><a href="{% url 'security:admin_docs' %}">Tutti i documenti</a></div>
    <ul class="sec-doc-list">
      {% for item in doc.toc %}
        <li class="sec-toc-l{{ item.level }}"><a href="#{{ item.slug }}">{{ item.text }}</a></li>
      {% empty %}
        <li class="sec-muted">Nessuna sezione.</li>
      {% endfor %}
    </ul>
    <p style="margin-top:12px"><a class="sec-button" href="{% url 'security:admin_diagnostics' %}">Diagnostica</a> <a class="sec-button" href="{% url 'security:admin_config' %}">Configurazione</a></p>
  </aside>
  <article class="sec-panel sec-doc-body">
    {{ doc.html }}
  </article>
</div>
{% endblock %}
```

- [ ] **Step 4: Verifica il passaggio dei test**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/security/views.py django_app/security/urls.py django_app/security/templates/security/doc_detail.html django_app/security/tests/test_docs_views.py
git commit -m "feat(security): view/route/template doc_detail per la guida SOC renderizzata"
```

---

### Task 3: Indici clickabili + voce nav "Guida"

**Files:**
- Modify: `django_app/security/templates/security/admin_docs.html`
- Modify: `django_app/security/templates/security/help.html`
- Modify: `django_app/security/templates/security/_base_soc.html`
- Test: estendi `django_app/security/tests/test_docs_views.py`

**Interfaces:**
- Consumes: `security:doc_detail`, `security:help`, `SECURITY_CENTER_DOCS[i].slug`.

- [ ] **Step 1: Aggiungi i test che falliscono** (in `test_docs_views.py`, nuova classe)

```python
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
```

- [ ] **Step 2: Verifica il fallimento**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views.DocsIndexTests --settings=config.settings.test`
Expected: FAIL (link assenti).

- [ ] **Step 3a: `admin_docs.html`** — rendi la prima colonna un link e aggiorna la nota percorso.

Sostituisci la riga `<p class="sec-muted">Indice in sola lettura ... <code>docs/security-center/</code>.</p>` con:
```django
      <p class="sec-muted">Documentazione operativa integrata nel modulo. Clicca un documento per aprirlo.</p>
```
Sostituisci la riga del `{% for %}`:
```django
        {% for doc in docs %}
          <tr><td><a href="{% url 'security:doc_detail' doc.slug %}"><code>{{ doc.file }}</code></a></td><td>{{ doc.title }}</td><td>{{ doc.summary }}</td></tr>
        {% endfor %}
```

- [ ] **Step 3b: `help.html`** — nella tabella "Riferimenti documentazione" rendi il nome file un link:
```django
        {% for doc in docs %}
          <tr><td><a href="{% url 'security:doc_detail' doc.slug %}"><code>{{ doc.file }}</code></a></td><td>{{ doc.title }}</td></tr>
        {% endfor %}
```

- [ ] **Step 3c: `_base_soc.html`** — aggiungi la voce "Guida" nella `soc-nav`, dopo il link "Config":
```django
    <a href="{% url 'security:help' %}" {% if url_name == 'help' or url_name == 'doc_detail' %}class="active"{% endif %}>Guida</a>
```

- [ ] **Step 4: Verifica il passaggio**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/security/templates/security/admin_docs.html django_app/security/templates/security/help.html django_app/security/templates/security/_base_soc.html django_app/security/tests/test_docs_views.py
git commit -m "feat(security): indici documentazione clickabili + voce nav Guida"
```

---

### Task 4: Help contestuale nelle 9 sezioni di configurazione

**Files:**
- Modify: `django_app/security/views.py` (dict `CONFIG_SECTION_HELP` + `section_help` nel context delle 9 view)
- Create: `django_app/security/templates/security/admin_config/_section_help.html`
- Modify: le 9 `admin_config/*.html` (include partial); `alert_rules.html` fix test-regola/empty-state
- Test: `django_app/security/tests/test_docs_views.py` (nuova classe)

**Interfaces:**
- Consumes: `SECURITY_CENTER_DOCS` slug; `security:doc_detail`, `security:admin_diagnostics`.
- Produces: context key `section_help` con `{title, intro, doc_slug, tips}` nelle 9 view.

- [ ] **Step 1: Test che falliscono** (nuova classe in `test_docs_views.py`)

```python
@override_settings(LEGACY_AUTH_ENABLED=False)
class ConfigSectionHelpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("soc_admin3", "soc3@example.org", "pw-Test-12345")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_each_config_section_shows_help(self):
        names = [
            "admin_config_general", "admin_config_sources", "admin_config_parsers",
            "admin_config_alert_rules", "admin_config_suppressions", "admin_config_backups",
            "admin_config_notifications", "admin_config_ticketing", "admin_config_audit",
        ]
        for name in names:
            resp = self.client.get(reverse(f"security:{name}"))
            self.assertEqual(resp.status_code, 200, name)
            self.assertContains(resp, "sec-section-help", msg_prefix=name)
            self.assertContains(resp, "Apri guida", msg_prefix=name)
```

- [ ] **Step 2: Verifica il fallimento**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views.ConfigSectionHelpTests --settings=config.settings.test`
Expected: FAIL (`sec-section-help` assente).

- [ ] **Step 3a: `CONFIG_SECTION_HELP`** in `views.py` (dopo `SECURITY_CENTER_DOCS`)

```python
CONFIG_SECTION_HELP = {
    "general": {
        "title": "Impostazioni generali",
        "intro": "Chiavi di configurazione globali del Security Center (soglie, finestre, comportamenti). Le voci marcate segrete non mostrano il valore.",
        "doc_slug": "08-configuration-guide",
        "tips": ["Dopo un `seed_security_center_config` rivedi qui le chiavi.", "Le modifiche sono tracciate nel registro audit."],
    },
    "sources": {
        "title": "Sorgenti",
        "intro": "Definisci da dove arrivano i report (email/PDF/CSV/API/manuale), i pattern mittente/oggetto e la cadenza attesa.",
        "doc_slug": "02-admin-guide",
        "tips": ["Imposta la cadenza attesa: l'assenza di un report genera un alert (heartbeat).", "Usa la Diagnostica per provare il match mittente/oggetto."],
    },
    "parsers": {
        "title": "Parser",
        "intro": "Abilita e ordina i parser che trasformano i report in metriche e finding. Priorita' piu' bassa = valutato prima.",
        "doc_slug": "02-admin-guide",
        "tips": ["Un parser disattivato non produce metriche.", "Verifica il nome parser sulla sorgente."],
    },
    "alert_rules": {
        "title": "Regole alert",
        "intro": "Condizioni su metriche che generano alert, con severita', cooldown e finestra di deduplica.",
        "doc_slug": "07-alert-lifecycle",
        "tips": ["Il campo Test accetta un JSON di metriche, es. {\"value\": 1}, e mostra se la regola scatterebbe.", "Cooldown e dedup evitano alert ripetuti sullo stesso finding."],
    },
    "suppressions": {
        "title": "Regole di soppressione",
        "intro": "Silenzia eventi noti/rumorosi per tipo, severita' o condizioni, con validita' temporale.",
        "doc_slug": "07-alert-lifecycle",
        "tips": ["Una soppressione attiva riduce il rumore ma puo' nascondere segnali: rivedila periodicamente.", "Imposta una scadenza quando possibile."],
    },
    "backups": {
        "title": "Monitoraggio backup",
        "intro": "Job di backup attesi e regole per rilevare backup mancanti, falliti o anomali per durata/dimensione.",
        "doc_slug": "06-backup-addon",
        "tips": ["Un job atteso non visto oltre le ore limite genera un alert 'mancante'.", "Marca come critici i job la cui assenza deve allertare subito."],
    },
    "notifications": {
        "title": "Notifiche",
        "intro": "Canali in uscita (email/Teams/dashboard), severita' minima e cooldown per canale. Ogni invio e' tracciato.",
        "doc_slug": "02-admin-guide",
        "tips": ["Prova un canale con `send_security_test_notification` prima di affidarti alle notifiche.", "Il cooldown evita raffiche sullo stesso alert."],
    },
    "ticketing": {
        "title": "Ticketing",
        "intro": "Come gli alert diventano ticket di remediation: strategia di aggregazione, assegnatario, SLA per severita'.",
        "doc_slug": "05-defender-addon",
        "tips": ["L'aggregazione per prodotto raggruppa CVE dello stesso prodotto.", "Gli SLA per severita' guidano gli avvisi di scadenza."],
    },
    "audit": {
        "title": "Registro audit",
        "intro": "Traccia in sola lettura di ogni modifica di configurazione: attore, oggetto, campo, valori.",
        "doc_slug": "08-configuration-guide",
        "tips": ["Usalo per capire chi ha cambiato cosa e quando.", "E' la fonte di verita' per gli audit di conformita'."],
    },
}
```

- [ ] **Step 3b: passa `section_help` nel context delle 9 view.**

Le sezioni che usano l'helper generico `_config_model_page(...)` (sources, parsers, suppressions, backups, notifications) passano `extra_context={"section_help": CONFIG_SECTION_HELP["<key>"]}`. Esempio, nella view `admin_config_sources`:
```python
    return _config_model_page(request, SecuritySourceConfig, SecuritySourceConfigForm,
                              "security/admin_config/sources.html", "security:admin_config_sources",
                              extra_context={"section_help": CONFIG_SECTION_HELP["sources"]})
```
Applica lo stesso pattern (`extra_context={"section_help": CONFIG_SECTION_HELP["<key>"]}`) a `admin_config_parsers` ("parsers"), `admin_config_suppressions` ("suppressions"), `admin_config_backups` ("backups"), `admin_config_notifications` ("notifications").
Per `admin_config_general`, `admin_config_alert_rules`, `admin_config_ticketing`, `admin_config_audit` (che fanno `render(...)` diretto), aggiungi al dict di context la chiave `"section_help": CONFIG_SECTION_HELP["<key>"]` (rispettivamente "general", "alert_rules", "ticketing", "audit").

> Se una di queste view ha una firma diversa da quanto sopra, adatta solo l'aggiunta di `section_help` al context — non modificare la logica.

- [ ] **Step 3c: Partial** `django_app/security/templates/security/admin_config/_section_help.html`

```django
{% if section_help %}
<section class="sec-panel sec-section-help">
  <div class="sec-section-head">
    <div>
      <h2>{{ section_help.title }}</h2>
      <p class="sec-muted">{{ section_help.intro }}</p>
    </div>
    <div class="sec-section-help-actions">
      <a class="sec-button sec-button-primary" href="{% url 'security:doc_detail' section_help.doc_slug %}">Apri guida</a>
      <a class="sec-button" href="{% url 'security:admin_diagnostics' %}">Diagnostica</a>
    </div>
  </div>
  {% if section_help.tips %}
  <ul class="sec-doc-list">
    {% for tip in section_help.tips %}<li>{{ tip }}</li>{% endfor %}
  </ul>
  {% endif %}
</section>
{% endif %}
```

- [ ] **Step 3d: includi il partial** in cima al `{% block soc_content %}` di ognuna delle 9 pagine `admin_config/*.html` (general, sources, parsers, alert_rules, suppressions, backups, notifications, ticketing, audit). Subito dopo la riga `{% block soc_content %}`:
```django
{% include "security/admin_config/_section_help.html" %}
```

- [ ] **Step 3e: fix `alert_rules.html`** — rendi esplicito l'input di test. Sostituisci la cella `<td><form ...>...</form></td>` del test con:
```django
              <td>
                <form method="post" class="sec-grid">{% csrf_token %}
                  <input type="hidden" name="action" value="test-rule">
                  <input type="hidden" name="rule_id" value="{{ object.pk }}">
                  <label class="sec-muted" for="metrics_json_{{ object.pk }}">Metriche JSON</label>
                  <input id="metrics_json_{{ object.pk }}" name="metrics_json" value='{"value": 1}' aria-label="Metriche di test in JSON">
                  <button type="submit">Test</button>
                </form>
                <small class="sec-muted">Simula la regola su metriche fittizie (es. <code>{"value": 1}</code>): mostra se scatterebbe, senza creare alert.</small>
              </td>
```

- [ ] **Step 4: Verifica il passaggio**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_views.ConfigSectionHelpTests --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/security/views.py django_app/security/templates/security/admin_config/
git add django_app/security/tests/test_docs_views.py
git commit -m "feat(security): help contestuale nelle 9 sezioni di configurazione + fix test-regola"
```

---

### Task 5: Documenti core (configurazione) + guard test presenza/rendering

**Files:**
- Create: `django_app/security/guide/00_START_HERE.md`, `01_ARCHITECTURE.md`, `02_ADMIN_GUIDE.md`, `07_ALERT_LIFECYCLE.md`, `08_CONFIGURATION_GUIDE.md`, `09_TROUBLESHOOTING.md`, `11_OPERATIONS_RUNBOOK.md`, `MAILBOX_INGESTION.md`
- Test: estendi `test_docs_render.py`

**Contenuto (outline per documento — prosa in italiano, esempi SOLO sintetici, costrutti Markdown supportati dal renderer):**

- **00_START_HERE.md** — `# Da qui`. Sezioni: *Cos'e' e cosa non e'* (intelligence sui report ricorrenti, non un SIEM); *Prerequisiti*; *Primo setup in 30 minuti* (lista ordinata: `seed_security_center_config`; verifica 9 sezioni; `security_center_diagnostics`; ingerisci campioni; esegui pipeline `run_security_parsers`/`evaluate_security_rules`/`build_daily_kpi_snapshots`); *Dove guardare ogni giorno*; *Link* alla guida configurazione e al runbook.
- **01_ARCHITECTURE.md** — `# Architettura`. Flusso in code fence: `report/email/upload -> ingestione -> parser -> metriche/finding -> regole -> alert/soppressione -> evidence -> ticket -> dashboard/KPI`. Tabella componente→responsabilita' (Sorgenti, Parser, Regole, Soppressioni, Evidence, Ticket, Notifiche, KPI, Audit). Nota su dedup a indice unico parziale e heartbeat sorgenti.
- **02_ADMIN_GUIDE.md** — `# Guida admin`. Una sottosezione `##` per ciascuna delle 9 aree della Configuration Studio, con: a cosa serve, campi principali, errori comuni. Rimanda a 08 per il seed.
- **07_ALERT_LIFECYCLE.md** — `# Ciclo di vita degli alert`. Tabella stato→significato→quando usarlo per: new, open, acknowledged, in_progress, snoozed, muted, suppressed, resolved, false_positive, closed. Differenza tra soppressione (regola preventiva) e silenziamento (sul singolo alert). Come cooldown e dedup interagiscono.
- **08_CONFIGURATION_GUIDE.md** — `# Guida alla configurazione` *(documento centro)*. Sezioni: *Seed iniziale* (`seed_security_center_config`, idempotente); *Sorgenti* (pattern mittente/oggetto, cadenza attesa/heartbeat, gate DKIM/SPF); *Parser* (priorita', abilitazione); *Regole alert* (metrica/operatore/soglia, severita', cooldown, dedup, auto-ticket); *Soppressioni* (scope, scadenza); *Backup* (job attesi, finestra, mancanti/critici); *Notifiche* (canali email/Teams/dashboard, severita' minima, cooldown, test con `send_security_test_notification`); *Ticketing* (aggregazione, SLA per severita'); *Permessi/ACL* (`security.config.view`, `manage_security_configuration`, `is_staff`); *Audit* (dove leggere le modifiche). Ogni sezione con una micro-tabella campo→significato→default consigliato (valori d'esempio sintetici).
- **09_TROUBLESHOOTING.md** — `# Risoluzione problemi`. Formato problema→cause→verifica per: nessun parser corrisponde, nessun alert creato, nessun ticket creato, backup mancante non rilevato, notifiche non inviate, sorgente "silente"/heartbeat, permesso negato, doc non visibili in prod (verifica cartella `guide/` inclusa nel pacchetto). Rimanda a `security_center_diagnostics` e `security_db_check`.
- **11_OPERATIONS_RUNBOOK.md** — `# Runbook operativo`. Tre liste: *Giornaliera*, *Settimanale*, *Mensile* (dal contenuto gia' presente in `help.html`, ampliato). Comandi schedulati consigliati (`ingest_security_mailbox`, `check_security_source_heartbeat`, `build_daily_kpi_snapshots`).
- **MAILBOX_INGESTION.md** — `# Ingestione da mailbox`. Sezioni: *Provider* (manual/mock/graph/imap); *Configurazione sorgente mail* (allowlist mittente, `require_verified_sender`, include/exclude oggetto/corpo, allegati, `max_messages_per_run`, `expected_every_hours`); *Deduplica* (fingerprint messaggio); *Schedulazione* (`ingest_security_mailbox`, cadenza, `--loop`); *Heartbeat* (`check_security_source_heartbeat`); *Troubleshooting*.

- [ ] **Step 1: Scrivi gli 8 documenti core** nei percorsi indicati, seguendo gli outline. Usa solo: heading `#`/`##`/`###`, paragrafi, liste `-`/`1.`, code fence ```` ``` ````, tabelle GFM, `**grassetto**`, `` `code` ``, link `[t](/soc/...)` o esterni `https://`.

- [ ] **Step 2: Aggiungi il guard test** in `test_docs_render.py`:
```python
class GuideFilesRenderTests(SimpleTestCase):
    def test_core_docs_present_and_render(self):
        core = [
            "00_START_HERE.md", "01_ARCHITECTURE.md", "02_ADMIN_GUIDE.md",
            "07_ALERT_LIFECYCLE.md", "08_CONFIGURATION_GUIDE.md",
            "09_TROUBLESHOOTING.md", "11_OPERATIONS_RUNBOOK.md", "MAILBOX_INGESTION.md",
        ]
        for f in core:
            path = dr.GUIDE_DIR / f
            self.assertTrue(path.exists(), f"manca {f}")
            doc = dr.load_doc(dr.slug_for(f))
            self.assertNotIn("non e' ancora stato scritto", doc["html"])
            self.assertTrue(len(doc["html"]) > 200, f)
```

- [ ] **Step 3: Esegui i test**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_render --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 4: Apri in browser** `/soc/security/docs/08-configuration-guide/` e verifica il rendering (heading, tabelle, code). Correggi eventuali costrutti non resi.

- [ ] **Step 5: Commit**

```bash
git add django_app/security/guide/ django_app/security/tests/test_docs_render.py
git commit -m "docs(security): documenti core della guida SOC (config, architettura, runbook, mailbox)"
```

---

### Task 6: Documenti moduli + sviluppo + guard test completo (13/13)

**Files:**
- Create: `django_app/security/guide/03_ADDONS.md`, `04_WATCHGUARD_ADDON.md`, `05_DEFENDER_ADDON.md`, `06_BACKUP_ADDON.md`, `10_DEVELOPER_GUIDE.md`
- Test: estendi `test_docs_render.py`

**Contenuto (outline):**
- **03_ADDONS.md** — `# Moduli`. Core (motore condiviso) vs modulo (parser+seed+regole+metriche+doc). Elenco moduli attuali (WatchGuard, Microsoft Defender, Backup/NAS). Come si innesta un modulo.
- **04_WATCHGUARD_ADDON.md** — `# Modulo WatchGuard`. Input supportati (sintetici), metriche prodotte, regole tipiche, riduzione rumore, limiti.
- **05_DEFENDER_ADDON.md** — `# Modulo Microsoft Defender`. Email vulnerabilita'→evidenze CVE→ticket; dedup e ricorrenze; aggregazione per prodotto.
- **06_BACKUP_ADDON.md** — `# Modulo Backup/NAS`. Sorgente Synology Active Backup, job attesi, logica "mancante", finestre e anomalie durata/dimensione, salute.
- **10_DEVELOPER_GUIDE.md** — `# Guida sviluppo`. Purezza dei parser (nessun side-effect), struttura output metriche/finding, come aggiungere una regola/seed, dove aggiungere i test, visibilita' dashboard. Nota **operativa**: i doc vivono in `django_app/security/guide/` (non `docs/`) per il vincolo del packager.

- [ ] **Step 1: Scrivi i 5 documenti** seguendo gli outline (stessi vincoli Markdown/contenuto sintetico del Task 5).

- [ ] **Step 2: Sostituisci il guard test** in `test_docs_render.py` con la versione completa (tutti i 13):
```python
class AllGuideFilesRenderTests(SimpleTestCase):
    def test_all_indexed_docs_present_and_render(self):
        for f in dr.DOC_FILES:
            path = dr.GUIDE_DIR / f
            self.assertTrue(path.exists(), f"manca {f}")
            doc = dr.load_doc(dr.slug_for(f))
            self.assertNotIn("non e' ancora stato scritto", doc["html"])
            self.assertTrue(len(doc["html"]) > 200, f)
```
(rimuovi `GuideFilesRenderTests` del Task 5, sostituita da questa)

- [ ] **Step 3: Esegui i test**

Run: `python django_app\manage.py test django_app.security.tests.test_docs_render --settings=config.settings.test`
Expected: PASS (indice 13/13 senza voci rotte).

- [ ] **Step 4: Commit**

```bash
git add django_app/security/guide/ django_app/security/tests/test_docs_render.py
git commit -m "docs(security): documenti moduli (WatchGuard/Defender/Backup) + guida sviluppo; indice 13/13"
```

---

### Task 7: CHANGELOG, README e verifica finale

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: `CHANGELOG.md`** — sotto `## [Unreleased]`, aggiungi una voce che elenca i file toccati (docs_render.py, guide/*.md, doc_detail view/route/template, indici clickabili, _section_help nelle 9 sezioni, fix test-regola, README) e la descrizione: "Guida di configurazione SOC IT resa in-app (renderer Markdown interno) + help contestuale nella Configuration Studio".

- [ ] **Step 2: `README.md`** — nella riga 171 (modulo `security`), aggiungi che la documentazione operativa/guida di configurazione e' ora **integrata e renderizzata in-app** (`/soc/security/admin/docs/` → doc singoli), servita da `django_app/security/guide/`.

- [ ] **Step 3: Suite del modulo**

Run: `python django_app\manage.py test django_app.security --settings=config.settings.test --keepdb`
Expected: PASS (0 failure attribuibili a queste modifiche). Se compaiono 3 failure automazioni da `.env` mancante nel worktree, sono note e non regressive.

- [ ] **Step 4: `check`**

Run: `python django_app\manage.py check --settings=config.settings.test`
Expected: System check identified no issues.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(security): CHANGELOG + README per la guida SOC in-app"
```

---

## Self-Review (compilata dall'autore del piano)

- **Spec coverage:** §5.1 renderer→Task 1; §5.2 rendering in-app→Task 2+3; §5.3 rifiniture UX→Task 4; §7 13 doc→Task 5+6; §8 test→Task 1/2/3/4/5/6; §4 vincolo packager→Global Constraints + Task 6 nota; CHANGELOG/README→Task 7. Nessuna sezione scoperta.
- **Placeholder scan:** codice completo per renderer/view/route/template/partial/test; per i doc, outline dettagliati con fatti obbligatori (comandi/permessi/stati reali) — la prosa e' il deliverable, non un placeholder di codice.
- **Type consistency:** `load_doc`/`slug_for`/`filename_for`/`DOC_FILES`/`render_markdown`/`build_toc` usati coerentemente tra Task 1→2→5→6; `section_help`/`CONFIG_SECTION_HELP` coerenti Task 4; url name `security:doc_detail` coerente Task 2→3→4.

## Handoff
Vedi header: eseguire con executing-plans (inline) o subagent-driven-development, task per task, commit ad ogni task nel worktree `C:\Dev\pn-soc-guide`.
