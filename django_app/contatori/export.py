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


def letture_mensili_xlsx(dati):
    """Workbook delle letture mensili di un mese (dati di ``mail_mensile.riepilogo``)."""
    wb = Workbook()
    ws = wb.active
    ws.title = f"Letture {dati['mese']:%m-%Y}"
    etichette = [e for _, e in services.CONTATORI]
    _intesta(ws, ["Reparto", "Matricola", "Modello", "IP", "Letta il", *etichette, "Totale",
                  *[f"Copie {e}" for e in etichette], "Copie del mese"])
    for r in dati["lette"]:
        m, l, c = r["macchina"], r["lettura"], r["copie"] or {}
        append_row(ws, [m.reparto, m.matricola, m.modello, m.host,
                        timezone.localtime(l.rilevata_il).strftime("%d/%m/%Y %H:%M"),
                        *[getattr(l, campo) for campo in services.CAMPI], l.totale,
                        *[c.get(campo) for campo in services.CAMPI], c.get("totale")])
    if dati["mancanti"]:
        append_row(ws)
        append_row(ws, ["Mancanti"])
        ws.cell(row=ws.max_row, column=1).font = _DANGER
        for r in dati["mancanti"]:
            m = r["macchina"]
            append_row(ws, [m.reparto, m.matricola, m.modello, m.host, r["motivo"]])
    _autolarghezza(ws)
    return wb


def _data_ora(valore):
    return timezone.localtime(valore).strftime("%d/%m/%Y %H:%M") if valore else ""


def _giorni_testo(giorni):
    if giorni is None:
        return ""
    return "esaurito" if giorni == 0 else giorni


def _evidenzia_riga(ws):
    for cell in ws[ws.max_row]:
        cell.font = _DANGER


def consumabili_xlsx(righe):
    """Consumabili flotta: una riga per consumabile di ogni MFC delle righe mostrate (filtro compreso)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Consumabili"
    _intesta(ws, ["Reparto", "Matricola", "Modello", "IP", "Consumabile", "Livello %", "Giorni stimati",
                  "Sotto soglia", "Letto il"])
    for r in righe:
        m, stato = r["macchina"], r["stato"]
        if not stato or not stato["voci"]:
            append_row(ws, [m.reparto, m.matricola, m.modello, m.host, "nessuna lettura salvata"])
            continue
        for v in stato["voci"]:
            append_row(ws, [m.reparto, m.matricola, m.modello, m.host, v["nome"], v["pct"],
                            _giorni_testo(v["giorni"]), "sì" if v["critico"] else "no",
                            _data_ora(stato["rilevata_il"])])
            if v["critico"]:
                _evidenzia_riga(ws)
    _autolarghezza(ws)
    return wb


def fabbisogno_xlsx(dati):
    """Fabbisogno per consumabile (dati di ``services.fabbisogno_consumabili``)."""
    breve, lungo = dati["giorni"]
    wb = Workbook()
    ws = wb.active
    ws.title = "Fabbisogno"
    _intesta(ws, ["Consumabile", "MFC che lo usano", "Modelli MFC", "Durata media (giorni)",
                  "Cambi misurati", "Pezzi stimati all'anno", f"Finiscono entro {breve} giorni",
                  f"Finiscono entro {lungo} giorni"])
    for r in dati["righe"]:
        append_row(ws, [r["nome"], r["n_macchine"], ", ".join(r["modelli"]), r["durata_media"],
                        r["cambi_misurati"], r["pezzi_anno"], r["entro_30"], r["entro_60"]])
    _autolarghezza(ws)
    return wb


def registro_letture_xlsx(registro):
    """Registro letture: MFC × trimestri con il totale letto (o lo stato della lettura mancante)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Registro letture"
    _intesta(ws, ["Reparto", "Matricola", "Attiva", *registro["trimestri"]])
    for r in registro["righe"]:
        celle = []
        for c in r["celle"]:
            if c.get("lettura"):
                celle.append(c["lettura"].totale)
            elif c.get("provvisoria"):
                celle.append(f"{c['provvisoria'].totale} (mensile, provvisoria)")
            elif c.get("stato") == "mancante":
                celle.append("manca")
            else:
                celle.append("")
        append_row(ws, [r["macchina"].reparto, r["macchina"].matricola, "sì" if r["macchina"].attiva else "no",
                        *celle])
    _autolarghezza(ws)

    # Dettaglio per contatore: le stesse letture, una riga ciascuna.
    ws = wb.create_sheet("Letture")
    _intesta(ws, ["Reparto", "Matricola", "Trimestre", "Data", "Fonte", *[e for _, e in services.CONTATORI],
                  "Totale", "Copie nel trimestre", "Calo"])
    for r in registro["righe"]:
        for c in r["celle"]:
            lett = c.get("lettura")
            if lett is None:
                continue
            append_row(ws, [r["macchina"].reparto, r["macchina"].matricola, lett.trimestre, lett.data,
                            lett.get_fonte_display(), *[getattr(lett, campo) for campo in services.CAMPI], lett.totale,
                            c.get("copie"), ", ".join(c.get("cali") or [])])
            if c.get("cali"):
                _evidenzia_riga(ws)
    _autolarghezza(ws)
    return wb


