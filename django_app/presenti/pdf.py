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
               contati: set[int] | None = None, esterni: list[dict] | None = None) -> bytes:
    """PDF della lista. Con ``contati`` aggiunge la colonna «CONTATO» (stampa dell'appello).

    ``esterni`` (visitatori, ditte, docenti dal GuestPortal) vanno in una seconda tabella
    «ESTERNI IN AZIENDA», con la stessa colonna «CONTATO» nell'appello.
    """
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
    st_cella = ParagraphStyle("x", parent=ss["Normal"], fontSize=8.5, leading=10, textColor=testo)
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

    if esterni is not None:
        storia.append(Spacer(1, 6 * mm))
        storia.append(Paragraph("ESTERNI IN AZIENDA", ParagraphStyle(
            "e", parent=ss["Normal"], fontSize=12, fontName="Helvetica-Bold", textColor=primario, spaceAfter=2 * mm)))
        if esterni:
            intest = ["NOME", "AZIENDA", "TIPO", "REFERENTE", "ENTRATA"]
            largh = [45 * mm, 45 * mm, 25 * mm, 45 * mm, 20 * mm]
            if contati is not None:
                intest = ["NOME", "AZIENDA", "TIPO", "REFERENTE", "CONTATO"]
                largh = [45 * mm, 45 * mm, 25 * mm, 47 * mm, 18 * mm]
            righe_e = [intest]
            for p in esterni:
                ultima = ("SÌ" if p.get("solari_id") in contati else "") if contati is not None else p.get("entrata", "")
                righe_e.append([Paragraph(escape(p.get("cognome", "")), st_cella),
                                Paragraph(escape(p.get("azienda", "")), st_cella),
                                p.get("tipo", ""), Paragraph(escape(p.get("referente", "")), st_cella), ultima])
            tab_e = Table(righe_e, colWidths=largh, repeatRows=1)
            stile_e = [
                ("BACKGROUND", (0, 0), (-1, 0), primario),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (4, 1), (4, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, -1), (-1, -1), 0.5, primario),
                ("LINEAFTER", (0, 0), (-2, -1), 0.25, griglia),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
            if contati is not None:
                stile_e.append(("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold"))
            for i in range(2, len(righe_e), 2):
                stile_e.append(("BACKGROUND", (0, i), (-1, i), riga_alt))
            tab_e.setStyle(TableStyle(stile_e))
            storia.append(tab_e)
            tot_e = f"Totale esterni: {len(esterni)}"
            if contati is not None:
                n = sum(1 for p in esterni if p.get("solari_id") in contati)
                tot_e += f" · contati: {n} · da trovare: {len(esterni) - n}"
            storia.append(Paragraph(tot_e, st_tot))
        else:
            storia.append(Paragraph("Nessun esterno registrato in azienda al GuestPortal.", st_cella))

    storia.append(Spacer(1, 10 * mm))
    storia.append(Paragraph(f"Generato da NOVICROM HUB il {aggiornato_il:%d/%m/%Y %H:%M:%S}", st_piede))
    doc.build(storia)
    return buf.getvalue()


