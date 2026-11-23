"""Assembla prototipo/prototipo_rmc.html: un solo file, nessuna richiesta di rete.

Uso:  python build/costruisci_prototipo.py   (dalla cartella dell'analisi, dentro il repository)

Prende i CSS REALI dell'HUB dal repository (così il prototipo ha l'aspetto del portale), lo sprite
delle icone del modulo Anagrafica, i dati finti (prototipo/dati/dataset.json, generati da
build/motore_rif.py) e la logica (prototipo/src/app.js, app.css). Dai CSS toglie @import, @font-face
e ogni url(...) esterno. Il carattere Outfit del portale e le catture delle pagine attuali sono incorporati
come dati: nessuna richiesta di rete. Barra in alto e menu del modulo sono il markup reale (prototipo/src/guscio/).
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

QUI = Path(__file__).resolve().parent.parent
REPO = QUI.parents[2]                      # …/docs/feasibility/<cartella> → radice del repository
APP = REPO / "django_app"

CSS_REALI = [
    "core/static/core/css/tokens.css",
    "core/static/core/css/theme.css",
    "core/static/core/css/layout.css",
    "core/static/core/css/components.css",
    "core/static/core/css/hub.css",
    "core/static/core/css/hub-percorso.css",
    "anagrafica/static/anagrafica/css/subnav.css",
    "anagrafica/static/anagrafica/css/hr_restyle.css",
    "anagrafica/static/anagrafica/css/formazione_design.css",
    "anagrafica/static/anagrafica/css/mansionario.css",
]
TEMPLATE_CON_STILE = ["anagrafica/templates/anagrafica/components/_hr_tokens.html"]
SPRITE = "anagrafica/templates/anagrafica/components/_fm_icons.html"


def pulisci_css(testo: str) -> str:
    testo = re.sub(r"@import[^;]+;", "", testo)
    testo = re.sub(r"@font-face\s*\{[^}]*\}", "", testo, flags=re.S)
    testo = re.sub(r"url\((?!['\"]?data:)[^)]*\)", "none", testo)
    return testo.replace("</style", "<\\/style")


def carattere() -> str:
    """Il carattere del portale (Outfit) come dati incorporati: stesso aspetto, nessuna richiesta di rete."""
    cartella = APP / "core/static/core/vendor/outfit"
    css = (cartella / "outfit.css").read_text(encoding="utf-8")

    def incorpora(m):
        nome = m.group(1).strip("'\"").split("/")[-1]
        return "url(data:font/woff2;base64," + base64.b64encode((cartella / nome).read_bytes()).decode() + ")"
    return re.sub(r"url\(([^)]+)\)", incorpora, css)


def stile_da_template(testo: str) -> str:
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", testo, flags=re.S))


def voce(rotta: str, etichetta: str) -> str:
    return f'<a href="#{rotta}" data-nav="{rotta}">{etichetta}</a>'


GUSCIO = """<!doctype html>
<!--
  PROTOTIPO «Ruoli, mansioni, competenze» — NOVICROM HUB. Dati inventati, nessun dato reale.
  File unico: CSS, dati, icone e logica sono tutti qui dentro; non fa richieste di rete.

  SCHERMATE (navigazione con l'ancora nell'indirizzo):
    #persone             Ingresso della sezione Persone (modello «ingresso di sezione»)
    #elenco-dipendenti   Elenco dipendenti (modello «elenco»)
    #corso               Scheda corso (modello «scheda», pilastro Formazione)
    #da-fare             Da fare: scadenze, valutazioni, richieste e segnalazioni in un elenco
    #v-<voce>            Voci del menu non costruite: mostrano dove va la pagina e quale modello prende
    #cruscotto-qualita   Cruscotto Qualità: copertura per reparto, casi da sistemare, scadenze
    #matrice             Matrice persone × competenze (interruttore Oggi / Proposta, filtri, «Perché?»)
    #dipendente-rivalta  Scheda persona (anche #dipendente-<cognome>): requisiti, posseduto, mancanze, potenziali
    #editor-mansione     Profilo della mansione con anteprima d'impatto
    #simulatore          Simulatore del cambio mansione
    #inserimento         Inserimento di un nuovo dipendente: la pratica esistente più la scheda MOD.053
    #ram                 Richiesta di aggiornamento mansione: il MOD.053 compilato a video, con firme ed esito
    #sessione-formativa  Sessione formativa: persone, competenze, modalità P/A/C, livello raggiunto, effetti
    #cruscotto-rdd       Cruscotto RDD: richieste, deroghe, profili da pubblicare, segnalazioni
    #coda-car            Coda del responsabile: valutazioni, richieste, segnalazioni
    #pianificatore       Pianificatore della formazione dalle mancanze
    #vista-dipendente    La mia scheda (telefono, postazioni condivise)

  DOVE STA LA LOGICA: nell'ultimo <script>. Sezione «MOTORE» = le regole (validita, valutaMansione,
  requisitiEffettivi, potenziali, quadro, impattoRevisione, simulaCambio), identiche a build/motore_rif.py.
  Sezione «VISTE» = una funzione per schermata. I dati sono nel blocco <script id="px-dati">.
  Rigenerare: python build/motore_rif.py && python build/costruisci_prototipo.py
