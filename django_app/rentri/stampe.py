"""Stampe annuali RENTRI: registro cronologico e riepilogo per codice.

Intestazione su ogni pagina con ragione sociale e codice di iscrizione RENTRI
(Impostazioni del modulo) e numerazione «Pagina N di M», per stampa e
archiviazione. Il contenuto viene da :mod:`rentri.registro_annuale`.
"""
from __future__ import annotations

from io import BytesIO

from django.utils import timezone

from .registro_annuale import TIPO_OPERAZIONE, annotazioni, codice_esteso


def _num(q, unita: str = "") -> str:
    if q is None:
        return ""
    testo = f"{q:,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{testo} {unita}".strip()


def _intestazione(cfg) -> str:
    parti = [cfg.ragione_sociale.strip() or "Ragione sociale da indicare nelle Impostazioni RENTRI"]
    parti.append(
        f"Codice iscrizione RENTRI: {cfg.codice_iscrizione_rentri.strip()}"
        if cfg.codice_iscrizione_rentri.strip() else "Codice iscrizione RENTRI da indicare nelle Impostazioni"
    )
    return "  ·  ".join(parti)


def _costruisci(titolo: str, sottotitolo: str, cfg, storia) -> bytes:
    """PDF A4 orizzontale; due passaggi per scrivere «Pagina N di M»."""
    from reportlab.lib.units import mm

    from core.pdf import FOOTER_HEIGHT, PdfTheme, draw_canvas_footer, draw_canvas_header, make_document

    theme = PdfTheme.from_branding()
    generato = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    intest = _intestazione(cfg)

    def _pdf(totale: int | None) -> tuple[bytes, int]:
        buf = BytesIO()
        doc = make_document(buf, title=titolo, landscape=True, top_margin=36 * mm,
                            left_margin=12 * mm, right_margin=12 * mm)

        def _pagina(canv, d):
            canv.saveState()
            w, h = d.pagesize
            y = draw_canvas_header(canv, theme=theme, page_width=w, page_height=h, left_margin=d.leftMargin,
                                   right_margin=d.rightMargin, title=titolo, subtitle=sottotitolo,
                                   right_subtitle=f"Generato il {generato}")
            canv.setFont("Helvetica-Bold", 8.5)
            canv.setFillColor(theme.c_text())
            canv.drawString(d.leftMargin, y + 1.5 * mm, intest)
            numero = f"Pagina {d.page} di {totale}" if totale else f"Pagina {d.page}"
            draw_canvas_footer(canv, theme=theme, page_width=w, left_margin=d.leftMargin,
                               right_margin=d.rightMargin, baseline_y=FOOTER_HEIGHT - 4 * mm,
                               page_number=None, right_text=numero)
            canv.restoreState()

        doc.build(storia(), onFirstPage=_pagina, onLaterPages=_pagina)
        return buf.getvalue(), doc.page

    _bozza, pagine = _pdf(None)
    finale, _ = _pdf(pagine)
    return finale


def _stili():
    from reportlab.lib.styles import ParagraphStyle

    return {
        "h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=7, leading=8.5, textColor="#ffffff"),
        "c": ParagraphStyle("c", fontName="Helvetica", fontSize=7, leading=8.5),
        "r": ParagraphStyle("r", fontName="Helvetica", fontSize=7, leading=8.5, alignment=2),
        "n": ParagraphStyle("n", fontName="Helvetica", fontSize=8, leading=10),
    }


def _tabella(intestazioni, righe, larghezze, grigie=()):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    t = Table([intestazioni, *righe], colWidths=larghezze, repeatRows=1)
    st = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a5f")),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
    ])
    for i in grigie:
        st.add("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#94a3b8"))
    t.setStyle(st)
    return t


