"""Export Excel (.xlsx) di riconciliazione e analisi. Usa openpyxl.

Le celle passano da `core.excel_export.append_row` (sede unica della
sanificazione anti formula injection): `ws.append` scriverebbe come formula
viva qualunque stringa che inizia con "=" (descrizioni/reparti dal DB).
"""
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from core.excel_export import append_row

from . import services

_HEADER = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="12395F")
_DANGER = Font(color="C0392B", bold=True)


def _intesta(ws, colonne):
    append_row(ws, colonne)
    for cell in ws[1]:
        cell.font = _HEADER
        cell.fill = _HEADER_FILL


def _autolarghezza(ws):
    for col in ws.columns:
        larg = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(larg + 3, 48)


def riconciliazione_xlsx(trimestre):
    """Workbook con la riconciliazione di un trimestre."""
    righe, riep = services.riconcilia(trimestre)
    wb = Workbook()
    ws = wb.active
    ws.title = f"Riconciliazione {trimestre}"[:31]
    _intesta(ws, ["Contratto", "Unità", "Pool", "Contatore",
                  "Fornitore", "Interno", "Scarto", "Esito"])
    for r in righe:
        append_row(ws, [r["contratto"], r["descrizione"], "sì" if r["pool"] else "",
                        r["contatore"], r["fornitore"], r["ns"], r["scarto"], r["esito"]])
        if r["livello"] == "danger":
            for cell in ws[ws.max_row]:
                cell.font = _DANGER
    append_row(ws)
    append_row(ws, ["Trimestre", trimestre, "", "Contatori", riep["contatori"],
                    "Anomalie", riep["anomalie"], "OK" if riep["ok"] else "DA CONTROLLARE"])
    _autolarghezza(ws)
    return wb


def analisi_xlsx():
    """Workbook multi-foglio con andamento, consumo, classifica, ripartizione."""
    wb = Workbook()

    ws = wb.active
    ws.title = "Andamento"
    _intesta(ws, ["Trimestre", "A4 BN", "A3 BN", "A4 COL", "A3 COL",
                  "BN", "Colore", "Totale", "MFC lette / attese"])
    for a in services.andamento_trimestri():
        append_row(ws, [a["trimestre"], a["a4_bn"], a["a3_bn"], a["a4_col"], a["a3_col"],
                        a["bn"], a["col"], a["totale"], f"{a['macchine']}/{a['attese']}"])
    _autolarghezza(ws)

    consumo, anomalie = services.consumo_per_trimestre()
    ws = wb.create_sheet("Consumo")
    _intesta(ws, ["Trimestre", "BN", "Colore", "Totale prodotto", "MFC contate / attese", "Note"])
    for c in consumo:
        note = "in corso" if c["in_corso"] else ("parziale" if c["parziale"] else "")
        append_row(ws, [c["trimestre"], c["bn"], c["col"], c["totale"],
                        f"{c['macchine']}/{c['attese']}", note])
    append_row(ws)
    append_row(ws, ["Cali contati come 0 (refusi o azzeramenti)", anomalie])
    _autolarghezza(ws)

    ws = wb.create_sheet("Classifica reparti")
    _intesta(ws, ["#", "Reparto", "Matricola", "BN", "Colore", "Totale", "Quota colore %"])
    for i, r in enumerate(services.classifica_reparti(), 1):
        append_row(ws, [i, r["reparto"], r["matricola"], r["bn"], r["col"],
                        r["totale"], r["quota_col"]])
    _autolarghezza(ws)

    rip = services.ripartizione()
    ws = wb.create_sheet("Ripartizione")
    _intesta(ws, ["Metrica", "Valore"])
    append_row(ws, ["Ultima lettura di", f"{rip.get('macchine', 0)} MFC (fino al {rip.get('trimestre', '')})"])
    append_row(ws, ["Totale copie", rip.get("totale", 0)])
    append_row(ws, ["% Bianco/Nero", rip.get("bn_pct", 0)])
    append_row(ws, ["% Colore", rip.get("col_pct", 0)])
    append_row(ws, ["% A4", rip.get("a4_pct", 0)])
    append_row(ws, ["% A3", rip.get("a3_pct", 0)])
    _autolarghezza(ws)

    return wb


def storico_macchina_xlsx(macchina):
    """Workbook con lo storico di una MFC: letture trimestrali (con copie e lacune) e mensili."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Trimestrali"
    _intesta(ws, ["Trimestre", "Data", "Fonte", "A4 BN", "A3 BN", "A4 COL", "A3 COL",
                  "Totale", "Copie nel trimestre", "Note"])
    for r in services.righe_letture_macchina(macchina):
        l = r["lettura"]
        if l is None:
            append_row(ws, [r["trimestre"], "", "", "", "", "", "", "", "",
                            "Lettura mancante: copie del trimestre successivo non calcolabili"])
            continue
        nota = ("Calo: " + ", ".join(r["cali"])) if r["cali"] else l.note
        append_row(ws, [l.trimestre, l.data, l.get_fonte_display(), l.a4_bn, l.a3_bn, l.a4_col,
                        l.a3_col, l.totale, r["copie"], nota])
        if r["cali"]:
            for cell in ws[ws.max_row]:
                cell.font = _DANGER
    _autolarghezza(ws)

    ws = wb.create_sheet("Mensili")
    _intesta(ws, ["Mese", "Rilevata il", "A4 BN", "A3 BN", "A4 COL", "A3 COL", "Totale",
                  "Copie nel mese"])
    for r in services.righe_mensili_macchina(macchina, ultimi=120):
        l = r["lettura"]
        append_row(ws, [l.mese.strftime("%m/%Y"), timezone.localtime(l.rilevata_il).strftime("%d/%m/%Y %H:%M"),
                        l.a4_bn, l.a3_bn, l.a4_col, l.a3_col, l.totale, r["copie"]])
    _autolarghezza(ws)

    ws = wb.create_sheet("Anagrafica")
    for etichetta, valore in (("Reparto", macchina.reparto), ("Matricola", macchina.matricola),
                              ("Modello", macchina.modello), ("Contratto", macchina.contratto),
                              ("Fornitore", macchina.get_fornitore_display()),
                              ("Indirizzo IP", macchina.host or ""),
                              ("Attiva", "sì" if macchina.attiva else "no")):
        append_row(ws, [etichetta, valore])
    _autolarghezza(ws)
    return wb
