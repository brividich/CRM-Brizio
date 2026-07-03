"""#2 parte 2 — Sovrapposizione dei timbri sul composito (pymupdf).

Timbri distinti (ognuno gestito in Admin, per capocommessa):
- **RICEVUTO** (timbro del compilatore): **solo sulle pagine del documento originale** (NON sul
  MOD.133), in alto a destra, con la **data odierna** scritta nella banda centrale vuota del timbro.
- **Firma MOD.133 Revisore** (timbro del compilatore): nell'area firma «Revisore Autorizzato» (sx).
- **Firma MOD.133 Approvatore** (timbro dell'approvatore): nell'area firma «Approvazione» (dx).

I timbri sono PNG (idealmente con trasparenza). Le posizioni sono costanti tarabili.
"""
from __future__ import annotations

import fitz

# Proporzioni note dei PNG forniti (w/h) — per dimensionare mantenendo l'aspetto.
_RATIO_RICEVUTO = 296 / 196   # ~1.51
_RATIO_MOD133 = 736 / 489     # ~1.505

# RICEVUTO: larghezza in punti + margini dall'angolo alto-destra della pagina.
_RIC_W = 120.0
_RIC_MARGIN_X = 16.0
_RIC_MARGIN_Y = 12.0
# Banda della data dentro il timbro RICEVUTO (frazioni dell'altezza del timbro).
_RIC_DATA_TOP = 0.34
_RIC_DATA_BOT = 0.66

# Firme sul MOD.133: larghezza + angolo alto-sinistra dei due blocchi firma (misurati sul template).
_STAMP_W = 115.0
_STAMP_REVISORE_XY = (92.0, 700.0)      # blocco «Revisore Autorizzato» (sinistra)
_STAMP_APPROVATORE_XY = (360.0, 700.0)  # blocco «Responsabile Approvazione» (destra)


def _fit_center(page, rect, text, color):
    """Scrive `text` centrato in `rect`, rimpicciolendo finché entra (colore RGB 0-1)."""
    text = (text or "").strip()
    if not text:
        return
    for size in (12, 11, 10, 9, 8, 7):
        if page.insert_textbox(rect, text, fontsize=size, fontname="helv",
                               align=1, color=color) >= 0:
            return


def applica_timbri(pdf_bytes: bytes, *, ricevuto: bytes | None = None,
                   stamp_revisore: bytes | None = None, stamp_approvatore: bytes | None = None,
                   data_testo: str = "", n_pagine_mod133: int = 1) -> bytes:
    """Ritorna il composito con i timbri sovrapposti. Non modifica l'input.

    Il composito è [MOD.133 (prime ``n_pagine_mod133`` pagine)] + [documento originale].
    RICEVUTO va SOLO sulle pagine dell'originale; le firme vanno sull'ultima pagina del MOD.133.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    ric_h = _RIC_W / _RATIO_RICEVUTO
    stamp_h = _STAMP_W / _RATIO_MOD133
    ultima_mod133 = max(0, n_pagine_mod133 - 1)
    for pno, page in enumerate(doc):
        r = page.rect
        # RICEVUTO — solo sulle pagine del documento ORIGINALE (dopo il MOD.133)
        if ricevuto and pno >= n_pagine_mod133:
            x1 = r.width - _RIC_MARGIN_X
            x0 = x1 - _RIC_W
            y0 = _RIC_MARGIN_Y
            page.insert_image(fitz.Rect(x0, y0, x1, y0 + ric_h), stream=ricevuto,
                              keep_proportion=True, overlay=True)
            if data_testo:
                band = fitz.Rect(x0 + 4, y0 + ric_h * _RIC_DATA_TOP,
                                 x1 - 4, y0 + ric_h * _RIC_DATA_BOT)
                _fit_center(page, band, data_testo, (0.05, 0.05, 0.6))
        # Firme sul MOD.133 (ultima pagina del MOD.133)
        if pno == ultima_mod133:
            if stamp_revisore:
                x0, y0 = _STAMP_REVISORE_XY
                page.insert_image(fitz.Rect(x0, y0, x0 + _STAMP_W, y0 + stamp_h),
                                  stream=stamp_revisore, keep_proportion=True, overlay=True)
            if stamp_approvatore:
                x0, y0 = _STAMP_APPROVATORE_XY
                page.insert_image(fitz.Rect(x0, y0, x0 + _STAMP_W, y0 + stamp_h),
                                  stream=stamp_approvatore, keep_proportion=True, overlay=True)
    out = doc.tobytes()
    doc.close()
    return out
