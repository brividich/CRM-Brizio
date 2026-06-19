"""Renderer Markdown minimale e sicuro per le slide dei micro-corsi e-learning.

Scelta conservativa (NOVICROM HUB): niente nuove dipendenze (no ``markdown``/``bleach``)
sull'ambiente Windows/IIS. Il contenuto viene **prima** escapato (HTML-safe), poi si
applica un sottoinsieme controllato di Markdown. Così anche se un autore incolla HTML
o uno script, questo finisce come testo: nessun XSS.

Sottoinsieme supportato (sufficiente per ~10 slide):
- Titoli: ``#`` ``##`` ``###``
- Grassetto ``**testo**`` e corsivo ``*testo*``
- Codice inline `` `code` ``
- Liste puntate (``- `` / ``* ``) e numerate (``1. ``)
- Link ``[testo](https://…)`` — solo schemi http/https/mailto
- Paragrafi (riga vuota) e a-capo singolo (<br>)

Gli autori sono utenti interni con permesso di modifica formazione (ACL), ma il
modello resta fail-closed comunque.
"""
from __future__ import annotations

import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

# Link: solo schemi sicuri. Tutto il resto del testo è già escapato a monte.
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+|mailto:[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    """Applica le sostituzioni inline su una riga GIÀ escapata."""
    text = _CODE_RE.sub(r"<code>\1</code>", text)
    text = _BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    text = _LINK_RE.sub(r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', text)
    return text


def render_markdown(raw: str) -> str:
    """Rende il Markdown della slide in HTML sicuro (stringa già ``mark_safe``)."""
    if not raw:
        return mark_safe("")
    # 1) Escape totale: qualunque HTML/script diventa testo.
    safe = escape(raw).replace("\r\n", "\n").replace("\r", "\n")

    html_parts: list[str] = []
    list_buffer: list[str] = []
    list_type: str | None = None  # "ul" | "ol"
    para_buffer: list[str] = []

    def flush_list():
        nonlocal list_buffer, list_type
        if list_buffer:
            items = "".join(f"<li>{_inline(i)}</li>" for i in list_buffer)
            html_parts.append(f"<{list_type}>{items}</{list_type}>")
            list_buffer = []
            list_type = None

    def flush_para():
        nonlocal para_buffer
        if para_buffer:
            joined = "<br>".join(_inline(line) for line in para_buffer)
            html_parts.append(f"<p>{joined}</p>")
            para_buffer = []

    for line in safe.split("\n"):
        stripped = line.strip()

        if not stripped:                       # riga vuota → chiude blocchi
            flush_para()
            flush_list()
            continue

        # Titoli
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1)) + 1         # # → h2, ## → h3, ### → h4
            html_parts.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
            continue

        # Liste numerate
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            flush_para()
            if list_type and list_type != "ol":
                flush_list()
            list_type = "ol"
            list_buffer.append(m.group(1))
            continue

        # Liste puntate
        m = re.match(r"^[-*]\s+(.*)$", stripped)
        if m:
            flush_para()
            if list_type and list_type != "ul":
                flush_list()
            list_type = "ul"
            list_buffer.append(m.group(1))
            continue

        # Testo normale → paragrafo
        flush_list()
        para_buffer.append(stripped)

    flush_para()
    flush_list()
    return mark_safe("".join(html_parts))
