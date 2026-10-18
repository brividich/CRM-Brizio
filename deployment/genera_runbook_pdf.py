"""Genera deployment/RUNBOOK_RIPRISTINO.pdf da docs/dr/RUNBOOK_RIPRISTINO.md.

Stessa libreria e palette di genera_guida_release_pdf.py (reportlab). Il PDF sta in
deployment/ perché finisce nel pacchetto di release e si copia sul NAS: il runbook deve
essere leggibile anche quando il server del portale non c'è più.

    python deployment/genera_runbook_pdf.py [--src docs/dr/RUNBOOK_RIPRISTINO.md] [--out deployment/RUNBOOK_RIPRISTINO.pdf]
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

BRAND = colors.HexColor("#1a56db")
BRAND_DARK = colors.HexColor("#1e429f")
GRAY100 = colors.HexColor("#f3f4f6")
GRAY200 = colors.HexColor("#e5e7eb")
GRAY600 = colors.HexColor("#4b5563")
GRAY800 = colors.HexColor("#1f2937")
CODE_BG = colors.HexColor("#0d1117")
CODE_FG = colors.HexColor("#c9d1d9")

ROOT = Path(__file__).resolve().parents[1]


def styles():
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13, textColor=GRAY800, alignment=TA_LEFT)
    return {
        "h1": ParagraphStyle("h1", **{**base, "fontName": "Helvetica-Bold", "fontSize": 18, "leading": 22, "textColor": BRAND_DARK, "spaceAfter": 6}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "Helvetica-Bold", "fontSize": 13, "leading": 17, "textColor": BRAND, "spaceBefore": 10, "spaceAfter": 4}),
        "h3": ParagraphStyle("h3", **{**base, "fontName": "Helvetica-Bold", "fontSize": 11, "leading": 14, "spaceBefore": 8, "spaceAfter": 3}),
        "p": ParagraphStyle("p", **{**base, "spaceAfter": 4}),
        "li": ParagraphStyle("li", **{**base, "leftIndent": 14, "bulletIndent": 4, "spaceAfter": 2}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 8.5, "leading": 11}),
        "cellh": ParagraphStyle("cellh", **{**base, "fontSize": 8.5, "leading": 11, "fontName": "Helvetica-Bold", "textColor": colors.white}),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=8, leading=10, textColor=CODE_FG, backColor=CODE_BG,
                               borderPadding=6, leftIndent=4, spaceBefore=4, spaceAfter=6),
    }


_KEEP = set("–—«»·’‘“”…×€")


def printable(text: str) -> str:
    """Toglie i simboli che Helvetica non ha (emoji, frecce): resterebbero spazi vuoti."""
    text = text.replace("→", ">").replace("≥", ">=").replace("≤", "<=")
    return "".join(c for c in text if ord(c) <= 0x24F or c in _KEEP).replace("  ", " ")


def inline(text: str) -> str:
    """Markdown in linea → markup reportlab (grassetto, codice, link come testo)."""
    text = printable(text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`"):
            out.append(f'<font face="Courier" size="8.5">{escape(part[1:-1])}</font>')
        else:
            seg = escape(part)
            seg = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", seg)
            out.append(seg)
    return "".join(out)


def table(rows: list[list[str]], s) -> Table:
    header, body = rows[0], rows[1:]
    data = [[Paragraph(inline(c), s["cellh"]) for c in header]] + [[Paragraph(inline(c), s["cell"]) for c in r] for r in body]
    t = Table(data, repeatRows=1, hAlign="LEFT", colWidths=[(A4[0] - 3.6 * cm) / len(header)] * len(header))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GRAY100]),
        ("GRID", (0, 0), (-1, -1), 0.4, GRAY200),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def build(src: Path, out: Path) -> None:
    s = styles()
    story = []
    lines = src.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            story.append(Preformatted("\n".join(buf), s["code"]))
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            story += [table(rows, s), Spacer(1, 6)]
            continue
        elif line.startswith("# "):
            story += [Paragraph(inline(line[2:]), s["h1"]), HRFlowable(width="100%", color=BRAND, thickness=1.2), Spacer(1, 4)]
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), s["h2"]))
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), s["h3"]))
        elif re.match(r"^\s*- \[ \] ", line):
            story.append(Paragraph(inline(re.sub(r"^\s*- \[ \] ", "", line)), s["li"], bulletText="[ ]"))
        elif re.match(r"^\s*- ", line):
            story.append(Paragraph(inline(re.sub(r"^\s*- ", "", line)), s["li"], bulletText="•"))
        elif re.match(r"^\s*\d+\. ", line):
            num = re.match(r"^\s*(\d+)\. ", line).group(1)
            story.append(Paragraph(inline(re.sub(r"^\s*\d+\. ", "", line)), s["li"], bulletText=f"{num}."))
        elif line.strip():
            story.append(Paragraph(inline(line), s["p"]))
        i += 1

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRAY600)
        canvas.drawString(1.8 * cm, 1.1 * cm, f"NOVICROM HUB · Runbook di ripristino · generato il {datetime.now():%d/%m/%Y}")
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"pag. {doc.page}")
        canvas.restoreState()

    out.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm,
                            bottomMargin=1.8 * cm, title="Runbook di ripristino — NOVICROM HUB", author="NOVICROM HUB")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "docs" / "dr" / "RUNBOOK_RIPRISTINO.md"))
    ap.add_argument("--out", default=str(ROOT / "deployment" / "RUNBOOK_RIPRISTINO.pdf"))
    a = ap.parse_args()
    build(Path(a.src), Path(a.out))
    print(f"Scritto {a.out}")