def letture_gestione_xlsx(tipo, righe):
    """Gestisci letture: tutte le righe del filtro (tutte le pagine)."""
    mensili = tipo == "mensili"
    wb = Workbook()
    ws = wb.active
    ws.title = "Letture mensili" if mensili else "Letture trimestrali"
    _intesta(ws, ["Reparto", "Matricola", "Mese" if mensili else "Trimestre",
                  "Rilevata il" if mensili else "Data", *[e for _, e in services.CONTATORI], "Totale",
                  *([] if mensili else ["Fonte"]), "Controllo"])
    for r in righe:
        lett = r["lettura"]
        append_row(ws, [r["macchina"].reparto, r["macchina"].matricola, r["periodo"],
                        _data_ora(lett.rilevata_il) if mensili else lett.data,
                        *[getattr(lett, campo) for campo in services.CAMPI], lett.totale,
                        *([] if mensili else [lett.get_fonte_display()]),
                        ("calo " + ", ".join(r["cali"])) if r["cali"] else "ok"])
        if r["cali"]:
            _evidenzia_riga(ws)
    _autolarghezza(ws)
    return wb


def macchine_xlsx(macchine, *, trimestre, con_lettura, consumabili):
    """Stampanti MFC dell'elenco filtrato."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Stampanti MFC"
    _intesta(ws, ["Reparto", "Matricola", "Modello", "Contratto", "Fornitore", "IP", "Asset HUB",
                  "Salute SNMP", "Ultimo controllo SNMP", "Ultimo errore SNMP", f"Lettura {trimestre}",
                  "Consumabile più basso", "Livello %", "Attiva"])
    for m in macchine:
        peggiore = (consumabili.get(m.pk) or {}).get("peggiore") or {}
        append_row(ws, [m.reparto, m.matricola, m.modello, m.contratto, m.get_fornitore_display(), m.host,
                        m.asset.asset_tag if m.asset_id else "", m.get_snmp_stato_display(),
                        _data_ora(m.snmp_ultimo_controllo), m.snmp_ultimo_errore,
                        "presente" if m.pk in con_lettura else ("manca" if m.attiva else ""),
                        peggiore.get("nome", ""), peggiore.get("pct"), "sì" if m.attiva else "no"])
    _autolarghezza(ws)
    return wb


def monitor_snmp_xlsx(dispositivi, macchine, disponibilita):
    """Monitor SNMP con i filtri correnti: un foglio per i dispositivi, uno per le MFC."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Dispositivi"
    _intesta(ws, ["Dispositivo", "Categoria", "Posizione", "Host", "Porta", "Stato", "Ultimo controllo",
                  "Latenza ms", "Risposte 24 h %", "Ultimo errore", "Asset HUB", "Verificato", "Attivo"])
    for d in dispositivi:
        append_row(ws, [d.nome, d.get_categoria_display(), d.posizione, d.host, d.porta,
                        d.get_snmp_stato_display(), _data_ora(d.snmp_ultimo_controllo), d.snmp_tempo_risposta_ms,
                        disponibilita.get(d.pk), d.snmp_ultimo_errore,
                        d.asset.asset_tag if d.asset_id else "", "sì" if d.verificato else "no",
                        "sì" if d.attivo else "no"])
    _autolarghezza(ws)
    ws = wb.create_sheet("Stampanti MFC")
    _intesta(ws, ["Reparto", "Matricola", "Modello", "Host", "Stato", "Ultimo controllo", "Latenza ms",
                  "Ultimo errore", "Asset HUB"])
    for m in macchine:
        append_row(ws, [m.reparto, m.matricola, m.modello, m.host, m.get_snmp_stato_display(),
                        _data_ora(m.snmp_ultimo_controllo), m.snmp_tempo_risposta_ms, m.snmp_ultimo_errore,
                        m.asset.asset_tag if m.asset_id else ""])
    _autolarghezza(ws)
    return wb


def _esito_archivio(riep):
    if riep is None:
        return ""
    if riep["contratti_danger"]:
        return f"{riep['contratti_danger']} da controllare"
    if riep["letture_mancanti"]:
        return f"{riep['letture_mancanti']} letture interne mancanti"
    return f"{riep['contratti_ok']}/{riep['contratti']} ok"


def fatture_xlsx(archivio):
    """Archivio fatture: un foglio per trimestre ed esito, uno con le righe di ogni fattura."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Archivio"
    _intesta(ws, ["Trimestre", "Fattura", "Data", "Fornitore", "Dettaglio", "Chiusura letture",
                  "Letture interne", "Contratti", "Esito riconciliazione"])
    for a in archivio:
        riep = a["riepilogo"]
        if not a["fatture"]:
            append_row(ws, [a["trimestre"], "in corso" if a["in_corso"] else "fattura mancante", "", "", "", "",
                            a["letture"], "", ""])
            if not a["in_corso"]:
                ws.cell(row=ws.max_row, column=2).font = _DANGER
            continue
        for f in a["fatture"]:
            append_row(ws, [a["trimestre"], f.numero, f.data, f.fornitore, f.get_dettaglio_display(),
                            f.periodo_al, a["letture"], riep["contratti"] if riep else "", _esito_archivio(riep)])
    _autolarghezza(ws)
    ws = wb.create_sheet("Righe fatture")
    _intesta(ws, ["Trimestre", "Fattura", "Contratto", "Descrizione", *[e for _, e in services.CONTATORI]])
    for a in archivio:
        for f in a["fatture"]:
            for riga in f.righe.all():
                append_row(ws, [a["trimestre"], f.numero, riga.contratto, riga.descrizione,
                                *[getattr(riga, campo) for campo in services.CAMPI]])
    _autolarghezza(ws)
    return wb
