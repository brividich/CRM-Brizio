"""PDF della Skill Matrix (28/11/2026): «Report HUB» e modulo «MOD.187».

Entrambi partono da ``skillmatrix_vista.costruisci`` (stessi numeri della pagina) e
sono A3 orizzontali. Se le colonne non stanno in larghezza si va su più fogli,
spezzando fra i reparti; le righe vanno a capo pagina ripetendo le intestazioni.

- MOD.187: ricalca il modulo SGI «MOD.187 - SKM Skill Matrix Rev.0» (9100_Qualità/
  _Modelli): fascia SKILL MATRIX, Data e Firma CEO, CAR e reparto sopra le colonne,
  totali I/L/U/O, nomi delle colonne in verticale, Ruolo · Orario · Nome Operatore,
  righe dei CAR in azzurro, lettere nelle caselle, «Pag. x/y».
- Report HUB: grafica del portale, numeri chiave, celle a colori, operativi per
  macchina e per persona, legenda, chi e quando l'ha generato.
"""
from __future__ import annotations

import io

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A3, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .skillmatrix_vista import LEGENDA, LIVELLI

PAGINA = landscape(A3)
NAVY = HexColor("#0c2545")
ARANCIO = HexColor("#ff6b00")
AZZURRO_CAR = HexColor("#b4c6e7")
FASCIA = HexColor("#dde9f5")
GRIGIO = HexColor("#64748b")
RIGA = HexColor("#e2e8f0")
COLORI = {"I": HexColor("#fde68a"), "L": HexColor("#bfdbfe"), "U": HexColor("#bbf7d0"), "O": HexColor("#c7d2fe")}


def _triangolo(c, x: float, y: float, lato: float) -> None:
    p = c.beginPath()
    p.moveTo(x - lato / 2, y)
    p.lineTo(x + lato / 2, y)
    p.lineTo(x, y + lato)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _adatta(testo: str, font: str, size: float, larghezza: float, minimo: float = 4.5) -> float:
    while size > minimo and stringWidth(testo, font, size) > larghezza:
        size -= 0.5
    return size


def _taglia(testo: str, font: str, size: float, larghezza: float) -> str:
    if stringWidth(testo, font, size) <= larghezza:
        return testo
    while testo and stringWidth(testo + "…", font, size) > larghezza:
        testo = testo[:-1]
    return testo + "…"


def _fogli_colonne(dati: dict, max_colonne: int) -> list[list[int]]:
    """Indici delle colonne per foglio: si spezza fra i reparti, un reparto troppo
    largo si spezza a sua volta."""
    fogli: list[list[int]] = [[]]
    i = 0
    for g in dati["gruppi_colonne"]:
        idx = list(range(i, i + len(g["colonne"])))
        i += len(g["colonne"])
        if fogli[-1] and len(fogli[-1]) + len(idx) > max_colonne:
            fogli.append([])
        while len(idx) > max_colonne:
            if fogli[-1]:
                fogli.append([])
            fogli[-1].extend(idx[:max_colonne])
            idx = idx[max_colonne:]
            fogli.append([])
        fogli[-1].extend(idx)
    return [f for f in fogli if f] or [[]]


def _gruppi_di(dati: dict, indici: list[int]) -> list[tuple[dict, list[int]]]:
    """(gruppo, indici del foglio) nell'ordine delle colonne."""
    esito = []
    for i in indici:
        col = dati["colonne"][i]
        if not esito or esito[-1][0]["reparto"] != col["reparto"]:
            g = next(g for g in dati["gruppi_colonne"] if g["reparto"] == col["reparto"])
            esito.append((g, []))
        esito[-1][1].append(i)
    return esito


# ── MOD.187 ─────────────────────────────────────────────────────────────

