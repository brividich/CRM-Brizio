from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, Callable, Iterable

from django.http import HttpResponse
from django.utils import timezone


ExportColumn = tuple[str, str | Callable[[Any], Any]]


def _resolve_value(row: Any, accessor: str | Callable[[Any], Any]) -> Any:
    if callable(accessor):
        return accessor(row)
    value: Any = row
    for part in str(accessor).split("__"):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
        if callable(value):
            value = value()
        if value is None:
            return ""
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.strftime("%d-%m-%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d-%m-%Y")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (dict, list, tuple, set)):
        return str(value)
    return str(value)


def export_rows_response(
    *,
    rows: Iterable[Any],
    columns: Iterable[ExportColumn],
    filename: str,
    fmt: str = "csv",
) -> HttpResponse:
    columns = list(columns)
    fmt = (fmt or "csv").strip().lower()
    stem = filename.rsplit(".", 1)[0]

    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        # Sanificazione formula injection centralizzata in core.excel_export:
        # `ws.append` scriverebbe come formula viva qualunque stringa che inizia con "=".
        from core.excel_export import append_row

        wb = Workbook()
        ws = wb.active
        ws.title = "Export"
        append_row(ws, [label for label, _accessor in columns])
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            append_row(
                ws,
                [_stringify(_resolve_value(row, accessor)) for _label, accessor in columns],
            )
        for col in ws.columns:
            max_len = max(len(_stringify(cell.value)) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 48)
        output = BytesIO()
        wb.save(output)
        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{stem}.xlsx"'
        return response

    # Anche il CSV va sanificato: Excel valuta le formule pure aprendo un .csv.
    from core.csv_export import CSV_CONTENT_TYPE, safe_csv_writer

    response = HttpResponse(content_type=CSV_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{stem}.csv"'
    response.write("\ufeff")
    writer = safe_csv_writer(response)
    writer.writerow([label for label, _accessor in columns])
    for row in rows:
        writer.writerow([_stringify(_resolve_value(row, accessor)) for _label, accessor in columns])
    return response


class ExportMixin:
    export_filename = "export"
    export_columns: tuple[ExportColumn, ...] = ()

    def get_export_filename(self) -> str:
        return self.export_filename

    def get_export_columns(self) -> Iterable[ExportColumn]:
        return self.export_columns

    def get_export_format(self, request) -> str:
        return (request.GET.get("export") or request.GET.get("format") or "csv").strip().lower()

    def build_export_response(self, request, rows: Iterable[Any]) -> HttpResponse:
        return export_rows_response(
            rows=rows,
            columns=self.get_export_columns(),
            filename=self.get_export_filename(),
            fmt=self.get_export_format(request),
        )
