"""Generazione del report PDF riepilogativo di un OP e delle sue anomalie.

Il report a video (``anomalie:anomalie_report_segnalazione``) è un foglio HTML
stampabile e personalizzabile. Per una copia ordinata e archiviabile serve però
un PDF reale: questo modulo lo genera lato server con ``reportlab`` riusando il
tema PDF condiviso del portale (:mod:`core.pdf`), così la veste resta coerente
con gli altri report (attestati formazione, RENTRI, ecc.).

Punto d'ingresso unico: :func:`build_op_report_pdf_bytes`, che riceve lo stesso
contesto già costruito dalla view HTML (``op``, ``report``, ``anomalie``) e
ritorna i ``bytes`` del PDF. L'incorporamento delle immagini allegate è
opzionale e degrada in sicurezza: se un file non è leggibile o non è
un'immagine valida viene semplicemente saltato.
"""
from __future__ import annotations

import logging
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, Spacer, Table, TableStyle

from core.pdf import (
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
    section_heading,
)

logger = logging.getLogger(__name__)

# Larghezza utile del corpo pagina (A4 verticale, margini 18mm per lato).
_CONTENT_WIDTH = 174 * mm
_MAX_IMAGES_PER_ANOMALIA = 3
_THUMB_MAX_W = 52 * mm
_THUMB_MAX_H = 40 * mm


def _esc(value) -> str:
    return escape(str(value if value is not None else "").strip())


def _flag(value) -> str:
    return "Sì" if value else "No"


def build_op_report_pdf_bytes(
    op: dict,
    report: dict,
    anomalie: list[dict],
    *,
    attachment_path_resolver=None,
) -> bytes:
    """Costruisce il PDF del report OP e ritorna i suoi ``bytes``.

    ``op``/``report``/``anomalie`` hanno la stessa forma del contesto della view
    HTML. ``attachment_path_resolver`` è un callable ``(local_id, file_id) ->
    path`` usato per incorporare le immagini; se assente, niente immagini.
    """
    op = op or {}
    report = report or {}
    anomalie = anomalie or []

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)

    buf = BytesIO()
    op_label = _esc(op.get("id") or op.get("item_id") or "OP")
    doc = make_document(buf, title=f"Report OP {op.get('id') or ''}".strip())

    story: list = []
    story += _summary_section(op, styles, theme)
    story.append(Spacer(1, 4 * mm))
    story.append(_metrics_band(report, styles, theme))
    story.append(Spacer(1, 5 * mm))
    story += _anomalie_overview(anomalie, styles, theme)
    story += _anomalie_detail(anomalie, styles, theme, attachment_path_resolver)

    draw = header_footer_callback(
        theme,
        title="REPORT SEGNALAZIONE OP",
        subtitle=op.get("id") or op.get("item_id") or "",
    )
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sezioni
# ---------------------------------------------------------------------------

def _summary_section(op: dict, styles, theme) -> list:
    def lbl(text):
        return Paragraph(_esc(text), styles["label"])

    def val(text):
        return Paragraph(_esc(text) or "—", styles["value"])

    rows = [
        [lbl("OP"), val(op.get("id")), lbl("P/N"), val(op.get("pn"))],
        [lbl("Capocommessa"), val(op.get("capo")), lbl("CAR / Incaricato"), val(op.get("car"))],
        [lbl("Stato"), val(op.get("stato")), lbl("Item ID"), val(op.get("item_id"))],
        [lbl("Creato"), val(op.get("created_datetime")), lbl("Aggiornato"), val(op.get("modified_datetime"))],
    ]
    info = str(op.get("info") or "").strip()
    if info:
        rows.append([lbl("Info"), Paragraph(_esc(info), styles["value"]), "", ""])

    table = Table(rows, colWidths=[30 * mm, 57 * mm, 30 * mm, 57 * mm])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if info:
        # L'ultima riga "Info" occupa l'intera larghezza per il valore.
        style.append(("SPAN", (1, len(rows) - 1), (3, len(rows) - 1)))
    table.setStyle(TableStyle(style))
    return section_heading("Riepilogo OP", theme, styles) + [table]


def _metric_cell(value, label, styles, theme, accent=False):
    color = theme.accent if accent else theme.primary
    num = Paragraph(
        f'<font color="{color}" size="18"><b>{_esc(value)}</b></font>',
        styles["value"],
    )
    cap = Paragraph(_esc(label).upper(), styles["label"])
    inner = Table([[num], [cap]], colWidths=[(_CONTENT_WIDTH / 4) - 4 * mm])
    inner.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return inner


