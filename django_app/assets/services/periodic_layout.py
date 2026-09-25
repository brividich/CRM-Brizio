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


def extract_points(pdf_bytes: bytes, page_index: int = 0, *, label_regex: str = r"\d{1,3}") -> list[dict]:
    """Punti della planimetria: riquadro rosso con la X + etichetta rossa vicina.

    E' il disegno delle planimetrie Novicrom (luci di emergenza). Alcune X sono
    tratti, altre triangoli pieni: entrambe valgono."""
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        page = doc[page_index]
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
                    if re.fullmatch(label_regex, txt) and span["color"] == 0xFF0000:
                        x0, y0, x1, y1 = span["bbox"]
                        labels.append((txt, (x0 + x1) / 2, (y0 + y1) / 2))

    def centre(r):
        return (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2

    x_boxes = [
        b for b in boxes
        if any(abs(centre(c)[0] - centre(b)[0]) < 3 and abs(centre(c)[1] - centre(b)[1]) < 3 for c in crosses)
    ]
    pairs = sorted(
        (math.hypot(bx - lx, by - ly), i, j)
        for i, (_, lx, ly) in enumerate(labels)
        for j, (bx, by) in enumerate(centre(b) for b in x_boxes)
    )
    used_l, used_b, points = set(), set(), []
    for dist, i, j in pairs:
        if i in used_l or j in used_b or dist > 25:
            continue
        used_l.add(i)
        used_b.add(j)
        code, lx, ly = labels[i]
        bx, by = centre(x_boxes[j])
        points.append({"code": code, "x": round(bx, 2), "y": round(by, 2), "label_x": round(lx, 2), "label_y": round(ly, 2)})
    points.sort(key=lambda p: (int(p["code"]) if p["code"].isdigit() else 10**6, p["code"]))
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
    for rect in marker_rects():
        page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0), width=0)

    # Intestazione
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
    legend = "Segna sulla planimetria:  evidenziatore = " + categories[0]
    if len(categories) > 1:
        legend += "   ·   cerchio a penna = " + categories[1]
    page.insert_text((left, top + 86), legend, fontsize=7.5, fontname="hebo", color=(0.1, 0.1, 0.1))

    if token:
        page.insert_image(fitz.Rect(qr_left, top, qr_left + QR_SIZE, top + QR_SIZE), stream=_qr_png(QR_PREFIX + token))
        page.insert_text((qr_left, top + QR_SIZE + 9), token, fontsize=7, fontname="cour", color=(0.2, 0.2, 0.2))

    footer_y = SHEET_H - MARKER_MARGIN - 4
    footer = f"Foglio generato dal portale{' il ' + printed_on.strftime('%d/%m/%Y') if printed_on else ''}"
    footer += " · scansionare intero, senza ritagli" + (f" · codice {token}" if token else "")
    page.insert_text((MARKER_MARGIN + MARKER + 6, footer_y), footer, fontsize=6.5, fontname="helv", color=(0.4, 0.4, 0.4))

    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    src.close()
    return data, geo
