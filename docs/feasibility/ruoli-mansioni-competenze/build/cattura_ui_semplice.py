"""Cattura in PNG le schermate della bozza ``ui_semplice/bozza.html`` (dati inventati)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

RADICE = Path(__file__).resolve().parent.parent / "ui_semplice"
NOMI = {"s1": "01_struttura", "s2": "02_persona", "s3": "03_richiesta", "s4": "04_da_fare"}

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pagina = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pagina.goto((RADICE / "bozza.html").as_uri())
    pagina.evaluate("document.fonts.ready")
    pagina.wait_for_timeout(400)
    for ident, nome in NOMI.items():
        el = pagina.locator(f"#{ident}")
        el.screenshot(path=str(RADICE / f"{nome}.png"))
        box = el.bounding_box()
        print(nome, int(box["width"]), "x", int(box["height"]),
              "| carattere:", pagina.evaluate("document.fonts.check('14px Outfit')"),
              "| sborda:", pagina.evaluate(f"document.getElementById('{ident}').scrollWidth > 1440"))
    b.close()
