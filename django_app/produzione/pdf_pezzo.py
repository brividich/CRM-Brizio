"""PDF «Scheda pezzo»: i report di un S/N e le sue quote fase per fase, da allegare o mandare al cliente."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone

MAX_COLONNE_PDF = 6


def _fmt(v, d=4):
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def genera(dati: dict, utente: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Scheda pezzo {dati['pn']} {dati['sn']}")
    st = getSampleStyleSheet()
    piccolo = ParagraphStyle("p", parent=st["Normal"], fontSize=8, textColor=colors.HexColor("#5b6476"))
    colonne = dati["colonne"][-MAX_COLONNE_PDF:]
    k0 = len(dati["colonne"]) - len(colonne)
    storia = [Paragraph(f"Scheda pezzo · {escape(dati['pn'])} · S/N {escape(dati['sn'])}", st["Title"]),
              Paragraph(escape(f"OP {', '.join(dati['ops']) or '—'} · {len(dati['reports'])} report CMM · "
                               f"{dati['n_fuori']} quote fuori almeno una volta"
                               + (" · primo articolo del FAI" if dati["primo_articolo"] else "")), piccolo), Spacer(1, 6)]
    rep = [["Data", "Programma", "OP", "Quote", "Fuori", "Esito"]]
    for r in dati["reports"]:
        rep.append([r.data.strftime("%d/%m/%Y") if r.data else "—", r.programma_base or "—", r.op or "—", str(r.righe), str(r.fuori),
                    "escluso" if r.escluso else ("fuori tolleranza" if r.fuori else "in tolleranza")])
    t = Table(rep, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e7ee"))]))
    storia += [t, Spacer(1, 8)]
    testa = ["Quota", "Lim. inf.", "Lim. sup."] + [f"{c.data.strftime('%d/%m/%Y') if c.data else '—'}\n{(c.programma_base or '—')[:12]}" for c in colonne] + ["Δ ultimo−primo"]
    tab = [testa]
    stile = [("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")),
             ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, 0), "BOTTOM"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e7ee"))]
    for i, riga in enumerate(dati["righe"], start=1):
        valori = riga["valori"][k0:]
        tab.append([riga["nome"][:38], _fmt(riga["lsl"]), _fmt(riga["usl"])] + [_fmt(v["x"]) if v else "—" for v in valori]
                   + [_fmt(riga["delta"])])
        for j, v in enumerate(valori):
            if v and v["fuori"]:
                stile.append(("TEXTCOLOR", (3 + j, i), (3 + j, i), colors.HexColor("#d03b3b")))
    larghezze = [56 * mm, 18 * mm, 18 * mm] + [26 * mm] * len(colonne) + [24 * mm]
    q = Table(tab, repeatRows=1, colWidths=larghezze, hAlign="LEFT")
    q.setStyle(TableStyle(stile))
    storia += [q, Spacer(1, 8)]
    if len(dati["colonne"]) > len(colonne):
        storia.append(Paragraph(f"Nel PDF gli ultimi {len(colonne)} report; tutti nella pagina del portale.", piccolo))
    storia.append(Paragraph(escape(f"Generato da NOVICROM HUB il {timezone.localtime():%d/%m/%Y %H:%M} da {utente} · dati dei report CMM"), piccolo))
    doc.build(storia)
    return buf.getvalue()
