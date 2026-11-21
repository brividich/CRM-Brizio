"""Verifica il prototipo con Playwright (Chromium) e salva le schermate in prototipo/png/.

Uso:  python build/verifica_prototipo.py
Apre ogni schermata, esegue le interazioni chiave (filtro della matrice, «Perché?», simulazione del
cambio mansione, anteprima d'impatto, coda del responsabile), controlla che la console non riporti
errori, che non partano richieste di rete e che i numeri coincidano con build/risultati.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

QUI = Path(__file__).resolve().parent.parent
FILE = (QUI / "prototipo/prototipo_rmc.html").as_uri()
PNG = QUI / "prototipo/png"
RIS = json.loads((QUI / "build/risultati.json").read_text(encoding="utf-8"))
errori: list[str] = []
richieste: list[str] = []


def controlla(cond: bool, testo: str) -> None:
    print(("  ok   " if cond else "  ERRORE ") + testo)
    if not cond:
        errori.append(testo)


def main() -> int:
    PNG.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        pg = ctx.new_page()
        pg.on("console", lambda m: errori.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errori.append(f"errore pagina: {e}"))
        pg.on("request", lambda r: richieste.append(r.url) if not r.url.startswith("file:") and not r.url.startswith("data:") else None)

        def apri(rotta: str):
            pg.goto(FILE + "#" + rotta)
            pg.wait_for_selector("#vista > *", state="attached")

        def foto(nome: str, pagina_intera: bool = False):
            pg.screenshot(path=str(PNG / f"{nome}.png"), full_page=pagina_intera)

        # 0. Menu dell'intera Anagrafica, modelli di pagina, due stili
        apri("persone")
        controlla(pg.locator(".hrnav-tabs a.hrnav-tab").count() == 6 and pg.locator(".hrnav-tabs a.active").inner_text().strip() == "Persone", "menu riordinato: sei pilastri, «Persone» attivo")
        foto("20_persone_ingresso", True)
        pg.click('[data-stile="FRESCO"]')
        controlla(pg.evaluate("() => document.body.classList.contains('px-fresco')"), "interruttore dello stile: variante rinfrescata")
        foto("21_persone_stile_rinfrescato", True)
        pg.click('[data-stile="ATTUALE"]')
        apri("elenco-dipendenti")
        n0 = pg.locator("#vista .fmd-table tbody tr").count()
        pg.select_option('[data-filtro="reparto"]', "CMM")
        controlla(0 < pg.locator("#vista .fmd-table tbody tr").count() < n0, "elenco dipendenti: il filtro per reparto funziona")
        pg.select_option('[data-filtro="reparto"]', "")
        foto("22_elenco_dipendenti")
        apri("corso")
        controlla(pg.inner_text("#px-corso-tenuti") == "20", "scheda corso: 20 persone a cui serve «Prevenzione FOD»")
        foto("23_scheda_corso", True)
        apri("da-fare")
        controlla(int(pg.inner_text("#px-dafare-n")) > 5, "«Da fare» riunisce scadenze, valutazioni, richieste e segnalazioni")
        foto("24_da_fare", True)
        apri("v-scadenzario")
        controlla("Scadenzario unico" in pg.inner_text("#vista") and pg.locator("#vista .fmd-table tbody tr").count() >= 3, "una voce non costruita mostra dove va e il suo modello")
        foto("25_voce_del_menu")
        apri("matrice")
        pg.click('[data-mvista="MANSIONE"]')
        controlla(pg.locator(".px-mtx tbody tr").count() > 10, "matrice unica: vista per mansione")
        foto("26_matrice_per_mansione")
        pg.click('[data-mvista="COMPETENZA"]')

        # 1. Cruscotto: numeri uguali al motore di riferimento
        apri("cruscotto-qualita")
        q = pg.evaluate("() => { const q = PX.quadro(); return {stati: q.stati, gap: q.gap, segn: q.segn, personeNC: q.personeNC, potS: q.potS, potP: q.potP, ass: q.assegnazioni}; }")
        r = RIS["quadro"]
        controlla(q["stati"] == r["stati"], f"stati cruscotto = motore di riferimento {r['stati']}")
        controlla(q["gap"] == r["gap"] and q["personeNC"] == r["persone_non_conformi"], "mancanze e persone non conformi coincidono")
        controlla(q["potS"] == r["potenziali_soddisfatte"] and q["potP"] == r["potenziali_parziali"], "mansioni potenziali coincidono")
        foto("01_cruscotto_qualita")
        # modalità blocco
        pg.click('[data-modalita="BLOCCO"]')
        qb = pg.evaluate("() => PX.quadro().stati")
        controlla(qb == RIS["quadro_blocco"]["stati"], f"modalità blocco = {RIS['quadro_blocco']['stati']}")
        pg.click('[data-modalita="SEGNALAZIONE"]')

        # 2. Matrice: proposta, filtro, Perché, oggi
        apri("matrice")
        n_tutti = pg.locator(".px-mtx tbody tr").count()
        pg.select_option('[data-filtro="reparto"]', "CN5")
        n_cn5 = pg.locator(".px-mtx tbody tr").count()
        controlla(0 < n_cn5 < n_tutti, f"il filtro per reparto restringe la matrice ({n_tutti} → {n_cn5} persone)")
        foto("02_matrice_proposta")
        pg.locator(".px-cell").first.click()
        pg.wait_for_selector(".px-perche.px-on")
        controlla(pg.locator(".px-perche .px-catena li").count() >= 1, "il pannello «Perché?» mostra la catena delle fonti")
        pg.wait_for_timeout(450)  # il pannello entra con una transizione di 180 ms: la cattura va presa a pannello fermo
        foto("03_matrice_perche")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(450)  # stessa transizione in uscita: la cattura successiva non deve mostrare il pannello
        pg.click('[data-vista="OGGI"]')
        controlla(pg.locator(".px-oggi").count() == 1 and pg.locator("img.px-cattura").count() == 1, "«Oggi» mostra la cattura della pagina reale")
        foto("04_matrice_oggi")
        pg.click('[data-vista="PROPOSTA"]')

        # 3. Scheda persona
        apri("dipendente-rinaldi")
        controlla("RINALDI MARCO" in pg.inner_text("#vista"), "scheda di Marco Rinaldi")
        controlla(pg.locator(".px-filo .mns-filo-qui").inner_text().endswith("Competenze"), "il filo conduttore segna «sei qui» sul pilastro Competenze")
        controlla(pg.locator("#px-sez a.active").inner_text() == "Quadro" and pg.locator("#px-voci a.active").inner_text() == "Scheda persona", "il menu a sezioni segue la pagina")
        controlla(pg.locator("text=DM6 – Fresatura 5 assi grande formato").count() >= 1, "DM6 compare fra le mansioni potenziali")
        foto("05_scheda_persona", True)
        pg.click('[data-vista="OGGI"]')
        foto("06_scheda_persona_oggi")
        pg.click('[data-vista="PROPOSTA"]')

        # 4. Editor mansione: anteprima d'impatto
        apri("editor-mansione")
        controlla(pg.inner_text("#px-impatto") == "0", "senza modifiche l'impatto è 0")
        pg.select_option("[data-req-aggiungi]", "C03")
        imp = RIS["casi"]["impatto_M01_C03_L_I"]
        controlla(pg.inner_text("#px-impatto") == str(len(imp["cambi"])), f"aggiungendo «Programmazione a bordo» a DM3 cambiano {len(imp['cambi'])} titolari su {imp['titolari']}")
        foto("07_editor_mansione")

        # 5. Simulatore
        apri("simulatore")
        s = RIS["casi"]["cambio_P01_M02"]
        controlla(pg.inner_text("#px-coperti") == str(s["coperti"]) and pg.inner_text("#px-mancanti") == str(len(s["mancanti"])), f"Marco su DM6: {s['coperti']} coperti, {len(s['mancanti'])} da colmare")
        foto("08_simulatore")
        pg.select_option('[data-filtro="simPersona"]', "P02")
        pg.select_option('[data-filtro="simMansione"]', "M02")
        s2 = RIS["casi"]["cambio_P02_M02"]
        controlla(pg.inner_text("#px-mancanti") == str(len(s2["mancanti"])), f"cambiando persona il simulatore ricalcola (Giulia su DM6: {len(s2['mancanti'])} da colmare)")

        # 6. Coda del responsabile: approvare cambia i dati in memoria
        apri("coda-car")
        prima = int(pg.inner_text("#px-coda-n"))
        foto("09_coda_responsabile")
        pg.click('[data-azione="coda-ok"][data-arg="SF-2027-0063"]')
        dopo = int(pg.inner_text("#px-coda-n"))
        pot = pg.evaluate("() => PX.potenziali(PX.pers('P01')).filter(x => x.mansione === 'M02')[0].esito")
        controlla(dopo == prima - 1 and pot == "SODDISFATTA", "confermando la SF di Marco, DM6 diventa «requisiti soddisfatti»")
        pg.click('[data-azione="ripristina"]')

        # 6b. Richiesta di mansione: dal modulo a video all'esito, passando dalla sessione formativa
        apri("ram")
        controlla("RAM-2027-0041" in pg.inner_text("#vista") and pg.locator(".px-passi li.px-qui").inner_text().endswith("Bozza"), "richiesta di mansione in bozza, precompilata")
        foto("13_richiesta_mansione", True)
        pg.click('[data-azione="ram-invia"]')
        pg.click('[data-azione="ram-avvia"]')
        controlla(pg.locator('[data-azione="ram-valuta"]').is_disabled(), "con una competenza da colmare l'esito finale non è disponibile")
        pg.click('[data-azione="ram-apri-sf"]')
        pg.wait_for_selector('[data-azione="sf-chiudi"]')
        controlla(pg.locator("#vista .fmd-table tbody tr").count() == 1, "la sessione formativa nasce con la sola competenza mancante")
        foto("14_sessione_formativa")
        pg.click('[data-azione="sf-chiudi"]')
        apri("ram")
        pg.click('[data-azione="ram-valuta"]')
        controlla(not pg.locator('[data-azione="ram-pos"]').is_disabled(), "chiusa la sessione, l'esito POS diventa disponibile")
        pg.click('[data-azione="ram-pos"]')
        eff = pg.evaluate("() => PX.pers('P01').mansioni.filter(a => a.mansione === 'M02')[0].stato")
        controlla(eff == "EFFETTIVA", "esito POS: DM6 è effettiva per Marco Rinaldi")
        foto("15_richiesta_approvata")
        pg.click('[data-azione="ripristina"]')
        # sessione formativa di esempio: più persone, più competenze, effetti in anteprima
        apri("sessione-formativa")
        controlla(pg.locator("#vista .fmd-table tbody tr").count() == 3 and int(pg.inner_text("#px-sf-effetti")) >= 1, "sessione con più persone e competenze, effetti calcolati prima di chiudere")
        foto("16_sessione_formativa_effetti", True)

        # 6b-bis. Inserimento di un nuovo dipendente
        apri("inserimento")
        foto("18_inserimento", True)
        pg.click('[data-azione="ins-avvia"]')
        nuova = pg.evaluate("() => { const p = PX.pers('P33'); return {m: p.mansioni.map(a => a.stato), l: Object.values(p.livelli).map(x => x.livello)}; }")
        controlla(nuova["m"] == ["AVVIATA"] and set(nuova["l"]) == {"I"}, "all'avvio la nuova persona entra in skill matrix a livello I, mansione avviata")
        controlla(pg.locator('[data-azione="ins-pos"]').is_disabled(), "esito POS non disponibile finché mancano i livelli minimi")
        pg.click('[data-azione="ins-sf"]')
        pg.wait_for_selector('[data-azione="sf-chiudi"]')
        pg.click('[data-azione="sf-chiudi"]')
        apri("inserimento")
        foto("19_inserimento_avviato", True)
        pg.click('[data-azione="ripristina"]')

        # 6c. Cruscotto RDD
        apri("cruscotto-rdd")
        n_ram = int(pg.inner_text("#px-rdd-ram"))
        foto("17_cruscotto_rdd")
        pg.click('[data-azione="coda-ok"][data-arg="RAM-2027-0042"]')
        controlla(int(pg.inner_text("#px-rdd-ram")) == n_ram - 1, "RDD approva una richiesta: il conteggio scende")
        pg.click('[data-azione="ripristina"]')

        # 7. Pianificatore
        apri("pianificatore")
        controlla(pg.locator(".fmd-table tbody tr").count() > 3, "il pianificatore elenca le competenze da colmare")
        foto("10_pianificatore")

        # 8. Vista del dipendente, anche a 390×844 e a 360 px
        apri("vista-dipendente")
        foto("11_vista_dipendente_desktop")
        tel = br.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        pt = tel.new_page()
        pt.on("pageerror", lambda e: errori.append(f"errore pagina (telefono): {e}"))
        pt.goto(FILE + "#vista-dipendente")
        pt.wait_for_selector("#vista > *", state="attached")
        pt.screenshot(path=str(PNG / "12_vista_dipendente_telefono.png"), full_page=True)
        stretto = br.new_context(viewport={"width": 360, "height": 740})
        ps = stretto.new_page()
        for rotta in ("persone", "elenco-dipendenti", "corso", "da-fare", "v-scadenzario", "cruscotto-qualita", "matrice", "dipendente-rinaldi", "editor-mansione", "simulatore", "inserimento", "ram", "sessione-formativa", "coda-car", "cruscotto-rdd", "pianificatore", "vista-dipendente"):
            ps.goto(FILE + "#" + rotta)
            ps.wait_for_selector("#vista > *", state="attached")
            largo = ps.evaluate("() => document.documentElement.scrollWidth")
            controlla(largo <= 362, f"a 360 px «{rotta}» non scorre in orizzontale (larghezza {largo})")
        br.close()

    controlla(not richieste, f"nessuna richiesta di rete ({len(richieste)})")
    for u in richieste[:5]:
        print("     ", u)
    console = [e for e in errori if e.startswith(("console", "errore pagina"))]
    print(f"\nErrori di console: {len(console)}")
    for e in errori:
        print("  -", e)
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
