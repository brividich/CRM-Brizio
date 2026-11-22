"""Genera i due PDF-presentazione degli algoritmi di NOVICROM HUB e il catalogo Markdown.

Uso (dalla radice del repo):
    python tools/gen_algoritmi_pdf.py            # PDF Direzione + PDF tecnico + catalogo .md
    python tools/gen_algoritmi_pdf.py --verifica # controlla che file e simboli esistano ancora

I contenuti stanno in tools/algoritmi_dati.py. Solo reportlab, nessuna dipendenza da Django.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from algoritmi_dati import ALGORITMI  # noqa: E402

APP = RADICE / "django_app"
USCITA = RADICE / "docs" / "audit"
LOGO = APP / "core" / "static" / "core" / "img" / "novicrom_hub.png"
DATA = "22/11/2026"

NAVY, NAVY_MID, ORANGE = HexColor("#002b5c"), HexColor("#2f5f89"), HexColor("#ff6b00")
SFONDO, TESTO, GRIGIO, BORDO = HexColor("#f2f5f8"), HexColor("#1a202c"), HexColor("#5b6675"), HexColor("#d5dce4")
AVVISO_BG, AVVISO_BORDO = HexColor("#fff4ea"), HexColor("#ffb27a")

W, H = landscape(A4)
MARGINE = 36


def stile(nome, size, colore=TESTO, bold=False, lead=None, align=0):
    return ParagraphStyle(nome, fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size,
                          leading=lead or size * 1.3, textColor=colore, alignment=align)


def esc(testo: str) -> str:
    return testo.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def disegna(c, testo, st, x, y_top, larghezza) -> float:
    """Disegna un paragrafo con l'angolo in alto a sinistra in (x, y_top); ritorna l'altezza."""
    p = Paragraph(testo, st)
    _, h = p.wrap(larghezza, 1000)
    p.drawOn(c, x, y_top - h)
    return h


def altezza(testo, st, larghezza) -> float:
    return Paragraph(testo, st).wrap(larghezza, 1000)[1]


def cornice(c, titolo_doc, pagina):
    c.setFillColor(white)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(ORANGE)
    c.rect(0, H - 6, W, 6, stroke=0, fill=1)
    if LOGO.exists():
        c.drawImage(str(LOGO), W - MARGINE - 112, H - 48, width=112, height=28, mask="auto")
    c.setStrokeColor(BORDO)
    c.line(MARGINE, 30, W - MARGINE, 30)
    c.setFont("Helvetica", 8)
    c.setFillColor(GRIGIO)
    c.drawString(MARGINE, 18, f"NOVICROM HUB  ·  {titolo_doc}  ·  {DATA}")
    c.drawRightString(W - MARGINE, 18, str(pagina))


def flusso(c, passi, x, y, larghezza, alt=54):
    """Riquadri in fila collegati da frecce."""
    n = len(passi)
    spazio = 20
    lw = (larghezza - spazio * (n - 1)) / n
    st = stile("passo", 12 if n <= 4 else 10.5, NAVY, bold=True, align=TA_CENTER)
    for i, passo in enumerate(passi):
        bx = x + i * (lw + spazio)
        c.setFillColor(SFONDO)
        c.setStrokeColor(NAVY_MID)
        c.setLineWidth(1)
        c.roundRect(bx, y, lw, alt, 7, stroke=1, fill=1)
        c.setFillColor(ORANGE)
        c.circle(bx + 10, y + alt - 10, 6.5, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(bx + 10, y + alt - 12.8, str(i + 1))
        p = Paragraph(esc(passo), st)
        _, ph = p.wrap(lw - 16, alt)
        p.drawOn(c, bx + 8, y + (alt - ph) / 2 - 2)
        if i < n - 1:
            ax, ay = bx + lw + 3, y + alt / 2
            c.setStrokeColor(ORANGE)
            c.setFillColor(ORANGE)
            c.setLineWidth(1.6)
            c.line(ax, ay, ax + spazio - 9, ay)
            f = c.beginPath()
            f.moveTo(ax + spazio - 5, ay)
            f.lineTo(ax + spazio - 11, ay + 4)
            f.lineTo(ax + spazio - 11, ay - 4)
            f.close()
            c.drawPath(f, stroke=0, fill=1)


def copertina(c, titolo_doc, sottotitolo, n):
    c.setFillColor(NAVY)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(white)
    c.roundRect(MARGINE, H - 120, 250, 76, 8, stroke=0, fill=1)
    if LOGO.exists():
        c.drawImage(str(LOGO), MARGINE + 17, H - 109, width=216, height=54, mask="auto")
    c.setFillColor(ORANGE)
    c.rect(MARGINE, H / 2 + 26, 70, 5, stroke=0, fill=1)
    disegna(c, "Gli algoritmi interni del portale", stile("t", 34, white, bold=True), MARGINE, H / 2 + 10, W - 2 * MARGINE)
    disegna(c, esc(sottotitolo), stile("s", 15, HexColor("#c9d8e8")), MARGINE, H / 2 - 44, W - 2 * MARGINE)
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#c9d8e8"))
    c.drawString(MARGINE, 44, f"{titolo_doc}  ·  {n} algoritmi  ·  {DATA}")


def indice(c, titolo_doc, moduli, pagina):
    cornice(c, titolo_doc, pagina)
    disegna(c, "Indice", stile("h", 22, NAVY, bold=True), MARGINE, H - 28, 500)
    col_w = (W - 2 * MARGINE - 24) / 2
    st_m = stile("m", 10.5, NAVY, bold=True)
    st_v = stile("v", 9, TESTO, lead=11.5)
    x, y = MARGINE, H - 78
    for modulo, voci in moduli:
        testo_voci = "<br/>".join(f"{esc(t)} <font color='#5b6675'>· pag. {pg}</font>" for t, pg in voci)
        h = altezza(esc(modulo), st_m, col_w) + altezza(testo_voci, st_v, col_w) + 12
        if y - h < 40:
            x, y = MARGINE + col_w + 24, H - 78
        y -= disegna(c, esc(modulo), st_m, x, y, col_w) + 2
        y -= disegna(c, testo_voci, st_v, x, y, col_w) + 10
    c.showPage()


def slide(c, titolo_doc, alg, pagina, tecnico: bool, righe: dict):
    cornice(c, titolo_doc, pagina)
    larg = W - 2 * MARGINE
    y = H - 26
    y -= disegna(c, esc(alg["modulo"]).upper(), stile("mod", 9, ORANGE, bold=True), MARGINE, y, larg - 130) + 3
    y -= disegna(c, esc(alg["titolo"]), stile("tit", 22, NAVY, bold=True), MARGINE, y, larg - 130) + 10

    alt_flusso = 74
    y_flusso = 44
    disponibile = y - (y_flusso + alt_flusso + 22)
    for corpo in (16, 14.5, 13, 11.5, 10.5, 9.5, 8.5, 7.8):
        st_cosa = stile("cosa", corpo + 1.5, TESTO, lead=(corpo + 1.5) * 1.35)
        st_et = stile("et", corpo - 1, NAVY_MID, bold=True)
        st_r = stile("r", corpo, TESTO, lead=corpo * 1.4)
        regole = "<br/>".join(f"<font color='#ff6b00'><b>&bull;</b></font>&nbsp;&nbsp;{esc(r)}" for r in alg["regole"])
        if tecnico:
            col_sx = larg * 0.5
            col_dx = larg - col_sx - 22
            riga = righe.get(id(alg))
            dove = alg["file"] + (f" · {alg['simbolo']}" if alg["simbolo"] else "") + (f" · riga {riga}" if riga else "")
            st_code = ParagraphStyle("code", fontName="Courier", fontSize=corpo - 1.5, leading=(corpo - 1.5) * 1.3, textColor=NAVY)
            h_sx = (altezza(esc(alg["cosa"]), st_cosa, col_sx) + 12 + altezza("REGOLE E SOGLIE", st_et, col_sx) + 4
                    + altezza(regole, st_r, col_sx))
            h_dx = (altezza("DOVE", st_et, col_dx) + 3 + altezza(esc(dove), st_code, col_dx) + 10
                    + altezza("DETTAGLIO TECNICO", st_et, col_dx) + 3 + altezza(esc(alg["tecnico"]), st_r, col_dx))
            if alg["limiti"]:
                h_dx += 12 + altezza("LIMITI NOTI", st_et, col_dx - 16) + 3 + altezza(esc(alg["limiti"]), st_r, col_dx - 16) + 14
            if max(h_sx, h_dx) <= disponibile:
                break
        else:
            col_sx = larg
            h_sx = (altezza(esc(alg["cosa"]), st_cosa, col_sx) + 14 + altezza("LE REGOLE", st_et, col_sx) + 4
                    + altezza(regole, st_r, col_sx))
            if h_sx <= disponibile:
                break

    ys = y
    ys -= disegna(c, esc(alg["cosa"]), st_cosa, MARGINE, ys, col_sx) + (12 if tecnico else 14)
    ys -= disegna(c, "REGOLE E SOGLIE" if tecnico else "LE REGOLE", st_et, MARGINE, ys, col_sx) + 4
    disegna(c, regole, st_r, MARGINE, ys, col_sx)

    if tecnico:
        xd = MARGINE + col_sx + 22
        yd = y
        yd -= disegna(c, "DOVE", st_et, xd, yd, col_dx) + 3
        yd -= disegna(c, esc(dove), st_code, xd, yd, col_dx) + 10
        yd -= disegna(c, "DETTAGLIO TECNICO", st_et, xd, yd, col_dx) + 3
        yd -= disegna(c, esc(alg["tecnico"]), st_r, xd, yd, col_dx) + 12
        if alg["limiti"]:
            hb = altezza("LIMITI NOTI", st_et, col_dx - 16) + 3 + altezza(esc(alg["limiti"]), st_r, col_dx - 16) + 14
            c.setFillColor(AVVISO_BG)
            c.setStrokeColor(AVVISO_BORDO)
            c.roundRect(xd, yd - hb, col_dx, hb, 6, stroke=1, fill=1)
            yb = yd - 7
            yb -= disegna(c, "LIMITI NOTI", stile("etl", st_et.fontSize, ORANGE, bold=True), xd + 8, yb, col_dx - 16) + 3
            disegna(c, esc(alg["limiti"]), st_r, xd + 8, yb, col_dx - 16)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(NAVY_MID)
    c.drawString(MARGINE, y_flusso + alt_flusso + 7, "COME FUNZIONA")
    flusso(c, alg["passi"], MARGINE, y_flusso, larg, alt_flusso)
    c.showPage()


def trova_righe() -> tuple[dict, list[str]]:
    """Riga del simbolo in ogni file; elenco dei problemi (file o simbolo mancante)."""
    righe, problemi = {}, []
    for alg in ALGORITMI:
        f = APP / alg["file"]
        if not f.exists():
            problemi.append(f"file mancante: {alg['file']} ({alg['titolo']})")
            continue
        if not alg["simbolo"]:
            continue
        modello = re.compile(rf"^\s*(def|class)\s+{re.escape(alg['simbolo'])}\b|^{re.escape(alg['simbolo'])}\s*[:=]")
        for n, linea in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if modello.search(linea):
                righe[id(alg)] = n
                break
        else:
            problemi.append(f"simbolo non trovato: {alg['file']} · {alg['simbolo']}")
    return righe, problemi


def genera_pdf(nome, titolo_doc, sottotitolo, tecnico, righe):
    percorso = USCITA / nome
    c = canvas.Canvas(str(percorso), pagesize=(W, H))
    c.setTitle(f"NOVICROM HUB - {titolo_doc}")
    c.setAuthor("NOVICROM HUB")
    copertina(c, titolo_doc, sottotitolo, len(ALGORITMI))
    c.showPage()
    moduli: list[tuple[str, list]] = []
    for i, alg in enumerate(ALGORITMI):
        if not moduli or moduli[-1][0] != alg["modulo"]:
            moduli.append((alg["modulo"], []))
        moduli[-1][1].append((alg["titolo"], i + 3))
    indice(c, titolo_doc, moduli, 2)
    for i, alg in enumerate(ALGORITMI):
        slide(c, titolo_doc, alg, i + 3, tecnico, righe)
    c.save()
    return percorso


def genera_markdown(righe):
    out = ["# Algoritmi interni di NOVICROM HUB", "",
           f"Catalogo rilevato sul codice il {DATA} (main `07b18cc67`). Generato da `tools/gen_algoritmi_pdf.py` "
           "a partire da `tools/algoritmi_dati.py`: non modificare a mano. Percorsi relativi a `django_app/`.", ""]
    modulo = None
    for alg in ALGORITMI:
        if alg["modulo"] != modulo:
            modulo = alg["modulo"]
            out += [f"## {modulo}", ""]
        riga = righe.get(id(alg))
        dove = f"`{alg['file']}`" + (f" · `{alg['simbolo']}`" if alg["simbolo"] else "") + (f" · riga {riga}" if riga else "")
        out += [f"### {alg['titolo']}", "", alg["cosa"], "", f"- **Dove:** {dove}",
                f"- **Flusso:** {' → '.join(alg['passi'])}", "- **Regole e soglie:**"]
        out += [f"  - {r}" for r in alg["regole"]]
        out.append(f"- **Dettaglio tecnico:** {alg['tecnico']}")
        if alg["limiti"]:
            out.append(f"- **Limiti noti:** {alg['limiti']}")
        out.append("")
    percorso = USCITA / "ALGORITMI_PORTALE_2026-11-22.md"
    percorso.write_text("\n".join(out), encoding="utf-8")
    return percorso


def main() -> int:
    righe, problemi = trova_righe()
    for p in problemi:
        print("ATTENZIONE:", p)
    if "--verifica" in sys.argv:
        print(f"{len(ALGORITMI)} algoritmi, {len(problemi)} problemi")
        return 1 if problemi else 0
    USCITA.mkdir(parents=True, exist_ok=True)
    print(genera_pdf("Algoritmi_NOVICROM_HUB_Direzione.pdf", "Algoritmi interni - versione per la Direzione",
                     "Come decide il portale: le regole e le soglie, spiegate in modo semplice", False, righe))
    print(genera_pdf("Algoritmi_NOVICROM_HUB_Tecnico.pdf", "Algoritmi interni - versione tecnica",
                     "Funzioni, file, soglie e limiti noti, per sviluppatori, IT e auditor", True, righe))
    print(genera_markdown(righe))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
