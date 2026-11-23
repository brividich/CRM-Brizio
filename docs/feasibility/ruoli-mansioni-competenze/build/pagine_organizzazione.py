"""Bozze delle otto pagine a cui portano i collegamenti di «Organizzazione».

Ogni bozza parte dalla pagina vera «Organizzazione» (HTML salvato da un test: barra del portale,
menu, carattere e stili sono quelli veri) e ne sostituisce il contenuto. Nella seconda riga del menu
compaiono le pagine della sezione in fila, come nel disegno approvato. I dati sono inventati.

    python pagine_organizzazione.py <guscio .html> <cartella di uscita>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

GUSCIO, USCITA = Path(sys.argv[1]), Path(sys.argv[2])
VOCI = ["Panoramica", "Esplora la struttura", "Mansioni", "Richieste", "Reparti e capi", "Centri di costo",
        "Organigramma", "Prova un cambiamento", "Struttura e revisioni"]

STILE = """
.m-filtri{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:0 0 12px}
.m-campo{display:inline-flex;align-items:center;height:36px;padding:0 12px;border:1px solid #d7e0ea;border-radius:10px;background:#fff;font-size:13px;color:#94a3b8;min-width:170px}
.m-campo.largo{min-width:300px}
.m-chip{padding:6px 12px;border-radius:999px;border:1px solid #d7e0ea;background:#fff;font-size:12.5px;font-weight:600;color:#475569}
.m-chip.on{background:#e8f3fb;border-color:#9cc6e6;color:#0c2545}
.m-card{background:#fff;border:1px solid #d7e0ea;border-radius:14px;overflow:hidden;margin:0 0 16px}
.m-pad{padding:14px 16px}
table.m-tab{width:100%;border-collapse:collapse;font-size:13.5px}
.m-tab th{text-align:left;padding:9px 16px;background:#f8fafc;color:#64748b;font-weight:600;font-size:12px;border-bottom:1px solid #e2e8f0;white-space:nowrap}
.m-tab td{padding:10px 16px;border-bottom:1px solid #eef2f7;vertical-align:middle}
.m-tab tr:last-child td{border-bottom:0}
.m-tab td b{color:#0f172a}
.m-tab tr.on td{background:#e8f3fb}
.m-tab small{display:block;font-size:12px;color:#64748b}
.m-campi{margin:0;display:grid;grid-template-columns:minmax(0,1fr);gap:8px}
.m-campi.due{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 28px}
.m-campi div{display:flex;gap:10px;align-items:baseline}
.m-campi dt{flex:0 0 150px;font-size:13px;color:#64748b}
.m-campi dd{margin:0;font-weight:600;font-size:13.5px;color:#0f172a}
.m-st{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;white-space:nowrap;background:#eef2f7;color:#475569}
.m-st.ok{background:#dcfce7;color:#166534}.m-st.info{background:#e8f3fb;color:#1d4f7c}.m-st.warn{background:#fef3c7;color:#92400e}.m-st.ko{background:#fee2e2;color:#b91c1c}
.m-lv{display:inline-flex;align-items:center;gap:7px;white-space:nowrap;color:#475569;font-size:13px}
.m-lv b{display:inline-flex;width:22px;height:22px;border-radius:6px;align-items:center;justify-content:center;font-size:12.5px;color:#fff !important;background:#94a3b8}
.m-lv .L{background:#d69e2e}.m-lv .U{background:#38a169}.m-lv .O{background:#2f5f89}
.m-dove{display:flex;flex-wrap:wrap;gap:6px;align-items:center;padding:10px 16px;font-size:13px}
.m-dove span{color:#64748b}.m-dove b{color:#0c2545}.m-dove i{font-style:normal;color:#b6c2d1;margin:0 6px}
.m-colonne{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:0 0 16px}
.m-col{height:206px}
.m-col h3{margin:0;padding:10px 14px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#64748b;border-bottom:1px solid #eef2f7}
.m-col ul{list-style:none;margin:0;padding:6px}
.m-col li{padding:7px 10px;border-radius:8px;font-weight:600;font-size:13.5px;display:flex}
.m-col li.on{background:#e8f3fb;color:#0c2545}
.m-col li.on::after{content:"›";margin-left:auto;color:#6b8db3;font-size:17px;line-height:1}
.m-passi{display:flex;margin:0 0 16px}
.m-passo{flex:1;padding:10px 14px;background:#fff;border:1px solid #d7e0ea;font-size:12.5px;color:#64748b}
.m-passo+.m-passo{border-left:0}
.m-passo:first-child{border-radius:12px 0 0 12px}.m-passo:last-child{border-radius:0 12px 12px 0}
.m-passo b{display:block;font-size:13.5px;color:#0f172a}
.m-passo.fatto b::before{content:"✓ ";color:#38a169}
.m-passo.ora{background:#e8f3fb;border-color:#9cc6e6}
.m-albero{padding:22px 16px 26px;text-align:center}
.m-nodo{display:inline-block;padding:9px 14px;border:1px solid #d7e0ea;border-radius:10px;background:#fff;font-size:13px;min-width:150px}
.m-nodo b{display:block;color:#0f172a}.m-nodo span{font-size:12px;color:#64748b}
.m-nodo.capo{border-color:#0c2545;background:#f4f8fc}
.m-nodo.on{border-color:#ff6b00;background:#fff7f0}
.m-gambo{width:1px;height:20px;background:#b6c2d1;margin:0 auto}
.m-fila{display:flex;justify-content:center;gap:16px;position:relative;padding-top:20px}
.m-fila::before{content:"";position:absolute;top:0;left:8%;right:8%;height:1px;background:#b6c2d1}
.m-fila>div{position:relative}
.m-fila>div::before{content:"";position:absolute;top:-20px;left:50%;width:1px;height:20px;background:#b6c2d1}
.m-sotto{display:flex;flex-direction:column;gap:8px;align-items:center;margin-top:10px}
.m-sotto .m-nodo{min-width:140px;padding:6px 10px;font-size:12px}
.m-confronto{display:grid;grid-template-columns:1fr 1fr;gap:0}
.m-confronto>div{padding:14px 16px}
.m-confronto>div+div{border-left:1px solid #eef2f7;background:#fbfdff}
.m-confronto h4{margin:0 0 10px;font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:#64748b}
.m-cambia dd{color:#c2410c !important}
.m-elenco{list-style:none;margin:0;padding:0}
.m-elenco li{display:flex;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid #eef2f7;font-size:13.5px}
.m-elenco li:last-child{border-bottom:0}
.m-elenco li>span:last-child{margin-left:auto}
.m-seg{display:inline-flex;width:22px;height:22px;border-radius:6px;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex:none}
.m-seg.piu{background:#dcfce7;color:#166534}.m-seg.meno{background:#fee2e2;color:#b91c1c}.m-seg.mod{background:#fef3c7;color:#92400e}
.m-legenda{display:flex;flex-wrap:wrap;gap:6px 18px;padding:10px 16px;border-top:1px solid #eef2f7;font-size:12.5px;color:#64748b}
"""


def ico(nome):
    return f'<svg class="op-ico"><use href="#i-{nome}"/></svg>'


def btn(testo, icona="", primario=False, piccolo=False):
    classi = "op-btn" + (" op-btn-p" if primario else "") + (" op-btn-s" if piccolo else "")
    return f'<a class="{classi}" href="#">{ico(icona) if icona else ""}{testo}</a>'


def testa(titolo, sotto, azioni):
    return (f'<div class="op-testa"><div><h1>{titolo}</h1><p>{sotto}</p></div>'
            f'<div class="op-azioni">{"".join(azioni)}</div></div>')


def h(titolo, lato=""):
    return f'<div class="op-h"><h2>{titolo}</h2><span>{lato}</span></div>'


def tabella(intestazioni, righe, scelta=None):
    testa_ = "".join(f"<th>{x}</th>" for x in intestazioni)
    corpo = "".join(f'<tr{" class=on" if i == scelta else ""}>' + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                    for i, r in enumerate(righe))
    return (f'<div data-fm-table-skip="1" data-mcards-off><table class="m-tab"><thead><tr>{testa_}</tr></thead>'
            f'<tbody>{corpo}</tbody></table></div>')


def campi(coppie, due=False, classe=""):
    righe = "".join(f"<div><dt>{k}:</dt><dd>{v}</dd></div>" for k, v in coppie)
    return f'<dl class="m-campi{" due" if due else ""} {classe}">{righe}</dl>'


def st(testo, tono=""):
    return f'<span class="m-st {tono}">{testo}</span>'


PAROLE = {"I": "in formazione", "L": "intermedio", "U": "autonomo", "O": "esperto"}


def lv(codice, parola=True):
    return f'<span class="m-lv"><b class="{codice}">{codice}</b>{PAROLE[codice] if parola else ""}</span>'


def fare(righe):
    out = ""
    for n, titolo, sotto, azione, urgente in righe:
        out += (f'<div class="op-riga{" is-urgente" if urgente else ""}"><b>{n}</b><div><strong>{titolo}</strong>'
                f'<small>{sotto}</small></div>{btn(azione, piccolo=True)}</div>')
    return f'<div class="op-fare">{out}</div>'


LEGENDA = '<div class="m-legenda">' + "".join(f"<span><b>{c}</b> {p}</span>" for c, p in PAROLE.items()) + "</div>"
GUIDA = btn("? Guida")

PAGINE = {}

# 1 ─ Esplora la struttura
PAGINE["01_esplora_la_struttura"] = ("Esplora la struttura", testa(
    "Esplora la struttura", "Scegli a sinistra e scendi: sotto trovi che cosa richiede la mansione e chi ce l'ha.",
    [GUIDA, btn("Nuova richiesta per questa mansione", "plus", True)]) + f"""
<div class="m-card m-dove"><span>Centro di costo:</span> <b>CN5G</b><i>›</i><span>Reparto:</span> <b>CN5GL</b><i>›</i><span>Ruolo:</span> <b>Operatore macchina utensile</b><i>›</i><span>Mansione:</span> <b>DM7 - DMC 160U Duoblock</b></div>
<div class="m-colonne">
  <div class="m-card m-col"><h3>Centri di costo</h3><ul><li>AGGIUSTAGGIO</li><li>CN4</li><li>CN5</li><li class="on">CN5G</li><li>CONTROLLO</li></ul></div>
  <div class="m-card m-col"><h3>Reparti</h3><ul><li class="on">CN5GL</li><li>CN5GS</li><li>ALC</li></ul></div>
  <div class="m-card m-col"><h3>Ruoli</h3><ul><li class="on">Operatore macchina utensile</li><li>Capo reparto</li></ul></div>
  <div class="m-card m-col"><h3>Mansioni</h3><ul><li>DM6 - DMC 125U Duoblock</li><li class="on">DM7 - DMC 160U Duoblock</li><li>DM12 - DMC 160U Duoblock</li><li>Responsabilità del reparto</li></ul></div>
</div>
<div class="op-due">
  <section>{h("Mansione scelta", "Ogni dato con la sua etichetta")}
    <div class="m-card m-pad">{campi([("Mansione", "DM7 - DMC 160U Duoblock"), ("Ruolo", "Operatore macchina utensile"), ("Reparto", "CN5GL"), ("Responsabile del reparto", "Elio Vantaro"), ("Centro di costo", "CN5G"), ("Macchina", "DM7 · DMC 160U")], due=True)}</div>
    {h("Competenze richieste dalla mansione", "5")}
    <div class="m-card">{tabella(["Competenza", "Livello richiesto"], [["<b>Lettura del disegno tecnico</b>", lv("U")], ["<b>Set-up macchina</b>", lv("U")], ["<b>Uso degli strumenti di misura</b>", lv("U")], ["<b>FOD</b>", lv("U")], ["<b>Procedure interne</b>", lv("U")]])}</div>
  </section>
  <section>{h("Persone con questa mansione", "4")}
    <div class="m-card">{tabella(["Persona", "Livello", "Stato"], [["<b>Tullio Brevani</b>", lv("O"), st("Abilitato", "ok")], ["<b>Nora Castelvi</b>", lv("U"), st("Abilitato", "ok")], ["<b>Ivo Marendi</b>", lv("L"), st("In addestramento", "info")], ["<b>Mira Dossen</b>", lv("I"), st("In formazione", "warn")]])}{LEGENDA}</div>
  </section>
</div>""")

# 1 bis ─ Esplora la struttura con la ricerca e con la colonna «Mansioni» spostabile (richiesta del 23/11/2026):
# la colonna può stare per ultima (si scende dal centro di costo) o per prima (si parte dalla mansione).
STILE += """
.m-sposta{display:flex;align-items:center}
.m-sposta a{margin-left:auto;display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;border:1px solid #9cc6e6;background:#e8f3fb;color:#0c2545;font-size:11.5px;font-weight:700;letter-spacing:0;text-transform:none;text-decoration:none}
.m-col.spostata{border-color:#9cc6e6;box-shadow:0 0 0 3px #e8f3fb}
"""
_RICERCA = ('<div class="m-filtri"><span class="m-campo largo" style="min-width:520px">Cerca centro di costo, reparto, ruolo, '
            'mansione o competenza…</span>' + btn("Cerca", "search") + "</div>")
_COL_MANSIONI = ('<div class="m-card m-col"><h3>Mansioni</h3><ul><li>DM6 - DMC 125U Duoblock</li><li class="on">DM7 - DMC 160U Duoblock</li>'
                 '<li>DM12 - DMC 160U Duoblock</li><li>Responsabilità del reparto</li></ul></div>')
_DOVE_ULTIMA = ('<span>Centro di costo:</span> <b>CN5G</b><i>›</i><span>Reparto:</span> <b>CN5GL</b><i>›</i><span>Ruolo:</span> '
                '<b>Operatore macchina utensile</b><i>›</i><span>Mansione:</span> <b>DM7 - DMC 160U Duoblock</b>')
_DOVE_PRIMA = ('<span>Mansione:</span> <b>DM7 - DMC 160U Duoblock</b><i>›</i><span>Centro di costo:</span> <b>CN5G</b><i>›</i>'
               '<span>Reparto:</span> <b>CN5GL</b><i>›</i><span>Ruolo:</span> <b>Operatore macchina utensile</b>')


def _esplora(per_prima: bool) -> str:
    base = PAGINE["01_esplora_la_struttura"][1]
    assert _COL_MANSIONI in base and _DOVE_ULTIMA in base
    comando = "Metti per ultima ›" if per_prima else "‹ Metti per prima"
    colonna = _COL_MANSIONI.replace('<div class="m-card m-col"><h3>Mansioni</h3>',
                                    f'<div class="m-card m-col{" spostata" if per_prima else ""}">'
                                    f'<h3 class="m-sposta">Mansioni<a href="#">{comando}</a></h3>')
    if per_prima:
        colonna = colonna.replace("<ul>", '<ul><li style="font-weight:400;color:#94a3b8">Filtra mansioni…</li>')
        out = base.replace(_COL_MANSIONI, "").replace('<div class="m-colonne">', '<div class="m-colonne">' + colonna)
        out = out.replace(_DOVE_ULTIMA, _DOVE_PRIMA)
    else:
        out = base.replace(_COL_MANSIONI, colonna)
    return out.replace('<div class="m-card m-dove">', _RICERCA + '<div class="m-card m-dove">')


PAGINE["01b_esplora_mansioni_per_prime"] = ("Esplora la struttura", _esplora(True))
PAGINE["01_esplora_la_struttura"] = ("Esplora la struttura", _esplora(False))

# Caso con tante competenze (richiesta del 23/11/2026): l'interfaccia non deve sballare.
# Il riquadro ha un'altezza fissa e scorre al suo interno; i nomi lunghi vanno a capo nella cella.
STILE += """
.m-scorre{max-height:300px;overflow-y:auto;scrollbar-gutter:stable}
.m-scorre thead th{position:sticky;top:0;z-index:1}
.m-scorre td:first-child{overflow-wrap:anywhere}
.m-scorre td:last-child{white-space:nowrap;width:1%}
"""
TANTE_COMPETENZE = [
    ("Lettura del disegno tecnico", "U"), ("Set-up macchina", "U"), ("Uso degli strumenti di misura", "U"),
    ("Industrializzazione e definizione del processo produttivo per prodotti soggetti a EN 9100 e requisiti cliente speciali", "U"),
    ("FOD", "U"), ("Procedure interne", "U"), ("Programmazione a bordo macchina", "L"), ("Cambio utensile e presetting", "U"),
    ("Controllo dimensionale in processo", "U"), ("Compilazione dei fogli operativi", "U"), ("Gestione delle non conformità", "L"),
    ("Sicurezza sulla macchina", "U"), ("Movimentazione dei pezzi", "U"), ("Manutenzione di primo livello", "L"),
    ("Lettura del ciclo di lavoro", "U"), ("Uso del gestionale di produzione", "U"), ("Tracciabilità dei materiali", "U"),
    ("Marcatura e identificazione", "U"), ("Pulizia e 5S", "U"), ("Rilievo e registrazione delle misure", "U"),
    ("Segnalazione delle anomalie", "U"), ("Passaggio di consegne tra turni", "U"),
]
assert len(TANTE_COMPETENZE) == 22


# 2 ─ Mansioni
PAGINE["02_mansioni"] = ("Mansioni", testa(
    "Mansioni", "Tutte le mansioni: che cosa richiedono e chi le ha.",
    [GUIDA, btn("Importa da Excel", "download"), btn("Nuova mansione", "plus", True)]) + f"""
<div class="m-filtri"><span class="m-campo largo">Cerca una mansione…</span><span class="m-campo">Reparto: tutti</span><span class="m-campo">Ruolo: tutti</span>
  <span class="m-chip on">Tutte · 253</span><span class="m-chip">Senza competenze · 182</span><span class="m-chip">Senza persone · 21</span></div>
<div class="op-due">
  <section>{h("Elenco", "253 mansioni")}
    <div class="m-card">{tabella(["Mansione", "Reparto", "Ruolo", "Competenze richieste", "Persone", "Stato"], [
        ["<b>DM6 - DMC 125U Duoblock</b>", "CN5GL", "Operatore macchina utensile", "5", "3", st("Completa", "ok")],
        ["<b>DM7 - DMC 160U Duoblock</b>", "CN5GL", "Operatore macchina utensile", "22", "4", st("Completa", "ok")],
        ["<b>DM12 - DMC 160U Duoblock</b>", "CN5GL", "Operatore macchina utensile", "5", "2", st("Completa", "ok")],
        ["<b>Marcatura laser</b>", "MARCATURA", "Operatore manuale", "0", "2", st("Senza competenze", "warn")],
        ["<b>Liquidi penetranti</b>", "CND", "Operatore controlli", "0", "1", st("Senza competenze", "warn")],
        ["<b>Programmazione CAM/CNC</b>", "UFFICIO TECNICO (CAM)", "Programmatore", "9", "4", st("Completa", "ok")],
        ["<b>Controllo durezza</b>", "CONTROLLO TRADIZIONALE", "Operatore controlli", "0", "0", st("Senza persone", "ko")],
    ], scelta=1)}</div>
  </section>
  <section>{h("Mansione scelta", "")}
    <div class="m-card m-pad">{campi([("Mansione", "DM7 - DMC 160U Duoblock"), ("Reparto", "CN5GL"), ("Ruolo", "Operatore macchina utensile"), ("Responsabile", "Elio Vantaro"), ("Competenze richieste", "22"), ("Persone", "4")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Apri la mansione", "arrow-right", piccolo=True)}{btn("Modifica", "edit", piccolo=True)}</div></div>
    {h("Competenze richieste", "22 · l'elenco scorre nel riquadro")}
    <div class="m-card"><div class="m-scorre">{tabella(["Competenza", "Livello richiesto"], [[f"<b>{n}</b>", lv(l)] for n, l in TANTE_COMPETENZE])}</div><div class="m-legenda"><span>22 competenze. Il riquadro ha un'altezza fissa: la pagina non si allunga.</span></div></div>
  </section>
</div>""")

# 3 ─ Richieste
PAGINE["03_richieste"] = ("Richieste", testa(
    "Richieste", "Ogni cambio su una mansione o su una competenza parte da qui.",
    [GUIDA, btn("Nuova richiesta", "plus", True)]) + f"""
<div class="m-filtri"><span class="m-chip on">Tutte · 14</span><span class="m-chip">In approvazione · 3</span><span class="m-chip">Approvate · 4</span><span class="m-chip">Respinte · 1</span><span class="m-chip">Evase · 6</span>
  <span class="m-campo largo" style="margin-left:auto">Cerca persona o mansione…</span></div>
<div class="op-due">
  <section>{h("Elenco", "14 richieste")}
    <div class="m-card">{tabella(["Persona", "Tipo di richiesta", "Mansione o competenza", "Richiesta", "Stato", "Tocca a"], [
        ["<b>Ivo Marendi</b>", "Assegnazione di mansione", "DM12 - DMC 160U Duoblock", "RAM-2027-0021", st("In approvazione", "warn"), "RDD: approvare"],
        ["<b>Mira Dossen</b>", "Assegnazione di mansione", "DM7 - DMC 160U Duoblock", "RAM-2027-0018", st("Approvata", "info"), "Qualità o HR: aprire la sessione"],
        ["<b>Dario Selvani</b>", "Acquisizione di competenza", "FOD", "RAC-2027-0006", st("In approvazione", "warn"), "MSO: approvare"],
        ["<b>Lea Zuffardi</b>", "Sospensione di mansione", "DM6 - DMC 125U Duoblock", "RAM-2027-0015", st("Evasa", "ok"), "Nessuno"],
        ["<b>Nora Castelvi</b>", "Assegnazione di mansione", "DM12 - DMC 160U Duoblock", "RAM-2027-0009", st("Respinta", "ko"), "Nessuno"],
    ])}</div>
  </section>
  <section>{h("Da fare", "Ciò che aspetta te")}
    {fare([(2, "Richieste da approvare", "Tocca a te decidere", "Decidi", True), (1, "Le mie richieste in attesa di altri", "Tocca a RDD", "Apri", False)])}
    <p class="op-nota">{ico("alert-cir")}<span>Le richieste su mansioni le approva RDD, quelle su competenze MSO. Nessuno approva la propria.</span></p>
  </section>
</div>""")

# 4 ─ Reparti e capi
PAGINE["04_reparti_e_capi"] = ("Reparti e capi", testa(
    "Reparti e capi", "Chi guida ogni reparto e quante persone ci lavorano.",
    [GUIDA, btn("Nuovo reparto", "plus", True)]) + f"""
<div class="m-filtri"><span class="m-campo largo">Cerca un reparto o una persona…</span><span class="m-campo">Centro di costo: tutti</span>
  <span class="m-chip on">Tutti · 39</span><span class="m-chip">Senza responsabile · 3</span></div>
<div class="op-due">
  <section>{h("Elenco", "39 reparti")}
    <div class="m-card">{tabella(["Reparto", "Centro di costo", "Responsabile", "Ruolo responsabile", "Persone", "Stato"], [
        ["<b>CN5GL</b>", "CN5G", "Elio Vantaro", "Capo reparto", "6", st("Completo", "ok")],
        ["<b>CN5GS</b>", "CN5G", "Sara Bellandi", "Capo reparto", "8", st("Completo", "ok")],
        ["<b>MARCATURA</b>", "AGGIUSTAGGIO", "Nessuno", "Nessuno", "2", st("Senza responsabile", "warn")],
        ["<b>CND</b>", "CONTROLLO", "Tullio Brevani", "Capo reparto", "3", st("Completo", "ok")],
        ["<b>UFFICIO TECNICO (CAM)</b>", "UT", "Nessuno", "Nessuno", "4", st("Senza responsabile", "warn")],
        ["<b>LAVAGGIO</b>", "AGGIUSTAGGIO", "Nora Castelvi", "Capo reparto", "2", st("Completo", "ok")],
    ], scelta=0)}</div>
  </section>
  <section>{h("Reparto scelto", "")}
    <div class="m-card m-pad">{campi([("Reparto", "CN5GL"), ("Centro di costo", "CN5G"), ("Responsabile", "Elio Vantaro"), ("Ruolo responsabile", "Capo reparto"), ("Persone", "6"), ("Mansioni", "4")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Cambia responsabile", "edit", piccolo=True)}{btn("Vedi le persone", "users", piccolo=True)}</div></div>
    {h("Da fare", "")}
    {fare([(3, "Reparti senza responsabile", "Manca il ruolo responsabile", "Apri", False)])}
  </section>
</div>""")

# 5 ─ Centri di costo
PAGINE["05_centri_di_costo"] = ("Centri di costo", testa(
    "Centri di costo", "Quali reparti stanno in quale centro di costo.",
    [GUIDA, btn("Nuovo centro di costo", "plus", True)]) + f"""
<div class="m-filtri"><span class="m-campo largo">Cerca un centro di costo o un reparto…</span><span class="m-chip on">Tutti · 26</span><span class="m-chip">Senza reparti · 5</span></div>
<div class="op-due">
  <section>{h("Elenco", "26 centri di costo")}
    <div class="m-card">{tabella(["Centro di costo", "Reparti", "Persone", "Ruoli previsti"], [
        ["<b>AGGIUSTAGGIO</b>", "Aggiustaggio · Lavaggio · Marcatura · Montaggio", "6", "Operatore manuale, Capo reparto"],
        ["<b>ALC</b>", "ALC", "4", "Operatore macchina utensile"],
        ["<b>CN4</b>", "CN4", "12", "Operatore macchina utensile, Capo reparto"],
        ["<b>CN5</b>", "CN5", "6", "Operatore macchina utensile, Capo reparto"],
        ["<b>CN5G</b>", "CN5GL · CN5GS", "14", "Operatore macchina utensile, Capo reparto"],
        ["<b>CND</b>", "CND", "3", "Operatore controlli"],
    ], scelta=4)}</div>
  </section>
  <section>{h("Centro scelto", "")}
    <div class="m-card m-pad">{campi([("Centro di costo", "CN5G"), ("Reparti", "CN5GL, CN5GS"), ("Persone", "14"), ("Ruoli previsti", "Operatore macchina utensile, Capo reparto")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Collega un reparto", "plus", piccolo=True)}{btn("Vedi le persone", "users", piccolo=True)}</div></div>
    {h("Da fare", "")}
    {fare([(2, "Reparti senza centro di costo", "Non collegati a nessun centro", "Collega", False)])}
  </section>
</div>""")

# 6 ─ Organigramma
PAGINE["06_organigramma"] = ("Organigramma", testa(
    "Organigramma", "Chi riporta a chi. Clicca un riquadro per vedere la persona o il reparto.",
    [GUIDA, btn("Scarica in PDF", "download"), btn("Prova un cambiamento", "refresh", True)]) + f"""
<div class="m-filtri"><span class="m-campo largo">Cerca una persona o un reparto…</span><span class="m-campo">Parti da: Direzione</span>
  <span class="m-chip on">Per reparto</span><span class="m-chip">Per ruolo</span></div>
<div class="op-due">
  <section>{h("Disegno", "Direzione › Produzione")}
    <div class="m-card m-albero">
      <div class="m-nodo capo"><b>Direzione</b><span>Sara Bellandi · Direttore</span></div>
      <div class="m-gambo"></div>
      <div class="m-nodo capo"><b>Produzione</b><span>Tullio Brevani · Responsabile</span></div>
      <div class="m-gambo"></div>
      <div class="m-fila">
        <div><div class="m-nodo on"><b>CN5GL</b><span>Elio Vantaro · Capo reparto</span></div>
          <div class="m-sotto"><div class="m-nodo">Mira Dossen</div><div class="m-nodo">Ivo Marendi</div><div class="m-nodo">+ altre 4 persone</div></div></div>
        <div><div class="m-nodo"><b>CN5GS</b><span>Nora Castelvi · Capo reparto</span></div>
          <div class="m-sotto"><div class="m-nodo">Dario Selvani</div><div class="m-nodo">+ altre 7 persone</div></div></div>
        <div><div class="m-nodo"><b>CN4</b><span>Lea Zuffardi · Capo reparto</span></div>
          <div class="m-sotto"><div class="m-nodo">+ 11 persone</div></div></div>
        <div><div class="m-nodo"><b>MARCATURA</b><span>Senza responsabile</span></div>
          <div class="m-sotto"><div class="m-nodo">+ 2 persone</div></div></div>
      </div>
    </div>
  </section>
  <section>{h("Riquadro scelto", "")}
    <div class="m-card m-pad">{campi([("Reparto", "CN5GL"), ("Responsabile", "Elio Vantaro"), ("Ruolo", "Capo reparto"), ("Riporta a", "Tullio Brevani"), ("Persone", "6")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Apri il reparto", "arrow-right", piccolo=True)}{btn("Vedi le persone", "users", piccolo=True)}</div></div>
    <p class="op-nota">{ico("alert-cir")}<span>Il riquadro arancione è quello scelto. Un reparto senza responsabile è scritto in chiaro.</span></p>
  </section>
</div>""")

# 7 ─ Prova un cambiamento
PAGINE["07_prova_un_cambiamento"] = ("Prova un cambiamento", testa(
    "Prova un cambiamento", "Guarda che cosa succede prima di spostare una persona o cambiare un ruolo. Finché non confermi non cambia niente.",
    [GUIDA, btn("Annulla la prova"), btn("Applica il cambiamento", "check", True)]) + f"""
<div class="m-passi"><div class="m-passo fatto"><b>1 · Che cosa cambia</b>Persona e nuovo reparto</div><div class="m-passo ora"><b>2 · Confronto</b>Oggi e dopo, fianco a fianco</div><div class="m-passo"><b>3 · Conferma</b>Applica o annulla</div></div>
<div class="op-due">
  <section>{h("Confronto", "In arancione ciò che cambia")}
    <div class="m-card m-confronto">
      <div><h4>Oggi</h4>{campi([("Persona", "Ivo Marendi"), ("Reparto", "CN5GL"), ("Ruolo", "Operatore macchina utensile"), ("Responsabile", "Elio Vantaro"), ("Centro di costo", "CN5G"), ("Mansioni", "DM6, DM12")])}</div>
      <div><h4>Dopo</h4>{campi([("Persona", "Ivo Marendi"), ("Reparto", "CN5GS"), ("Ruolo", "Operatore macchina utensile"), ("Responsabile", "Nora Castelvi"), ("Centro di costo", "CN5G"), ("Mansioni", "da assegnare")], classe="m-cambia")}</div>
    </div>
    {h("Che cosa comporta", "3 conseguenze")}
    <div class="m-card">{tabella(["Che cosa", "Dettaglio", "Che cosa fare"], [
        ["<b>Mansioni da rivedere</b>", "DM6 e DM12 non sono mansioni del reparto CN5GS", st("Richiesta di sospensione", "warn")],
        ["<b>Mansioni nuove</b>", "Il reparto CN5GS ne ha 7: nessuna assegnata", st("Richiesta di assegnazione", "warn")],
        ["<b>Responsabile</b>", "Passa da Elio Vantaro a Nora Castelvi", st("Automatico", "ok")],
    ])}</div>
  </section>
  <section>{h("Che cosa cambia", "Passo 1")}
    <div class="m-card m-pad">{campi([("Tipo di cambiamento", "Spostamento di reparto"), ("Persona", "Ivo Marendi"), ("Da", "CN5GL"), ("A", "CN5GS"), ("Dal", "01/03/2027")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Modifica", "edit", piccolo=True)}</div></div>
    <p class="op-nota">{ico("alert-cir")}<span>È una prova: la struttura vera resta com'è finché non premi «Applica il cambiamento».</span></p>
  </section>
</div>""")

# 8 ─ Struttura e revisioni
PAGINE["08_struttura_e_revisioni"] = ("Struttura e revisioni", testa(
    "Struttura e revisioni", "La struttura approvata dalla Qualità e ciò che è cambiato dall'ultima emissione.",
    [GUIDA, btn("Scarica in Excel", "download"), btn("Emetti la revisione", "check", True)]) + f"""
<div class="m-card m-pad">{campi([("Revisione in vigore", "Rev. 3"), ("Emessa il", "14/02/2027"), ("Emessa da", "MSM"), ("Modifiche non emesse", "4"), ("Stato", st("Bozza diversa dalla revisione", "warn")), ("Chi può emettere", "Solo chi ha il ruolo MSM")], due=True)}</div>
<div class="op-due">
  <section>{h("Modifiche non ancora emesse", "4")}
    <div class="m-card"><ul class="m-elenco">
      <li><span class="m-seg piu">+</span><span><b>Mansione aggiunta:</b> Tornio attrezzeria, reparto TRADIZIONALE</span><span>{st("Aggiunta", "ok")}</span></li>
      <li><span class="m-seg mod">~</span><span><b>Responsabile cambiato:</b> CN5GS, da nessuno a Capo reparto</span><span>{st("Cambiata", "warn")}</span></li>
      <li><span class="m-seg mod">~</span><span><b>Mansione rinominata:</b> «Governance del SGI» diventa «Gestione del SGI»</span><span>{st("Cambiata", "warn")}</span></li>
      <li><span class="m-seg meno">−</span><span><b>Ruolo tolto:</b> CMM Specialist</span><span>{st("Tolta", "ko")}</span></li>
    </ul></div>
    {h("Da completare prima di emettere", "3")}
    <div class="m-card">{tabella(["Che cosa manca", "Quante", ""], [
        ["<b>Reparti senza ruolo responsabile</b>", "3", btn("Apri", piccolo=True)],
        ["<b>Mansioni senza ruolo</b>", "5", btn("Apri", piccolo=True)],
        ["<b>Rischi da confermare</b>", "4", btn("Conferma", piccolo=True)],
    ])}</div>
  </section>
  <section>{h("Revisioni emesse", "3")}
    <div class="m-card">{tabella(["Revisione", "Emessa il", "Da", ""], [
        ["<b>Rev. 3</b>", "14/02/2027", "MSM", btn("Apri", piccolo=True)],
        ["<b>Rev. 2</b>", "03/11/2026", "MSM", btn("Apri", piccolo=True)],
        ["<b>Rev. 1</b>", "21/10/2026", "MSM", btn("Apri", piccolo=True)],
    ])}</div>
    <p class="op-nota">{ico("alert-cir")}<span>Una revisione emessa non si modifica: per cambiare si emette la successiva.</span></p>
  </section>
</div>""")

# 5 bis ─ Centri di costo con l'albero che si apre sotto il centro scelto: reparti, ruoli, mansioni.
STILE += """
.m-cc{display:flex;align-items:center;gap:10px;padding:11px 16px;border-bottom:1px solid #eef2f7;font-size:13.5px}
.m-cc b{color:#0f172a}
.m-cc span{color:#64748b;font-size:12.5px}
.m-cc .fr{flex:none;width:18px;color:#6b8db3;font-size:13px}
.m-cc .dx{margin-left:auto;display:flex;gap:8px;align-items:center}
.m-cc.on{background:#e8f3fb}
.m-ramo{border-bottom:1px solid #eef2f7;background:#fbfdff;padding:6px 0 8px}
.m-ramo div{display:flex;align-items:center;gap:8px;padding:6px 16px;font-size:13px}
.m-ramo .l1{padding-left:44px}.m-ramo .l2{padding-left:72px}.m-ramo .l3{padding-left:100px}
.m-ramo em{font-style:normal;color:#64748b}
.m-ramo b{color:#0f172a}
.m-ramo .fr{flex:none;width:16px;color:#6b8db3;font-size:12px}
.m-ramo .q{margin-left:auto;color:#64748b;font-size:12.5px}
"""


def _cc(nome, dettaglio, aperto=False):
    return (f'<div class="m-cc{" on" if aperto else ""}"><span class="fr">{"▾" if aperto else "▸"}</span><b>{nome}</b>'
            f'<span>{dettaglio}</span><span class="dx">{btn("Chiudi" if aperto else "Apri l\'albero", piccolo=True)}</span></div>')


def _ramo(livello, etichetta, nome, quanti, aperto=None):
    freccia = "" if aperto is None else ("▾" if aperto else "▸")
    return f'<div class="l{livello}"><span class="fr">{freccia}</span><em>{etichetta}:</em> <b>{nome}</b><span class="q">{quanti}</span></div>'


_ALBERO_CN5G = '<div class="m-ramo">' + "".join([
    _ramo(1, "Reparto", "CN5GL", "Responsabile: Elio Vantaro · 6 persone", True),
    _ramo(2, "Ruolo", "Operatore macchina utensile", "5 persone", True),
    _ramo(3, "Mansione", "DM6 - DMC 125U Duoblock", "3 persone"),
    _ramo(3, "Mansione", "DM7 - DMC 160U Duoblock", "4 persone"),
    _ramo(3, "Mansione", "DM12 - DMC 160U Duoblock", "2 persone"),
    _ramo(2, "Ruolo", "Capo reparto", "1 persona", False),
    _ramo(1, "Reparto", "CN5GS", "Responsabile: Nora Castelvi · 8 persone", False),
]) + "</div>"

PAGINE["05_centri_di_costo"] = ("Centri di costo", testa(
    "Centri di costo", "Quali reparti stanno in quale centro di costo. Apri un centro per vedere il suo albero.",
    [GUIDA, btn("Nuovo centro di costo", "plus", True)]) + f"""
<div class="m-filtri"><span class="m-campo largo">Cerca un centro di costo o un reparto…</span><span class="m-chip on">Tutti · 26</span><span class="m-chip">Senza reparti · 5</span>
  <span style="margin-left:auto;display:flex;gap:8px">{btn("Apri tutto", piccolo=True)}{btn("Chiudi tutto", piccolo=True)}</span></div>
<div class="op-due">
  <section>{h("Elenco", "26 centri di costo · 1 aperto")}
    <div class="m-card">
      {_cc("AGGIUSTAGGIO", "4 reparti · 6 persone")}{_cc("ALC", "1 reparto · 4 persone")}{_cc("CN4", "1 reparto · 12 persone")}{_cc("CN5", "1 reparto · 6 persone")}
      {_cc("CN5G", "2 reparti · 14 persone", True)}{_ALBERO_CN5G}
      {_cc("CND", "1 reparto · 3 persone")}{_cc("CONTROLLO", "3 reparti · 9 persone")}
    </div>
  </section>
  <section>{h("Centro scelto", "")}
    <div class="m-card m-pad">{campi([("Centro di costo", "CN5G"), ("Reparti", "CN5GL, CN5GS"), ("Persone", "14"), ("Ruoli previsti", "Operatore macchina utensile, Capo reparto")])}
      <div style="display:flex;gap:8px;margin-top:14px">{btn("Collega un reparto", "plus", piccolo=True)}{btn("Vedi le persone", "users", piccolo=True)}</div></div>
    {h("Da fare", "")}
    {fare([(2, "Reparti senza centro di costo", "Non collegati a nessun centro", "Collega", False)])}
    <p class="op-nota">{ico("alert-cir")}<span>L'albero si apre sotto il centro: reparto, ruolo, mansione. Ogni riga si apre e si chiude da sola.</span></p>
  </section>
</div>""")


# ─ Altre informazioni e pagine collegate ─────────────────────────────────────────────────────────
# In ogni pagina, accanto alla cosa scelta: altri dati che la riguardano e i collegamenti diretti
# alle pagine dove si prosegue, già aperte su quella cosa.
STILE += """
.m-lk{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid #eef2f7;text-decoration:none;color:#0f172a;font-size:13.5px}
.m-lk:last-child{border-bottom:0}
.m-lk .ic{display:inline-flex;width:28px;height:28px;flex:none;border-radius:8px;background:#e8f3fb;color:#1f6fb0;align-items:center;justify-content:center;font-size:14px}
.m-lk b{display:block;font-weight:600}
.m-lk small{display:block;font-size:12px;color:#64748b}
.m-lk .fr{margin-left:auto;color:#94a3b8;font-size:15px;display:inline-flex}
.m-lk .n{margin-left:auto;display:inline-flex;min-width:19px;height:19px;padding:0 5px;border-radius:999px;background:#ea580c;color:#fff;font-size:11px;font-weight:700;align-items:center;justify-content:center}
.m-lk .n + .fr{margin-left:8px}
"""


def _collegate(voci):
    righe = ""
    for nome, spiega, icona, n in voci:
        conta = f'<span class="n">{n}</span>' if n else ""
        righe += (f'<a class="m-lk" href="#"><span class="ic">{ico(icona)}</span><span><b>{nome}</b><small>{spiega}</small></span>'
                  f'{conta}<span class="fr">{ico("arrow-right")}</span></a>')
    return h("Pagine collegate", f"{len(voci)} · già aperte su ciò che hai scelto") + f'<div class="m-card">{righe}</div>'


def _altre(coppie, titolo="Altre informazioni"):
    return h(titolo, "") + f'<div class="m-card m-pad">{campi(coppie)}</div>'


def _arricchisci(chiave, altre, collegate, dove="dopo_la_scheda", prima=""):
    attiva, html = PAGINE[chiave]
    taglio = html.index("<section>", html.index("<section>") + 1)
    sinistra, destra = html[:taglio], html[taglio:]
    nuovo = prima + (_altre(altre) if altre else "") + _collegate(collegate)
    if dove == "in_cima":
        destra = destra.replace("<section>", "<section>" + nuovo, 1)
    elif dove == "in_fondo":
        i = destra.rindex("</section>")
        destra = destra[:i] + nuovo + destra[i:]
    else:
        i = destra.index("</div></div>", destra.index('class="m-card m-pad"')) + len("</div></div>")
        destra = destra[:i] + nuovo + destra[i:]
    PAGINE[chiave] = (attiva, sinistra + destra)


for _chiave in ("01_esplora_la_struttura", "01b_esplora_mansioni_per_prime"):
    _arricchisci(_chiave, [("Processo", "Produzione"), ("Mansioni di rischio", "Addetto macchine utensili"),
                           ("Abilitazione con scadenza", "No"), ("Copertura", "2 persone autonome su 4"),
                           ("Richieste aperte", "2")],
                 [("Apri la mansione", "Competenze, persone e valutazioni", "clipboard", 0),
                  ("Richieste su questa mansione", "2 aperte, 1 da approvare", "edit", 1),
                  ("Reparto CN5GL", "Responsabile, persone e ruoli", "users", 0),
                  ("Centro di costo CN5G", "Reparti e persone del centro", "coins", 0),
                  ("Organigramma del reparto", "Chi riporta a chi", "building", 0)], dove="in_fondo")

_arricchisci("02_mansioni", [("Processo", "Produzione"), ("Macchina", "DM7 · DMC 160U"), ("Mansioni di rischio", "Addetto macchine utensili"),
                             ("Persone abilitate", "2 su 4"), ("In formazione", "1 persona"), ("Richieste aperte", "2")],
             [("Esplora la struttura", "Aperta su questa mansione", "grid", 0),
              ("Richieste su questa mansione", "2 aperte, 1 da approvare", "edit", 1),
              ("Persone con la mansione", "Livello e stato di ognuna", "users", 0),
              ("Reparto CN5GL", "Responsabile, persone e ruoli", "building", 0),
              ("Corsi collegati", "Formazione prevista per le competenze", "book", 0)])

_arricchisci("03_richieste", [], [("Apri la richiesta", "Passi, competenze che servono, storia", "edit", 0),
                                  ("Scheda di Ivo Marendi", "Mansioni e competenze della persona", "users", 0),
                                  ("Mansione DM12 - DMC 160U Duoblock", "Che cosa richiede e chi ce l'ha", "clipboard", 0),
                                  ("Reparto CN5GL", "Responsabile, persone e ruoli", "building", 0)],
             dove="in_cima",
             prima=h("Richiesta scelta", "") + '<div class="m-card m-pad">' + campi([
                 ("Richiesta", "RAM-2027-0021"), ("Tipo di richiesta", "Assegnazione di mansione"), ("Persona", "Ivo Marendi"),
                 ("Mansione", "DM12 - DMC 160U Duoblock"), ("Livello da raggiungere", lv("U")), ("Richiesta da", "Elio Vantaro · 18/01/2027"),
                 ("Stato", st("In approvazione", "warn")), ("Tocca a", "RDD: approvare")]) + "</div>")
PAGINE["03_richieste"] = (PAGINE["03_richieste"][0], PAGINE["03_richieste"][1].replace("<tbody><tr>", "<tbody><tr class=on>", 1))

_arricchisci("04_reparti_e_capi", [("Aree", "CN5GL"), ("Ruoli previsti", "Operatore macchina utensile, Capo reparto"),
                                   ("Mansioni", "4"), ("In formazione", "1 persona"), ("Richieste aperte", "2")],
             [("Esplora la struttura", "Aperta su questo reparto", "grid", 0),
              ("Persone del reparto", "6 persone, con ruolo e mansioni", "users", 0),
              ("Richieste del reparto", "2 aperte, 1 da approvare", "edit", 1),
              ("Centro di costo CN5G", "Reparti e persone del centro", "coins", 0),
              ("Organigramma del reparto", "Chi riporta a chi", "building", 0)])

_arricchisci("05_centri_di_costo", [("Responsabili", "Elio Vantaro, Nora Castelvi"), ("Mansioni", "9"), ("Richieste aperte", "3")],
             [("Esplora la struttura", "Aperta su questo centro di costo", "grid", 0),
              ("Persone del centro", "14 persone, con reparto e ruolo", "users", 0),
              ("Costo orario del centro", "Solo per chi lavora sui dati HR", "clock", 0),
              ("Report per centro di costo", "Organico e costo orario, in Excel", "download", 0)])

_arricchisci("06_organigramma", [("Centro di costo", "CN5G"), ("Mansioni del reparto", "4"), ("In formazione", "1 persona")],
             [("Reparto CN5GL", "Responsabile, persone e ruoli", "users", 0),
              ("Esplora la struttura", "Aperta su questo reparto", "grid", 0),
              ("Prova un cambiamento", "Sposta una persona di questo reparto", "refresh", 0),
              ("Scheda di Elio Vantaro", "Il responsabile del reparto", "users", 0)])

_arricchisci("07_prova_un_cambiamento", [("Mansioni di oggi", "DM6, DM12"), ("Mansioni del nuovo reparto", "7, nessuna assegnata"),
                                         ("Richieste da aprire", "2 sospensioni, fino a 7 assegnazioni")],
             [("Scheda di Ivo Marendi", "Mansioni e competenze di oggi", "users", 0),
              ("Reparto CN5GL", "Il reparto di partenza", "building", 0),
              ("Reparto CN5GS", "Il reparto di arrivo e le sue mansioni", "building", 0),
              ("Nuova richiesta", "Per le mansioni del nuovo reparto", "plus", 0)])

_arricchisci("08_struttura_e_revisioni", [], [("Reparti e capi", "3 reparti senza ruolo responsabile", "users", 3),
                                              ("Mansioni", "5 mansioni senza ruolo", "clipboard", 5),
                                              ("Rischi da confermare", "Mansioni di rischio proposte", "shield", 4),
                                              ("Scarica la revisione 3", "La revisione in vigore, in PDF", "download", 0)],
             dove="in_fondo")


# ─ Disposizione dinamica ─────────────────────────────────────────────────────────────────────────
# Tre colonne: la tabella ne occupa due, ogni riquadro una. I riquadri si mettono nel primo posto
# libero: accanto alla tabella finché c'è spazio, poi sotto. Con una tabella corta si infilano sotto
# di lei, così non resta un vuoto al centro; con una tabella lunga restano in colonna a destra.
STILE += """
.m-flusso{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));column-gap:20px;grid-auto-rows:4px;grid-auto-flow:row dense;align-items:start}
.m-blocco{min-width:0}
.m-blocco.largo{grid-column:span 2}
.m-blocco-in>.m-card:last-child,.m-blocco-in>.op-fare:last-child{margin-bottom:0}
"""

_REPARTI_TANTI = [("CN5GL", "CN5G", "Elio Vantaro"), ("CN5GS", "CN5G", "Sara Bellandi"), ("ALC", "CN5G", "Nora Castelvi"),
                  ("CN4", "CN4", "Lea Zuffardi"), ("CN5", "CN5", "Dario Selvani"), ("CNC", "CNC", "Tullio Brevani"),
                  ("PRESETTING", "CNC", "Tullio Brevani"), ("MARCATURA", "AGGIUSTAGGIO", ""), ("LAVAGGIO", "AGGIUSTAGGIO", "Nora Castelvi"),
                  ("MONTAGGIO", "AGGIUSTAGGIO", "Mira Dossen"), ("RETTIFICA", "AGGIUSTAGGIO", "Ivo Marendi"),
                  ("SALA TAGLIO", "AGGIUSTAGGIO", "Ivo Marendi"), ("VERNICIATURA", "AGGIUSTAGGIO", ""), ("CND", "CONTROLLO", "Tullio Brevani"),
                  ("CONTROLLO CMM", "CONTROLLO", "Sara Bellandi"), ("TNF", "TNF", "Lea Zuffardi"), ("TORNI", "TORNI", "Dario Selvani"),
                  ("LOGISTICA", "LOGISTICA", "Mira Dossen"), ("UFFICIO TECNICO (CAM)", "UT", ""), ("UFFICIO FAI", "UT", "Elio Vantaro")]


def _reparti_lunghi():
    attiva, html = PAGINE["04_reparti_e_capi"]
    inizio = html.index("<tbody>") + len("<tbody>")
    fine = html.index("</tbody>")
    righe = ""
    for i, (nome, centro, capo) in enumerate(_REPARTI_TANTI):
        stato = st("Completo", "ok") if capo else st("Senza responsabile", "warn")
        celle = [f"<b>{nome}</b>", centro, capo or "Nessuno", "Capo reparto" if capo else "Nessuno", str(2 + (i * 3) % 9), stato]
        righe += f'<tr{" class=on" if i == 0 else ""}>' + "".join(f"<td>{c}</td>" for c in celle) + "</tr>"
    return attiva, html[:inizio] + righe + html[fine:]


PAGINE["04b_reparti_e_capi_tabella_lunga"] = _reparti_lunghi()


SCRIPT = """
([contenuto, attiva, voci, stile]) => {
  const st = document.createElement('style'); st.textContent = stile; document.head.appendChild(st);
  document.querySelector('.op-pagina').innerHTML = contenuto;
  const sub = document.querySelector('.hrnav-sub');
  if (sub) {
    const sez = sub.querySelector('.hrnav-sub-sez'); if (sez) sez.remove();
    const gruppo = sub.querySelector('.hrnav-sub-voci');
    if (gruppo) gruppo.innerHTML = voci.map(v => `<a href="#" class="${v === attiva ? 'active' : ''}">${v}</a>`).join('');
  }
  const percorso = document.querySelector('.hub-percorso');
  if (percorso) [...percorso.querySelectorAll('*')].forEach(e => {
    if (!e.children.length && e.textContent.trim() === 'Organizzazione') e.textContent = 'Organizzazione › ' + attiva;
  });
  document.querySelectorAll('.devgit').forEach(e => e.remove());
  // Disposizione dinamica: ogni titolo con il suo riquadro diventa un blocco; quelli di sinistra sono larghi.
  document.querySelectorAll('.op-due').forEach(due => {
    const flusso = document.createElement('div'); flusso.className = 'm-flusso';
    [...due.children].forEach((sezione, i) => {
      let dentro = null;
      [...sezione.children].forEach(n => {
        if (n.classList.contains('op-h') || !dentro) {
          const blocco = document.createElement('div'); blocco.className = 'm-blocco' + (i === 0 ? ' largo' : '');
          dentro = document.createElement('div'); dentro.className = 'm-blocco-in';
          blocco.appendChild(dentro); flusso.appendChild(blocco);
        }
        dentro.appendChild(n);
      });
    });
    due.replaceWith(flusso);
  });
  document.querySelectorAll('.m-blocco').forEach(b => { b.style.gridRowEnd = 'span ' + Math.ceil((b.firstChild.offsetHeight + 18) / 4); });
  return document.documentElement.scrollWidth > window.innerWidth + 1;
}
"""

USCITA.mkdir(parents=True, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for nome, (attiva, contenuto) in PAGINE.items():
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(GUSCIO.as_uri())
        pg.wait_for_timeout(500)
        sborda = pg.evaluate(SCRIPT, [contenuto, attiva, VOCI, STILE])
        pg.wait_for_timeout(250)
        pg.screenshot(path=str(USCITA / f"{nome}.png"), full_page=True)
        print(nome, "| sborda:", sborda, "| altezza:", pg.evaluate("document.documentElement.scrollHeight"))
        pg.close()
    b.close()
