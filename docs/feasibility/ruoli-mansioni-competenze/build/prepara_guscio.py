"""Porta nel prototipo il guscio REALE dell'HUB e le catture delle pagine attuali.

Uso:  python build/prepara_guscio.py <cartella con topnav.html, hrnav.html, oggi_*.png>

I file d'ingresso si ottengono da un server di prova locale su un database SQLite usa-e-getta con dati
sintetici (mai produzione): markup di `nav.topnav` e `.hrnav` di una pagina del modulo Anagrafica, e le
catture a pagina intera delle pagine attuali. Qui vengono ripuliti e copiati in prototipo/src/guscio/ e
prototipo/src/oggi/ (JPEG ridotti), da dove li prende build/costruisci_prototipo.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image

QUI = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1])
GUSCIO = QUI / "prototipo/src/guscio"
OGGI = QUI / "prototipo/src/oggi"
GUSCIO.mkdir(parents=True, exist_ok=True)
OGGI.mkdir(parents=True, exist_ok=True)

top = (SRC / "topnav.html").read_text(encoding="utf-8")
# Utente di prova → etichetta neutra; nessun dato reale nel markup (verificato a mano).
top = re.sub(r"\s+\n", "\n", top)
(GUSCIO / "topnav.html").write_text(top, encoding="utf-8")

hr = (SRC / "hrnav.html").read_text(encoding="utf-8")
# La seconda riga del menu la disegna il prototipo (sezioni e voci della proposta), con le stesse classi.
hr = re.sub(r'<nav class="hrnav-sub".*?</nav>',
            '<nav class="hrnav-sub" aria-label="Competenze"><div class="hrnav-sub-sez" id="px-sez"></div>'
            '<div class="hrnav-sub-voci" role="group" aria-label="Competenze" id="px-voci"></div></nav>', hr, flags=re.S)
hr = re.sub(r"\s+\n", "\n", hr)
(GUSCIO / "hrnav.html").write_text(hr, encoding="utf-8")

for png in sorted(SRC.glob("oggi_*.png")):
    im = Image.open(png).convert("RGB")
    if im.height > 2000:
        im = im.crop((0, 0, im.width, 2000))
    w = 1100
    im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    dest = OGGI / (png.stem + ".jpg")
    im.save(dest, "JPEG", quality=70, optimize=True)
    print(dest.name, f"{dest.stat().st_size / 1024:.0f} KB", im.size)
print("guscio:", [f"{p.name} {p.stat().st_size / 1024:.0f} KB" for p in GUSCIO.iterdir()])