def pdf_mod187(dati: dict, *, data_documento, reparto: str = "") -> bytes:
    W, H = PAGINA
    mx, top, bottom = 34, 34, 30
    w_ruolo, w_orario, w_nome = 92, 15, 128
    sinistra = w_ruolo + w_orario + w_nome
    disponibile = W - 2 * mx - sinistra
    fogli = _fogli_colonne(dati, max(1, int(disponibile // 8.5)))
    h_tit, h_car, h_rep, h_cnt, h_vert, h_riga = 26, 17, 20, 9.5, 118, 11
    h_testa = h_tit + h_car + h_rep + 5 * h_cnt + h_vert
    per_pagina = max(1, int((H - top - bottom - h_testa) // h_riga))
    righe = dati["righe"]
    pagine_righe = [righe[i:i + per_pagina] for i in range(0, len(righe), per_pagina)] or [[]]
    totale_pagine = len(fogli) * len(pagine_righe)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGINA)
    c.setTitle("MOD.187 - SKM Skill Matrix")
    n_pag = 0
    for foglio in fogli:
        cw = min(60.0, disponibile / max(1, len(foglio)))
        larghezza = sinistra + cw * len(foglio)
        for blocco in pagine_righe:
            n_pag += 1
            c.setLineWidth(0.4)
            x0, y = mx, H - top
            # fascia del titolo
            c.setFillColor(FASCIA)
            c.rect(x0 + w_ruolo, y - h_tit, larghezza - w_ruolo, h_tit, fill=1, stroke=0)
            c.setFillColor(black)
            c.rect(x0, y - h_tit, larghezza, h_tit, fill=0, stroke=1)
            c.setFont("Helvetica-Bold", 19)
            c.drawString(x0 + w_ruolo + 4, y - h_tit + 7, "SKILL MATRIX")
            c.setFont("Helvetica-Bold", 7)
            c.drawString(x0 + w_ruolo + 4 + stringWidth("SKILL MATRIX", "Helvetica-Bold", 19) + 12, y - h_tit + 8,
                         "MOD.187 - SKM Skill Matrix Rev.0")
            y -= h_tit
            xc = x0 + sinistra
            # Data / Firma CEO + CAR e reparto sopra i gruppi
            c.rect(x0, y - h_car, w_ruolo + w_orario, h_car)
            c.rect(x0 + w_ruolo + w_orario, y - h_car, w_nome, h_car)
            c.setFont("Helvetica", 7)
            c.drawRightString(x0 + w_ruolo + w_orario - 3, y - h_car + 5, "Data")
            c.drawString(x0 + w_ruolo + w_orario + 3, y - h_car + 5, data_documento.strftime("%d/%m/%Y"))
            c.rect(x0, y - h_car - h_rep, w_ruolo + w_orario, h_rep)
            c.rect(x0 + w_ruolo + w_orario, y - h_car - h_rep, w_nome, h_rep)
            c.drawRightString(x0 + w_ruolo + w_orario - 3, y - h_car - h_rep + 6, "Firma CEO")
            for g, idx in _gruppi_di(dati, foglio):
                gw = cw * len(idx)
                c.rect(xc, y - h_car, gw, h_car)
                c.rect(xc, y - h_car - h_rep, gw, h_rep)
                testo = g["car"] or ""
                fs = _adatta(testo, "Helvetica-Bold", 9, gw - 4)
                c.setFont("Helvetica-Bold", fs)
                c.drawCentredString(xc + gw / 2, y - h_car + 5, testo)
                fs = _adatta(g["reparto"].upper(), "Helvetica-Bold", 12, gw - 4)
                c.setFont("Helvetica-Bold", fs)
                c.drawCentredString(xc + gw / 2, y - h_car - h_rep + 6, g["reparto"].upper())
                xc += gw
            y -= h_car + h_rep
            # legenda + totali per livello
            for k in list(LIVELLI) + ["tot"]:
                c.rect(x0, y - h_cnt, w_ruolo + w_orario, h_cnt)
                c.rect(x0 + w_ruolo + w_orario, y - h_cnt, w_nome, h_cnt)
                if k != "tot":
                    c.setFont("Helvetica-Bold", 6.5)
                    c.drawString(x0 + w_ruolo + w_orario + 3, y - h_cnt + 2.5, k)
                    c.setFont("Helvetica", 6.5)
                    c.drawString(x0 + w_ruolo + w_orario + 10, y - h_cnt + 2.5, f"= {LEGENDA[k]}")
                xc = x0 + sinistra
                for i in foglio:
                    col = dati["colonne"][i]
                    c.rect(xc, y - h_cnt, cw, h_cnt)
                    v = col["totale"] if k == "tot" else col["conta"][k]
                    c.setFont("Helvetica-Bold" if k == "tot" else "Helvetica", min(6.5, cw * .7))
                    c.drawCentredString(xc + cw / 2, y - h_cnt + 2.5, str(v))
                    xc += cw
                y -= h_cnt
            # intestazioni verticali
            c.rect(x0, y - h_vert, w_ruolo, h_vert)
            c.rect(x0 + w_ruolo, y - h_vert, w_orario, h_vert)
            c.rect(x0 + w_ruolo + w_orario, y - h_vert, w_nome, h_vert)
            c.setFont("Helvetica-Bold", 8)
            c.drawRightString(x0 + w_ruolo - 3, y - h_vert + 3, "Ruolo")
            c.drawRightString(x0 + sinistra - 3, y - h_vert + 3, "Nome Operatore")
            c.saveState()
            c.translate(x0 + w_ruolo + w_orario / 2 + 2.5, y - h_vert + 3)
            c.rotate(90)
            c.setFont("Helvetica", 6)
            c.drawString(0, 0, "Orario as is")
            c.restoreState()
            xc = x0 + sinistra
            for i in foglio:
                col = dati["colonne"][i]
                c.rect(xc, y - h_vert, cw, h_vert)
                fs = min(6.5, cw * .72)
                c.saveState()
                c.translate(xc + cw / 2 + fs / 3, y - h_vert + 3)
                c.rotate(90)
                c.setFont("Helvetica", fs)
                c.drawString(0, 0, _taglia(col["nome"], "Helvetica", fs, h_vert - 6))
                c.restoreState()
                xc += cw
            y -= h_vert
            # righe
            for r in blocco:
                if r["car"]:
                    c.setFillColor(AZZURRO_CAR)
                    c.rect(x0, y - h_riga, sinistra, h_riga, fill=1, stroke=0)
                    c.setFillColor(black)
                c.rect(x0, y - h_riga, w_ruolo, h_riga)
                c.rect(x0 + w_ruolo, y - h_riga, w_orario, h_riga)
                c.rect(x0 + w_ruolo + w_orario, y - h_riga, w_nome, h_riga)
                c.setFont("Helvetica", 6.5)
                c.drawRightString(x0 + w_ruolo - 2, y - h_riga + 3, _taglia(r["ruolo"].upper(), "Helvetica", 6.5, w_ruolo - 4))
                c.drawCentredString(x0 + w_ruolo + w_orario / 2, y - h_riga + 3, r["orario"])
                c.drawRightString(x0 + sinistra - 2, y - h_riga + 3, _taglia(r["nome_mod"], "Helvetica", 6.5, w_nome - 4))
                xc = x0 + sinistra
                for i in foglio:
                    c.rect(xc, y - h_riga, cw, h_riga)
                    cella = r["celle"][i]
                    if cella and cella["livello"]:
                        b = min(cw - 3, 9)
                        c.rect(xc + (cw - b) / 2, y - h_riga + 1.5, b, h_riga - 3)
                        c.setFont("Helvetica", min(6.5, cw * .7))
                        c.drawCentredString(xc + cw / 2, y - h_riga + 3, cella["livello"])
                    xc += cw
                y -= h_riga
            c.setFont("Helvetica", 7)
            c.drawRightString(W - mx, bottom - 14, f"Pag. {n_pag}/{totale_pagine}")
            if reparto:
                c.drawString(mx, bottom - 14, f"Reparto: {reparto}")
            c.showPage()
    c.save()
    return buf.getvalue()


# ── Report HUB ──────────────────────────────────────────────────────────

def pdf_hub(dati: dict, *, kpi: list[tuple[str, str, str]], filtri: str, generato_da: str, quando) -> bytes:
    W, H = PAGINA
    mx = 30
    w_nome, w_tot = 150, 40
    disponibile = W - 2 * mx - w_nome - w_tot
    fogli = _fogli_colonne(dati, max(1, int(disponibile // 15)))
    h_banda, h_kpi, h_grp, h_vert, h_riga, h_rep = 50, 46, 16, 104, 13, 12
    corpo_alto = H - h_banda - 16 - h_kpi - 12 - h_grp - h_vert - 60

    # righe con intestazione di reparto: impaginazione
    voci = []
    for g in dati["gruppi_righe"]:
        voci.append(("rep", g["reparto"]))
        voci.extend(("riga", r) for r in g["righe"])
    pagine, corrente, alto = [], [], 0.0
    for v in voci:
        h = h_rep if v[0] == "rep" else h_riga
        if corrente and alto + h > corpo_alto:
            pagine.append(corrente)
            corrente, alto = [], 0.0
        corrente.append(v)
        alto += h
    pagine.append(corrente)
    totale_pagine = len(fogli) * len(pagine)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGINA)
    c.setTitle("Skill Matrix - Report HUB")
    n_pag = 0
    for foglio in fogli:
        cw = min(34.0, disponibile / max(1, len(foglio)))
        for blocco in pagine:
            n_pag += 1
            # banda
            c.setFillColor(NAVY)
            c.rect(0, H - h_banda, W, h_banda, fill=1, stroke=0)
            c.setFillColor(ARANCIO)
            c.roundRect(mx, H - h_banda + 13, 40, 24, 6, fill=1, stroke=0)
            c.setFillColor(white)
            c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(mx + 20, H - h_banda + 21, "HUB")
            c.setFont("Helvetica-Bold", 17)
            c.drawString(mx + 52, H - h_banda + 26, "Skill Matrix — abilitazioni")
            c.setFont("Helvetica", 9)
            c.drawString(mx + 52, H - h_banda + 12, filtri)
            c.drawRightString(W - mx, H - h_banda + 26, f"Report del {quando:%d/%m/%Y} ore {quando:%H:%M}")
            c.drawRightString(W - mx, H - h_banda + 12, f"generato da {generato_da}")
            y = H - h_banda - 16
            # numeri chiave
            kw = (W - 2 * mx - 3 * 10) / 4
            for n, (valore, etichetta, colore) in enumerate(kpi[:4]):
                x = mx + n * (kw + 10)
                c.setStrokeColor(RIGA)
                c.setFillColor(white)
                c.roundRect(x, y - h_kpi, kw, h_kpi, 7, fill=1, stroke=1)
                c.setFillColor(HexColor(colore))
                c.rect(x + 1, y - 3, kw - 2, 3, fill=1, stroke=0)
                c.setFillColor(NAVY)
                c.setFont("Helvetica-Bold", 18)
                c.drawString(x + 10, y - 24, str(valore))
                c.setFillColor(GRIGIO)
                c.setFont("Helvetica", 8.5)
                c.drawString(x + 10, y - 38, etichetta)
            y -= h_kpi + 12
            x0 = mx
            # gruppi di colonne
            xc = x0 + w_nome
            for g, idx in _gruppi_di(dati, foglio):
                gw = cw * len(idx)
                c.setFillColor(HexColor("#f1f5f9"))
                c.rect(xc + .5, y - h_grp, gw - 1, h_grp, fill=1, stroke=0)
                c.setFillColor(NAVY)
                testo = g["reparto"] + (f" · CAR {g['car']}" if g["car"] else "")
                fs = _adatta(testo, "Helvetica-Bold", 8, gw - 4)
                c.setFont("Helvetica-Bold", fs)
                c.drawCentredString(xc + gw / 2, y - h_grp + 5, _taglia(testo, "Helvetica-Bold", fs, gw - 4))
                xc += gw
            y -= h_grp
            # intestazioni verticali
            c.setFillColor(GRIGIO)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(x0 + 2, y - h_vert + 4, "Persona")
            c.saveState()
            c.translate(x0 + w_nome + cw * len(foglio) + w_tot / 2 + 3, y - h_vert + 4)
            c.rotate(90)
            c.drawString(0, 0, "Operativo su")
            c.restoreState()
            xc = x0 + w_nome
            for i in foglio:
                col = dati["colonne"][i]
                c.saveState()
                c.translate(xc + cw / 2 + 2.5, y - h_vert + 4)
                c.rotate(90)
                c.setFillColor(black)
                c.setFont("Helvetica", 7)
                c.drawString(0, 0, _taglia(col["nome"], "Helvetica", 7, h_vert - 26))
                c.setFillColor(HexColor("#16a34a"))
                c.setFont("Helvetica-Bold", 6.5)
                c.drawString(h_vert - 22, 0, f"{col['operativi']} op.")
                c.restoreState()
                xc += cw
            y -= h_vert
            c.setStrokeColor(RIGA)
            c.line(x0, y, x0 + w_nome + cw * len(foglio) + w_tot, y)
            # righe
            for tipo, v in blocco:
                if tipo == "rep":
                    c.setFillColor(HexColor("#eef2f7"))
                    c.rect(x0, y - h_rep, w_nome + cw * len(foglio) + w_tot, h_rep, fill=1, stroke=0)
                    c.setFillColor(NAVY)
                    c.setFont("Helvetica-Bold", 8)
                    c.drawString(x0 + 3, y - h_rep + 3.5, v)
                    y -= h_rep
                    continue
                r = v
                c.setFillColor(black)
                c.setFont("Helvetica-Bold" if r["car"] else "Helvetica", 7.5)
                nome = r["nome"] + (" · CAR" if r["car"] else "") + (f" · {r['orario']}" if r["orario"] else "")
                c.drawString(x0 + 3, y - h_riga + 4, _taglia(nome, "Helvetica", 7.5, w_nome - 6))
                xc = x0 + w_nome
                for i in foglio:
                    cella = r["celle"][i]
                    if cella and cella["livello"]:
                        b = min(cw - 4, 18)
                        bx, by = xc + (cw - b) / 2, y - h_riga + 2
                        c.setFillColor(HexColor("#e2e8f0") if cella["sospesa"] else COLORI.get(cella["livello"], RIGA))
                        c.roundRect(bx, by, b, h_riga - 4, 2.5, fill=1, stroke=0)
                        if cella["arretrata"]:
                            c.setStrokeColor(HexColor("#b45309"))
                            c.setDash(1.5, 1.2)
                            c.roundRect(bx, by, b, h_riga - 4, 2.5, fill=0, stroke=1)
                            c.setDash()
                        c.setFillColor(GRIGIO if cella["sospesa"] else NAVY)
                        c.setFont("Helvetica-Bold", 7)
                        c.drawCentredString(xc + cw / 2, y - h_riga + 4.2, cella["livello"])
                        if cella["sotto"]:
                            c.setFillColor(HexColor("#dc2626"))
                            _triangolo(c, bx + b + 2, by + h_riga - 5, 3.2)
                    xc += cw
                c.setFillColor(NAVY)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawCentredString(xc + w_tot / 2, y - h_riga + 4, str(sum(1 for i in foglio if r["celle"][i] and r["celle"][i]["operativa"])))
                c.setStrokeColor(RIGA)
                c.line(x0, y - h_riga, xc + w_tot, y - h_riga)
                y -= h_riga
            # operativi per colonna
            c.setFillColor(HexColor("#eef2f7"))
            c.rect(x0, y - h_rep - 2, w_nome + cw * len(foglio) + w_tot, h_rep + 2, fill=1, stroke=0)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(x0 + 3, y - h_rep + 2, "Operativi per colonna")
            xc = x0 + w_nome
            for i in foglio:
                c.drawCentredString(xc + cw / 2, y - h_rep + 2, str(dati["colonne"][i]["operativi"]))
                xc += cw
            y -= h_rep + 14
            # legenda
            xl = x0
            c.setFont("Helvetica", 7.5)
            for k in LIVELLI:
                c.setFillColor(COLORI[k])
                c.roundRect(xl, y - 3, 12, 10, 2, fill=1, stroke=0)
                c.setFillColor(NAVY)
                c.setFont("Helvetica-Bold", 7)
                c.drawCentredString(xl + 6, y, k)
                c.setFont("Helvetica", 7.5)
                c.setFillColor(GRIGIO)
                testo = LEGENDA[k]
                c.drawString(xl + 15, y, testo)
                xl += 22 + stringWidth(testo, "Helvetica", 7.5) + 10
            c.drawString(xl, y, "bordo tratteggiato = da rivalutare · grigio = sospesa · triangolo rosso = sotto il livello richiesto")
            # piede
            c.setFillColor(GRIGIO)
            c.setFont("Helvetica", 7.5)
            c.drawString(mx, 16, "NOVICROM HUB · Anagrafica › Competenze › Skill Matrix · documento interno: il modulo firmato è il MOD.187")
            c.drawRightString(W - mx, 16, f"Pagina {n_pag} di {totale_pagine}")
            c.showPage()
    c.save()
    return buf.getvalue()
