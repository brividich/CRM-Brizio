"""Planimetrie delle verifiche periodiche: punti e foglio stampabile «layout Novicrom».

Il foglio lo genera il portale, quindi di ogni punto si sa dove cade. Tre scelte,
le stesse del foglio firme della formazione (``anagrafica/services/foglio_firme.py``):

1. **Un QR porta il token della verifica**: la scansione torna da sola alla verifica
   giusta, nessuna associazione da fare a mano.
2. **Quattro marcatori d'angolo** e la planimetria stessa servono a raddrizzare la
   scansione (storta, ruotata, A3 o A4).
3. **Si segna solo sulla planimetria**: evidenziatore e cerchio a penna. Nessuna
   lista scritta a mano da leggere; il vecchio cartiglio «non funzionanti / bassa
   autonomia» viene coperto.

Le coordinate sono in punti PDF. Quelle dei punti sono salvate sulla planimetria
originale; :func:`sheet_geometry` le porta sul foglio.
"""
from __future__ import annotations

import math
import re
import secrets
from dataclasses import dataclass
from datetime import date
from io import BytesIO

import fitz  # PyMuPDF

SHEET_W, SHEET_H = fitz.paper_size("a4")  # verticale
MM = 72 / 25.4
MARKER = 6 * MM
MARKER_MARGIN = 8 * MM
HEADER_TOP = MARKER_MARGIN + MARKER + 4
HEADER_H = 92
PLAN_MARGIN = 14 * MM
FOOTER_H = 16
QR_SIZE = 64

TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
QR_PREFIX = "NVC-VP:"


def generate_token(exists) -> str:
    """Token breve senza caratteri ambigui; ``exists(token)`` dice se e' gia' usato."""
    for _ in range(50):
        token = "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(10))
        if not exists(token):
            return token
    raise RuntimeError("impossibile generare un token univoco per il foglio di verifica")


def token_from_qr(text: str) -> str:
    text = (text or "").strip().upper()
    if text.startswith(QR_PREFIX):
        text = text[len(QR_PREFIX):]
    return text[:16] if re.fullmatch(r"[A-Z0-9]{6,16}", text[:16] or "-") else ""


# ---------------------------------------------------------------------------
# Estrazione dei punti dalla planimetria vettoriale
# ---------------------------------------------------------------------------

def _is_red(color) -> bool:
    return bool(color) and len(color) == 3 and color[0] > 0.9 and color[1] < 0.1 and color[2] < 0.1


STYLE_RED_X = "riquadro rosso con la X e numero rosso"
STYLE_MARKER = "quadratino colorato con l'etichetta accanto"

# Etichette dei punti nel secondo stile: «D12», «D3/A», «Q2», oppure solo il numero.
MARKER_LABEL = re.compile(r"[A-Z]{0,2}\d{1,3}(?:/[A-Z])?")


