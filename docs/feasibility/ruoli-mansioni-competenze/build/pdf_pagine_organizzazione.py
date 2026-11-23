"""Un solo PDF con le pagine proposte per la sezione «Organizzazione»: una schermata per pagina.

    python pdf_pagine_organizzazione.py

Legge le immagini di ``ui_completa/pagine`` in ordine di nome e scrive
``Organizzazione_pagine_proposte.pdf`` nella cartella dei documenti da presentare.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

RADICE = Path(__file__).resolve().parent.parent
PAGINE = RADICE / "ui_completa" / "pagine"
USCITA = RADICE / "Organizzazione_pagine_proposte_v3.pdf"  # v1 e v2 restano come erano (23/11/2026)

TITOLI = {
    "00_panoramica": ("Panoramica", "La pagina che si apre cliccando «Organizzazione»: numeri, collegamenti diretti, cose da fare."),
    "01_esplora_la_struttura": ("Esplora la struttura", "Dal centro di costo alla mansione: che cosa richiede e chi ce l'ha."),
    "01b_esplora_mansioni_per_prime": ("Esplora la struttura, con «Mansioni» per prima",
                                       "La stessa pagina dopo aver spostato la colonna: si parte dalla mansione."),
    "02_mansioni": ("Mansioni", "Tutte le mansioni, con le competenze richieste e le persone."),
    "03_richieste": ("Richieste", "Ogni cambio su una mansione o su una competenza parte da qui."),
    "04_reparti_e_capi": ("Reparti e capi", "Chi guida ogni reparto e quante persone ci lavorano."),
    "05_centri_di_costo": ("Centri di costo", "Quali reparti stanno in quale centro di costo."),
    "06_organigramma": ("Organigramma", "Chi riporta a chi."),
    "07_prova_un_cambiamento": ("Prova un cambiamento", "Oggi e dopo fianco a fianco, prima di spostare persone o ruoli."),
    "08_struttura_e_revisioni": ("Struttura e revisioni", "La struttura approvata dalla Qualità e ciò che è cambiato."),
}

immagini = sorted(p for p in PAGINE.glob("*.png") if p.stem in TITOLI)
fogli = ""
for n, img in enumerate(immagini, 1):
    titolo, sotto = TITOLI[img.stem]
    fogli += (f'<section><header><b>{n}. {titolo}</b><span>{sotto}</span><em>{n} di {len(immagini)}</em></header>'
              f'<img src="{img.as_uri()}" alt="{titolo}"></section>')

HTML = f"""<!doctype html><html lang="it"><head><meta charset="utf-8"><title>Organizzazione: pagine proposte</title>
<style>
@page {{ size: A4 landscape; margin: 9mm 10mm; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #1a202c; }}
section {{ height: 192mm; display: flex; flex-direction: column; break-after: page; }}
section:last-child {{ break-after: auto; }}
header {{ display: flex; align-items: baseline; gap: 10px; padding: 0 0 3mm; border-bottom: 0.4mm solid #002b5c; margin: 0 0 3mm; }}
header b {{ font-size: 13pt; color: #002b5c; white-space: nowrap; }}
header span {{ font-size: 9.5pt; color: #4a5568; }}
header em {{ margin-left: auto; font-style: normal; font-size: 8.5pt; color: #94a3b8; white-space: nowrap; }}
img {{ display: block; margin: 0 auto; max-width: 100%; max-height: 176mm; border: 0.2mm solid #d7e0ea; }}
</style></head><body>{fogli}</body></html>"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page()
    foglio = PAGINE / "_unico.html"
    foglio.write_text(HTML, encoding="utf-8")
    pg.goto(foglio.as_uri(), wait_until="load")
    pg.wait_for_timeout(500)
    rotte = pg.evaluate("[...document.images].filter(i => !i.complete || !i.naturalWidth).length")
    pg.pdf(path=str(USCITA), format="A4", landscape=True, print_background=True, prefer_css_page_size=True)
    foglio.unlink()
    b.close()

try:
    import fitz  # PyMuPDF

    with fitz.open(str(USCITA)) as documento:
        pagine_pdf = documento.page_count
        con_immagine = sum(1 for foglio_pdf in documento if foglio_pdf.get_images())
except Exception:  # PyMuPDF non installato: il controllo resta sulle immagini caricate
    pagine_pdf, con_immagine = "?", "?"
print("pagine con immagine:", con_immagine)
print("schermate:", len(immagini), "| immagini non caricate:", rotte, "| pagine del PDF:", pagine_pdf,
      "| peso KB:", USCITA.stat().st_size // 1024, "|", USCITA)
