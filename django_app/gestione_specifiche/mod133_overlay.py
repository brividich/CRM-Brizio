"""#1 — Render del MOD.133 sovrapponendo i dati al TEMPLATE REALE dell'azienda (pymupdf).

Il template è il modulo MOD.133 vuoto reale (``assets/mod133_template.pdf``, 1 pag. A4),
ottenuto una volta dal .docx aziendale. A runtime scriviamo sopra, con pymupdf, i campi di
testata + una riga di tabella per ogni ``RigaMOD133`` + i nomi Revisore/Approvatore.
**Nessun Word/LibreOffice a runtime.** Le coordinate sono misurate sul template (A4 595x842,
origine in alto a sinistra).
"""
from __future__ import annotations

from pathlib import Path

import fitz

TEMPLATE_PATH = Path(__file__).parent / "assets" / "mod133_template.pdf"
_FONT = "helv"
_RIGHE_PER_PAGINA = 7


def _fit_and_draw(page, rect, text, base_size, align=0):
    """Scrive `text` in `rect` scegliendo la dimensione più grande che entra; tronca con … se serve.

    Usa il valore di ritorno di ``insert_textbox`` (>= 0 = entra e ha disegnato; < 0 = non entra,
    nulla disegnato) così da rispettare esattamente il layout di pymupdf, evitando il suo
    comportamento tutto-o-niente.
    """
    text = (text or "").strip()
    if not text:
        return
    for size in (base_size, base_size - 0.5, base_size - 1, base_size - 1.5, base_size - 2, 6.5, 6.0):
        if page.insert_textbox(rect, text, fontsize=size, fontname=_FONT, align=align) >= 0:
            return
    # non entra nemmeno a 6pt: tronca progressivamente (a 6pt) finché entra
    t = text
    while len(t) > 1:
        t = t[: max(1, int(len(t) * 0.85))]
        if page.insert_textbox(rect, t.rstrip() + "…", fontsize=6.0, fontname=_FONT, align=align) >= 0:
            return

# Testata — punto d'inserimento del VALORE (baseline), a destra dell'etichetta.
_HEADER = {
    "fonte":        (318, 71),
    "documento":    (280, 111),
    "documenti_cn": (447, 150),
    "data":         (116, 184),
}

# Colonne della tabella: (x0, x1)
_COLS = {
    "paragrafi":    (56, 113),
    "argomenti":    (115, 220),
    "imp_doc":      (221, 319),
    "imp_op":       (320, 404),
    "paragrafi_cn": (405, 461),
    "argomenti_cn": (462, 570),
}
# Righe dati: (y0, y1) — 7 righe
_ROWS = [(308, 341), (342, 375), (377, 409), (411, 444),
         (445, 478), (479, 512), (514, 546)]

# Blocchi firma (rect dove centrare il nome, sotto l'etichetta)
_FIRMA_REVISORE = (55, 692, 295, 722)
_FIRMA_APPROVATORE = (297, 692, 570, 722)


def _scrivi_riga(page, r: dict, y0, y1) -> None:
    pad = 3
    cells = [
        ("paragrafi", r.get("paragrafi", ""), 8, 1),
        ("argomenti", r.get("argomenti", ""), 7.5, 0),
        ("imp_doc", r.get("impatto_doc", ""), 9, 1),
        ("imp_op", r.get("impatto_operativo", ""), 9, 1),
        ("paragrafi_cn", r.get("paragrafi_cn", ""), 8, 1),
        ("argomenti_cn", r.get("argomenti_cn", ""), 7.5, 0),
    ]
    for col, testo, size, align in cells:
        if not testo:
            continue
        x0, x1 = _COLS[col]
        _fit_and_draw(page, fitz.Rect(x0 + pad, y0 + pad, x1 - pad, y1 - pad), str(testo), size, align=align)


def render_mod133_overlay(dati: dict) -> bytes:
    """Rende il MOD.133 sovrapponendo i dati al template reale. Drop-in di ``render_mod133``.

    ``dati`` è il dict prodotto da ``composito.dati_mod133_da_spec`` (fonte, documento_analizzato,
    documenti_cn_interessati, data, righe[], revisore, approvatore). ~7 righe per pagina.
    """
    righe = list(dati.get("righe") or [])
    header = {
        "fonte": dati.get("fonte", ""),
        "documento": dati.get("documento_analizzato", ""),
        "documenti_cn": dati.get("documenti_cn_interessati", ""),
        "data": dati.get("data", ""),
    }
    doc = fitz.open(str(TEMPLATE_PATH))
    tpl = fitz.open(str(TEMPLATE_PATH))
    chunks = [righe[i:i + _RIGHE_PER_PAGINA] for i in range(0, len(righe), _RIGHE_PER_PAGINA)] or [[]]
    for pi, chunk in enumerate(chunks):
        if pi == 0:
            page = doc[0]
        else:
            page = doc.new_page(width=tpl[0].rect.width, height=tpl[0].rect.height)
            page.show_pdf_page(page.rect, tpl, 0)
        for key, (x, y) in _HEADER.items():
            if header.get(key):
                _fit_and_draw(page, fitz.Rect(x, y - 10, 572, y + 3), header[key], 9)
        for riga, (y0, y1) in zip(chunk, _ROWS):
            _scrivi_riga(page, riga, y0, y1)
        if pi == len(chunks) - 1:
            _fit_and_draw(page, fitz.Rect(*_FIRMA_REVISORE), dati.get("revisore", ""), 10, align=1)
            _fit_and_draw(page, fitz.Rect(*_FIRMA_APPROVATORE), dati.get("approvatore", ""), 10, align=1)
    out = doc.tobytes()
    doc.close()
    tpl.close()
    return out
