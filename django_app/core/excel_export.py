"""Util riusabile per esportare un "report a tabella" in .xlsx (openpyxl).

Stile NOVICROM HUB: intestazione navy con testo bianco, larghezze auto, riga
intestazione bloccata e autofiltro. Da usare nelle view per restituire un download
Excel coerente, riusando i dati gia' calcolati (ACL/filtri a carico della view).

Esempio::

    from core.excel_export import make_xlsx_response
    return make_xlsx_response(
        filename="conformita-dpi.xlsx",
        columns=["Categoria", "Stato"],
        rows=[["Guanti", "OK"], ["Scarpe", "Mancante"]],
        title="Conformità DPI — Mario Rossi",
    )
"""
from __future__ import annotations

from io import BytesIO

from django.http import HttpResponse

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_xlsx_bytes(*, columns, rows, sheet_title: str = "Dati", title: str | None = None) -> bytes:
    """Costruisce il file .xlsx (bytes). `columns`: intestazioni; `rows`: iterabile di righe."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    columns = list(columns)
    rows = [list(r) for r in rows]

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or "Dati")[:31]

    header_row = 1
    if title:
        ws.cell(row=1, column=1, value=str(title)).font = Font(bold=True, size=14, color="0C2545")
        header_row = 3

    header_fill = PatternFill("solid", fgColor="0C2545")
    header_font = Font(bold=True, color="FFFFFF")
    for c, col in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=c, value=str(col))
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center")

    r = header_row
    for row in rows:
        r += 1
        for c, val in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=val)

    # Larghezze auto (cap 60) sul contenuto.
    for c, col in enumerate(columns, start=1):
        maxlen = len(str(col))
        for row in rows:
            if c - 1 < len(row) and row[c - 1] is not None:
                maxlen = max(maxlen, len(str(row[c - 1])))
        ws.column_dimensions[get_column_letter(c)].width = min(60, max(10, maxlen + 2))

    ws.freeze_panes = ws.cell(row=header_row + 1, column=1)
    if rows and columns:
        last = get_column_letter(len(columns))
        ws.auto_filter.ref = f"A{header_row}:{last}{header_row + len(rows)}"

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_xlsx_response(*, filename: str, columns, rows, sheet_title: str = "Dati", title: str | None = None) -> HttpResponse:
    """Risposta HTTP di download .xlsx. La view resta responsabile di ACL/filtri."""
    data = build_xlsx_bytes(columns=columns, rows=rows, sheet_title=sheet_title, title=title)
    safe_name = (filename or "export.xlsx").replace('"', "")
    response = HttpResponse(data, content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{safe_name}"'
    response["Content-Length"] = str(len(data))
    return response
