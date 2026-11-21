"""Compone e stampa i due PDF della fattibilità Ruoli → Mansioni → Competenze.

Fonte unica: i markdown delle fasi 1-3 (01_asis.md, 02_tobe_flusso_algoritmo.md, 03_ux.md), più i testi propri in
build/pdf_tecnico_testi.md e il corpo della sintesi in build/pdf_direzione.html. Il foglio di stampa comune è
build/stampa.css.

Uso (dal Python che ha playwright, markdown-it-py e PyMuPDF):

    python build/costruisci_pdf.py                         # entrambi i PDF
    python build/costruisci_pdf.py --solo direzione
    python build/costruisci_pdf.py --raster C:/temp/pagine   # anche le pagine in PNG, per il controllo a vista

I diagrammi Mermaid vengono convertiti in SVG con @mermaid-js/mermaid-cli e conservati in build/svg/: se il sorgente
di un diagramma non è cambiato si riusa l'SVG, quindi la ricostruzione funziona anche senza mermaid-cli. Per
rigenerarli: `npm install @mermaid-js/mermaid-cli` in una cartella qualsiasi e variabile d'ambiente
MMDC=<cartella>/node_modules/.bin/mmdc.cmd (PUPPETEER_SKIP_DOWNLOAD=1: si usa il Chromium di Playwright).

Scrive solo dentro docs/feasibility/ruoli-mansioni-competenze/ (e nella cartella indicata con --raster).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

QUI = Path(__file__).resolve().parent
RADICE = QUI.parent
REPO = RADICE.parents[2]
SVG = QUI / "svg"

VERSIONE = "1.0"
DATA = "21/11/2026"
TITOLO = "Ruoli, mansioni e competenze"

DOC = {"01": "01_asis.md", "02": "02_tobe_flusso_algoritmo.md", "03": "03_ux.md", "04": "04_gap_sgi.md"}

# Termini che il PDF per la Direzione non deve contenere: i sei indicati dalla missione più altri termini informatici.
VIETATI_MISSIONE = ["FSM", "motore", "cache", "ACL", "HTMX", "DB"]
VIETATI_ALTRI = ["database", "algoritmo", "algoritmi", "Django", "template", "migrazione", "migrazioni", "backend",
                 "frontend", "server", "query", "script", "software", "API", "SQL", "JSON", "CSS", "HTML", "workflow",
                 "repository", "deploy", "bug", "codice", "sistema informativo", "lorem"]


# --------------------------------------------------------------------------------------------------------------------
# Lettura dei markdown
# --------------------------------------------------------------------------------------------------------------------

def leggi(rel: str) -> str:
    return (RADICE / rel).read_text(encoding="utf-8")


def sezioni(testo: str) -> dict:
    """Divide un documento in sezioni «## N. Titolo» e sottosezioni «### N.M Titolo»."""
    out: dict[str, dict] = {}
    corrente = None
    padre = None
    for riga in testo.split("\n"):
        m2 = re.match(r"^## (\d+)\. (.+)$", riga)
        m3 = re.match(r"^### (\d+\.\d+) (.+)$", riga)
        if m2:
            corrente = padre = m2.group(1)
            out[corrente] = {"titolo": m2.group(2).strip(), "righe": [], "figli": []}
        elif m3:
            corrente = m3.group(1)
            out[corrente] = {"titolo": m3.group(2).strip(), "righe": [], "figli": []}
            if padre:
                out[padre]["figli"].append(corrente)
        elif corrente is not None:
            out[corrente]["righe"].append(riga)
    for s in out.values():
        corpo = "\n".join(s["righe"]).strip()
        corpo = re.sub(r"\n-{3,}\s*$", "", corpo).strip()
        s["corpo"] = corpo
    return out


def blocchi_propri() -> dict:
    testo = leggi("build/pdf_tecnico_testi.md")
    parti = re.split(r"<!-- blocco: (\w+) -->", testo)
    return {parti[i]: parti[i + 1].strip() for i in range(1, len(parti), 2)}


def questionario() -> str:
    """Il questionario per la Qualità, senza intestazione, con i titoli abbassati di un livello."""
    testo = leggi("Domande_per_la_Qualita.md")
    testo = testo.split("\n---\n", 1)[1] if "\n---\n" in testo else testo
    testo = re.sub(r"^## ", "#### ", testo, flags=re.M)
    testo = testo.replace("[ ]", "☐")
    return testo.strip()


# --------------------------------------------------------------------------------------------------------------------
# Piano del PDF tecnico
# --------------------------------------------------------------------------------------------------------------------
# S(doc, n)      una sezione «##» con le sue sottosezioni → sezione di secondo livello del capitolo
# P(doc, n.m)    una sottosezione «###» promossa a sezione di secondo livello
# F(doc, n)      una sezione usata come corpo del capitolo: le sue sottosezioni diventano sezioni di secondo livello
# T(nome, tit)   un testo proprio (build/pdf_tecnico_testi.md); con titolo diventa una sezione di secondo livello
# G()            la galleria delle schermate

def S(doc, n, titolo=None): return ("S", doc, n, titolo)
def P(doc, n, titolo=None): return ("P", doc, n, titolo)
def F(doc, n): return ("F", doc, n, None)
def T(nome, titolo=None): return ("T", nome, None, titolo)
def G(titolo): return ("G", None, None, titolo)
def Q(titolo): return ("Q", None, None, titolo)
def R(titolo): return ("R", None, None, titolo)


