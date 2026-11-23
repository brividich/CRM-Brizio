"""Cattura in PNG le quattro tavole di confronto di ``ui_completa/scelte.html`` (dati inventati)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

RADICE = Path(__file__).resolve().parent.parent / "ui_completa"
NOMI = {"t1": "scelta_1_pilastri", "t2": "scelta_2_skill_matrix", "t3": "scelta_3_nome", "t4": "scelta_4_collegamenti"}

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pagina = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pagina.goto((RADICE / "scelte.html").as_uri())
    pagina.wait_for_timeout(500)
    for ident, nome in NOMI.items():
        el = pagina.locator(f"#{ident}")
        el.screenshot(path=str(RADICE / f"{nome}.png"))
        box = el.bounding_box()
        stretto = pagina.evaluate(
            f"[...document.querySelectorAll('#{ident} .tabs, #{ident} .sub')].some(e => e.scrollWidth > e.clientWidth + 1)")
        print(nome, int(box["width"]), "x", int(box["height"]), "| barre che sbordano:", stretto)
    b.close()
