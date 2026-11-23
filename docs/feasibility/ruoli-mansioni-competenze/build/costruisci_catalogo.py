"""Catalogo pilota delle competenze per il reparto CN5G, da completare con la Qualità e il capo reparto.

Le voci vengono dalla tabella «Ruolo → Mansione → Competenza di mansione → Competenza generica» del MOD.053 Rev.4
(sistema di gestione in vigore, letto il 21/11/2026). Qui sono trascritte: lo script non accede alla cartella di rete.
Nessun nominativo: solo macchine e competenze.

    python build/costruisci_catalogo.py      →  Catalogo_pilota_CN5G.xlsx
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

RADICE = Path(__file__).resolve().parent.parent
FONTE = "MOD.053 Rev.4"

# (competenza, tipo, dove compare nel MOD.053)
COMPETENZE = [
    ("Disegno tecnico", "Generica", "Reparto"),
    ("Presetting", "Generica", "Reparto"),
    ("Utilizzo degli strumenti di misura di reparto", "Generica", "Reparto"),
    ("Conoscenza procedure interne", "Generica", "Reparto"),
    ("FOD", "Generica", "Reparto"),
    ("Programmazione bordo macchina Heidenhain", "Di mansione", "Scritta sulla DM3"),
    ("Prova programma Heidenhain", "Di mansione", "Scritta sulla DM3"),
    ("Piazzamento bascula", "Di mansione", "Per macchina"),
    ("Piazzamento testa tiltante", "Di mansione", "Per macchina"),
    ("Piazzamento testa tiltante S", "Di mansione", "Per macchina"),
    ("Piazzamento tavola a tornire", "Di mansione", "Per macchina"),
]
# macchina → competenze di piazzamento indicate nel MOD.053; «in skill matrix» = colonna presente nel MOD.187 del 30/04/2026
MACCHINE = [
    ("DM3 - DMG 85 Monoblock", ["Piazzamento bascula"], True),
    ("DM6 - DMC125U Duoblock", ["Piazzamento testa tiltante S"], True),
    ("DM7 - DMC160U Duoblock", ["Piazzamento testa tiltante"], True),
    ("DM10 - DMC 85 Duoblock", ["Piazzamento bascula"], True),
    ("DM11 - DMG 85 Monoblock", ["Piazzamento bascula"], True),
    ("DM12 - DMC160U Duoblock", ["Piazzamento testa tiltante"], True),
    ("DM13 - DMG 75 Monoblock", ["Piazzamento bascula"], True),
    ("DM14 - DMG 65 FD Monoblock", ["Piazzamento bascula", "Piazzamento tavola a tornire"], True),
    ("DM16", ["Piazzamento bascula"], False),
    ("DM17", ["Piazzamento bascula"], False),
]

ARIAL = "Arial"
BLU = "10233F"
GIALLO = PatternFill("solid", start_color="FFF59D")
TESTA = PatternFill("solid", start_color=BLU)
GRIGIO = PatternFill("solid", start_color="EEF2F7")
ESEMPIO = PatternFill("solid", start_color="F3F4F6")
BORDO = Border(*(Side(style="thin", color="C5CED9"),) * 4)


def cella(ws, rif, valore, grassetto=False, colore="1A202C", riempi=None, a_capo=True, corsivo=False, dim=10, centro=False):
    c = ws[rif]
    c.value = valore
    c.font = Font(name=ARIAL, size=dim, bold=grassetto, italic=corsivo, color=colore)
    c.alignment = Alignment(wrap_text=a_capo, vertical="center", horizontal="center" if centro else "left")
    if riempi is not None:
        c.fill = riempi
    return c


def intestazione(ws, riga, titoli):
    for i, t in enumerate(titoli, 1):
        c = cella(ws, f"{get_column_letter(i)}{riga}", t, grassetto=True, colore="FFFFFF", riempi=TESTA, centro=i > 1)
        c.border = BORDO
    ws.row_dimensions[riga].height = 34


wb = Workbook()

# ---------------------------------------------------------------- Leggimi
ws = wb.active
ws.title = "Leggimi"
ws.column_dimensions["A"].width = 26
ws.column_dimensions["B"].width = 96
cella(ws, "A1", "Catalogo pilota delle competenze · reparto CN5G", grassetto=True, colore=BLU, dim=16, a_capo=False)
cella(ws, "A2", "Fresatura a 5 assi grande formato · da completare con la Qualità e il capo reparto", colore="4A5568", a_capo=False)
righe = [
    ("A che cosa serve", "Portare nel portale ciò che il sistema di gestione ha già scritto: quali competenze servono su ogni macchina. Per farlo mancano due informazioni per ogni competenza: il livello richiesto e quanto pesa."),
    ("Da dove vengono le voci", f"Dalla tabella «Ruolo → Mansione → Competenza di mansione → Competenza generica» del {FONTE}. Nessuna voce è stata aggiunta o tolta."),
    ("Che cosa compilare", "Solo le celle gialle. Foglio «Competenze»: livello richiesto, criticità, eventuale requisito formale. Foglio «Macchine»: la X è già messa dove il modulo indica la competenza; cambiatela se serve."),
    ("Livello richiesto", "I = in formazione, solo in affiancamento · L = in autonomia sulle operazioni note, firma · U = in autonomia · O = forma altri operatori. Definizioni di MT CN 06 Rev.21 §8.3."),
    ("Criticità", "Bloccante = senza, la persona non può svolgere la mansione da sola · Importante = serve per l'autonomia piena · Utile = completa il profilo. È una proposta dell'analisi: nel sistema di gestione oggi non c'è."),
    ("Requisito formale", "Se la competenza richiede un corso, una qualifica o un'abilitazione con scadenza, scrivetelo qui (per esempio: corso FOD, validità 24 mesi). Altrimenti lasciate vuoto."),
    ("La riga di esempio", "La riga grigia in cima al foglio «Competenze» mostra come si compila. Non è una voce del catalogo e non entra nei conteggi."),
    ("Tre cose da chiarire", "1) «Programmazione bordo macchina Heidenhain» e «Prova programma Heidenhain» nel modulo sono scritte sulla sola DM3: valgono per tutte le macchine del reparto? Nel foglio «Macchine» sono proposte su tutte. 2) DM16 e DM17 sono nel MOD.053 ma non nella skill matrix (MOD.187) del 30/04/2026. 3) Il «piazzamento bascula» è una sola competenza valida su sei macchine, o va valutato macchina per macchina?"),
    ("Che cosa succede dopo", "Il file compilato si carica nel portale così com'è. Poi si ripete per gli altri reparti, partendo da quelli con più persone e dai processi qualificati."),
]
for i, (a, b) in enumerate(righe, 4):
    cella(ws, f"A{i}", a, grassetto=True, colore=BLU)
    cella(ws, f"B{i}", b)
    ws.row_dimensions[i].height = 30 + 13 * (len(b) // 105)

# ---------------------------------------------------------------- Competenze
wc = wb.create_sheet("Competenze")
for col, larg in zip("ABCDEFGH", (5, 44, 14, 18, 13, 15, 40, 40)):
    wc.column_dimensions[col].width = larg
cella(wc, "A1", "Competenze del reparto CN5G", grassetto=True, colore=BLU, dim=14, a_capo=False)
cella(wc, "A2", "Compilare le celle gialle. Livello: I, L, U oppure O. Criticità: Bloccante, Importante oppure Utile.", colore="4A5568", a_capo=False)
intestazione(wc, 4, ["#", "Competenza", "Tipo", "Nel MOD.053", "Livello richiesto", "Criticità", "Requisito formale (se c'è)", "Note"])
for col, v in zip("ABCDEFGH", ("es.", "Lettura del ciclo di lavoro", "Generica", "—", "L", "Importante", "Nessuno", "Riga di esempio: non compilare")):
    c = cella(wc, f"{col}5", v, corsivo=True, colore="6B7280", riempi=ESEMPIO, centro=col in "ACDEF")
    c.border = BORDO
PRIMA = 6
for i, (nome, tipo, dove) in enumerate(COMPETENZE):
    r = PRIMA + i
    for col, v in zip("ABCD", (i + 1, nome, tipo, dove)):
        c = cella(wc, f"{col}{r}", v, centro=col in "ACD", grassetto=col == "B")
        c.border = BORDO
    for col in "EFGH":
        c = cella(wc, f"{col}{r}", None, riempi=GIALLO, centro=col in "EF")
        c.border = BORDO
    wc.row_dimensions[r].height = 22
ULTIMA = PRIMA + len(COMPETENZE) - 1
dv_liv = DataValidation(type="list", formula1='"I,L,U,O"', allow_blank=True, showErrorMessage=True,
                        errorTitle="Livello", error="Scegliere I, L, U oppure O")
dv_cri = DataValidation(type="list", formula1='"Bloccante,Importante,Utile"', allow_blank=True, showErrorMessage=True,
                        errorTitle="Criticità", error="Scegliere Bloccante, Importante oppure Utile")
wc.add_data_validation(dv_liv)
wc.add_data_validation(dv_cri)
dv_liv.add(f"E{PRIMA}:E{ULTIMA}")
dv_cri.add(f"F{PRIMA}:F{ULTIMA}")
cella(wc, f"A{ULTIMA + 2}", f"Fonte delle voci: {FONTE}, tabella ruoli, mansioni e competenze, sezione «Operatore CN5G».", colore="6B7280", corsivo=True, a_capo=False, dim=9)
wc.freeze_panes = "C5"

# ---------------------------------------------------------------- Macchine
wm = wb.create_sheet("Macchine")
wm.column_dimensions["A"].width = 30
wm.column_dimensions["B"].width = 13
for i in range(len(COMPETENZE)):
    wm.column_dimensions[get_column_letter(3 + i)].width = 15
wm.column_dimensions[get_column_letter(3 + len(COMPETENZE))].width = 13
cella(wm, "A1", "Quali competenze servono su ogni macchina", grassetto=True, colore=BLU, dim=14, a_capo=False)
cella(wm, "A2", "X = competenza richiesta su quella macchina. Le X sono proposte dal MOD.053: correggetele nelle celle gialle.", colore="4A5568", a_capo=False)
intestazione(wm, 4, ["Macchina (mansione)", "Nella skill matrix"] + [c[0] for c in COMPETENZE] + ["Competenze richieste"])
wm.row_dimensions[4].height = 62
PM = 5
for i, (macchina, piazzamenti, in_skm) in enumerate(MACCHINE):
    r = PM + i
    cella(wm, f"A{r}", macchina, grassetto=True).border = BORDO
    cella(wm, f"B{r}", "Sì" if in_skm else "No", centro=True, colore="1A202C" if in_skm else "B45309").border = BORDO
    for j, (nome, tipo, dove) in enumerate(COMPETENZE):
        richiesta = dove != "Per macchina" or nome in piazzamenti
        c = cella(wm, f"{get_column_letter(3 + j)}{r}", "X" if richiesta else None, riempi=GIALLO, centro=True, grassetto=True)
        c.border = BORDO
    primo, ultimo = get_column_letter(3), get_column_letter(2 + len(COMPETENZE))
    c = cella(wm, f"{get_column_letter(3 + len(COMPETENZE))}{r}", f'=COUNTIF({primo}{r}:{ultimo}{r},"X")', centro=True, riempi=GRIGIO)
    c.border = BORDO
    wm.row_dimensions[r].height = 22
UM = PM + len(MACCHINE) - 1
dv_x = DataValidation(type="list", formula1='"X"', allow_blank=True)
wm.add_data_validation(dv_x)
dv_x.add(f"C{PM}:{get_column_letter(2 + len(COMPETENZE))}{UM}")
cella(wm, f"A{UM + 1}", "Macchine che la richiedono", grassetto=True, riempi=GRIGIO).border = BORDO
cella(wm, f"B{UM + 1}", None, riempi=GRIGIO).border = BORDO
for j in range(len(COMPETENZE)):
    col = get_column_letter(3 + j)
    cella(wm, f"{col}{UM + 1}", f'=COUNTIF({col}{PM}:{col}{UM},"X")', centro=True, riempi=GRIGIO).border = BORDO
wm.freeze_panes = "C5"

# ---------------------------------------------------------------- Riepilogo
wr = wb.create_sheet("Riepilogo")
wr.column_dimensions["A"].width = 52
wr.column_dimensions["B"].width = 16
cella(wr, "A1", "A che punto siamo", grassetto=True, colore=BLU, dim=14, a_capo=False)
cella(wr, "A2", "Si aggiorna da solo mentre compilate gli altri fogli.", colore="4A5568", a_capo=False)
E, F = f"Competenze!E{PRIMA}:E{ULTIMA}", f"Competenze!F{PRIMA}:F{ULTIMA}"
voci = [
    ("Competenze del reparto", f"=ROWS({E})", "0"),
    ("Macchine del reparto", f"=ROWS(Macchine!A{PM}:A{UM})", "0"),
    ("Competenze con il livello richiesto", f"=COUNTA({E})", "0"),
    ("Competenze con la criticità", f"=COUNTA({F})", "0"),
    ("Competenze complete (livello e criticità)", f'=COUNTIFS({E},"<>",{F},"<>")', "0"),
    ("Completamento", "=IF(B4=0,0,B8/B4)", "0%"),
    ("Di cui bloccanti", f'=COUNTIF({F},"Bloccante")', "0"),
    ("Di cui importanti", f'=COUNTIF({F},"Importante")', "0"),
    ("Di cui utili", f'=COUNTIF({F},"Utile")', "0"),
    ("Abbinamenti macchina e competenza da caricare", f'=COUNTIF(Macchine!C{PM}:{get_column_letter(2 + len(COMPETENZE))}{UM},"X")', "0"),
]
for i, (etichetta, formula, formato) in enumerate(voci, 4):
    cella(wr, f"A{i}", etichetta).border = BORDO
    c = cella(wr, f"B{i}", formula, grassetto=True, centro=True, riempi=GRIGIO)
    c.number_format = formato
    c.border = BORDO
    wr.row_dimensions[i].height = 22

for foglio in wb.worksheets:
    foglio.sheet_view.showGridLines = False
    foglio.page_setup.orientation = "landscape"
    foglio.page_setup.fitToWidth = 1
    foglio.sheet_properties.pageSetUpPr.fitToPage = True
    foglio.page_setup.fitToHeight = 0
uscita = RADICE / "archivio" / "Catalogo_pilota_CN5G.xlsx"  # superato dai fogli CN5GS e CN5GL della bozza della Qualità
wb.save(uscita)
print(uscita, "·", len(COMPETENZE), "competenze,", len(MACCHINE), "macchine")