PIANO = [
    ("1", "Sommario esecutivo", [T("sommario")]),
    ("2", "Requisiti della Qualità e matrice di tracciabilità", [
        S("01", "1"), S("01", "4"), S("01", "7")]),
    ("2b", "Studi precedenti: che cosa è stato fatto, che cosa resta valido", [F("01", "5")]),
    ("2c", "Matrice «C'è / Manca / Come introdurlo»", [F("01", "6")]),
    ("3", "AS-IS: modello dati, motori, divergenze, qualità dei dati", [
        S("01", "2"), S("01", "3"), S("01", "8"), S("01", "11"), S("01", "12")]),
    ("3b", "Confronto con il Sistema di Gestione Integrato in vigore", [
        S("04", "0"), S("04", "1"), S("04", "2"), S("04", "3"), S("04", "4"), S("04", "5"), S("04", "6"), S("04", "7")]),
    ("4", "TO-BE: livelli, algoritmo, flussi, permessi", [
        S("02", "0"), S("02", "1"), S("02", "2"), S("02", "3"), S("02", "4"), S("02", "5"), S("02", "6")]),
    ("5", "UX: persone, architettura dell'informazione, prototipo", [
        S("03", "2"), S("03", "3"), S("03", "4", "Le schermate: elenco e verifiche"), G("Galleria delle schermate"), S("03", "5"), S("03", "6"),
        S("03", "1"), S("03", "8"), S("03", "7"), S("03", "9"), S("03", "10")]),
    ("6", "Impatti tecnici, migrazione, test, rischi", [
        P("02", "7.1"), P("02", "7.2"), P("02", "7.3"), P("02", "7.4"), P("02", "7.5"), S("02", "8")]),
    ("7", "Roadmap a blocchi, con stime e dipendenze", [F("02", "7.6")]),
    ("8", "Domande aperte e decisioni richieste", [
        T("decisioni", "Decisioni richieste"), S("02", "9"),
        P("01", "9.1", "Domande per la Qualità (elenco di lavoro)"), P("01", "9.2"), S("01", "10")]),
    ("A", "Appendice", [
        T("glossario", "Glossario"), T("en9100", "Riferimenti EN 9100: 7.1.2, 7.2, 7.3"),
        R("Riferimenti al codice"), Q("Questionario per la Qualità: 18 domande con le ipotesi adottate")]),
]

GALLERIA = [
    ("01_cruscotto_qualita.png", "Cruscotto Qualità", "#cruscotto-qualita",
     "I numeri calcolati dal motore, la copertura per reparto, i casi da sistemare e le scadenze a 30, 60 e 90 giorni."),
    ("02_matrice_proposta.png", "Matrice, vista per competenza", "#matrice",
     "Una lettera per competenza, con validità e mancanze; filtri per reparto, mansione e nome."),
    ("03_matrice_perche.png", "Matrice, pannello «Perché?»", "#matrice",
     "Un clic sulla cella spiega la catena ruolo → mansione → requisito e l'evidenza posseduta."),
    ("26_matrice_per_mansione.png", "Matrice, vista per mansione", "#matrice",
     "La stessa pagina con una lettera per mansione: è la vista che sostituisce le matrici di oggi."),
    ("04_matrice_oggi.png", "Matrice, vista «Oggi»", "#matrice",
     "Cattura della pagina reale del portale, presa da un server di prova con persone inventate, a confronto con la proposta."),
    ("05_scheda_persona.png", "Scheda della persona", "#dipendente-rivalta",
     "Le mansioni con lo stato e ciò che la persona può fare; i requisiti con la loro origine; le mansioni potenziali."),
    ("07_editor_mansione.png", "Profilo della mansione", "#editor-mansione",
     "Livello atteso e criticità di ogni competenza; l'anteprima d'impatto si ricalcola a ogni modifica."),
    ("08_simulatore.png", "Simulatore del cambio mansione", "#simulatore",
     "Requisiti coperti e da colmare, effetto sulla mansione di rischio, apertura della richiesta."),
    ("18_inserimento.png", "Inserimento di un nuovo dipendente", "#inserimento",
     "La pratica a cinque fasi che esiste già, accanto alla scheda MOD.053; l'esito resta bloccato finché mancano i livelli minimi."),
    ("13_richiesta_mansione.png", "Richiesta di aggiornamento mansione (RAM)", "#ram",
     "Il MOD.053 a video: campi compilati dal portale, evidenze riusate, avanzamento a passi, firme."),
    ("16_sessione_formativa_effetti.png", "Sessione formativa, con l'anteprima degli effetti", "#sessione-formativa",
     "Più persone e più competenze, modalità P/A/C; prima della chiusura si vede che cosa cambierà."),
    ("09_coda_responsabile.png", "Coda del responsabile", "#coda-car",
     "Valutazioni da confermare e richieste da approvare: a ogni azione i dati si ricalcolano."),
    ("17_cruscotto_rdd.png", "Cruscotto RDD", "#cruscotto-rdd",
     "Richieste da approvare, deroghe in corso, profili da pubblicare, segnalazioni senza presa in carico."),
    ("10_pianificatore.png", "Pianificatore della formazione", "#pianificatore",
     "Le mancanze raggruppate per competenza e ordinate per urgenza; corso o affiancamento, con i tutor proposti."),
    (("11_vista_dipendente_desktop.png", "12_vista_dipendente_telefono.png"), "La mia scheda, su schermo e su telefono",
     "#vista-dipendente", "La vista personale, in parole semplici; utilizzabile da 360 px di larghezza."),
    ("20_persone_ingresso.png", "Ingresso del pilastro Persone, stile attuale", "#persone",
     "Modello «ingresso di sezione»: una fascia, pochi numeri cliccabili, una griglia di schede."),
    ("21_persone_stile_rinfrescato.png", "La stessa pagina nello stile rinfrescato", "#persone",
     "Stessi colori, carattere e icone; bordi più sottili, più spazio, striscia «sei qui» più leggera."),
    ("22_elenco_dipendenti.png", "Elenco dei dipendenti", "#elenco-dipendenti",
     "Modello «elenco»: filtri in una riga, lo stato in parole, una sola azione accanto alla cosa più urgente."),
    ("23_scheda_corso.png", "Scheda del corso", "#corso",
     "Modello «scheda»: il filo del corso, da dove viene e quali competenze alimenta."),
    ("24_da_fare.png", "Da fare", "#da-fare",
     "Le code personali e lo scadenzario unico, con il filtro per tipo."),
    ("25_voce_del_menu.png", "Voce di menu non ancora disegnata", "#v-<voce>",
     "Per le voci non costruite il prototipo dice dove sta oggi la pagina, dove va e quale modello prende."),
]