-->
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prototipo NOVICROM HUB — Competenze</title>
<style>
__CSS__
</style>
</head>
<body class="nav-top fs-normal">
__SPRITE__
<div class="main-wrap">
  __TOPNAV__
  __HRNAV__
  <nav class="hub-percorso" aria-label="Percorso"><ol class="hub-percorso-lista"><li><a class="hub-percorso-tappa" href="#cruscotto-qualita">Home</a></li><li><a class="hub-percorso-tappa" href="#persone">Anagrafica HR</a></li><li><span class="hub-percorso-tappa" aria-current="page" id="px-percorso-qui"></span></li></ol></nav>
  <div class="px-tour" role="region" aria-label="Tour del prototipo">
    <span class="px-proto-tag">Tour del prototipo</span>
    <span class="px-tour-nav">
      <button type="button" class="px-btn" id="px-tour-prec" data-vai="" aria-label="Schermata precedente">‹</button>
      <b id="px-tour-n"></b>
      <button type="button" class="px-btn" id="px-tour-succ" data-vai="" aria-label="Schermata successiva">›</button>
    </span>
    <span class="px-tour-txt" id="px-tour-t"></span>
    <span class="px-seg" role="group" aria-label="Che cosa succede quando una competenza non è più valida">
      <button type="button" class="px-btn" data-modalita="SEGNALAZIONE" aria-pressed="true" title="Scelta del progetto: il portale segnala, non ferma">Solo segnalazione</button>
      <button type="button" class="px-btn" data-modalita="BLOCCO" aria-pressed="false" title="Alternativa: la competenza non valida toglie l'operatività">Blocco</button>
    </span>
    <span class="px-seg" role="group" aria-label="Aspetto delle pagine">
      <button type="button" class="px-btn" data-stile="ATTUALE" aria-pressed="true" title="Colori e componenti di oggi, solo più ordine">Stile attuale</button>
      <button type="button" class="px-btn" data-stile="FRESCO" aria-pressed="false" title="Lo stesso portale, con più aria e meno bordi">Stile rinfrescato</button>
    </span>
    <button type="button" class="px-btn" data-azione="ripristina">Ripristina i dati</button>
  </div>
  <div class="content">
    <div class="fmd"><div class="fmd-wrap" id="vista"></div></div>
  </div>
