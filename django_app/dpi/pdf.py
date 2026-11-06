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

from django.utils import timezone
from django.utils.html import escape
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle

from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document

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


def _e(value) -> str:
    """Testo utente sicuro dentro un Paragraph (che interpreta il markup)."""
    return escape(str(value if value not in (None, "") else "—"))


def _articoli_row(consegna: ConsegnaDPI, styles: dict) -> list:
    r = consegna.richiesta
    cell, right = styles["cell"], styles["cell_right"]
    dpi = f"<b>{_e(r.categoria.nome if r.categoria_id else None)}</b>"
    if r.tipo_dpi_id:
        dpi += f"<br/>{_e(r.tipo_dpi.nome)}"
    modello = "—"
    if r.modello_dpi_id:
        modello = _e(r.modello_dpi.nome)
        if r.modello_dpi.codice:
            modello += f'<br/><font color="#64748b">Cod. {_e(r.modello_dpi.codice)}</font>'
    scadenza = consegna.data_scadenza_stimata.strftime("%d-%m-%Y") if consegna.data_scadenza_stimata else "—"
    return [
        Paragraph(_e(r.numero), cell),
        Paragraph(dpi, cell),
        Paragraph(modello, cell),
        Paragraph(_e(r.taglia_dpi.valore if r.taglia_dpi_id else None), cell),
        Paragraph(str(r.quantita or 0), right),
        Paragraph(scadenza, cell),
    ]


def _articoli_table(consegne: Sequence[ConsegnaDPI], theme: PdfTheme, styles: dict) -> Table:
    head = styles["table_header"]
    header = [Paragraph(t, head) for t in ("Richiesta", "DPI", "Modello", "Taglia", "Q.tà", "Scadenza stimata")]
    rows = [header] + [_articoli_row(c, styles) for c in consegne]
    # 170 mm = la riga utile della pagina (A4, margini e padding del frame): il testo va a capo.
    table = data_table(rows, theme, col_widths=[24 * mm, 44 * mm, 50 * mm, 16 * mm, 12 * mm, 24 * mm])
    table.hAlign = "LEFT"
    return table


def _kv_table(rows: Sequence[tuple[str, str]], theme: PdfTheme, styles: dict) -> Table:
    """Etichetta -> valore su due colonne, compatto (i valori sono gia' sicuri)."""
    label, value = styles["cell"], styles["body"]
    data = [[Paragraph(f'<font color="#64748b">{k}</font>', label), Paragraph(v, value)] for k, v in rows]
    table = Table(data, colWidths=[36 * mm, 134 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, theme.c_border()),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _righe_dipendente(consegna: ConsegnaDPI) -> list[tuple[str, str]]:
    r = consegna.richiesta
    return [
        ("Nome", f"<b>{_e((r.richiedente_nome or '').upper() or None)}</b>"),
        ("Reparto", _e(r.richiedente_reparto)),
        ("Email", _e(r.richiedente_email)),
        ("ID anagrafica", _e(r.richiedente_legacy_id)),
    ]


def _righe_consegna(consegne: Sequence[ConsegnaDPI]) -> list[tuple[str, str]]:
    c0 = consegne[0]
    rows = [
        ("Data consegna", c0.data_consegna.strftime("%d-%m-%Y") if c0.data_consegna else "—"),
        ("Consegnato da", _e((c0.consegnato_da_nome or "").upper() or None)),
    ]
    if len(consegne) > 1:
        rows.append(("Articoli", str(len(consegne))))
    motivi = sorted({c.richiesta.motivazione.strip() for c in consegne if (c.richiesta.motivazione or "").strip()})
    if motivi:
        rows.append(("Motivazione", "<br/>".join(_e(m) for m in motivi)))
    note = sorted({c.note_consegna.strip() for c in consegne if (c.note_consegna or "").strip()})
    if note:
        rows.append(("Note", "<br/>".join(_e(n) for n in note)))
    return rows


def _ricevuta_flowables(consegna: ConsegnaDPI, theme: PdfTheme, styles: dict) -> list:
    """Come il dipendente ha confermato di aver ricevuto i DPI: firma al banco,
    conferma via mail (dipendente o responsabile) o firma su carta di questo modulo."""
    body = styles["body"]
    flow: list = [Paragraph("Ricevuta", styles["section"])]
    png_bytes = _decode_firma_data_uri(consegna.firma_immagine or "")
    if png_bytes:
        try:
            flow.append(Paragraph("Firmata al banco dal ricevente:", body))
            img = Image(io.BytesIO(png_bytes), width=60 * mm, height=22 * mm)
            img.hAlign = "LEFT"
            flow.append(img)
            return flow
        except Exception:
            logger.warning("Impossibile inserire la firma nel PDF", exc_info=True)
    conferma = getattr(consegna, "conferma", None)
    if conferma is not None:
        chi = conferma.get_destinatario_tipo_display().lower()
        if conferma.decisa_il:
            quando = timezone.localtime(conferma.decisa_il).strftime("%d-%m-%Y alle %H:%M")
            esito = "confermata" if conferma.stato == conferma.Stato.CONFERMATA else "CONTESTATA"
            testo = f"Ricevuta <b>{esito}</b> via mail il {quando} da {_e(conferma.decisa_da_email)} ({_e(chi)})."
            if conferma.nota:
                testo += f"<br/>Nota: {_e(conferma.nota)}"
        else:
            testo = f"Conferma di ricevuta richiesta via mail ({_e(chi)}): <b>in attesa</b>."
        flow.append(_kv_table([("Conferma via mail", testo)], theme, styles))
        if conferma.decisa_il:
            return flow
    elif consegna.confermata_badge_il:
        quando = timezone.localtime(consegna.confermata_badge_il).strftime("%d/%m/%Y %H:%M")
        flow.append(Paragraph(f"Ricevuta confermata dal dipendente con il proprio badge al banco il {quando}.", body))
        return flow
    elif consegna.firmato_ricevuta:
        flow.append(Paragraph("Ricevuta firmata su carta al momento della consegna.", body))
        return flow
    flow.append(Spacer(1, 4 * mm))
    flow.append(Paragraph("Firma del ricevente (se il modulo viene firmato su carta)", body))
    flow.append(Spacer(1, 10 * mm))
    flow.append(Paragraph("________________________________________", body))
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

    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    section_style = styles["section"]

    buf = io.BytesIO()
    doc = make_document(buf, title="Modulo consegna DPI")
    flow: list = []

    flow.append(Paragraph("Dipendente", section_style))
    flow.append(_kv_table(_righe_dipendente(consegne_list[0]), theme, styles))

    flow.append(Paragraph("Articoli consegnati", section_style))
    flow.append(_articoli_table(consegne_list, theme, styles))

    flow.append(Paragraph("Dettagli consegna", section_style))
    flow.append(_kv_table(_righe_consegna(consegne_list), theme, styles))

    # Firma e conferma sono della prima consegna: al banco le consegne della stessa
    # persona condividono firma e conferma via mail.
    flow.extend(_ricevuta_flowables(consegne_list[0], theme, styles))

    draw = header_footer_callback(theme, title="MODULO DI CONSEGNA DPI")
    doc.build(flow, onFirstPage=draw, onLaterPages=draw)
    return buf.getvalue()
