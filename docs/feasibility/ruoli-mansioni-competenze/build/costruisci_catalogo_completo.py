"""Catalogo completo di ruoli, mansioni e competenze, con l'incrocio fra MOD.053 e skill matrix.

Legge due file senza nominativi, ricavati dai documenti in vigore del sistema di gestione il 22/11/2026:
  build/catalogo_mod053.json   la tabella «Ruolo → Mansione → Competenze» del MOD.053 Rev.4
  build/skm_aggregati.json     le colonne della skill matrix MOD.187 del 30/04/2026, con i soli conteggi per livello

    python build/costruisci_catalogo_completo.py   →   Catalogo_competenze_completo.xlsx
"""
import json
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

QUI = Path(__file__).resolve().parent
RADICE = QUI.parent
ruoli = json.loads((QUI / "catalogo_mod053.json").read_text(encoding="utf-8"))
skm = json.loads((QUI / "skm_aggregati.json").read_text(encoding="utf-8"))
testa = skm["totali_in_testa"]
colonne = [m["mansione"] for m in skm["mansioni"]]

# Colonne della skill matrix che nel MOD.053 hanno un altro nome o stanno a un altro livello: (parte del ruolo, nota)
CQ = "Addetti Controllo Qualità"
ALTRO_NOME = {
    "Affilatura": ("MAG3", "nel MOD.053 è scritta «Affiliatura»"),
    "Marcatura": ("Operatore Marcatura", "mansione «Marcatura pezzi»"),
    "Mascheratura": ("MAS", "mansione «Mascheratura componenti»"),
    "Sala taglio": ("MAG1", "mansione «Taglio con sega»"),
    "Verniciatura": ("VER", "mansione «Verniciatura componenti meccanici»"),
    "Lavaggio": ("LAV", "mansione «Lavaggio componenti meccanici»"),
    "Magazzino 02": ("MAG2", "mansione «Gestione magazzino»"),
    "Trasporti": ("Addetto Trasporti", "mansione «Trasporto merci e movimentazione»"),
    "Pulizie": ("PUL", "mansione «Pulizia reparti produttivi»"),
    "Imballaggio": ("IMB", "mansione «Imballaggio componenti»"),
    "Manutenzione": ("MAN", "mansione «Manutenzione ordinaria impianti e stabile»"),
}
for c in ("Controllo configurazione finale", "Programmazione Offline", "ZEISS - PRISMO USS2", "ZEISS - PRISMO NAVIGATOR",
          "ZEISS - PRISMO 10HTG VAST", "ZEISS - CONTURA G2", "ZEISS - DURAMAX Matr. 140642", "ZEISS - DURAMAX - Matr. 14301",
          "Controlli di banco", "Controllo visivo", "Controllo montaggi", "Cleanliness Check", "Liquidi penetranti",
          "Taratura strumenti", "Controllo durezza", "Controllo conducibilità", "Controllo marcatura",
          "Gestione documenti ingresso e uscita"):
    ALTRO_NOME[c] = (CQ, "nel MOD.053 è un'attività dell'unica mansione «Controllo qualità prodotto»")

# Colonne della skill matrix firmata che nella bozza della Qualità hanno cambiato nome o sono state divise.
# È una proposta di abbinamento dell'analisi: le voci in DA_CONFERMARE sono le più incerte.
bozza = json.loads((QUI / "bozza_qualita.json").read_text(encoding="utf-8"))
RINOMINATE = {
    "Montaggio per aeronautica": "Montaggio 9100",
    "Montaggio per automotive": "Montaggio 9001",
    "Lavaggio": "Lavaggio standard",
    "Manutenzione": "Manutenzione Impianti",
    "Sala taglio": "Taglio Materiale",
}
DIVISE = {
    "Ritocchi Galvanici": ["Ritocchi Galvanici DOW19", "Ritocchi Galvanici ALODINE"],
    "Montaggio per accoppiamento termico": ["Montaggio per accoppiamento termico 9100",
                                            "Montaggio per accoppiamento termico 9001"],
    "Marcatura": ["Marcatura laser", "Marcatura manuale", "Marcatura a punti", "Marcatura elettrolitica"],
    "Prova pressione": ["Prova pressione aria/acqua", "Prova pressione olio"],
    "Controllo montaggi": ["Controllo montaggio 9100", "Controllo montaggio 9001",
                           "Controllo Montaggio per accoppiamento termico 9100",
                           "Controllo Montaggio per accoppiamento termico 9001"],
    "Magazzino 02": ["Magazzino normaleria", "Magazzino prodotti chimici", "Magazzino materia prima"],
}
DA_CONFERMARE = {"Sala taglio", "Magazzino 02"}

norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower().split(" - ")[0])  # noqa: E731
per_codice = {}
for r in ruoli:
    for m in r["mansioni"]:
        per_codice.setdefault(norm(m["mansione"]), (r, m))
ruolo_di = lambda parte: next((r for r in ruoli if parte.lower() in r["ruolo"].lower()), None)  # noqa: E731
operativi = {id(per_codice[norm(c)][0]) for c in colonne if norm(c) in per_codice}
operativi |= {id(ruolo_di(p)) for p, _ in ALTRO_NOME.values() if ruolo_di(p)}

ARIAL, BLU = "Arial", "10233F"
GIALLO = PatternFill("solid", start_color="FFF59D")
TESTA = PatternFill("solid", start_color=BLU)
GRIGIO = PatternFill("solid", start_color="EEF2F7")
ARANCIO = PatternFill("solid", start_color="FFE8D6")
BORDO = Border(*(Side(style="thin", color="C5CED9"),) * 4)


def cella(ws, rif, v, grassetto=False, colore="1A202C", riempi=None, centro=False, dim=10, a_capo=True):
    c = ws[rif]
    c.value = v
    c.font = Font(name=ARIAL, size=dim, bold=grassetto, color=colore)
    c.alignment = Alignment(wrap_text=a_capo, vertical="center", horizontal="center" if centro else "left")
    if riempi is not None:
        c.fill = riempi
    c.border = BORDO
    return c


def intestazione(ws, riga, titoli, alt=30):
    for i, t in enumerate(titoli, 1):
        cella(ws, f"{get_column_letter(i)}{riga}", t, grassetto=True, colore="FFFFFF", riempi=TESTA, centro=True)
    ws.row_dimensions[riga].height = alt


