"""Cattura in PNG le due tavole di ``ui_completa/proposta.html`` (dati inventati)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

RADICE = Path(__file__).resolve().parent.parent / "ui_completa"
NOMI = {"s1": "02_dashboard_proposta", "s2": "03_menu_proposto"}

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pagina = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pagina.goto((RADICE / "proposta.html").as_uri())
    pagina.wait_for_timeout(500)
    for ident, nome in NOMI.items():
        el = pagina.locator(f"#{ident}")
        el.screenshot(path=str(RADICE / f"{nome}.png"))
        box = el.bounding_box()
        print(nome, int(box["width"]), "x", int(box["height"]),
              "| sborda:", pagina.evaluate(f"document.getElementById('{ident}').scrollWidth > 1440"),
              "| vai a, punti dall'alto:", pagina.evaluate(
                  "(() => { const e = document.querySelector('#s1 .vai'); return Math.round(e.getBoundingClientRect().top - document.getElementById('s1').getBoundingClientRect().top); })()"))
    b.close()
