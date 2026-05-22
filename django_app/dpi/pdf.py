"""Generazione PDF dei moduli di consegna DPI.

Il PDF viene generato lato server con ``reportlab`` (Platypus) e archiviato
nello spazio documenti del dipendente (``anagrafica.DocumentoDipendente``)
con storage privato fuori webroot.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import Iterable, Sequence

from django.conf import settings
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .models import ConsegnaDPI


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _decode_firma_data_uri(data_uri: str) -> bytes | None:
    """Decodifica una firma serializzata come data URI base64.

    Formato atteso: ``data:image/png;base64,<base64>``. Ritorna i bytes
    PNG decodificati oppure None se il formato non è valido.
    """
    if not data_uri:
        return None
    try:
        head, _, payload = data_uri.partition(",")
        if "base64" not in head or not payload:
            return None
        return base64.b64decode(payload, validate=False)
    except Exception:
        logger.warning("Firma data URI non decodificabile", exc_info=True)
        return None


def _styles():
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleNH",
        parent=styles["Title"],
        fontSize=16,
        leading=20,
        spaceAfter=4 * mm,
    )
    subtitle = ParagraphStyle(
        "SubtitleNH",
        parent=styles["Heading3"],
        fontSize=11,
        textColor=colors.HexColor("#475569"),
        spaceAfter=4 * mm,
    )
    h2 = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=4 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=13)
    return title, subtitle, h2, body


def _articoli_row(consegna: ConsegnaDPI) -> list[str]:
    r = consegna.richiesta
    categoria = r.categoria.nome if r.categoria_id else "—"
    tipo = r.tipo_dpi.nome if r.tipo_dpi_id else "—"
    modello = r.modello_dpi.nome if r.modello_dpi_id else "—"
    taglia = r.taglia_dpi.valore if r.taglia_dpi_id else "—"
    scadenza = (
        consegna.data_scadenza_stimata.strftime("%d/%m/%Y")
        if consegna.data_scadenza_stimata else "—"
    )
    return [categoria, tipo, modello, taglia, str(r.quantita or 0), scadenza]


def _articoli_table(consegne: Sequence[ConsegnaDPI]) -> Table:
    header = [
        "Categoria",
        "Tipo",
        "Modello",
        "Taglia",
        "Q.tà",
        "Scadenza stimata",
    ]
    rows = [header] + [_articoli_row(c) for c in consegne]
    table = Table(rows, colWidths=[36 * mm, 32 * mm, 38 * mm, 18 * mm, 14 * mm, 32 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (4, 1), (4, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _info_dipendente_paragraphs(
    consegna: ConsegnaDPI, body_style: ParagraphStyle
) -> list[Paragraph]:
    r = consegna.richiesta
    rows = [
        ("Nome", r.richiedente_nome or "—"),
        ("ID anagrafica", str(r.richiedente_legacy_id or "—")),
        ("Reparto", r.richiedente_reparto or "—"),
        ("Email", r.richiedente_email or "—"),
    ]
    return [Paragraph(f"<b>{k}:</b> {v}", body_style) for k, v in rows]


def _info_consegna_paragraphs(
    consegna: ConsegnaDPI, body_style: ParagraphStyle
) -> list[Paragraph]:
    rows = [
        ("Data consegna", consegna.data_consegna.strftime("%d/%m/%Y") if consegna.data_consegna else "—"),
        ("Consegnato da", consegna.consegnato_da_nome or "—"),
        ("Firma ricevuta", "Sì" if consegna.firmato_ricevuta else "No"),
    ]
    items = [Paragraph(f"<b>{k}:</b> {v}", body_style) for k, v in rows]
    if consegna.note_consegna:
        items.append(Paragraph(f"<b>Note:</b> {consegna.note_consegna}", body_style))
    return items


def _firma_flowables(
    firma_data_uri: str, body_style: ParagraphStyle
) -> list:
    flow: list = [Paragraph("<b>Firma del ricevente</b>", body_style)]
    png_bytes = _decode_firma_data_uri(firma_data_uri)
    if png_bytes:
        try:
            img = Image(io.BytesIO(png_bytes), width=60 * mm, height=22 * mm)
            img.hAlign = "LEFT"
            flow.append(img)
            return flow
        except Exception:
            logger.warning("Impossibile inserire la firma nel PDF", exc_info=True)
    # placeholder se manca o non decodifica
    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph("________________________________________", body_style))
    return flow


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def render_modulo_consegna_dpi(consegna: ConsegnaDPI) -> bytes:
    """Genera il PDF del modulo di consegna DPI per una singola consegna.

    Ritorna i bytes del PDF (pronti per essere salvati o restituiti
    in ``HttpResponse``).
    """
    return render_modulo_consegna_dpi_multipla([consegna])


def render_modulo_consegna_dpi_multipla(consegne: Iterable[ConsegnaDPI]) -> bytes:
    """Genera un singolo PDF cumulativo per più consegne DPI.

    Tutte le consegne devono riferirsi allo stesso dipendente (i dati
    anagrafica sono presi dalla prima). Usato per archiviare il modulo
    di consegna iniziale all'ingresso del dipendente.
    """
    consegne_list = list(consegne)
    if not consegne_list:
        raise ValueError("render_modulo_consegna_dpi_multipla: lista consegne vuota")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title="Modulo consegna DPI",
        author=getattr(settings, "INSTANCE_NAME", "NOVICROM HUB"),
    )

    title_style, subtitle_style, section_style, body_style = _styles()
    flow: list = []

    flow.append(Paragraph("MODULO DI CONSEGNA DPI", title_style))
    instance_name = getattr(settings, "INSTANCE_NAME", "NOVICROM HUB")
    now = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    flow.append(Paragraph(f"{instance_name} — generato il {now}", subtitle_style))

    flow.append(Paragraph("Dipendente", section_style))
    flow.extend(_info_dipendente_paragraphs(consegne_list[0], body_style))

    flow.append(Paragraph("Articoli consegnati", section_style))
    flow.append(_articoli_table(consegne_list))

    flow.append(Paragraph("Dettagli consegna", section_style))
    if len(consegne_list) == 1:
        flow.extend(_info_consegna_paragraphs(consegne_list[0], body_style))
    else:
        # Cumulativo: i singoli dettagli sono già in tabella;
        # mostra solo data e operatore (presi dalla prima consegna).
        c0 = consegne_list[0]
        rows = [
            ("Data consegna", c0.data_consegna.strftime("%d/%m/%Y") if c0.data_consegna else "—"),
            ("Consegnato da", c0.consegnato_da_nome or "—"),
            ("Numero articoli", str(len(consegne_list))),
        ]
        flow.extend([Paragraph(f"<b>{k}:</b> {v}", body_style) for k, v in rows])

    flow.append(Spacer(1, 6 * mm))
    # La firma viene presa dalla prima consegna; nei moduli cumulativi
    # (consegne iniziali) la firma è normalmente differita e quindi vuota.
    flow.extend(_firma_flowables(consegne_list[0].firma_immagine or "", body_style))

    doc.build(flow)
    return buf.getvalue()