# --------------------------------------------------------------------------------------------------------------------
# Markdown → HTML
# --------------------------------------------------------------------------------------------------------------------

MD = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable("table")
_diagrammi: list[tuple[str, str]] = []  # (nome file svg, sorgente)
_avvisi: list[str] = []


def _fence(_renderer, tokens, idx, options, env):
    tok = tokens[idx]
    if tok.info.strip() == "mermaid":
        n = len(_diagrammi) + 1
        nome = f"d{n:02d}.svg"
        _diagrammi.append((nome, tok.content))
        return f"@@DIAGRAMMA:{nome}@@\n"
    righe = tok.content.rstrip("\n").count("\n") + 1
    classe = ' class="corto"' if righe <= 45 else ""
    return f"<pre{classe}><code>{html.escape(tok.content.rstrip())}</code></pre>\n"


MD.add_render_rule("fence", _fence)


def _spezzabile(m: re.Match) -> str:
    """Nei frammenti di codice aggiunge punti di a capo dopo i separatori, così le tabelle non sbordano."""
    return "<code>" + re.sub(r"([/_.:\-])(?=\w)", r"\1<wbr>", m.group(1)) + "</code>"


def rifinisci(h: str) -> str:
    h = re.sub(r'(?<!<pre>)(?<!<pre class="corto">)<code>([^<]{12,})</code>', _spezzabile, h)
    etichetta = lambda m: f'<span class="chip {m.group(1)}">{m.group(1)} {m.group(2)}</span>'  # noqa: E731
    h = re.sub(r"<strong>\[(deciso|ipotesi) ([^\]<]+)\]</strong>", etichetta, h)
    h = re.sub(r"\[(deciso|ipotesi) ([^\]<]+)\]", etichetta, h)
    h = h.replace("✅", '<span class="segno-ok">✓</span>').replace("❌", '<span class="segno-ko">✕</span>')
    h = h.replace("⚠️", '<span class="segno-av">!</span>').replace("⚠", '<span class="segno-av">!</span>')
    h = h.replace("🟡", '<span class="segno-av">◐</span>').replace("🛑", "")
    h = re.sub(r"<td>([^<\s]{1,9})</td>", r'<td class="nw">\1</td>', h)  # sigle brevi (REQ-01, D16): mai a capo
    # tabelle con molte colonne: carattere un po' più piccolo
    h = re.sub(r"<table>\s*<thead>\s*<tr>(.*?)</tr>",
               lambda m: ('<table class="larga">' if m.group(1).count("<th") >= 6 else "<table>")
               + "\n<thead>\n<tr>" + m.group(1) + "</tr>", h, flags=re.S)
    return h


def md(testo: str) -> str:
    return rifinisci(MD.render(testo))


# --------------------------------------------------------------------------------------------------------------------
# Rimandi fra sezioni
# --------------------------------------------------------------------------------------------------------------------

_ESTERNI = re.compile(r"SPEC|MT CN|EN 9100|M053|ISO 9001|Debole su|IDOR|MO-ID|MOD\.\d")
_RIF = re.compile(
    r"(?:`(01_asis\.md|02_tobe[\w.]*|03_ux\.md|04_gap_sgi\.md)`\s+|(Fase 2)\s+)?§(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?")


def traduci_rimandi(testo: str, doc: str, mappa: dict) -> str:
    """Sostituisce «§N.M» dei markdown con il numero di sezione del PDF. I paragrafi di norme e moduli restano."""
    righe = []
    for riga in testo.split("\n"):
        def sost(m: re.Match) -> str:
            prima = riga[:m.start()]
            cella = prima[prima.rfind("|") + 1:]
            if _ESTERNI.search(cella) and not m.group(1) and not m.group(2):
                return m.group(0)
            d = doc
            if m.group(1):
                d = m.group(1)[:2]
            elif m.group(2):
                d = "02"
            pezzi = []
            for n in (m.group(3), m.group(4)):
                if n is None:
                    continue
                nuovo = mappa.get((d, n))
                if nuovo is None:
                    _avvisi.append(f"rimando non tradotto: {d} §{n} — «{riga.strip()[:70]}»")
                    return m.group(0)
                pezzi.append(nuovo)
            return "§" + "-".join(pezzi)
        righe.append(_RIF.sub(sost, riga))
    return "\n".join(righe)


def traduci_propri(testo: str, mappa: dict) -> str:
    def sost(m):
        chiave = (m.group(1), m.group(2))
        nuovo = mappa.get(chiave)
        if nuovo is None:
            _avvisi.append(f"rimando proprio non tradotto: {chiave}")
            return m.group(0)
        return "§" + nuovo
    return re.sub(r"\{§(\w+):([\w.]+)\}", sost, testo)


# --------------------------------------------------------------------------------------------------------------------
# Composizione del PDF tecnico
# --------------------------------------------------------------------------------------------------------------------