def pdf_registro_cronologico(anno: int, registrazioni: list, cfg, catalogo: dict) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from .fili import chiave

    s = _stili()

    def P(t, st="c"):
        return Paragraph(str(t or "").replace("&", "&amp;").replace("<", "&lt;"), s[st])

    def storia():
        if not registrazioni:
            return [P(f"Nessuna registrazione nell'anno {anno}.", "n")]
        pericolosi = {chiave(r.codice) for r in registrazioni
                      if "*" in (r.codice or "") or (r.tipo == "C" and (r.pericolosita or "").strip())}
        righe, grigie = [], []
        for i, r in enumerate(registrazioni, start=1):
            k = chiave(r.codice)
            desc, per = catalogo.get(k, ("", False))
            per = per or "*" in (r.codice or "") or k in pericolosi
            codice = (codice_esteso(k) + ("*" if per else "")) if k else (r.codice or "")
            q = r.quantita if r.quantita is not None else r.rettifica_scarico
            righe.append([
                P(r.id_registrazione), P(r.data.strftime("%d/%m/%Y") if r.data else ""),
                P(TIPO_OPERAZIONE.get(r.tipo, r.tipo)), P(r.rif_op), P(codice),
                P(desc or " ".join((r.codice or "").split())), P(r.pericolosita),
                P(_num(q, r.unita), "r"), P(r.arrivo_fir), P(annotazioni(r)),
            ])
            if r.annullato:
                grigie.append(i)
        intest = [P(t, "h") for t in ("N. reg.", "Data", "Operazione", "Rif. operazioni", "Codice EER",
                                     "Descrizione", "Caratt. pericolo", "Quantità", "Formulario (FIR)", "Annotazioni")]
        larg = [w * mm for w in (18, 17, 21, 22, 17, 52, 20, 22, 30, 54)]
        return [_tabella(intest, righe, larg, grigie), Spacer(1, 4 * mm),
                P("Le registrazioni annullate restano a registro in grigio con il motivo. "
                  "Quantità con il segno registrato; la rettifica corregge il peso dello scarico.", "n")]

    return _costruisci(
        f"Registro cronologico di carico e scarico — anno {anno}",
        f"{len(registrazioni)} registrazioni",
        cfg, storia,
    )


def pdf_riepilogo(anno: int, righe: list, cfg) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    s = _stili()

    def P(t, st="c"):
        return Paragraph(str(t or "").replace("&", "&amp;").replace("<", "&lt;"), s[st])

    def storia():
        if not righe:
            return [P(f"Nessun codice movimentato o in giacenza nell'anno {anno}.", "n")]
        dati = []
        for rg in righe:
            u = rg.unita + (" (unità miste)" if rg.unita_miste else "")
            dati.append([
                P(rg.codice), P(rg.descrizione), P(_num(rg.giacenza_inizio, u), "r"),
                P(_num(rg.caricato, u), "r"), P(_num(rg.scaricato, u), "r"), P(_num(rg.giacenza_fine, u), "r"),
                P(f"{rg.n_carichi} / {rg.n_scarichi}", "r"), P(", ".join(rg.fir)),
                P(_num(rg.differenza, u) if abs(rg.differenza) > 0.0005 else "", "r"),
            ])
        intest = [P(t, "h") for t in ("Codice EER", "Descrizione", "Giacenza 1/1", "Caricato", "Scaricato",
                                     "Giacenza 31/12", "Carichi / scarichi", "Formulari", "Non torna")]
        larg = [w * mm for w in (20, 62, 24, 24, 24, 24, 20, 51, 24)]
        return [_tabella(intest, dati, larg), Spacer(1, 4 * mm),
                P("Giacenze dal conto del filo (come la pagina Giacenze). «Scaricato» = uscite dal deposito "
                  "(scarichi originali; lo scarico effettivo solo se il filo non ha lo scarico originale). "
                  "«Non torna» = scarichi oltre il carico: vedi la Verifica. Base per il MUD, da confrontare "
                  "col tracciato ufficiale.", "n")]

    return _costruisci(f"Riepilogo annuale per codice — anno {anno}", f"{len(righe)} codici", cfg, storia)
