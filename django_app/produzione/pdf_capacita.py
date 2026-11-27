"""PDF «Studio di capacità» di un programma CMM: tabella Cp/Cpk e un grafico per quota, con i filtri della pagina."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone

from . import report_cmm_indice as cmm
from . import spc


def _fmt(v, d=4):
    return "—" if v is None else f"{v:.{d}f}".replace(".", ",")


def righe_capacita(dati: dict, quote_scelte: set[str] | None, op: set[str], tieni: set[int] | None) -> list[dict]:
    out = []
    for q, vals in zip(dati["quote"], dati["valori"]):
        if quote_scelte and q["id"] not in quote_scelte:
            continue
        vs = [v for v in vals if v[1] is not None and (not op or (dati["report"][v[0]][2] or "—") in op)
              and (tieni is None or v[0] in tieni) and not dati["report"][v[0]][6]]
        if not vs:
            continue
        punti = [(v[1], q["nominale"] + v[3], q["nominale"] + v[2]) for v in vs]
        s = cmm.statistiche(punti, q["nominale"])
        out.append({"q": q, "vals": vs, "s": s, "n_fuori": sum(v[4] for v in vs), "ts": vs[-1][2], "ti": vs[-1][3]})
    return out


def _grafico(r, larghezza, altezza):
    from reportlab.graphics.shapes import Circle, Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors

    d = Drawing(larghezza, altezza)
    vs, q = r["vals"], r["q"]
    lsl, usl = q["nominale"] + r["ti"], q["nominale"] + r["ts"]
    xs = [v[1] for v in vs]
    lo, hi = min(xs + [lsl]), max(xs + [usl])
    pad = (hi - lo) * 0.1 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 34, 4, 4, 10
    X = lambda i: L + (i * (larghezza - L - R) / (len(vs) - 1) if len(vs) > 1 else (larghezza - L - R) / 2)  # noqa: E731
    Y = lambda v: B + (v - lo) / (hi - lo) * (altezza - T - B)  # noqa: E731
    d.add(Rect(L, Y(lsl), larghezza - L - R, Y(usl) - Y(lsl), fillColor=colors.Color(0.05, 0.64, 0.05, 0.10), strokeColor=None))
    for v in (lsl, usl):
        d.add(Line(L, Y(v), larghezza - R, Y(v), strokeColor=colors.HexColor("#d03b3b"), strokeDashArray=[3, 2], strokeWidth=0.8))
        d.add(String(L - 3, Y(v) - 2, _fmt(v, 3), fontSize=5.5, textAnchor="end", fillColor=colors.HexColor("#5b6476")))
    if len(vs) > 1:
        d.add(PolyLine([c for i, v in enumerate(vs) for c in (X(i), Y(v[1]))], strokeColor=colors.HexColor("#2a78d6"), strokeWidth=0.9))
    for i, v in enumerate(vs):
        if v[4]:
            d.add(Circle(X(i), Y(v[1]), 1.6, fillColor=colors.HexColor("#d03b3b"), strokeColor=None))
    return d


def genera(pn: str, dati: dict, righe: list[dict], filtri: str, utente: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Studio di capacità {pn}")
    st = getSampleStyleSheet()
    piccolo = ParagraphStyle("p", parent=st["Normal"], fontSize=8, textColor=colors.HexColor("#5b6476"))
    storia = [Paragraph(f"Studio di capacità · {escape(pn)}", st["Title"]),
              Paragraph(escape(f"Programma {dati['prog']} · {filtri}"), piccolo), Spacer(1, 6)]
    tab = [["Quota", "Nominale", "Tol +", "Tol −", "Misure", "Media", "σ", "Cp", "Cpk", "Fuori"]]
    for r in righe:
        s = r["s"]
        tab.append([r["q"]["nome"][:34], _fmt(r["q"]["nominale"]), _fmt(r["ts"]), _fmt(r["ti"]), str(s["n"]), _fmt(s.get("media")),
                    _fmt(s.get("sd")), _fmt(s.get("cp"), 2), _fmt(s.get("cpk"), 2), str(r["n_fuori"])])
    t = Table(tab, repeatRows=1, colWidths=[52 * mm] + [14.5 * mm] * 9)
    stile = [("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f5f8")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5b6476")), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#e3e7ee"))]
    for k, r in enumerate(righe, start=1):
        cpk = r["s"].get("cpk")
        if cpk is not None and cpk < spc.CAPACE:
            stile.append(("TEXTCOLOR", (8, k), (8, k), colors.HexColor("#d03b3b" if cpk < spc.AL_LIMITE else "#9a6700")))
        if r["n_fuori"]:
            stile.append(("TEXTCOLOR", (9, k), (9, k), colors.HexColor("#d03b3b")))
    t.setStyle(TableStyle(stile))
    storia += [t, Spacer(1, 8), Paragraph("Cpk: Capace ≥ 1,33 · Al limite 1–1,33 · Non capace < 1. Quote con solo limite superiore "
                                          "(forma, posizione): Cpk = (limite − media) / 3σ, Cp non calcolato.", piccolo), Spacer(1, 8)]
    for r in righe[:24]:
        storia.append(KeepTogether([Paragraph(f"<b>{escape(r['q']['nome'])}</b> · {escape(r['q']['sezione'] or '')}", piccolo),
                                    _grafico(r, 180 * mm, 30 * mm), Spacer(1, 4)]))
    storia.append(Paragraph(escape(f"Generato da NOVICROM HUB il {timezone.localtime():%d/%m/%Y %H:%M} da {utente} · dati dei report CMM"), piccolo))
    doc.build(storia)
    return buf.getvalue()