def componi_tecnico() -> tuple[str, list]:
    docs = {k: sezioni(leggi(v)) for k, v in DOC.items()}
    propri = blocchi_propri()

    # 1) numerazione: (doc, numero d'origine) → numero nel PDF
    mappa: dict[tuple[str, str], str] = {}
    struttura = []  # (capitolo, titolo, [voci]) con voce = dict(num, titolo, tipo, ...)
    for cap, titolo_cap, parti in PIANO:
        voci = []
        i = 0
        for tipo, a, b, titolo in parti:
            if tipo == "S":
                i += 1
                num = f"{cap}.{i}"
                sez = docs[a][b]
                mappa[(a, b)] = num
                figli = []
                for j, f in enumerate(sez["figli"], 1):
                    mappa[(a, f)] = f"{num}.{j}"
                    figli.append((f"{num}.{j}", f))
                voci.append({"tipo": "S", "num": num, "doc": a, "sez": b, "titolo": titolo or sez["titolo"], "figli": figli})
            elif tipo == "P":
                i += 1
                num = f"{cap}.{i}"
                mappa[(a, b)] = num
                voci.append({"tipo": "P", "num": num, "doc": a, "sez": b, "titolo": titolo or docs[a][b]["titolo"]})
            elif tipo == "F":
                sez = docs[a][b]
                mappa[(a, b)] = cap
                voci.append({"tipo": "Fcorpo", "doc": a, "sez": b})
                for f in sez["figli"]:
                    i += 1
                    mappa[(a, f)] = f"{cap}.{i}"
                    voci.append({"tipo": "P", "num": f"{cap}.{i}", "doc": a, "sez": f, "titolo": docs[a][f]["titolo"]})
            else:
                if titolo:
                    i += 1
                    num = f"{cap}.{i}"
                    chiave = {"T": a, "G": "galleria", "Q": "questionario", "R": "codice"}[tipo]
                    mappa[("T", chiave)] = num
                else:
                    num = None
                    mappa[("T", a)] = cap
                voci.append({"tipo": tipo, "num": num, "nome": a, "titolo": titolo})
        struttura.append((cap, titolo_cap, voci))
    # le sezioni «##» non incluse per intero ma con sottosezioni promosse rimandano al capitolo che le ospita
    for d, sez in docs.items():
        for n, s in sez.items():
            if (d, n) not in mappa and s["figli"] and (d, s["figli"][0]) in mappa:
                mappa[(d, n)] = mappa[(d, s["figli"][0])].split(".")[0]
    mappa[("01", "0")] = "1"

    def corpo(d, n):
        return md(traduci_rimandi(docs[d][n]["corpo"], d, mappa))

    def proprio(nome):
        return md(traduci_propri(propri[nome], mappa))

    indice = []
    out = []
    primo = True
    for cap, titolo_cap, voci in struttura:
        ancora = f"c-{cap}"
        etichetta = "Appendice" if cap == "A" else f"Capitolo {cap}"
        out.append(f'<h1 class="capitolo{" primo" if primo else ""}" id="{ancora}"><span class="num">{etichetta}</span>'
                   f"{html.escape(titolo_cap) if cap != 'A' else 'Glossario, riferimenti, questionario'}</h1>")
        indice.append(("c", cap, titolo_cap if cap != "A" else "Appendice: glossario, riferimenti, questionario", ancora))
        if primo:
            out.append(proprio("natura"))
        primo = False
        for v in voci:
            if v.get("num"):
                anc = "s-" + v["num"].replace(".", "-")
                v["titolo"] = v["titolo"].replace("`", "")
                out.append(f'<h2 id="{anc}"><span class="n">{v["num"]}</span>{html.escape(v["titolo"])}</h2>')
                indice.append(("s", v["num"], v["titolo"], anc))
            t = v["tipo"]
            if t == "S":
                out.append(corpo(v["doc"], v["sez"]))
                for num, f in v["figli"]:
                    out.append(f'<h3><span class="n">{num}</span>{html.escape(docs[v["doc"]][f]["titolo"].replace("`", ""))}</h3>')
                    out.append(corpo(v["doc"], f))
            elif t in ("P", "Fcorpo"):
                if t == "P" and v["doc"] == "01" and v["sez"] == "9.1":
                    out.append(proprio("domande_nota"))
                out.append(corpo(v["doc"], v["sez"]))
            elif t == "T":
                out.append(proprio(v["nome"]))
            elif t == "G":
                out.append(proprio("galleria"))
                out.append(galleria())
            elif t == "Q":
                out.append(md(questionario()))
            elif t == "R":
                out.append(proprio("codice"))
                out.append("@@CODICE@@")
    corpo_html = "\n".join(out)
    corpo_html = corpo_html.replace("@@CODICE@@", riferimenti_codice(corpo_html))
    return corpo_html, indice


def galleria() -> str:
    out = []
    for n, (file, titolo, rotta, testo) in enumerate(GALLERIA, 1):
        if isinstance(file, tuple):
            img = '<div class="coppia">' + "".join(f'<img src="../prototipo/png/{f}" alt="">' for f in file) + "</div>"
        else:
            img = f'<img src="../prototipo/png/{file}" alt="">'
        out.append(f'<figure class="schermata">{img}<figcaption><b>Figura {n}. {html.escape(titolo)}</b> · rotta '
                   f"<code>{html.escape(rotta)}</code>. {html.escape(testo)}</figcaption></figure>")
    return "\n".join(out)


def riferimenti_codice(corpo_html: str) -> str:
    """Indice dei file citati: raccoglie i frammenti `percorso/file.ext:righe` dal testo già composto."""
    testo = re.sub(r"<wbr>", "", corpo_html)
    trovati: dict[str, set] = {}
    ultimo = None
    for m in re.finditer(r"<code>([^<]+)</code>", testo):
        c = html.unescape(m.group(1)).strip()
        f = re.match(r"^([\w./\-]+\.(?:py|html|css|js))(?::(\d+(?:-\d+)?))?$", c)
        if f:
            ultimo = f.group(1)
            trovati.setdefault(ultimo, set())
            if f.group(2):
                trovati[ultimo].add(f.group(2))
            continue
        g = re.match(r"^:(\d+(?:-\d+)?)$", c)  # forma abbreviata «`:242`»: stessa fonte del file precedente
        if g and ultimo:
            trovati[ultimo].add(g.group(1))
    righe = ["<table><thead><tr><th>File</th><th>Righe citate</th></tr></thead><tbody>"]
    for f in sorted(trovati):
        nn = sorted(trovati[f], key=lambda x: int(x.split("-")[0]))
        nome = re.sub(r"([/_.])(?=\w)", r"\1<wbr>", html.escape(f))
        righe.append(f"<tr><td><code>{nome}</code></td><td>{', '.join(nn) if nn else '—'}</td></tr>")
    righe.append("</tbody></table>")
    return "\n".join(righe)


