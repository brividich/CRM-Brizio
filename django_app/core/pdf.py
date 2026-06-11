"""Template PDF unico per i report runtime del portale.

Questo modulo centralizza il *layout grafico* dei PDF generati lato server con
``reportlab`` (Platypus): palette, intestazione con logo/monogramma, piè di
pagina con paginazione, stili tipografici e helper per tabelle.

Le scelte grafiche (logo, nome portale, colori) provengono dal branding del
portale (:func:`core.branding.get_portal_branding`), modificabile dall'area
impostazioni senza toccare il codice. La struttura (font, margini, spaziature)
è invece definita qui, in un unico posto, così che tutti i report del portale
condividano la stessa veste.

Esempio d'uso minimale::

    from io import BytesIO
    from core.pdf import PdfTheme, build_styles, make_document, header_footer_callback

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buf = BytesIO()
    doc = make_document(buf, title="Mio report")
    story = [styles["title"] and Paragraph("Contenuto", styles["body"])]
    draw = header_footer_callback(theme, title="MIO REPORT", subtitle="sottotitolo")
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    pdf_bytes = buf.getvalue()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape as _landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Table, TableStyle

from core.branding import _mix_hex_color, get_portal_branding


logger = logging.getLogger(__name__)


# Estensioni raster gestite nativamente da reportlab per l'header.
# SVG/webp non sono supportate: in quei casi si ricade sul monogramma.
_RASTER_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg"}

# Grigi standard condivisi (prima ripetuti inline in ogni generatore).
_TEXT = "#1e293b"
_MUTED = "#64748b"
_LABEL = "#94a3b8"
_BORDER = "#e2e8f0"
_ROW_ALT = "#f8fafc"


# ---------------------------------------------------------------------------
# Risoluzione logo
# ---------------------------------------------------------------------------

def _resolve_logo_path(brand_logo_full: str) -> str | None:
    """Ricava il path su disco di un logo ``/media/...`` per reportlab.

    Ritorna il path assoluto solo se il file esiste ed è in un formato raster
    gestito da reportlab (``.png/.jpg/.jpeg``). Per SVG/webp, URL esterni,
    valori vuoti o file mancanti ritorna ``None`` (l'header userà il
    monogramma testuale).
    """
    cleaned = str(brand_logo_full or "").split("?")[0].strip()
    if not cleaned or not cleaned.startswith("/media/"):
        return None
    if os.path.splitext(cleaned)[1].lower() not in _RASTER_LOGO_EXTENSIONS:
        return None
    relative = cleaned[len("/media/"):]
    try:
        path = os.path.join(str(settings.MEDIA_ROOT), *relative.split("/"))
    except Exception:
        return None
    return path if os.path.isfile(path) else None


# ---------------------------------------------------------------------------
# Palette / tema
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PdfTheme:
    """Palette e metadati grafici condivisi dai PDF del portale."""

    primary: str
    primary_mid: str
    accent: str
    accent_light: str
    text: str
    muted: str
    label: str
    border: str
    row_alt: str
    portal_name: str
    monogram: str
    logo_path: str | None

    @classmethod
    def from_branding(cls) -> "PdfTheme":
        """Costruisce il tema dal branding portale (una sola query)."""
        b = get_portal_branding()
        portal_name = (b.portal_name or "").strip() or getattr(
            settings, "INSTANCE_NAME", "NOVICROM HUB"
        )
        return cls(
            primary=b.brand_primary_color,
            primary_mid=b.brand_primary_mid_color,
            accent=b.brand_accent_color,
            accent_light=b.brand_accent_light_color,
            text=_TEXT,
            muted=_MUTED,
            label=_LABEL,
            border=_BORDER,
            row_alt=_ROW_ALT,
            portal_name=portal_name,
            monogram=b.monogram,
            logo_path=_resolve_logo_path(b.brand_logo_full),
        )

    # Scorciatoie a ``colors.HexColor`` per i punti che lavorano con reportlab.
    def c_primary(self):
        return colors.HexColor(self.primary)

    def c_primary_mid(self):
        return colors.HexColor(self.primary_mid)

    def c_accent(self):
        return colors.HexColor(self.accent)

    def c_text(self):
        return colors.HexColor(self.text)

    def c_muted(self):
        return colors.HexColor(self.muted)

    def c_label(self):
        return colors.HexColor(self.label)

    def c_border(self):
        return colors.HexColor(self.border)

    def c_row_alt(self):
        return colors.HexColor(self.row_alt)


# ---------------------------------------------------------------------------
# Stili tipografici
# ---------------------------------------------------------------------------

def build_styles(theme: PdfTheme) -> dict[str, ParagraphStyle]:
    """Stylesheet condiviso dai report del portale.

    Sostituisce gli stili oggi duplicati inline nei singoli generatori.
    """
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "nhTitle", parent=base["Title"],
            fontSize=16, leading=20, spaceAfter=4 * mm,
            textColor=theme.c_text(),
        ),
        "subtitle": ParagraphStyle(
            "nhSubtitle", parent=base["Heading3"],
            fontSize=11, textColor=theme.c_muted(), spaceAfter=4 * mm,
        ),
        "section": ParagraphStyle(
            "nhSection", parent=base["Normal"],
            fontSize=10, fontName="Helvetica-Bold",
            textColor=theme.c_primary(), spaceBefore=4 * mm, spaceAfter=2 * mm,
        ),
        "label": ParagraphStyle(
            "nhLabel", parent=base["Normal"],
            fontSize=8, fontName="Helvetica-Bold",
            textColor=theme.c_label(), spaceAfter=1,
        ),
        "value": ParagraphStyle(
            "nhValue", parent=base["Normal"],
            fontSize=10, textColor=theme.c_text(), spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "nhBody", parent=base["BodyText"],
            fontSize=9, leading=13, textColor=theme.c_text(),
        ),
        "cell": ParagraphStyle(
            "nhCell", parent=base["Normal"],
            fontSize=8, leading=11, textColor=theme.c_text(), wordWrap="CJK",
        ),
        "cell_right": ParagraphStyle(
            "nhCellRight", parent=base["Normal"],
            fontSize=8, leading=11, textColor=theme.c_text(),
            wordWrap="CJK", alignment=2,
        ),
        "table_header": ParagraphStyle(
            "nhTableHeader", parent=base["Normal"],
            fontSize=8, leading=10, fontName="Helvetica-Bold",
            textColor=colors.white, alignment=1,
        ),
    }


# ---------------------------------------------------------------------------
# Documento
# ---------------------------------------------------------------------------

# Spazio riservato nel margine superiore/inferiore per header e footer
# disegnati su canvas dal callback.
HEADER_HEIGHT = 26 * mm
FOOTER_HEIGHT = 14 * mm


def make_document(
    buffer,
    *,
    title: str,
    landscape: bool = False,
    left_margin: float = 18 * mm,
    right_margin: float = 18 * mm,
    top_margin: float | None = None,
    bottom_margin: float | None = None,
) -> SimpleDocTemplate:
    """Factory di ``SimpleDocTemplate`` con margini coerenti.

    I margini ``top``/``bottom`` predefiniti riservano spazio all'header e al
    footer disegnati da :func:`header_footer_callback`. Possono essere
    sovrascritti dai chiamanti che disegnano decorazioni aggiuntive (es. la
    legenda RENTRI).
    """
    pagesize = _landscape(A4) if landscape else A4
    return SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=HEADER_HEIGHT if top_margin is None else top_margin,
        bottomMargin=FOOTER_HEIGHT if bottom_margin is None else bottom_margin,
        title=title,
        author=getattr(settings, "INSTANCE_NAME", "NOVICROM HUB"),
    )


def header_footer_callback(theme: PdfTheme, *, title: str, subtitle: str = ""):
    """Ritorna un callback ``onPage`` che disegna header e footer standard.

    Header: logo (se raster disponibile) o monogramma in box ``theme.primary``,
    titolo + sottotitolo a fianco, nome portale e data/ora a destra.
    Footer: linea + nome portale a sinistra, ``Pagina N`` a destra.
    """
    now_str = timezone.localtime().strftime("%d-%m-%Y %H:%M")

    def _draw(canv, doc):
        canv.saveState()
        page_w, page_h = doc.pagesize
        left = doc.leftMargin
        right = page_w - doc.rightMargin

        # --- Header -------------------------------------------------------
        box = 12 * mm
        box_top = page_h - 12 * mm
        box_y = box_top - box
        drawn_logo = False
        if theme.logo_path:
            try:
                canv.drawImage(
                    theme.logo_path, left, box_y, width=box, height=box,
                    preserveAspectRatio=True, mask="auto", anchor="sw",
                )
                drawn_logo = True
            except Exception:
                logger.warning("Logo PDF non disegnabile: %s", theme.logo_path, exc_info=True)
        if not drawn_logo:
            canv.setFillColor(theme.c_primary())
            canv.roundRect(left, box_y, box, box, 2 * mm, fill=1, stroke=0)
            canv.setFillColor(colors.white)
            canv.setFont("Helvetica-Bold", 11)
            canv.drawCentredString(left + box / 2, box_y + box / 2 - 4, theme.monogram)

        text_x = left + box + 5 * mm
        canv.setFillColor(theme.c_text())
        canv.setFont("Helvetica-Bold", 14)
        canv.drawString(text_x, box_top - 5 * mm, title)
        if subtitle:
            canv.setFillColor(theme.c_muted())
            canv.setFont("Helvetica", 9)
            canv.drawString(text_x, box_top - 9.5 * mm, subtitle)

        canv.setFillColor(theme.c_muted())
        canv.setFont("Helvetica-Bold", 9)
        canv.drawRightString(right, box_top - 5 * mm, theme.portal_name)
        canv.setFont("Helvetica", 8)
        canv.drawRightString(right, box_top - 9.5 * mm, now_str)

        # linea accent sotto l'header
        canv.setStrokeColor(theme.c_primary())
        canv.setLineWidth(1.2)
        canv.line(left, box_y - 2.5 * mm, right, box_y - 2.5 * mm)

        # --- Footer -------------------------------------------------------
        fy = FOOTER_HEIGHT - 4 * mm
        canv.setStrokeColor(theme.c_border())
        canv.setLineWidth(0.4)
        canv.line(left, fy + 3 * mm, right, fy + 3 * mm)
        canv.setFillColor(theme.c_muted())
        canv.setFont("Helvetica", 7.5)
        canv.drawString(left, fy, theme.portal_name)
        canv.drawRightString(right, fy, f"Pagina {doc.page}")

        canv.restoreState()

    return _draw


# ---------------------------------------------------------------------------
# Helper contenuto
# ---------------------------------------------------------------------------

def section_heading(text: str, theme: PdfTheme, styles: dict | None = None) -> list:
    """Titolo di sezione + linea divisoria (pattern ripetuto nei report)."""
    styles = styles or build_styles(theme)
    return [
        Paragraph(text, styles["section"]),
        HRFlowable(width="100%", thickness=1, color=theme.c_border(), spaceAfter=6),
    ]


def data_table(
    rows: list,
    theme: PdfTheme,
    *,
    col_widths=None,
    header: bool = True,
    repeat_rows: int = 0,
    extra_style: list | None = None,
) -> Table:
    """Tabella dati con stile standard (header colorato + zebra + griglia).

    ``rows`` è una lista di righe già pronte (stringhe o ``Paragraph``). Se
    ``header`` è ``True`` la prima riga è trattata come intestazione su sfondo
    ``theme.primary``. ``extra_style`` permette override locali (es. colori di
    dominio RENTRI per le singole celle).
    """
    table = Table(rows, colWidths=col_widths, repeatRows=repeat_rows or (1 if header else 0))
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, theme.c_border()),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), theme.c_primary()),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, theme.c_row_alt()]),
        ]
    else:
        style.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, theme.c_row_alt()]))
    if extra_style:
        style += extra_style
    table.setStyle(TableStyle(style))
    return table
