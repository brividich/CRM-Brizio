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
            # Schema non consentito: degrada al solo testo del label (nessun href).
            return stash(html.escape(label))
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