wb = Workbook()
ws = wb.active
ws.title = "Leggimi"
ws.column_dimensions["A"].width = 26
ws.column_dimensions["B"].width = 100
ws["A1"].value = "Catalogo completo di ruoli, mansioni e competenze"
ws["A1"].font = Font(name=ARIAL, size=16, bold=True, color=BLU)
ws["A2"].value = "Dalla tabella del MOD.053 Rev.4, incrociata con la skill matrix MOD.187 del 30/04/2026. Nessun nominativo."
ws["A2"].font = Font(name=ARIAL, size=10, color="4A5568")
note = [
    ("Foglio «Catalogo»", "Una riga per ogni competenza di ogni mansione di ogni ruolo. Le celle gialle sono da compilare: livello richiesto (solo ruoli operativi), criticità, requisito formale."),
    ("Foglio «Incrocio»", "Le 79 colonne della skill matrix a confronto con il MOD.053: dove i nomi coincidono, dove no, e quante persone autonome e formatori ha oggi ogni mansione."),
    ("Foglio «Riepilogo»", "I conteggi, aggiornati da soli."),
    ("Livello richiesto", "I, L, U oppure O, secondo MT CN 06 Rev.21 §8.3. Per i ruoli non operativi non si usa: il requisito è posseduto sì o no."),
    ("Criticità", "Bloccante, Importante oppure Utile. È una proposta dell'analisi."),
    ("Competenze generiche", "Proposta: «sì o no», valutate una volta per persona. I livelli si usano solo sulle competenze di mansione. Così il carico di valutazione resta quello di oggi."),
    ("Bozza della Qualità", "Ricevuta il 22/11/2026: elenco delle mansioni v9 e matrice delle competenze per reparto. È la struttura a cui tendere; il foglio «Catalogo», ricavato dal MOD.053, resta come riferimento per le descrizioni."),
    ("Foglio «Mansioni bozza»", "Le mansioni dell'elenco v9, con processo, reparto e centro di costo. Per ciascuna: se esiste già nella skill matrix firmata, quante persone autonome ha oggi, e se la sua ricetta (le competenze richieste) è compilata."),
    ("Foglio «Competenze bozza»", "Le competenze distinte della matrice, con tipo e origine dove indicati. Le celle gialle mancano nella bozza."),
    ("Foglio «Stato bozza»", "Quanto è compilato ogni foglio della matrice. In giallo i fogli ancora vuoti."),
    ("Abbinamento con la skill matrix", "Nel foglio «Incrocio» la colonna «Nella bozza della Qualità» dice dove finisce ogni colonna della skill matrix firmata. Le colonne divise in più mansioni non si caricano da sole: il livello va ripartito dal capo reparto. È una proposta dell'analisi."),
]
for i, (a, b) in enumerate(note, 4):
    cella(ws, f"A{i}", a, grassetto=True, colore=BLU)
    cella(ws, f"B{i}", b)
    ws.row_dimensions[i].height = 30 + 13 * (len(b) // 110)

wc = wb.create_sheet("Catalogo")
for col, larg in zip("ABCDEFGHI", (30, 16, 34, 52, 14, 13, 15, 34, 30)):
    wc.column_dimensions[col].width = larg
intestazione(wc, 1, ["Ruolo", "Tipo di ruolo", "Mansione", "Competenza", "Tipo", "Livello richiesto", "Criticità",
                     "Requisito formale (se c'è)", "Note"])
riga = 2
for r in ruoli:
    op = id(r) in operativi
    voci = [(m["mansione"], s, "Di mansione") for m in r["mansioni"] for s in m["specifiche"]]
    voci += [("(tutte le mansioni del ruolo)", g, "Generica") for g in r["generiche"]]
    for mans, comp, tipo in voci:
        for col, v in zip("ABCDE", (r["ruolo"], "Operativo" if op else "Non operativo", mans, comp, tipo)):
            cella(wc, f"{col}{riga}", v, centro=col in "BE")
        cella(wc, f"F{riga}", None if op and tipo == "Di mansione" else "—", riempi=GIALLO if op and tipo == "Di mansione" else GRIGIO, centro=True)
        for col in "GHI":
            cella(wc, f"{col}{riga}", None, riempi=GIALLO, centro=col == "G")
        riga += 1
ULT = riga - 1
dv1 = DataValidation(type="list", formula1='"I,L,U,O,—"', allow_blank=True)
dv2 = DataValidation(type="list", formula1='"Bloccante,Importante,Utile"', allow_blank=True)
wc.add_data_validation(dv1)
wc.add_data_validation(dv2)
dv1.add(f"F2:F{ULT}")
dv2.add(f"G2:G{ULT}")
wc.freeze_panes = "D2"
wc.auto_filter.ref = f"A1:I{ULT}"

wi = wb.create_sheet("Incrocio")
for col, larg in zip("ABCDEFGHIJ", (36, 22, 40, 50, 7, 7, 7, 7, 12, 12)):
    wi.column_dimensions[col].width = larg
intestazione(wi, 1, ["Colonna della skill matrix", "Esito", "Ruolo nel MOD.053", "Nota", "I", "L", "U", "O",
                     "Autonomi (U+O)", "Formatori (O)"], alt=34)
for k, nome in enumerate(colonne):
    n = k + 2
    if norm(nome) in per_codice:
        r, m = per_codice[norm(nome)]
        esito, ruolo, nota = "Stesso nome", r["ruolo"], "" if m["mansione"] == nome else f"nel MOD.053: «{m['mansione']}»"
    elif nome in ALTRO_NOME:
        parte, nota = ALTRO_NOME[nome]
        r = ruolo_di(parte)
        esito, ruolo = "Nome o livello diverso", r["ruolo"] if r else parte
    else:
        esito, ruolo, nota = "Solo nella skill matrix", "—", "nessuna voce corrispondente nel MOD.053"
    fondo = None if esito == "Stesso nome" and not nota else ARANCIO
    for col, v in zip("ABCD", (nome, esito, ruolo, nota)):
        cella(wi, f"{col}{n}", v, riempi=fondo, grassetto=col == "A")
    for col, liv in zip("EFGH", "ILUO"):
        cella(wi, f"{col}{n}", testa[liv][k], centro=True)
    cella(wi, f"I{n}", f"=G{n}+H{n}", centro=True, riempi=GRIGIO, grassetto=True)
    cella(wi, f"J{n}", f"=H{n}", centro=True, riempi=GRIGIO)
UI = len(colonne) + 1
solo53 = [(r["ruolo"], m["mansione"]) for r in ruoli if id(r) in operativi and CQ not in r["ruolo"]
          for m in r["mansioni"] if norm(m["mansione"]) not in {norm(c) for c in colonne}
          and not any(ruolo_di(p) is r for p, _ in ALTRO_NOME.values())]
n = UI + 2
cella(wi, f"A{n}", "Mansioni del MOD.053 senza colonna nella skill matrix", grassetto=True, colore=BLU)
for ruolo, mans in solo53:
    n += 1
    for col, v in zip("ABCD", (mans, "Solo nel MOD.053", ruolo, "")):
        cella(wi, f"{col}{n}", v, riempi=ARANCIO, grassetto=col == "A")
wi.freeze_panes = "B2"

# ---- Bozza della Qualità (22/11/2026): elenco delle mansioni v9 e matrice delle competenze per reparto
pieno = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
elenco, fogli = bozza["elenco"], bozza["fogli"]
nomi_elenco = {pieno(m["mansione"]) for m in elenco}
assert all(pieno(x) in nomi_elenco for x in RINOMINATE.values()), "rinominate: nome non trovato nella bozza"
assert all(pieno(x) in nomi_elenco for v in DIVISE.values() for x in v), "divise: nome non trovato nella bozza"
k_colonna = {pieno(c): k for k, c in enumerate(colonne)}
provenienza = {pieno(v): ("Rinominata", f"nella skill matrix: «{c}»", k_colonna[pieno(c)]) for c, v in RINOMINATE.items()}
provenienza.update({pieno(x): ("Divisa", f"dalla colonna «{c}»", None) for c, v in DIVISE.items() for x in v})
riga_matrice = {(pieno(m["reparto"]), pieno(m["mansione"])): (f["foglio"], m) for f in fogli for m in f["mansioni"]}

cella(wi, "K1", "Nella bozza della Qualità", grassetto=True, colore="FFFFFF", riempi=TESTA, centro=True)
wi.column_dimensions["K"].width = 58
for k, nome in enumerate(colonne):
    dubbio = " (da confermare)" if nome in DA_CONFERMARE else ""
    if pieno(nome) in nomi_elenco:
        v, fondo = "Stesso nome", None
    elif nome in RINOMINATE:
        v, fondo = f"Rinominata: «{RINOMINATE[nome]}»{dubbio}", ARANCIO
    elif nome in DIVISE:
        v, fondo = f"Divisa in {len(DIVISE[nome])}: {'; '.join(DIVISE[nome])}{dubbio}", ARANCIO
    else:
        v, fondo = "Assente", ARANCIO
    cella(wi, f"K{k + 2}", v, riempi=fondo)

wm = wb.create_sheet("Mansioni bozza")
for col, larg in zip("ABCDEFGHIJKLM", (22, 26, 24, 26, 58, 9, 9, 16, 40, 10, 10, 11, 15)):
    wm.column_dimensions[col].width = larg
intestazione(wm, 1, ["Processo", "Reparto", "Centro di costo", "Ruolo", "Mansione", "Resp. reparto", "Abilita-zione",
                     "Nella skill matrix firmata", "Nota", "Autonomi oggi (U+O)", "Formatori oggi (O)",
                     "Competenze richieste", "Ricetta"], alt=44)
for n, m in enumerate(elenco, 2):
    p = pieno(m["mansione"])
    if p in k_colonna:
        esito, nota, k = "Stesso nome", "", k_colonna[p]
    elif p in provenienza:
        esito, nota, k = provenienza[p]
    else:
        esito, nota, k = "Nuova", "", None
    foglio, rm = riga_matrice.get((pieno(m["reparto"]), p), (None, None))
    if rm is None:
        ricetta, richieste = "Non in matrice", "—"
    elif rm["celle"]:
        ricetta, richieste = "Compilata", sum(1 for v in rm["celle"].values() if v == "Sì")
    else:
        ricetta, richieste = "Da compilare", "—"
    fondo = None if esito == "Stesso nome" else (ARANCIO if esito in ("Rinominata", "Divisa") else GRIGIO)
    for col, v in zip("ABCDE", (m["processo"], m["reparto"], m["centro_di_costo"], m["ruolo"], m["mansione"])):
        cella(wm, f"{col}{n}", v, grassetto=col == "E")
    cella(wm, f"F{n}", "Sì" if m["responsabile"] else "", centro=True)
    cella(wm, f"G{n}", "Sì" if m["abilitazione"] else "", centro=True)
    cella(wm, f"H{n}", esito, riempi=fondo, centro=True)
    cella(wm, f"I{n}", nota, riempi=fondo)
    cella(wm, f"J{n}", testa["U"][k] + testa["O"][k] if k is not None else "—", centro=True)
    cella(wm, f"K{n}", testa["O"][k] if k is not None else "—", centro=True)
    cella(wm, f"L{n}", richieste, centro=True)
    cella(wm, f"M{n}", ricetta, centro=True, riempi=GIALLO if ricetta != "Compilata" else None)
UM = len(elenco) + 1
wm.freeze_panes = "F2"
wm.auto_filter.ref = f"A1:M{UM}"

gen53 = {pieno(g) for r in ruoli for g in r["generiche"]} | {pieno(s) for r in ruoli for m in r["mansioni"] for s in m["specifiche"]}
competenze = {}
for f in fogli:
    for c in f["competenze"]:
        d = competenze.setdefault(c["nome"], {"tipo": "", "origine": "", "fogli": 0, "si": 0, "vuote": 0})
        d["tipo"], d["origine"] = d["tipo"] or c["tipo"], d["origine"] or c["origine"]
        d["fogli"] += 1
        for m in f["mansioni"]:
            v = m["celle"].get(c["nome"], "")
            d["si"] += v == "Sì"
            d["vuote"] += v == ""
wk = wb.create_sheet("Competenze bozza")
for col, larg in zip("ABCDEFGH", (62, 10, 10, 9, 13, 13, 13, 36)):
    wk.column_dimensions[col].width = larg
intestazione(wk, 1, ["Competenza", "Tipo", "Origine", "Fogli", "Mansioni che la richiedono", "Celle ancora vuote",
                     "Stesso nome nel MOD.053", "Nota"], alt=44)
TIPI = {"TRASV": "Trasversale", "TEC": "Tecnica", "ABIL": "Abilitazione", "": ""}
ORIGINI = {"CAT": "Dal catalogo", "NEW": "Nuova", "": ""}
for n, (nome, d) in enumerate(sorted(competenze.items(), key=lambda x: (-x[1]["fogli"], x[0])), 2):
    cella(wk, f"A{n}", nome, grassetto=True)
    cella(wk, f"B{n}", TIPI[d["tipo"]], centro=True, riempi=None if d["tipo"] else GIALLO)
    cella(wk, f"C{n}", ORIGINI[d["origine"]], centro=True, riempi=None if d["origine"] else GIALLO)
    for col, v in zip("DEF", (d["fogli"], d["si"], d["vuote"])):
        cella(wk, f"{col}{n}", v, centro=True)
    cella(wk, f"G{n}", "Sì" if pieno(nome) in gen53 else "", centro=True)
    cella(wk, f"H{n}", "Nome da completare: controllo numerico non indicato" if "[" in nome else "",
          riempi=ARANCIO if "[" in nome else None)
UK = len(competenze) + 1
wk.freeze_panes = "B2"
wk.auto_filter.ref = f"A1:H{UK}"

wt = wb.create_sheet("Stato bozza")
for col, larg in zip("ABCDEFGH", (26, 52, 11, 12, 10, 12, 10, 12)):
    wt.column_dimensions[col].width = larg
intestazione(wt, 1, ["Foglio", "Reparti", "Mansioni", "Competenze", "Celle", "Compilate", "Di cui «Sì»", "Compilato"])
for n, f in enumerate(fogli, 2):
    reparti = list(dict.fromkeys(m["reparto"] for m in f["mansioni"]))
    piene = sum(len(m["celle"]) for m in f["mansioni"])
    si = sum(1 for m in f["mansioni"] for v in m["celle"].values() if v == "Sì")
    cella(wt, f"A{n}", f["foglio"], grassetto=True)
    cella(wt, f"B{n}", ", ".join(reparti))
    for col, v in zip("CDFG", (len(f["mansioni"]), len(f["competenze"]), piene, si)):
        cella(wt, f"{col}{n}", v, centro=True)
    cella(wt, f"E{n}", f"=C{n}*D{n}", centro=True, riempi=GRIGIO)
    cella(wt, f"H{n}", f"=IF(E{n}=0,0,F{n}/E{n})", centro=True, riempi=GIALLO if not piene else GRIGIO).number_format = "0%"
UT = len(fogli) + 1
cella(wt, f"A{UT + 1}", "Totale", grassetto=True, colore=BLU)
for col in "CEFG":
    cella(wt, f"{col}{UT + 1}", f"=SUM({col}2:{col}{UT})", grassetto=True, centro=True, riempi=GRIGIO)
cella(wt, f"H{UT + 1}", f"=IF(E{UT + 1}=0,0,F{UT + 1}/E{UT + 1})", grassetto=True, centro=True, riempi=GRIGIO).number_format = "0%"
wt.freeze_panes = "A2"
k_divise = [k_colonna[pieno(c)] for c in DIVISE]
livelli_divise = sum(testa[liv][k] for k in k_divise for liv in "ILUO")

wr = wb.create_sheet("Riepilogo")
wr.column_dimensions["A"].width = 58
wr.column_dimensions["B"].width = 14
wr["A1"].value = "Riepilogo"
wr["A1"].font = Font(name=ARIAL, size=14, bold=True, color=BLU)
voci = [
    ("Righe del catalogo (competenze per mansione)", f"=COUNTA(Catalogo!D2:D{ULT})"),
    ("Di cui in ruoli operativi", f'=COUNTIF(Catalogo!B2:B{ULT},"Operativo")'),
    ("Di cui generiche", f'=COUNTIF(Catalogo!E2:E{ULT},"Generica")'),
    ("Livelli richiesti da compilare", f'=COUNTIFS(Catalogo!B2:B{ULT},"Operativo",Catalogo!E2:E{ULT},"Di mansione")'),
    ("Livelli richiesti compilati", f'=COUNTIFS(Catalogo!B2:B{ULT},"Operativo",Catalogo!E2:E{ULT},"Di mansione",Catalogo!F2:F{ULT},"<>")'),
    ("Criticità compilate", f"=COUNTA(Catalogo!G2:G{ULT})"),
    ("Colonne della skill matrix", f"=COUNTA(Incrocio!A2:A{UI})"),
    ("Con lo stesso nome nel MOD.053", f'=COUNTIF(Incrocio!B2:B{UI},"Stesso nome")'),
    ("Con nome o livello diverso", f'=COUNTIF(Incrocio!B2:B{UI},"Nome o livello diverso")'),
    ("Solo nella skill matrix", f'=COUNTIF(Incrocio!B2:B{UI},"Solo nella skill matrix")'),
    ("Mansioni con una sola persona autonoma", f"=COUNTIF(Incrocio!I2:I{UI},1)"),
    ("Mansioni senza persone autonome", f"=COUNTIF(Incrocio!I2:I{UI},0)"),
    ("Mansioni con un solo formatore", f"=COUNTIF(Incrocio!J2:J{UI},1)"),
    ("Mansioni senza formatori", f"=COUNTIF(Incrocio!J2:J{UI},0)"),
    ("Livelli in tutto", f"=SUM(Incrocio!E2:H{UI})"),
    ("Bozza della Qualità: mansioni in elenco", f"=COUNTA('Mansioni bozza'!E2:E{UM})"),
    ("Di cui «Responsabilità del reparto»", f"=COUNTIF('Mansioni bozza'!F2:F{UM},\"Sì\")"),
    ("Di cui con abilitazione", f"=COUNTIF('Mansioni bozza'!G2:G{UM},\"Sì\")"),
    ("Di cui fuori dal processo «Produzione»", f"=COUNTIF('Mansioni bozza'!A2:A{UM},\"<>PRODUZIONE\")"),
    ("Mansioni già nella skill matrix con lo stesso nome", f"=COUNTIF('Mansioni bozza'!H2:H{UM},\"Stesso nome\")"),
    ("Mansioni rinominate", f"=COUNTIF('Mansioni bozza'!H2:H{UM},\"Rinominata\")"),
    ("Mansioni nate dalla divisione di una colonna", f"=COUNTIF('Mansioni bozza'!H2:H{UM},\"Divisa\")"),
    ("Mansioni nuove", f"=COUNTIF('Mansioni bozza'!H2:H{UM},\"Nuova\")"),
    ("Mansioni con la ricetta compilata", f"=COUNTIF('Mansioni bozza'!M2:M{UM},\"Compilata\")"),
    ("Mansioni con la ricetta da compilare", f"=COUNTIF('Mansioni bozza'!M2:M{UM},\"Da compilare\")"),
    ("Competenze distinte nella bozza", f"=COUNTA('Competenze bozza'!A2:A{UK})"),
    ("Celle della matrice", f"='Stato bozza'!E{UT + 1}"),
    ("Celle compilate", f"='Stato bozza'!F{UT + 1}"),
    ("Colonne della skill matrix divise nella bozza", len(DIVISE)),
    ("Livelli firmati su quelle colonne, da ripartire a mano", livelli_divise),
]
for i, (a, f) in enumerate(voci, 3):
    cella(wr, f"A{i}", a)
    cella(wr, f"B{i}", f, grassetto=True, centro=True, riempi=GRIGIO)

for f in wb.worksheets:
    f.sheet_view.showGridLines = False
uscita = RADICE / "Catalogo_competenze_completo.xlsx"
wb.save(uscita)
print(uscita.name, "· righe", ULT - 1, "· ruoli operativi", len(operativi), "· solo nel MOD.053:", solo53)
from collections import Counter  # noqa: E402

print("bozza · mansioni", len(elenco), "· esiti", dict(Counter(wm[f"H{n}"].value for n in range(2, UM + 1))),
      "· ricetta", dict(Counter(wm[f"M{n}"].value for n in range(2, UM + 1))), "· competenze", len(competenze),
      "· livelli da ripartire", livelli_divise, "· senza tipo", sum(1 for d in competenze.values() if not d["tipo"]))
print("livelli sulle colonne con lo stesso nome o rinominate:",
      sum(testa[liv][k] for k, c in enumerate(colonne) if c not in DIVISE for liv in "ILUO"))
