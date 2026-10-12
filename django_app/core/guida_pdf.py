"""PDF delle guide d'uso dei moduli, dallo stesso contenuto della pagina guida.

Le sezioni hanno la forma usata da ``anomalie/guida.py``: ``{"id", "titolo",
"blocchi"}``, con blocchi ``("p", testo)``, ``("passi", [voci])`` (numerati),
``("ul", [voci])``, ``("nota", testo)`` e ``("def", [(termine, spiegazione)])``.
Il testo e' semplice: qui passa da ``escape()``.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape


def render_guida_pdf(*, titolo: str, sottotitolo: str, sezioni: list[dict],
                     generato_da: str = "", generato_il: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    navy = colors.HexColor("#1f3a5f")
    grey = colors.HexColor("#64748b")
    ss = getSampleStyleSheet()
    st_title = ParagraphStyle("gt", parent=ss["Title"], textColor=navy, fontSize=20, leading=24, spaceAfter=2)
    st_sub = ParagraphStyle("gs", parent=ss["Normal"], textColor=grey, fontSize=10.5, spaceAfter=4)
    st_meta = ParagraphStyle("gm", parent=ss["Normal"], textColor=grey, fontSize=8.5, spaceAfter=12)
    st_h = ParagraphStyle("gh", parent=ss["Heading2"], textColor=navy, fontSize=13, leading=16, spaceBefore=12, spaceAfter=5)
    st_p = ParagraphStyle("gp", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=5)
    st_toc = ParagraphStyle("gtoc", parent=st_p, spaceAfter=1)
    st_nota = ParagraphStyle("gn", parent=st_p, fontSize=9.5, textColor=colors.HexColor("#7c2d12"), spaceAfter=0)

    def p(text, style=st_p):
        return Paragraph(escape(str(text)), style)

    def elenco(voci, numerato):
        items = [ListItem(p(voce), leftIndent=14) for voce in voci]
        if numerato:
            return ListFlowable(items, bulletType="1", leftIndent=14, bulletFontSize=9.5, spaceAfter=5)
        return ListFlowable(items, bulletType="bullet", start="•", leftIndent=14, bulletFontSize=8, spaceAfter=5)

    story = [Paragraph(escape(titolo), st_title), Paragraph(escape(sottotitolo), st_sub)]
    meta = " · ".join(x for x in [f"Generata il {generato_il}" if generato_il else "",
                                  f"da {generato_da}" if generato_da else ""] if x)
    if meta:
        story.append(Paragraph(escape(meta), st_meta))
    story.append(Paragraph("<b>Indice</b>", st_p))
    for i, sez in enumerate(sezioni, 1):
        story.append(p(f"{i}. {sez['titolo']}", st_toc))
    story.append(Spacer(1, 6))

    for i, sez in enumerate(sezioni, 1):
        parts = [Paragraph(escape(f"{i}. {sez['titolo']}"), st_h)]
        for kind, content in sez["blocchi"]:
            if kind == "p":
                parts.append(p(content))
            elif kind in ("ul", "passi"):
                parts.append(elenco(content, numerato=kind == "passi"))
            elif kind == "def":
                for term, desc in content:
                    parts.append(Paragraph(f"<b>{escape(term)}</b> — {escape(desc)}", st_p))
            elif kind == "nota":
                box = Table([[p(content, st_nota)]], colWidths=[174 * mm])
                box.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7ed")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#fdba74")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]))
                parts += [Spacer(1, 3), box, Spacer(1, 5)]
        story.append(KeepTogether(parts[:2]))
        story.extend(parts[2:])

    def _decor(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setStrokeColor(navy)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, h - 12 * mm, w - 18 * mm, h - 12 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(navy)
        canvas.drawString(18 * mm, h - 10.5 * mm, titolo)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 18 * mm, h - 10.5 * mm, "Guida d'uso")
        canvas.setFillColor(grey)
        canvas.drawString(18 * mm, 10 * mm, "NOVICROM HUB")
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=17 * mm,
        title=f"{titolo} - Guida d'uso", author="NOVICROM HUB", subject=f"Guida d'uso: {titolo}",
    )
    doc.build(story, onFirstPage=_decor, onLaterPages=_decor)
    return buf.getvalue()
