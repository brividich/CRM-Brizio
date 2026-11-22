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
    ("Da fondere", "La Qualità sta scrivendo altre competenze e mansioni: quando il file arriva, si aggiunge qui. Le righe evidenziate in arancio nel foglio «Incrocio» sono i punti da allineare fra i due documenti."),
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
]
for i, (a, f) in enumerate(voci, 3):
    cella(wr, f"A{i}", a)
    cella(wr, f"B{i}", f, grassetto=True, centro=True, riempi=GRIGIO)

for f in wb.worksheets:
    f.sheet_view.showGridLines = False
uscita = RADICE / "Catalogo_competenze_completo.xlsx"
wb.save(uscita)
print(uscita.name, "· righe", ULT - 1, "· ruoli operativi", len(operativi), "· solo nel MOD.053:", solo53)