def indice_html(indice: list, pagine: dict) -> str:
    out = ['<nav class="indice"><h1>Indice</h1><ol>']
    for tipo, num, titolo, anc in indice:
        etichetta = "" if tipo == "c" and num == "A" else f'<span class="n">{num}</span>'
        out.append(f'<li class="{tipo}"><a href="#{anc}"><span class="t">{etichetta}{html.escape(titolo)}</span>'
                   f'<span class="p"></span><span class="pg">{pagine.get(anc, "000")}</span></a></li>')
    out.append("</ol></nav>")
    return "\n".join(out)


# --------------------------------------------------------------------------------------------------------------------
# Mermaid → SVG
# --------------------------------------------------------------------------------------------------------------------

# Area utile in px CSS (96 px = 25,4 mm): nel testo 180 × 205 mm; a pagina intera 180 × 224 mm; ruotato 224 × 172 mm
# (a pagina intera resta lo spazio per il titolo della sezione, che viene portato in cima alla stessa pagina).
_AREE = {"testo": (680, 775), "alto": (680, 846), "ruotato": (846, 650), "pagina": (680, 930)}
_CORPO_PX = 16  # dimensione del testo nei diagrammi (mermaid.json)


def _varianti(sorgente: str) -> list[str]:
    """Lo stesso diagramma con l'orientamento alternativo: si tiene quello che in pagina viene più grande."""
    righe = sorgente.split("\n")
    testa = righe[0].strip()
    if testa in ("flowchart LR", "flowchart TD"):
        altra = "flowchart TD" if testa.endswith("LR") else "flowchart LR"
        return [sorgente, "\n".join([altra] + righe[1:])]
    if testa == "erDiagram":
        return [sorgente, "\n".join([testa, "    direction LR"] + righe[1:])]
    return [sorgente]


def _misura(svg: Path) -> tuple[float, float]:
    vb = re.search(r'viewBox="([^"]+)"', svg.read_text(encoding="utf-8")).group(1).split()
    return float(vb[2]), float(vb[3])


def rendi_diagrammi(chromium: str) -> dict:
    """Converte i diagrammi in SVG e sceglie come impaginarli. Restituisce {nome: modo}."""
    SVG.mkdir(exist_ok=True)
    registro_f = SVG / "indice.json"
    registro = json.loads(registro_f.read_text(encoding="utf-8")) if registro_f.exists() else {}
    mmdc = os.environ.get("MMDC")
    configurazione = (QUI / "mermaid.json").read_text(encoding="utf-8")
    nuovo = {}
    for nome, sorgente in _diagrammi:
        impronta = hashlib.sha256((sorgente + configurazione + "v5").encode("utf-8")).hexdigest()[:16]
        if registro.get(nome, {}).get("impronta") == impronta and (SVG / nome).exists():
            nuovo[nome] = registro[nome]
            continue
        if not mmdc:
            sys.exit(f"Il diagramma {nome} è cambiato e MMDC non è impostato: vedi l'intestazione dello script.")
        migliore = None
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            pup = tmp / "puppeteer.json"
            pup.write_text(json.dumps({"executablePath": chromium, "args": ["--no-sandbox"]}), encoding="utf-8")
            for k, variante in enumerate(_varianti(sorgente)):
                src = tmp / f"v{k}.mmd"
                dst = tmp / f"v{k}.svg"
                src.write_text(variante, encoding="utf-8")
                cmd = [mmdc, "-i", str(src), "-o", str(dst), "-c", str(QUI / "mermaid.json"), "-p", str(pup),
                       "-b", "transparent", "--svgId", nome[:-4], "-q"]
                r = subprocess.run(cmd, capture_output=True, text=True, shell=False)
                if r.returncode != 0 or not dst.exists():
                    if k == 0:
                        sys.exit(f"mermaid-cli ha fallito su {nome}:\n{r.stdout}\n{r.stderr}")
                    continue
                w, h = _misura(dst)
                for modo, (aw, ah) in _AREE.items():
                    scala = min(aw / w, ah / h, 1.0)
                    # a parità si preferisce il diagramma nel testo, poi l'originale
                    voto = scala - {"testo": 0, "alto": 0.02, "ruotato": 0.04, "pagina": 0.05}[modo] - 0.02 * k
                    if modo == "testo" and scala >= 0.6:
                        voto += 1
                    if migliore is None or voto > migliore[0]:
                        migliore = (voto, modo, scala, k, dst.read_text(encoding="utf-8"), w)
        _, modo, scala, k, contenuto, larghezza = migliore
        (SVG / nome).write_text(contenuto, encoding="utf-8")
        nuovo[nome] = {"impronta": impronta, "modo": modo, "scala": round(scala, 2), "variante": k, "larghezza": round(larghezza)}
        print(f"  diagramma {nome}: {modo}, scala {scala:.2f}, testo {_CORPO_PX * scala * 0.75:.1f} pt"
              + (" (orientamento alternativo)" if k else ""))
    for vecchio in SVG.glob("d*.svg"):
        if vecchio.name not in nuovo:
            vecchio.unlink()
    registro_f.write_text(json.dumps(nuovo, indent=1), encoding="utf-8")
    for nome, v in nuovo.items():
        if "larghezza" not in v:
            v["larghezza"] = round(_misura(SVG / nome)[0])
        if _CORPO_PX * v["scala"] * 0.75 < 5.5:
            _avvisi.append(f"diagramma {nome}: testo a {_CORPO_PX * v['scala'] * 0.75:.1f} pt, sotto i 5,5 pt")
    return nuovo