def genera_verbale(d: dict) -> bytes:
    """Verbale dell'appello (esercitazione o emergenza) per il registro della sicurezza.

    ``d`` = ``views._dati_verbale``: tempi, soglie 50/90/100 %, chi ha contato, mancanti,
    osservazioni. Spazi firma per coordinatore e RSPP.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    a = d["appello"]
    primario = colors.HexColor("#1a5276")
    griglia = colors.HexColor("#d5dbdb")
    chiaro = colors.HexColor("#eaf2f8")
    buf = BytesIO()
    titolo = "VERBALE DI " + ("ESERCITAZIONE DI EVACUAZIONE" if a.esercitazione else "EVACUAZIONE DI EMERGENZA")
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm, title=titolo)
    ss = getSampleStyleSheet()
    st_t = ParagraphStyle("t", parent=ss["Title"], fontSize=15, textColor=primario, alignment=TA_CENTER)
    st_h = ParagraphStyle("h", parent=ss["Normal"], fontSize=11.5, fontName="Helvetica-Bold", textColor=primario,
                          spaceBefore=5 * mm, spaceAfter=2 * mm)
    st_n = ParagraphStyle("n", parent=ss["Normal"], fontSize=9.5, leading=12)
    st_piede = ParagraphStyle("f", parent=ss["Normal"], fontSize=8, alignment=TA_RIGHT, textColor=colors.grey)

    def tabella(righe, larghezze, intestazione=False):
        t = Table(righe, colWidths=larghezze, repeatRows=1 if intestazione else 0)
        stile = [("FONTSIZE", (0, 0), (-1, -1), 9), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                 ("GRID", (0, 0), (-1, -1), 0.25, griglia),
                 ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
        if intestazione:
            stile += [("BACKGROUND", (0, 0), (-1, 0), primario), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                      ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold")]
        else:
            stile += [("BACKGROUND", (0, 0), (0, -1), chiaro), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")]
        t.setStyle(TableStyle(stile))
        return t

    storia = []
    logo = _logo_path()
    cella_logo = Image(logo, width=25 * mm, height=17 * mm, kind="proportional") if logo else ""
    testata = Table([[cella_logo, Paragraph(escape(titolo), st_t)]], colWidths=[30 * mm, 150 * mm])
    testata.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    storia.append(testata)

    storia.append(Paragraph("Dati generali", st_h))
    chiuso = f"{d['chiuso_il']:%H:%M:%S} da {d['chiuso_da']}" if d["chiuso_il"] else "appello ancora aperto"
    storia.append(tabella([
        ["Tipo", d["tipo"]],
        ["Data", f"{d['aperto_il']:%d/%m/%Y}"],
        ["Avviato", f"{d['aperto_il']:%H:%M:%S} da {d['aperto_da']}"],
        ["Chiuso", chiuso],
        ["Durata", d["durata"]],
        ["Nota all'avvio", Paragraph(escape(a.nota or "—"), st_n)],
    ], [45 * mm, 135 * mm]))

    storia.append(Paragraph("Conta al punto di raccolta", st_h))
    storia.append(tabella([
        ["Persone in elenco", f"{d['n_totale']} (dipendenti {d['n_dipendenti']}, esterni {d['n_esterni']})"],
        ["Contate", str(d["n_contati"])],
        ["Non contate", str(d["n_totale"] - d["n_contati"])],
    ] + [[f"Tempo al {s['perc']} %", f"{s['tempo']}" + (f"  ({s['serve']} persone)" if s["serve"] else "")]
         for s in d["soglie"]], [45 * mm, 135 * mm]))

    if d["per_chi"]:
        storia.append(Paragraph("Chi ha contato", st_h))
        storia.append(tabella([["Persona", "Spunte"]] + [[n, str(c)] for n, c in d["per_chi"]],
                              [140 * mm, 40 * mm], intestazione=True))

    storia.append(Paragraph(f"Non contati alla chiusura ({len(d['mancanti'])})", st_h))
    if d["mancanti"]:
        righe = [["Nome", "Reparto / azienda", "Tipo"]]
        for p in d["mancanti"]:
            nome = f"{(p.get('cognome') or '').upper()} {p.get('nome') or ''}".strip()
            righe.append([Paragraph(escape(nome), st_n),
                          Paragraph(escape(p.get("azienda") or p.get("reparto") or ""), st_n),
                          "Esterno" if p.get("esterno") else "Dipendente"])
        storia.append(tabella(righe, [80 * mm, 70 * mm, 30 * mm], intestazione=True))
    else:
        storia.append(Paragraph("Tutte le persone in elenco sono state contate.", st_n))

    storia.append(Paragraph("Osservazioni, criticità e azioni di miglioramento", st_h))
    testo = escape(a.osservazioni or "").replace("\n", "<br/>") or "&nbsp;<br/>&nbsp;<br/>&nbsp;"
    storia.append(tabella([[Paragraph(testo, st_n)]], [180 * mm]))

    storia.append(Spacer(1, 12 * mm))
    riga_firma = "\n\n____________________________"
    firme = Table([["Il coordinatore dell'emergenza", "", "RSPP"], [riga_firma, "", riga_firma]],
                  colWidths=[80 * mm, 20 * mm, 80 * mm])
    firme.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("ALIGN", (0, 0), (-1, -1), "CENTER")]))
    storia.append(firme)
    storia.append(Spacer(1, 8 * mm))
    storia.append(Paragraph(f"Generato da NOVICROM HUB il {timezone_now():%d/%m/%Y %H:%M}", st_piede))
    doc.build(storia)
    return buf.getvalue()


def timezone_now():
    from django.utils import timezone

    return timezone.localtime()