def _metrics_band(report: dict, styles, theme) -> Table:
    cells = [
        _metric_cell(report.get("anomalie_totali", 0), "Totali", styles, theme),
        _metric_cell(report.get("anomalie_aperte", 0), "Aperte", styles, theme, accent=True),
        _metric_cell(report.get("anomalie_chiuse", 0), "Chiuse", styles, theme),
        _metric_cell(report.get("allegati_totali", 0), "Allegati", styles, theme),
    ]
    band = Table([cells], colWidths=[_CONTENT_WIDTH / 4] * 4)
    band.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, theme.c_border()),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, theme.c_border()),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), theme.c_row_alt()),
    ]))
    return band


def _anomalie_overview(anomalie: list[dict], styles, theme) -> list:
    head = [
        Paragraph("S/N", styles["table_header"]),
        Paragraph("Descrizione", styles["table_header"]),
        Paragraph("Avanzamento", styles["table_header"]),
        Paragraph("RDC", styles["table_header"]),
        Paragraph("Stato", styles["table_header"]),
    ]
    rows = [head]
    for a in anomalie:
        rows.append([
            Paragraph(_esc(a.get("seriale")) or "—", styles["cell"]),
            Paragraph(_esc(a.get("descrizione")) or "—", styles["cell"]),
            Paragraph(_esc(a.get("avanzamento")) or "—", styles["cell"]),
            Paragraph(_esc(a.get("numero_rdc")) or "—", styles["cell"]),
            Paragraph("Chiusa" if a.get("is_closed") else "Aperta", styles["cell"]),
        ])

    out = section_heading(f"Anomalie ({len(anomalie)})", theme, styles)
    if len(rows) == 1:
        out.append(Paragraph("Nessuna anomalia registrata per questo OP.", styles["body"]))
        return out
    table = data_table(
        rows, theme,
        col_widths=[22 * mm, 78 * mm, 32 * mm, 20 * mm, 22 * mm],
        header=True, repeat_rows=1,
    )
    out.append(table)
    return out


def _anomalie_detail(anomalie: list[dict], styles, theme, resolver) -> list:
    if not anomalie:
        return []
    out: list = [Spacer(1, 5 * mm)]
    out += section_heading("Dettaglio anomalie", theme, styles)
    for a in anomalie:
        block: list = []
        titolo = f"S/N {_esc(a.get('seriale')) or '—'}"
        stato = "Chiusa" if a.get("is_closed") else "Aperta"
        block.append(Paragraph(
            f'<b>{titolo}</b> &nbsp;<font color="{theme.muted}" size="8">[{stato}]</font>',
            styles["value"],
        ))
        if a.get("descrizione"):
            block.append(Paragraph(_esc(a.get("descrizione")), styles["body"]))
        if a.get("note_capocommessa"):
            block.append(Paragraph(
                f'<font color="{theme.label}"><b>Note: </b></font>{_esc(a.get("note_capocommessa"))}',
                styles["body"],
            ))
        flags = (
            f"RDC: {_flag(a.get('aprire_rdc_bool'))}"
            f" · Segnala cliente: {_flag(a.get('segnalare_cliente_bool'))}"
            f" · Pezzo recuperato: {_flag(a.get('pezzo_recuperato_bool'))}"
        )
        block.append(Paragraph(_esc(flags), styles["label"]))

        thumbs = _image_thumbs(a, resolver)
        if thumbs:
            block.append(Spacer(1, 2 * mm))
            block.append(thumbs)
        block.append(Spacer(1, 4 * mm))
        out.append(KeepTogether(block))
    return out


def _image_thumbs(anomalia: dict, resolver):
    if resolver is None:
        return None
    local_id = anomalia.get("local_id")
    if local_id is None:
        return None
    images = [
        att for att in (anomalia.get("attachments") or [])
        if att.get("is_image")
    ][:_MAX_IMAGES_PER_ANOMALIA]
    if not images:
        return None

    cells = []
    for att in images:
        try:
            path = resolver(int(local_id), str(att.get("file_id") or ""))
        except Exception:
            path = None
        if not path:
            continue
        img = _scaled_image(str(path))
        if img is not None:
            cells.append(img)
    if not cells:
        return None
    table = Table([cells], colWidths=[_THUMB_MAX_W + 4 * mm] * len(cells))
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return table


def _scaled_image(path: str):
    try:
        reader = ImageReader(path)
        iw, ih = reader.getSize()
        if not iw or not ih:
            return None
        ratio = min(_THUMB_MAX_W / iw, _THUMB_MAX_H / ih)
        return Image(path, width=iw * ratio, height=ih * ratio)
    except Exception:
        logger.debug("Report PDF: immagine non incorporabile: %s", path, exc_info=True)
        return None
