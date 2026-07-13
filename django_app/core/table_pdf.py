"""Render di una tabella (headers + rows) in PDF col template HUB.

Promosso da ``assets/views.py::_report_table_pdf`` per essere riusato da tutti i
moduli (anagrafica, assets, ...). Le decisioni grafiche vengono dal branding via
``core.pdf.PdfTheme``.
"""
from __future__ import annotations

import io
from html import escape

from django.utils import timezone
from reportlab.platypus import Paragraph

from core.pdf import (
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
)


def _cell_text(value) -> str:
    """Normalizza un valore di cella come faceva il vecchio _coalesce_str/_clean_string."""
    return "" if value is None else str(value).strip()


def render_table_pdf(*, title: str, headers: list, rows: list, subtitle: str = "") -> bytes:
    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = io.BytesIO()
    doc = make_document(buf, title=title, landscape=True)
    elements: list = []

    if not rows:
        elements.append(Paragraph("Nessun record.", styles["body"]))
    else:
        page_w = doc.pagesize[0] - doc.leftMargin - doc.rightMargin
        col_w = page_w / max(len(headers), 1)
        table_rows = [
            [Paragraph(escape(str(header)), styles["table_header"]) for header in headers],
            *[
                [
                    Paragraph(escape(_cell_text(value)).replace("\n", "<br/>"), styles["cell"])
                    for value in row
                ]
                for row in rows
            ],
        ]
        elements.append(
            data_table(
                table_rows,
                theme,
                col_widths=[col_w] * len(headers),
                repeat_rows=1,
                extra_style=[
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            )
        )

    if not subtitle:
        subtitle = f"Generato il {timezone.localdate().strftime('%d-%m-%Y')}"
    draw = header_footer_callback(theme, title=title.upper(), subtitle=subtitle)
    doc.build(elements, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
