"""PDF «Personale presente in azienda» (sostituisce CN-PRESENZE.pdf dello script Solari).

Stesso impianto del vecchio report: logo, titolo, ora di aggiornamento, tabella
TURNO · MATRICOLA · COGNOME · NOME · INCARICO SICUREZZA, totale in fondo. Senza
l'ora di entrata. Usato dal pulsante «PDF» della lista, dalla stampa dell'appello
e dal task che pubblica il file su SharePoint.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

TITOLO = "PERSONALE PRESENTE IN AZIENDA"


def _logo_path() -> str:
    from django.contrib.staticfiles import finders

    return finders.find("core/img/logo_novicrom.png") or ""


def genera_pdf(presenti: list[dict], aggiornato_il, *, titolo: str = TITOLO, sottotitolo: str = "",
               contati: set[int] | None = None) -> bytes:
    """PDF della lista. Con ``contati`` aggiunge la colonna «CONTATO» (stampa dell'appello)."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    primario = colors.HexColor("#1a5276")
    testo = colors.HexColor("#2c3e50")
    riga_alt = colors.HexColor("#eaf2f8")
    griglia = colors.HexColor("#d5dbdb")
    sicurezza = colors.HexColor("#c0392b")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm, title=titolo)
    ss = getSampleStyleSheet()
    st_titolo = ParagraphStyle("t", parent=ss["Title"], fontSize=16, spaceAfter=2 * mm,
                               alignment=TA_CENTER, textColor=primario)
    st_sotto = ParagraphStyle("s", parent=ss["Normal"], fontSize=11, alignment=TA_CENTER,
                              textColor=testo, spaceAfter=4 * mm)
    st_tot = ParagraphStyle("c", parent=ss["Normal"], fontSize=11, alignment=TA_LEFT, textColor=primario,
                            fontName="Helvetica-Bold", spaceBefore=4 * mm)
    st_piede = ParagraphStyle("f", parent=ss["Normal"], fontSize=8, alignment=TA_RIGHT, textColor=colors.grey)
    st_inc = ParagraphStyle("i", parent=ss["Normal"], fontSize=7.5, textColor=sicurezza,
                            fontName="Helvetica-Bold", leading=9)

    storia = []
    logo = _logo_path()
    cella_logo = Image(logo, width=25 * mm, height=17 * mm, kind="proportional") if logo else ""
    testata = Table([[cella_logo, Paragraph(escape(titolo), st_titolo)]], colWidths=[30 * mm, 150 * mm])
    testata.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 0), (1, 0), "CENTER")]))
    storia.append(testata)
    storia.append(Paragraph(escape(sottotitolo or f"Aggiornamento: {aggiornato_il:%d/%m/%Y alle ore %H:%M}"),
                            st_sotto))
    storia.append(Spacer(1, 3 * mm))

    if presenti:
        intestazione = ["TURNO", "MATRICOLA", "COGNOME", "NOME", "INCARICO SICUREZZA"]
        larghezze = [13 * mm, 20 * mm, 50 * mm, 42 * mm, 55 * mm]
        if contati is not None:
            intestazione.append("CONTATO")
            larghezze = [14 * mm, 21 * mm, 44 * mm, 36 * mm, 47 * mm, 18 * mm]
        dati = [intestazione]
        for p in presenti:
            incarichi = ", ".join(i["nome"] for i in p.get("incarichi", []))
            riga = [p.get("turno", ""), p.get("matricola", ""), p.get("cognome", "").upper(), p.get("nome", ""),
                    Paragraph(escape(incarichi), st_inc) if incarichi else ""]
            if contati is not None:
                riga.append("SÌ" if p.get("solari_id") in contati else "")
            dati.append(riga)
        tabella = Table(dati, colWidths=larghezze, repeatRows=1)
        stile = [
            ("BACKGROUND", (0, 0), (-1, 0), primario),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8.5),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            ("ALIGN", (0, 1), (1, -1), "CENTER"),
            ("LINEBELOW", (0, 0), (-1, 0), 1, primario),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, primario),
            ("LINEAFTER", (0, 0), (-2, -1), 0.25, griglia),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
        if contati is not None:
            stile += [("ALIGN", (5, 1), (5, -1), "CENTER"), ("FONTNAME", (5, 1), (5, -1), "Helvetica-Bold")]
        for i in range(2, len(dati), 2):
            stile.append(("BACKGROUND", (0, i), (-1, i), riga_alt))
        tabella.setStyle(TableStyle(stile))
        storia.append(tabella)
        totale = f"Totale presenti: {len(presenti)}"
        if contati is not None:
            n = sum(1 for p in presenti if p.get("solari_id") in contati)
            totale += f" · contati: {n} · da trovare: {len(presenti) - n}"
        storia.append(Paragraph(totale, st_tot))
    else:
        storia.append(Spacer(1, 20 * mm))
        storia.append(Paragraph("Nessun dipendente risulta presente al momento.",
                                ParagraphStyle("v", parent=ss["Normal"], fontSize=12, alignment=TA_CENTER,
                                               textColor=colors.HexColor("#7f8c8d"))))

    storia.append(Spacer(1, 10 * mm))
    storia.append(Paragraph(f"Generato da NOVICROM HUB il {aggiornato_il:%d/%m/%Y %H:%M:%S}", st_piede))
    doc.build(storia)
    return buf.getvalue()
