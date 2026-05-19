"""Convertitore Markdown -> PDF (sottoinsieme) basato su reportlab.

Gestisce: titoli (#, ##, ###), paragrafi, elenchi puntati/numerati, tabelle
pipe, citazioni (>), righe orizzontali, grassetto **...** e codice inline `...`.
Nessuna dipendenza esterna oltre a reportlab.

Uso:
    python tools/md_to_pdf.py <input.md> [output.pdf]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

# Caratteri non rappresentabili dai font standard -> equivalente ASCII.
_UNICODE_MAP = {
    "✅": "[OK]",   # check verde
    "⚠": "[!]",    # warning
    "❌": "[X]",    # croce rossa
    "☑": "[x]",    # checkbox
    "→": "->",     # freccia
    "≠": "!=",     # diverso
    "️": "",       # variation selector
}

COL_DARK = colors.HexColor("#1e3a5f")
COL_MID = colors.HexColor("#2d5a9b")
COL_ALT = colors.HexColor("#eef2f8")
COL_GRID = colors.HexColor("#c9d4e3")


def _sanitize(text: str) -> str:
    for src, dst in _UNICODE_MAP.items():
        text = text.replace(src, dst)
    return text.encode("cp1252", "replace").decode("cp1252")


def _inline(text: str) -> str:
    """Converte il markup inline Markdown in markup reportlab."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"`([^`]+)`", lambda m: f'<font face="Courier" size="8">{m.group(1)}</font>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    return _sanitize(text)


def _is_separator_row(cells: list[str]) -> bool:
    relevant = [c.strip() for c in cells if c.strip()]
    return bool(relevant) and all(re.fullmatch(r":?-{2,}:?", c) for c in relevant)


def parse_blocks(lines: list[str]) -> list[tuple]:
    blocks: list[tuple] = []
    para: list[str] = []
    i, n = 0, len(lines)

    def flush_para() -> None:
        if para:
            blocks.append(("p", " ".join(para)))
            para.clear()

    while i < n:
        raw = lines[i].rstrip("\n")
        s = raw.strip()

        if not s:
            flush_para()
            i += 1
            continue
        if s.startswith("### "):
            flush_para(); blocks.append(("h3", s[4:])); i += 1; continue
        if s.startswith("## "):
            flush_para(); blocks.append(("h2", s[3:])); i += 1; continue
        if s.startswith("# "):
            flush_para(); blocks.append(("h1", s[2:])); i += 1; continue
        if s in ("---", "***", "___"):
            flush_para(); blocks.append(("hr", None)); i += 1; continue
        if s.startswith("|") and s.endswith("|"):
            flush_para()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not _is_separator_row(cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue
        if s.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(("quote", " ".join(quote)))
            continue
        if s.startswith("- ") or s.startswith("* "):
            flush_para()
            items = []
            while i < n and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append(("ul", items))
            continue
        if re.match(r"\d+\.\s", s):
            flush_para()
            items = []
            while i < n and re.match(r"\d+\.\s", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            blocks.append(("ol", items))
            continue
        para.append(s)
        i += 1

    flush_para()
    return blocks


def build(md_path: Path, pdf_path: Path) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    blocks = parse_blocks(lines)

    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13, spaceAfter=5)
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=17, leading=21,
                         textColor=COL_DARK, spaceBefore=6, spaceAfter=8)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                        textColor=COL_DARK, spaceBefore=14, spaceAfter=4)
    h3 = ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14,
                        textColor=COL_MID, spaceBefore=9, spaceAfter=3)
    quote = ParagraphStyle("quote", fontName="Helvetica-Oblique", fontSize=9, leading=12,
                           textColor=colors.HexColor("#475569"), leftIndent=8,
                           spaceBefore=3, spaceAfter=6)
    cell = ParagraphStyle("cell", fontName="Helvetica", fontSize=7.6, leading=9.6)
    cell_head = ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=7.8,
                               leading=9.8, textColor=colors.white)
    li = ParagraphStyle("li", parent=body, spaceAfter=2)

    story: list = []
    for kind, payload in blocks:
        if kind == "h1":
            story.append(Paragraph(_inline(payload), h1))
        elif kind == "h2":
            story.append(Paragraph(_inline(payload), h2))
        elif kind == "h3":
            story.append(Paragraph(_inline(payload), h3))
        elif kind == "p":
            story.append(Paragraph(_inline(payload), body))
        elif kind == "quote":
            story.append(Paragraph(_inline(payload), quote))
        elif kind == "hr":
            story.append(Spacer(1, 2))
            story.append(HRFlowable(width="100%", thickness=0.6, color=COL_GRID))
            story.append(Spacer(1, 4))
        elif kind in ("ul", "ol"):
            items = [ListItem(Paragraph(_inline(t), li), leftIndent=12) for t in payload]
            story.append(ListFlowable(
                items, bulletType="bullet" if kind == "ul" else "1",
                bulletFontSize=7, leftIndent=14, bulletColor=COL_MID,
            ))
            story.append(Spacer(1, 4))
        elif kind == "table":
            ncols = max(len(r) for r in payload)
            data = []
            for r_idx, row in enumerate(payload):
                row = row + [""] * (ncols - len(row))
                style = cell_head if r_idx == 0 else cell
                data.append([Paragraph(_inline(c), style) for c in row])
            usable = A4[0] - 36 * mm
            if ncols == 2:
                widths = [usable * 0.30, usable * 0.70]
            else:
                widths = [usable / ncols] * ncols
            table = Table(data, colWidths=widths, repeatRows=1)
            ts = TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), COL_DARK),
                ("LINEBELOW", (0, 0), (-1, 0), 1, COL_MID),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, COL_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.25, COL_GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ])
            table.setStyle(ts)
            story.append(table)
            story.append(Spacer(1, 7))

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title=md_path.stem,
    )
    doc.build(story)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    md_path = Path(sys.argv[1]).resolve()
    if not md_path.exists():
        print(f"File non trovato: {md_path}")
        return 1
    pdf_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else md_path.with_suffix(".pdf")
    build(md_path, pdf_path)
    print(f"PDF generato: {pdf_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