</div>
<div class="px-velo" id="px-velo"></div>
<aside class="px-perche" id="px-perche" role="dialog" aria-label="Perché?" aria-modal="true"></aside>
<script type="application/json" id="px-dati">__DATI__</script>
<script type="application/json" id="px-oggi">__OGGI__</script>
<script>
__JS__
</script>
</body>
</html>
"""


def costruisci() -> Path:
    css = []
    for rel in TEMPLATE_CON_STILE:
        css.append(f"/* === {rel} === */\n" + pulisci_css(stile_da_template((APP / rel).read_text(encoding="utf-8"))))
    for rel in CSS_REALI:
        css.append(f"/* === {rel} === */\n" + pulisci_css((APP / rel).read_text(encoding="utf-8")))
    css.append("/* === carattere Outfit del portale, incorporato === */\n" + carattere())
    css.append("/* === prototipo/src/app.css === */\n" + (QUI / "prototipo/src/app.css").read_text(encoding="utf-8"))
    sprite = (APP / SPRITE).read_text(encoding="utf-8")
    sprite = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", sprite, flags=re.S)
    sprite = re.sub(r"\{#.*?#\}", "", sprite, flags=re.S).strip()
    assert "{%" not in sprite and "{{" not in sprite, "lo sprite contiene tag di template"
    dati = json.loads((QUI / "prototipo/dati/dataset.json").read_text(encoding="utf-8"))
    dati_txt = json.dumps(dati, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    js = (QUI / "prototipo/src/app.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    oggi = {p.stem.replace("oggi_", ""): "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()
            for p in sorted((QUI / "prototipo/src/oggi").glob("oggi_*.jpg"))}
    topnav = (QUI / "prototipo/src/guscio/topnav.html").read_text(encoding="utf-8")
    hrnav = (QUI / "prototipo/src/guscio/hrnav.html").read_text(encoding="utf-8")
    _voci_non_usate = "\n        ".join(voce(r, e) for r, e in [
        ("cruscotto-qualita", "Cruscotto Qualità"), ("matrice", "Matrice competenze"),
        ("dipendente-rivalta", "Scheda persona"), ("editor-mansione", "Profilo mansione"),
        ("simulatore", "Simulatore"), ("inserimento", "Inserimento"), ("ram", "Richiesta di mansione"),
        ("sessione-formativa", "Sessione formativa"), ("coda-car", "Coda del responsabile"),
        ("cruscotto-rdd", "Cruscotto RDD"),
        ("pianificatore", "Pianificatore"), ("vista-dipendente", "La mia scheda")])
    html = (GUSCIO.replace("__CSS__", "\n".join(css)).replace("__SPRITE__", sprite)
            .replace("__TOPNAV__", topnav).replace("__HRNAV__", hrnav)
            .replace("__OGGI__", json.dumps(oggi)).replace("__DATI__", dati_txt).replace("__JS__", js))
    assert not re.search(r"""(src|href)=["']https?://""", html), "riferimento esterno nel prototipo"
    assert "url(http" not in html and "__" not in re.sub(r"__[a-z]+__", "", "")
    out = QUI / "prototipo/prototipo_rmc.html"
    out.write_text(html, encoding="utf-8")
    pubblica(html)
    return out


def pubblica(html: str) -> Path:
    """Variante per la pubblicazione come pagina claude.ai: stesso contenuto, senza doctype/html/head/body
    (li mette la piattaforma), con titolo in testa e le classi del body aggiunte da script."""
    stile = re.search(r"<style>.*?</style>", html, flags=re.S).group(0)
    corpo = re.search(r'<body class="([^"]*)">(.*)</body>', html, flags=re.S)
    classi = ", ".join(f'"{c}"' for c in corpo.group(1).split())
    pagina = ("<title>Prototipo Competenze HUB</title>\n"
              "<!-- Prototipo «Ruoli, mansioni, competenze» — NOVICROM HUB. Dati inventati. "
              "Sorgente: prototipo/src/, costruito da build/costruisci_prototipo.py -->\n"
              + stile.replace("<style>", "<style>\n:root { color-scheme: light; }", 1) + "\n"
              + f"<script>document.body.classList.add({classi});</script>\n" + corpo.group(2).strip() + "\n")
    assert "<html" not in pagina and "<body" not in pagina and "<!doctype" not in pagina.lower()
    dest = QUI / "prototipo/pubblicazione/prototipo-competenze-hub.html"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(pagina, encoding="utf-8")
    return dest


if __name__ == "__main__":
    f = costruisci()
    print(f"{f}  {f.stat().st_size / 1024:.0f} KB")
