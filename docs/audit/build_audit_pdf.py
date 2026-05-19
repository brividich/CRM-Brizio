"""Genera il PDF di audit unendo i report SEC-PREPROD-*_EVIDENCE.md.

Convertitore Markdown -> PDF minimale basato su reportlab (nessuna dipendenza
esterna oltre a reportlab, gia presente nel venv del progetto).

Uso:
    .venv\\Scripts\\python.exe docs\\audit\\build_audit_pdf.py

Sottoinsieme Markdown supportato: titoli #..####, regole ---, tabelle GFM,
liste puntate/numerate, citazioni >, blocchi di codice ```, **grassetto**,
`codice inline`, link [testo](url).
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

AUDIT_DIR = Path(__file__).resolve().parent
SOURCES = [
    AUDIT_DIR / "SEC-PREPROD-01_EVIDENCE.md",
    AUDIT_DIR / "SEC-PREPROD-02_EVIDENCE.md",
    AUDIT_DIR / "SEC-PREPROD-03_EVIDENCE.md",
]
OUTPUT = AUDIT_DIR / "SEC-PREPROD_AUDIT.pdf"

# Sostituzioni emoji/glifi non coperti dai font TrueType standard.
GLYPH_MAP = {
    "✅": "[OK]",     # check mark
    "⚠": "[!]",      # warning sign
    "❌": "[FAIL]",   # cross mark
    "ℹ": "[i]",      # information source
    "️": "",         # variation selector
    "→": "->",       # rightwards arrow
    "≡": "=",        # identical to
}


def _clean_glyphs(text: str) -> str:
    for src, dst in GLYPH_MAP.items():
        text = text.replace(src, dst)
    return text


# ---------------------------------------------------------------------------
# Font: usiamo Arial da Windows (copertura Latin completa). Fallback Helvetica.
# ---------------------------------------------------------------------------
FONT_NORMAL = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_MONO = "Courier"


def _register_fonts() -> None:
    global FONT_NORMAL, FONT_BOLD, FONT_MONO
    win_fonts = Path("C:/Windows/Fonts")
    candidates = {
        "AuditSans": win_fonts / "arial.ttf",
        "AuditSans-Bold": win_fonts / "arialbd.ttf",
        "AuditMono": win_fonts / "consola.ttf",
    }
    try:
        if candidates["AuditSans"].exists() and candidates["AuditSans-Bold"].exists():
            pdfmetrics.registerFont(TTFont("AuditSans", str(candidates["AuditSans"])))
            pdfmetrics.registerFont(TTFont("AuditSans-Bold", str(candidates["AuditSans-Bold"])))
            FONT_NORMAL = "AuditSans"
            FONT_BOLD = "AuditSans-Bold"
        if candidates["AuditMono"].exists():
            pdfmetrics.registerFont(TTFont("AuditMono", str(candidates["AuditMono"])))
            FONT_MONO = "AuditMono"
    except Exception as exc:  # pragma: no cover - best effort
        print(f"[warn] registrazione font fallita, uso Helvetica: {exc}")


# ---------------------------------------------------------------------------
# Inline markdown -> markup reportlab
# ---------------------------------------------------------------------------
def _inline(text: str) -> str:
    """Converte grassetto/codice/link in markup XML di reportlab."""
    text = _clean_glyphs(text)
    # Estrae i code span prima dell'escape, li reinserisce dopo.
    code_spans: list[str] = []

    def _stash_code(match: re.Match) -> str:
        code_spans.append(match.group(1))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _stash_code, text)
    text = html.escape(text, quote=False)
    # Grassetto **...**
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    # Link [testo](url) -> testo (url non navigabile in PDF, resta il testo)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
    # Reinserisce i code span
    for idx, raw in enumerate(code_spans):
        escaped = html.escape(raw, quote=False)
        text = text.replace(
            f"\x00CODE{idx}\x00",
            f'<font face="{FONT_MONO}" size="8.5">{escaped}</font>',
        )
    return text


# ---------------------------------------------------------------------------
# Stili
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body", fontName=FONT_NORMAL, fontSize=9.5, leading=13.5, spaceAfter=6,
    )
    return {
        "body": base,
        "h1": ParagraphStyle(
            "h1", parent=base, fontName=FONT_BOLD, fontSize=17, leading=21,
            spaceBefore=10, spaceAfter=10, textColor=colors.HexColor("#0b3d63"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=base, fontName=FONT_BOLD, fontSize=13, leading=17,
            spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#13507f"),
        ),
        "h3": ParagraphStyle(
            "h3", parent=base, fontName=FONT_BOLD, fontSize=11, leading=15,
            spaceBefore=9, spaceAfter=4, textColor=colors.HexColor("#1f6391"),
        ),
        "h4": ParagraphStyle(
            "h4", parent=base, fontName=FONT_BOLD, fontSize=10, leading=14,
            spaceBefore=7, spaceAfter=3, textColor=colors.HexColor("#33526b"),
        ),
        "quote": ParagraphStyle(
            "quote", parent=base, fontSize=9, leading=12.5,
            leftIndent=8, borderColor=colors.HexColor("#c8d4dd"),
            backColor=colors.HexColor("#f3f6f9"), borderPadding=5,
            textColor=colors.HexColor("#3a4a57"),
        ),
        "code": ParagraphStyle(
            "code", parent=base, fontName=FONT_MONO, fontSize=8.5, leading=11,
            backColor=colors.HexColor("#f3f3f3"), borderPadding=5,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "cell": ParagraphStyle(
            "cell", fontName=FONT_NORMAL, fontSize=8.3, leading=11,
        ),
        "cell_h": ParagraphStyle(
            "cell_h", fontName=FONT_BOLD, fontSize=8.3, leading=11,
            textColor=colors.white,
        ),
        "list": ParagraphStyle(
            "list", parent=base, spaceAfter=2,
        ),
    }


# ---------------------------------------------------------------------------
# Parser di una tabella GFM
# ---------------------------------------------------------------------------
def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_separator(line: str) -> bool:
    cells = _split_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells)


def _make_table(rows: list[list[str]], st: dict, content_width: float):
    header, *body = rows
    ncols = len(header)
    col_w = content_width / ncols
    data = [[Paragraph(_inline(c), st["cell_h"]) for c in header]]
    for row in body:
        cells = (row + [""] * ncols)[:ncols]
        data.append([Paragraph(_inline(c), st["cell"]) for c in cells])
    tbl = Table(data, colWidths=[col_w] * ncols, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#13507f")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#eef2f5")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b9c6d0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tbl


# ---------------------------------------------------------------------------
# Parser documento
# ---------------------------------------------------------------------------
def parse_markdown(text: str, st: dict, content_width: float) -> list:
    flow: list = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    para_buf: list[str] = []
    list_buf: list[str] = []
    list_ordered = False

    def flush_para():
        nonlocal para_buf
        if para_buf:
            flow.append(Paragraph(_inline(" ".join(para_buf)), st["body"]))
            para_buf = []

    def flush_list():
        nonlocal list_buf, list_ordered
        if list_buf:
            items = [
                ListItem(Paragraph(_inline(x), st["list"]), leftIndent=12)
                for x in list_buf
            ]
            flow.append(ListFlowable(
                items,
                bulletType="1" if list_ordered else "bullet",
                bulletFontName=FONT_NORMAL, bulletFontSize=8,
                leftIndent=14, spaceAfter=6,
            ))
            list_buf = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Blocco di codice ```
        if stripped.startswith("```"):
            flush_para()
            flush_list()
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # salta ``` di chiusura
            body = html.escape(_clean_glyphs("\n".join(code_lines)), quote=False)
            body = body.replace(" ", "&nbsp;").replace("\n", "<br/>")
            flow.append(Paragraph(body, st["code"]))
            flow.append(Spacer(1, 4))
            continue

        # Tabella
        if stripped.startswith("|") and i + 1 < n and _is_separator(lines[i + 1]):
            flush_para()
            flush_list()
            tbl_rows = [_split_row(line)]
            i += 2  # salta header + separatore
            while i < n and lines[i].strip().startswith("|"):
                tbl_rows.append(_split_row(lines[i]))
                i += 1
            flow.append(Spacer(1, 2))
            flow.append(_make_table(tbl_rows, st, content_width))
            flow.append(Spacer(1, 8))
            continue

        # Riga vuota
        if not stripped:
            flush_para()
            flush_list()
            i += 1
            continue

        # Regola orizzontale
        if re.fullmatch(r"-{3,}", stripped):
            flush_para()
            flush_list()
            flow.append(Spacer(1, 3))
            flow.append(HRFlowable(
                width="100%", thickness=0.6,
                color=colors.HexColor("#c2cdd6"), spaceAfter=6,
            ))
            i += 1
            continue

        # Titoli
        head = re.match(r"(#{1,6})\s+(.*)", stripped)
        if head:
            flush_para()
            flush_list()
            level = min(len(head.group(1)), 4)
            flow.append(Paragraph(_inline(head.group(2)), st[f"h{level}"]))
            i += 1
            continue

        # Citazione
        if stripped.startswith(">"):
            flush_para()
            flush_list()
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            flow.append(Paragraph(_inline(" ".join(quote_lines)), st["quote"]))
            flow.append(Spacer(1, 4))
            continue

        # Lista puntata
        bullet = re.match(r"[-*]\s+(.*)", stripped)
        if bullet:
            flush_para()
            if list_buf and list_ordered:
                flush_list()
            list_ordered = False
            list_buf.append(bullet.group(1))
            i += 1
            continue

        # Lista numerata
        num = re.match(r"\d+\.\s+(.*)", stripped)
        if num:
            flush_para()
            if list_buf and not list_ordered:
                flush_list()
            list_ordered = True
            list_buf.append(num.group(1))
            i += 1
            continue

        # Paragrafo
        flush_list()
        para_buf.append(stripped)
        i += 1

    flush_para()
    flush_list()
    return flow


# ---------------------------------------------------------------------------
# Header/footer
# ---------------------------------------------------------------------------
def _decorate(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT_NORMAL, 7.5)
    canvas.setFillColor(colors.HexColor("#8a98a4"))
    canvas.drawString(
        20 * mm, 8 * mm,
        "NOVICROM HUB - Security Pre-Prod Audit - Riservato / Interno",
    )
    canvas.drawRightString(
        A4[0] - 20 * mm, 8 * mm, f"Pag. {doc.page}",
    )
    canvas.setStrokeColor(colors.HexColor("#d4dce2"))
    canvas.line(20 * mm, 11 * mm, A4[0] - 20 * mm, 11 * mm)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    _register_fonts()
    st = _styles()

    margin = 20 * mm
    content_width = A4[0] - 2 * margin

    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title="NOVICROM HUB - Security Pre-Prod Audit",
        author="Application Security Engineer",
    )

    story: list = []
    # Copertina
    story.append(Spacer(1, 60 * mm))
    story.append(Paragraph("NOVICROM HUB", st["h1"]))
    story.append(Paragraph("Security Pre-Production Audit", st["h2"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Evidence Report consolidato &mdash; patch SEC-PREPROD-01, "
        "SEC-PREPROD-02, SEC-PREPROD-03", st["body"],
    ))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Branch <font face=\"%s\">pre-prod-security</font> &mdash; "
        "baseline <font face=\"%s\">f8005f8</font> &mdash; 2026-05-16"
        % (FONT_MONO, FONT_MONO), st["body"],
    ))
    story.append(Paragraph(
        "Classificazione: Interno &mdash; documento di evidenza remediation.",
        st["body"],
    ))
    story.append(PageBreak())

    for idx, src in enumerate(SOURCES):
        if not src.exists():
            print(f"[warn] sorgente mancante: {src.name}")
            continue
        text = src.read_text(encoding="utf-8")
        story.extend(parse_markdown(text, st, content_width))
        if idx < len(SOURCES) - 1:
            story.append(PageBreak())

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"[ok] PDF generato: {OUTPUT}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