def impagina_diagrammi(corpo_html: str, modi: dict) -> str:
    """Mette i diagrammi in pagina. Quelli nel testo non superano i 9,6 pt di corpo; quelli a pagina intera
    portano in cima alla pagina il titolo della sezione che li introduce, così il titolo non resta solo."""
    pezzi = re.split(r"@@DIAGRAMMA:(d\d+\.svg)@@", corpo_html)
    out = [pezzi[0]]
    for i in range(1, len(pezzi), 2):
        nome, dopo = pezzi[i], pezzi[i + 1]
        v = modi[nome]
        modo = v["modo"]
        stile = ""
        classe = "diagramma"
        if modo == "testo":
            stile = f' style="width:{min(680, round(v["larghezza"] * 0.8))}px"'
        else:
            classe += " " + modo
            prima = "".join(out)
            pos = max(prima.rfind("<h3"), prima.rfind("<h2"))
            spazio = 246  # mm utili in una pagina
            if pos >= 0 and len(re.sub(r"<[^>]+>", "", prima[pos:])) < 420:
                h2 = prima.rfind("<h2", 0, pos)
                # un titolo di sezione seguito subito dal titolo della sottosezione: si sposta il primo dei due
                if h2 >= 0 and prima[pos:pos + 3] == "<h3" and not re.sub(r"<[^>]+>|\s", "", prima[prima.find("</h2>", h2) + 5:pos]):
                    pos = h2
                    spazio -= 14
                coda = prima[pos:]
                testo = re.sub(r"<[^>]+>", "", coda[coda.find("</h") + 5:])
                spazio -= 11 + coda.count("<p") * 3 + (len(testo) // 105 + (1 if testo.strip() else 0)) * 4.7
                prima = prima[:pos + 3] + ' class="np"' + prima[pos + 3:]
                out = [prima]
            else:
                classe += " sola"
            spazio = int(spazio - 4)
            if modo == "ruotato":
                out.append(f'<figure class="{classe}" style="height:{spazio}mm"><img src="svg/{nome}" '
                           f'alt="Diagramma {int(nome[1:3])}" style="width:{spazio - 2}mm"></figure>')
                out.append(dopo)
                continue
            stile = f' style="max-height:{spazio}mm"'
        out.append(f'<figure class="{classe}"><img src="svg/{nome}" alt="Diagramma {int(nome[1:3])}"{stile}></figure>')
        out.append(dopo)
    return "".join(out)


# --------------------------------------------------------------------------------------------------------------------
# Pagina di stampa
# --------------------------------------------------------------------------------------------------------------------

def carattere() -> str:
    """Il carattere del portale (Outfit), incorporato: i PDF non dipendono dai font installati."""
    cartella = REPO / "django_app/core/static/core/vendor/outfit"
    css = (cartella / "outfit.css").read_text(encoding="utf-8")

    def incorpora(m):
        nome = m.group(1).strip("'\"").split("/")[-1]
        return "url(data:font/woff2;base64," + base64.b64encode((cartella / nome).read_bytes()).decode() + ")"
    return re.sub(r"url\(([^)]+)\)", incorpora, css)


def pagina(corpo: str, classe: str, titolo: str) -> str:
    return ("<!doctype html>\n<html lang=\"it\"><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(titolo)}</title>\n<style>\n{carattere()}\n{(QUI / 'stampa.css').read_text(encoding='utf-8')}\n</style>"
            f"</head>\n<body class=\"{classe}\">\n{corpo}\n</body></html>\n")


def copertina(tipo: str, titolo: str, sotto: str, per: str, nota: str) -> str:
    return f"""<div class="copertina">
  <div class="cop-logo">CN <span>HUB</span></div>
  <div class="cop-tipo">{html.escape(tipo)}</div>
  <div class="cop-titolo">{html.escape(titolo)}</div>
  <div class="cop-sotto">{html.escape(sotto)}</div>
  <div class="cop-riga"></div>
  <div class="cop-piede">
    <div><b>Destinatari</b>{html.escape(per)}</div>
    <div><b>Versione</b>{VERSIONE} · {DATA}</div>
    <div><b>Stato</b>Analisi di fattibilità: proposta, in attesa delle decisioni</div>
  </div>
  <div class="cop-nota">{nota}</div>
</div>"""


def _fascia(sinistra: str, destra: str) -> str:
    return ('<div style="font-family:\'Segoe UI\',Arial,sans-serif;font-size:7.4pt;color:#64748b;width:100%;'
            'padding:0 15mm;display:flex;justify-content:space-between;align-items:center;">'
            f"<span>{sinistra}</span><span>{destra}</span></div>")


def stampa(browser, sorgente: Path, uscita: Path, sottotitolo: str | None) -> None:
    pg = browser.new_page()
    pg.goto(sorgente.as_uri())
    pg.wait_for_load_state("networkidle")
    pg.evaluate("document.fonts.ready")
    if sottotitolo is None:  # copertina: pagina piena
        pg.pdf(path=str(uscita), format="A4", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    else:
        pg.pdf(path=str(uscita), format="A4", print_background=True, display_header_footer=True,
               margin={"top": "21mm", "bottom": "18mm", "left": "15mm", "right": "15mm"},
               header_template=_fascia('<b style="color:#10233f;letter-spacing:.1em">CN HUB</b> &nbsp;·&nbsp; '
                                       + html.escape(TITOLO), html.escape(sottotitolo)),
               footer_template=_fascia(f"Versione {VERSIONE} · {DATA}",
                                       'Pagina <span class="pageNumber"></span> di <span class="totalPages"></span>'))
    pg.close()


def sbordi(browser, sorgente: Path) -> list[str]:
    """Elementi più larghi dell'area di stampa (180 mm): tabelle, blocchi di codice, immagini."""
    pg = browser.new_page(viewport={"width": 680, "height": 900})
    pg.emulate_media(media="print")
    pg.goto(sorgente.as_uri())
    pg.wait_for_load_state("networkidle")
    fuori = pg.evaluate("""() => {
        const largo = document.body.clientWidth, out = [];
        for (const el of document.querySelectorAll('table, pre, img, figure, .pag > *')) {
            const r = el.getBoundingClientRect();
            if (r.right > largo + 1.5 || el.scrollWidth > el.clientWidth + 1.5)
                out.push(el.tagName + ' ' + Math.round(r.right - largo) + 'px: ' + (el.innerText || el.src || '').slice(0, 60).replace(/\\s+/g, ' '));
        }
        return out;
    }""")
    pg.close()
    return fuori


def unisci(cop: Path, corpo: Path, uscita: Path, titolo: str, segnalibri: list | None) -> int:
    doc = fitz.open()
    with fitz.open(cop) as a, fitz.open(corpo) as b:
        doc.insert_pdf(a)
        doc.insert_pdf(b)
    if segnalibri:
        doc.set_toc(segnalibri)
    doc.set_metadata({"title": titolo, "author": "CN HUB · analisi di fattibilità", "subject": TITOLO,
                      "keywords": "ruoli, mansioni, competenze, formazione, EN 9100", "creator": "build/costruisci_pdf.py"})
    doc.save(uscita, garbage=4, deflate=True)
    n = doc.page_count
    doc.close()
    return n


def pagine_delle_ancore(corpo_pdf: Path, indice: list) -> dict:
    """Pagina (del corpo, da 1) di ogni voce dell'indice, letta dai collegamenti interni dell'indice stesso."""
    doc = fitz.open(corpo_pdf)
    bersagli = []
    for p in doc:
        coll = [l for l in p.get_links() if l.get("kind") in (fitz.LINK_GOTO, fitz.LINK_NAMED) and "page" in l]
        coll.sort(key=lambda l: (round(l["from"].y0, 1), l["from"].x0))
        bersagli += [l["page"] + 1 for l in coll]
        if len(bersagli) >= len(indice):
            break
    doc.close()
    if len(bersagli) < len(indice):
        sys.exit(f"Indice: trovati {len(bersagli)} collegamenti su {len(indice)} voci.")
    return {voce[3]: bersagli[i] for i, voce in enumerate(indice)}


def rasterizza(pdf: Path, cartella: Path, prefisso: str) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    for vecchio in cartella.glob(prefisso + "_*.png"):
        vecchio.unlink()
    doc = fitz.open(pdf)
    for i, p in enumerate(doc, 1):
        p.get_pixmap(dpi=110).save(str(cartella / f"{prefisso}_{i:03d}.png"))
    doc.close()


def testo_pdf(pdf: Path) -> list[str]:
    doc = fitz.open(pdf)
    out = [p.get_text() for p in doc]
    doc.close()
    return out


def controlli_comuni(nome: str, pdf: Path) -> list[str]:
    esiti = []
    doc = fitz.open(pdf)
    vuote = [i for i, p in enumerate(doc, 1) if len(p.get_text().strip()) < 40 and not p.get_images()]
    caratteri = sorted({f[3].split("+")[-1] for p in doc for f in p.get_fonts()})
    esiti.append(f"{nome}: {doc.page_count} pagine, {pdf.stat().st_size / 1e6:.1f} MB; pagine vuote: {vuote or 'nessuna'}")
    esiti.append(f"{nome}: caratteri incorporati: {', '.join(caratteri)}")
    doc.close()
    return esiti


# --------------------------------------------------------------------------------------------------------------------
# I due PDF
# --------------------------------------------------------------------------------------------------------------------

def fai_tecnico(browser, chromium: str, raster: Path | None) -> list[str]:
    corpo_html, indice = componi_tecnico()
    corpo_html = impagina_diagrammi(corpo_html, rendi_diagrammi(chromium))
    sorgente = QUI / "stampa_tecnico.html"
    cop = QUI / "stampa_tecnico_copertina.html"
    cop.write_text(pagina(copertina(
        "Documento tecnico", "Ruoli, mansioni, competenze e formazione",
        "Analisi di fattibilità per NOVICROM HUB: stato attuale, proposta di flusso e di calcolo, interfaccia, piano.",
        "IT e Qualità",
        "Sola analisi: nessun codice, dato o impostazione del portale è stato modificato. Le proposte restano proposte: "
        "decidono il proprietario del progetto e la Qualità. Esempi e schermate usano dati inventati; i dati reali "
        "compaiono solo come conteggi."), "", "Fattibilità RMC · documento tecnico"), encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        pagine: dict = {}
        for giro in (1, 2, 3):
            sorgente.write_text(pagina(f'<main class="doc">{indice_html(indice, pagine)}\n{corpo_html}</main>', "",
                                       "Fattibilità RMC · documento tecnico"), encoding="utf-8")
            stampa(browser, sorgente, tmp / "corpo.pdf", "Documento tecnico")
            nuove = pagine_delle_ancore(tmp / "corpo.pdf", indice)
            if nuove == pagine:
                break
            pagine = nuove
        else:
            sys.exit("L'indice non si stabilizza.")
        stampa(browser, cop, tmp / "cop.pdf", None)
        segnalibri = [[1 if t == "c" else 2, (f"{n}  " if not (t == "c" and n == "A") else "") + tit, pagine[a] + 1]
                      for t, n, tit, a in indice]
        uscita = RADICE / "Fattibilita_RMC_Tecnico.pdf"
        unisci(tmp / "cop.pdf", tmp / "corpo.pdf", uscita, "Fattibilità Ruoli → Mansioni → Competenze · documento tecnico",
               segnalibri)
    esiti = controlli_comuni("Tecnico", uscita)
    fuori = sbordi(browser, sorgente)
    esiti.append(f"Tecnico: elementi che sbordano dall'area di stampa: {len(fuori)}" + "".join("\n    " + f for f in fuori))
    esiti.append(f"Tecnico: diagrammi Mermaid convertiti in SVG: {len(_diagrammi)}; schermate: {len(GALLERIA)}")
    if raster:
        rasterizza(uscita, raster, "tecnico")
    return esiti


def fai_direzione(browser, raster: Path | None) -> list[str]:
    corpo = leggi("build/pdf_direzione.html")
    corpo = re.sub(r"<!--.*?-->", "", corpo, flags=re.S)
    sorgente = QUI / "stampa_direzione.html"
    cop = QUI / "stampa_direzione_copertina.html"
    sorgente.write_text(pagina(f'<main class="dir">{corpo}</main>', "", "Fattibilità RMC · sintesi per la Direzione"),
                        encoding="utf-8")
    cop.write_text(pagina(copertina(
        "Sintesi per la Direzione", "Le persone giuste sul lavoro giusto, con le prove in mano",
        "Ruoli, mansioni e competenze nel portale: che cosa proponiamo, che cosa serve, che cosa chiediamo di decidere.",
        "Direzione",
        "È una proposta: nulla è stato cambiato nel portale. I numeri sul presente sono conteggi letti dal portale il "
        "21 novembre 2026; gli esempi usano nomi e dati inventati."), "", "Fattibilità RMC · sintesi per la Direzione"),
        encoding="utf-8")
    uscita = RADICE / "Fattibilita_RMC_Direzione.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        stampa(browser, sorgente, tmp / "corpo.pdf", "Sintesi per la Direzione")
        stampa(browser, cop, tmp / "cop.pdf", None)
        n = unisci(tmp / "cop.pdf", tmp / "corpo.pdf", uscita, "Fattibilità Ruoli → Mansioni → Competenze · sintesi per la Direzione", None)
    esiti = controlli_comuni("Direzione", uscita)
    sezioni_n = len(re.findall(r'<section class="pag">', corpo))
    esiti.append(f"Direzione: {n} pagine = 1 copertina + {sezioni_n} pagine di contenuto "
                 + ("(OK: entro le 10)" if n == sezioni_n + 1 and n <= 10 else "(ATTENZIONE: una pagina sborda o supera le 10)"))
    fuori = sbordi(browser, sorgente)
    esiti.append(f"Direzione: elementi che sbordano dall'area di stampa: {len(fuori)}" + "".join("\n    " + f for f in fuori))
    testo = "\n".join(testo_pdf(uscita))
    for gruppo, termini in (("termini vietati dalla missione", VIETATI_MISSIONE), ("altri termini informatici", VIETATI_ALTRI)):
        trovati = []
        for t in termini:
            maiuscole = t.isupper()
            for m in re.finditer(r"(?<![\wÀ-ÿ])" + re.escape(t) + r"(?![\wÀ-ÿ])", testo, flags=0 if maiuscole else re.I):
                trovati.append(f"{t}: «…{testo[max(0, m.start() - 30):m.end() + 30]}…»".replace("\n", " "))
        esiti.append(f"Direzione: {gruppo} ({', '.join(termini)}): " + ("NESSUNO" if not trovati else "".join("\n    " + x for x in trovati)))
    if raster:
        rasterizza(uscita, raster, "direzione")
    return esiti


def coerenza() -> list[str]:
    """Numeri chiave: devono comparire uguali nei markdown, nei risultati del motore di riferimento e nei PDF."""
    ris = json.loads((QUI / "risultati.json").read_text(encoding="utf-8"))
    q, qb = ris["quadro"], ris["quadro_blocco"]
    tecnico = " ".join(testo_pdf(RADICE / "Fattibilita_RMC_Tecnico.pdf"))
    direzione = " ".join(testo_pdf(RADICE / "Fattibilita_RMC_Direzione.pdf"))
    tecnico, direzione = (re.sub(r"\s+", " ", t).lower() for t in (tecnico, direzione))  # i titoletti sono in maiuscolo
    s = q["stati"]
    sb = qb["stati"]
    attesi_tecnico = [
        f'{s["CONFORME"]} conformi · {s["CON_RISERVA"]} con riserva · {s["SOTTO_SUPERVISIONE"]} sotto supervisione · {s["NON_CONFORME"]} non conformi',
        f'{sb["CONFORME"]} · {sb["CON_RISERVA"]} · {sb["SOTTO_SUPERVISIONE"]} · {sb["NON_CONFORME"]}',
        f'{q["persone"]} persone', f'{q["mansioni"]} mansioni', f'{q["competenze"]} competenze',
        "242 mansioni lavorative", "443", "203", "56 persone su 135", "MT CN 06 Rev.21", "circa 690", "774 corsi", "595", "51 controlli", "da 18 a 31",
        "da 7 a 11", "Marco Rivalta", "Giulia Ferrante", "Aldo Bianchetti", "Sara Colombari", "Piero Lombardini",
    ]
    attesi_direzione = ["242", "443", "203", "56 su 135", "5 ingredienti su 6", "Marco Rivalta", "18 domande",
                        "7-11 settimane", "4-7 mesi", "0 su 242", "0 su 443", "gennaio 2027", "sedici pagine"]
    marco = ris["casi"]["P01"]["potenziali"][0]
    esiti = [f'Coerenza: motore di riferimento, Marco Rivalta su «{marco["nome"]}»: {marco["ok"]} requisiti su {marco["tot"]}'
             + (" (OK)" if (marco["ok"], marco["tot"]) == (5, 6) else " (DIVERSO dal testo: 5 su 6)")]
    for nome, testo, attesi in (("Tecnico", tecnico, attesi_tecnico), ("Direzione", direzione, attesi_direzione)):
        mancanti = [a for a in attesi if a.lower() not in testo]
        esiti.append(f"Coerenza: {nome}, {len(attesi) - len(mancanti)} valori su {len(attesi)} presenti"
                     + ("" if not mancanti else "; MANCANO: " + " | ".join(mancanti)))
    return esiti


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--solo", choices=["tecnico", "direzione"])
    ap.add_argument("--raster", type=Path, help="cartella in cui salvare ogni pagina in PNG")
    arg = ap.parse_args()
    esiti: list[str] = []
    with sync_playwright() as pw:
        chromium = pw.chromium.executable_path
        browser = pw.chromium.launch()
        if arg.solo != "direzione":
            esiti += fai_tecnico(browser, chromium, arg.raster)
        if arg.solo != "tecnico":
            esiti += fai_direzione(browser, arg.raster)
        browser.close()
    if not arg.solo:
        esiti += coerenza()
    for a in sorted(set(_avvisi)):
        esiti.append("AVVISO " + a)
    (QUI / "controlli_pdf.txt").write_text("\n".join(esiti) + "\n", encoding="utf-8")
    print("\n".join(esiti))


if __name__ == "__main__":
    main()