def _centre(r) -> tuple[float, float]:
    return (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2


def _pair(labels, symbols, max_dist) -> list[dict]:
    """Abbina etichette e simboli per distanza crescente, uno a uno."""
    pairs = sorted(
        (math.hypot(sx - lx, sy - ly), i, j)
        for i, (_, lx, ly) in enumerate(labels)
        for j, (sx, sy) in enumerate(symbols)
        if abs(sx - lx) <= max_dist and abs(sy - ly) <= max_dist
    )
    used_l, used_s, points, seen = set(), set(), [], {}
    for dist, i, j in pairs:
        if i in used_l or j in used_s or dist > max_dist:
            continue
        used_l.add(i)
        used_s.add(j)
        code, lx, ly = labels[i]
        seen[code] = seen.get(code, 0) + 1
        if seen[code] > 1:  # stessa etichetta due volte sulla tavola: restano distinte
            code = f"{code} ({seen[code]})"
        sx, sy = symbols[j]
        points.append({"code": code, "x": round(sx, 2), "y": round(sy, 2), "label_x": round(lx, 2), "label_y": round(ly, 2)})
    return points


def point_sort_key(code: str):
    """«7» < «D3» < «D3/A» < «D12»: prima le lettere, poi il numero, poi il suffisso."""
    match = re.match(r"([A-Z]*)(\d+)(.*)", code)
    if not match:
        return (code, 0, "")
    return (match.group(1), int(match.group(2)), match.group(3))


def _sort_key(point: dict):
    return point_sort_key(point["code"])


def _red_x_points(page) -> list[dict]:
    """Stile luci di emergenza: riquadro rosso con la X (a tratti o a triangoli pieni) + numero rosso."""
    boxes, crosses = [], []
    for g in page.get_drawings():
        r = g["rect"]
        if _is_red(g.get("color")):
            if 7 <= r.width <= 11 and 7 <= r.height <= 11 and abs(r.width - r.height) < 0.6:
                boxes.append(r)
            elif 3.5 <= max(r.width, r.height) <= 9 and len(g["items"]) >= 8:
                crosses.append(r)
        elif _is_red(g.get("fill")) and 3.5 <= max(r.width, r.height) <= 6:
            crosses.append(r)
    labels = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                txt = span["text"].strip()
                if re.fullmatch(r"\d{1,3}", txt) and span["color"] == 0xFF0000:
                    labels.append((txt, *_centre(fitz.Rect(span["bbox"]))))
    x_boxes = [
        _centre(b) for b in boxes
        if any(abs(_centre(c)[0] - _centre(b)[0]) < 3 and abs(_centre(c)[1] - _centre(b)[1]) < 3 for c in crosses)
    ]
    return _pair(labels, x_boxes, 25)


def _is_marker(g) -> bool:
    fill = g.get("fill")
    r = g["rect"]
    if not fill or len(fill) != 3 or not (3 <= r.width <= 10 and 3 <= r.height <= 10):
        return False
    if max(r.width, r.height) / max(0.1, min(r.width, r.height)) > 2.2:
        return False
    return max(fill) - min(fill) > 0.4  # colore acceso, non grigio


def _marker_points(page) -> list[dict]:
    """Stile differenziali: quadratino pieno colorato con l'etichetta accanto (D12, D3/A, 7).

    Un'etichetta puo' contenere piu' codici attaccati («D52D53»): ognuno prende la
    posizione dei propri caratteri."""
    symbols = [_centre(g["rect"]) for g in page.get_drawings() if _is_marker(g)]
    labels = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                chars = span.get("chars", [])
                text = "".join(c["c"] for c in chars)
                for match in MARKER_LABEL.finditer(text):
                    boxes = [fitz.Rect(c["bbox"]) for c in chars[match.start():match.end()]]
                    if not boxes:
                        continue
                    rect = boxes[0]
                    for box in boxes[1:]:
                        rect |= box
                    labels.append((match.group(), *_centre(rect)))
    return _pair(labels, symbols, 16)


def extract_points(pdf_bytes: bytes, page_index: int = 0) -> list[dict]:
    """Punti numerati della planimetria, riconosciuti dal disegno.

    Due stili: le luci di emergenza (riquadro rosso con la X + numero rosso) e i
    differenziali (quadratino colorato con l'etichetta accanto). Vince quello che
    trova piu' punti."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_index]
        candidates = [(STYLE_RED_X, _red_x_points(page)), (STYLE_MARKER, _marker_points(page))]
    style, points = max(candidates, key=lambda c: len(c[1]))
    points.sort(key=_sort_key)
    for p in points:
        p["style"] = style
    return points


# ---------------------------------------------------------------------------
# Foglio stampabile
# ---------------------------------------------------------------------------

@dataclass
class SheetGeometry:
    """Dove finisce la planimetria sul foglio: plan_pt * scale + offset."""

    scale: float
    dx: float
    dy: float
    plan_rect: tuple[float, float, float, float]

    def to_sheet(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.dx, y * self.scale + self.dy

    def rect_to_sheet(self, rect) -> tuple[float, float, float, float]:
        x0, y0 = self.to_sheet(rect[0], rect[1])
        x1, y1 = self.to_sheet(rect[2], rect[3])
        return x0, y0, x1, y1


def sheet_geometry(plan_w: float, plan_h: float) -> SheetGeometry:
    top = HEADER_TOP + HEADER_H + 6
    bottom = SHEET_H - MARKER_MARGIN - MARKER - FOOTER_H
    avail_w = SHEET_W - 2 * PLAN_MARGIN
    avail_h = bottom - top
    scale = min(avail_w / plan_w, avail_h / plan_h)
    w, h = plan_w * scale, plan_h * scale
    dx = (SHEET_W - w) / 2
    dy = top + (avail_h - h) / 2
    return SheetGeometry(scale, dx, dy, (dx, dy, dx + w, dy + h))


def marker_rects() -> list[fitz.Rect]:
    m, s = MARKER_MARGIN, MARKER
    return [
        fitz.Rect(m, m, m + s, m + s),
        fitz.Rect(SHEET_W - m - s, m, SHEET_W - m, m + s),
        fitz.Rect(m, SHEET_H - m - s, m + s, SHEET_H - m),
        fitz.Rect(SHEET_W - m - s, SHEET_H - m - s, SHEET_W - m, SHEET_H - m),
    ]


def _qr_png(text: str) -> bytes:
    import qrcode

    qr = qrcode.QRCode(box_size=6, border=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    buf = BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def _draw_frame(page, *, title: str, subtitle: str, token: str, legend: str, printed_on: date | None,
                page_label: str = "") -> None:
    """Marcatori d'angolo, intestazione (titolo, data/tecnico/firma, legenda, QR) e pie' di pagina:
    uguali per il foglio a planimetria e per quello a misure."""
    for rect in marker_rects():
        page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0), width=0)
    left = PLAN_MARGIN
    top = HEADER_TOP
    qr_left = SHEET_W - PLAN_MARGIN - QR_SIZE
    page.insert_text((left, top + 12), "NOVICROM · VERIFICA PERIODICA", fontsize=7.5, fontname="hebo", color=(0.35, 0.35, 0.35))
    title_size = 13.0
    while title_size > 8 and fitz.get_text_length(title, fontname="hebo", fontsize=title_size) > qr_left - 12 - left:
        title_size -= 0.5
    page.insert_text((left, top + 29), title, fontsize=title_size, fontname="hebo", color=(0, 0, 0))
    if subtitle:
        page.insert_text((left, top + 42), subtitle, fontsize=8, fontname="helv", color=(0.3, 0.3, 0.3))
    y = top + 48
    fields = [("Data", 88), ("Tecnico", 160), ("Firma", qr_left - 12 - left - 88 - 160 - 16)]
    x = left
    for label, width in fields:
        page.insert_text((x, y + 8), label, fontsize=6.5, fontname="helv", color=(0.35, 0.35, 0.35))
        page.draw_rect(fitz.Rect(x, y + 10, x + width, y + 26), color=(0.4, 0.4, 0.4), width=0.6)
        x += width + 8
    page.insert_text((left, top + 86), legend, fontsize=7.5, fontname="hebo", color=(0.1, 0.1, 0.1))
    if token:
        page.insert_image(fitz.Rect(qr_left, top, qr_left + QR_SIZE, top + QR_SIZE), stream=_qr_png(QR_PREFIX + token))
        page.insert_text((qr_left, top + QR_SIZE + 9), token, fontsize=7, fontname="cour", color=(0.2, 0.2, 0.2))
    footer_y = SHEET_H - MARKER_MARGIN - 4
    footer = f"Foglio generato dal portale{' il ' + printed_on.strftime('%d/%m/%Y') if printed_on else ''}"
    footer += " · scansionare intero, senza ritagli" + (f" · codice {token}" if token else "")
    if page_label:
        footer += f" · {page_label}"
    page.insert_text((MARKER_MARGIN + MARKER + 6, footer_y), footer, fontsize=6.5, fontname="helv", color=(0.4, 0.4, 0.4))


MEASURE_ROW_H = 17.0


def _fit_text(page, rect, text: str, *, size: float, font: str, color=(0, 0, 0)) -> None:
    """Testo nella casella, rimpicciolito finche' ci sta (insert_textbox non disegna nulla se non entra)."""
    while size >= 4.5:
        if page.insert_textbox(rect, text, fontsize=size, fontname=font, color=color) >= 0:
            return
        size -= 0.5


def build_measure_sheet(
    *,
    title: str,
    subtitle: str = "",
    token: str = "",
    rows: list[str],
    fields: list[dict],
    printed_on: date | None = None,
    blank_rows: int = 4,
) -> bytes:
    """Foglio A4 delle verifiche a misure: griglia punti × grandezze da compilare a mano,
    con la soglia sotto ogni colonna. Piu' pagine se servono, ognuna col suo QR.

    ``fields``: [{"label", "unit", "range"}]. Le ultime righe restano vuote per i punti
    non previsti (es. un interruttore nuovo)."""
    rows = list(rows) + [""] * blank_rows
    top = HEADER_TOP + HEADER_H + 10
    bottom = SHEET_H - MARKER_MARGIN - MARKER - FOOTER_H
    head_h = 34.0
    per_page = max(1, int((bottom - top - head_h) // MEASURE_ROW_H))
    pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] or [[]]
    left, right = PLAN_MARGIN, SHEET_W - PLAN_MARGIN
    label_w = 150.0
    extra = [("Da sostituire", 46.0), ("Note", 96.0)]
    value_w = max(40.0, (right - left - label_w - sum(w for _, w in extra)) / max(1, len(fields)))
    columns = [("Punto", label_w, "")] + [(f["label"], value_w, f"{f.get('unit', '')} {f.get('range', '')}".strip()) for f in fields]
    columns += [(label, width, "") for label, width in extra]

    out = fitz.open()
    for index, chunk in enumerate(pages):
        page = out.new_page(width=SHEET_W, height=SHEET_H)
        _draw_frame(
            page, title=title, subtitle=subtitle, token=token, printed_on=printed_on,
            legend="Scrivi i valori misurati; spunta «Da sostituire» e scrivi una nota dove serve.",
            page_label=f"pagina {index + 1} di {len(pages)}" if len(pages) > 1 else "",
        )
        x = left
        for label, width, sub in columns:
            cell = fitz.Rect(x, top, x + width, top + head_h)
            page.draw_rect(cell, color=(0.3, 0.3, 0.3), fill=(0.93, 0.94, 0.96), width=0.5)
            _fit_text(page, cell + (3, 3, -3, -11), label, size=6.8, font="hebo")
            if sub:
                _fit_text(page, cell + (3, 23, -3, -1), sub, size=6, font="helv", color=(0.3, 0.3, 0.3))
            x += width
        y = top + head_h
        for label in chunk:
            x = left
            for col_index, (_label, width, _sub) in enumerate(columns):
                cell = fitz.Rect(x, y, x + width, y + MEASURE_ROW_H)
                page.draw_rect(cell, color=(0.45, 0.45, 0.45), width=0.4)
                if col_index == 0 and label:
                    page.insert_textbox(cell + (3, 4, -3, -1), label, fontsize=7, fontname="helv", color=(0, 0, 0))
                if _label == "Da sostituire":
                    box = fitz.Rect(cell.x0 + width / 2 - 4.5, cell.y0 + 4, cell.x0 + width / 2 + 4.5, cell.y0 + 13)
                    page.draw_rect(box, color=(0.2, 0.2, 0.2), width=0.6)
                x += width
            y += MEASURE_ROW_H
    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    return data


def build_sheet(
    plan_pdf: bytes,
    *,
    page_index: int = 0,
    title: str,
    subtitle: str = "",
    token: str = "",
    categories: list[str] | None = None,
    exclude_areas: list | None = None,
    printed_on: date | None = None,
) -> tuple[bytes, SheetGeometry]:
    """PDF A4 del foglio di verifica e la geometria con cui leggerlo.

    Senza ``token`` (anteprima, lettura) il QR non c'e': la lettura usa il foglio
    rigenerato come riferimento e il QR non serve ad allinearlo."""
    categories = categories or ["Segnalato"]
    src = fitz.open(stream=plan_pdf, filetype="pdf")
    plan_page = src[page_index]
    geo = sheet_geometry(plan_page.rect.width, plan_page.rect.height)

    out = fitz.open()
    page = out.new_page(width=SHEET_W, height=SHEET_H)
    page.show_pdf_page(fitz.Rect(*geo.plan_rect), src, page_index, keep_proportion=True)
    for area in exclude_areas or []:
        rect = fitz.Rect(*geo.rect_to_sheet(area))
        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
        page.insert_textbox(
            rect + (4, 4, -4, -4),
            "Non scrivere qui:\nsegna sulla planimetria",
            fontsize=7, fontname="helv", color=(0.55, 0.55, 0.55), align=fitz.TEXT_ALIGN_CENTER,
        )
    legend = "Segna sulla planimetria:  evidenziatore = " + categories[0]
    if len(categories) > 1:
        legend += "   ·   cerchio a penna = " + categories[1]
    _draw_frame(page, title=title, subtitle=subtitle, token=token, legend=legend, printed_on=printed_on)

    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    src.close()
    return data, geo
