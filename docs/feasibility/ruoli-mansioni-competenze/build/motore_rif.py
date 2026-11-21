"""Dataset finto e motore di riferimento dell'analisi RMC (nessun dato reale, nessun accesso al DB).

Uso:  python build/motore_rif.py
Scrive prototipo/dati/dataset.json e build/risultati.json, e stampa i numeri citati in
02_tobe_flusso_algoritmo.md. Il prototipo HTML incorpora lo stesso dataset e riscrive
in JavaScript le stesse regole: i numeri devono coincidere.

Nomi di persone inventati. Deterministico: nessuna casualità non seminata.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
OGGI = date(2027, 3, 15)
ORD = {"": 0, "I": 1, "L": 2, "U": 3, "O": 4}
DA_ORD = {v: k for k, v in ORD.items()}

# ── Parametri del modello (quelli che deve fissare la Qualità) ────────────────
PARAMETRI = {
    "soglia_operativa": "U",
    "conferma_periodica_mesi": 6,
    "finestra_esercizio_mesi": 12,
    "preavviso_esercizio_mesi": 9,
    "grazia_requisito_giorni": 30,
    "preavvisi_scadenza_giorni": [30, 60, 90],
    "transitorio_revisione_giorni": 90,
    "durata_massima_avviata_mesi": 6,
    "soglia_potenziale_parziale": 0.66,
    "regola_livello_mansione": "MIN_BLOCCANTI",
    # SEGNALAZIONE (deciso al GATE 2): una competenza non più valida si segnala e non toglie l'operatività.
    # BLOCCO (alternativa): la competenza sospesa vale «I» e la mansione diventa non conforme.
    "modalita_validita": "SEGNALAZIONE",
}

REPARTI = {
    "CN5": "Fresatura 5 assi", "TOR": "Tornitura", "CMM": "Collaudo",
    "TRT": "Trattamenti e controlli", "MAN": "Manutenzione",
}

# id, nome, requisito formale (tipo, nome, validità mesi) o None, esercizio critico
COMPETENZE = [
    ("C01", "Lettura del disegno tecnico", None, False),
    ("C02", "Set-up macchina 5 assi", None, False),
    ("C03", "Programmazione a bordo macchina", None, False),
    ("C04", "Controllo dimensionale in macchina", None, False),
    ("C05", "Gestione utensili e presetting", None, False),
    ("C06", "Prevenzione FOD e pulizia tecnica", ("corso", "CRS-006 Prevenzione FOD", 24), False),
    ("C07", "Fresatura ad alta velocità", None, False),
    ("C08", "Set-up tornio CNC", None, False),
    ("C09", "Programmazione ISO tornio", None, False),
    ("C10", "Lavorazione multitasking", None, False),
    ("C11", "Programmazione e uso CMM", None, False),
    ("C12", "Interpretazione tolleranze geometriche", None, False),
    ("C13", "Compilazione rapporti di collaudo", None, False),
    ("C14", "Controllo pezzi di classe 1", None, True),
    ("C15", "Abilitazione collaudo cliente", ("qualifica", "Delega collaudo cliente", 12), False),
    ("C16", "Uso strumenti di misura da banco", ("corso", "CRS-027 Metrologia di reparto", 0), False),
    ("C17", "Conduzione linea di passivazione", None, True),
    ("C18", "Gestione sostanze chimiche", ("corso", "CRS-018 Rischio chimico", 60), False),
    ("C19", "Registrazione parametri di processo", None, False),
    ("C20", "Liquidi penetranti livello 2", ("qualifica", "PT livello 2 EN 4179", 60), True),
    ("C21", "Valutazione delle indicazioni", None, False),
    ("C22", "Diagnosi guasti meccanici", None, False),
    ("C23", "Manutenzione preventiva programmata", None, False),
    ("C24", "Lavori su impianti elettrici", ("corso", "CRS-024 PES/PAV", 60), False),
    ("C25", "Conduzione carrello elevatore", ("qualifica", "Patentino carrello", 60), False),
    ("C26", "Sbavatura e finitura manuale", None, False),
    ("C27", "Marcatura laser", None, False),
    ("C28", "Imballaggio e protezione pezzi", None, False),
    ("C29", "Conduzione del reparto", None, False),
    ("C30", "Affiancamento e formazione dei colleghi", None, False),
]

# id, nome, reparto, tipo, mansione di rischio, [(competenza, minimo, criticità B/I/U)]
MANSIONI = [
    ("M01", "DM3 – Fresatura 5 assi", "CN5", "macchina", "Operatore macchine utensili",
     [("C01", "U", "B"), ("C02", "U", "B"), ("C04", "U", "I"), ("C05", "L", "U"), ("C06", "U", "B")]),
    ("M02", "DM6 – Fresatura 5 assi grande formato", "CN5", "macchina", "Operatore macchine utensili",
     [("C01", "U", "B"), ("C02", "U", "B"), ("C03", "L", "I"), ("C04", "U", "I"), ("C05", "L", "U"), ("C06", "U", "B")]),
    ("M03", "MK1 – Fresatura ad alta velocità", "CN5", "macchina", "Operatore macchine utensili",
     [("C01", "U", "B"), ("C07", "U", "B"), ("C04", "L", "I"), ("C06", "U", "B")]),
    ("M04", "TN2 – Tornitura CNC", "TOR", "macchina", "Operatore macchine utensili",
     [("C01", "U", "B"), ("C08", "U", "B"), ("C09", "L", "I"), ("C05", "L", "U"), ("C06", "U", "B")]),
    ("M05", "TN5 – Tornio multitasking", "TOR", "macchina", "Operatore macchine utensili",
     [("C01", "U", "B"), ("C08", "U", "B"), ("C10", "U", "I"), ("C06", "U", "B")]),
    ("M06", "CMM1 – Collaudo a coordinate", "CMM", "macchina", "Addetto collaudo",
     [("C01", "U", "B"), ("C11", "U", "B"), ("C12", "U", "B"), ("C13", "L", "I")]),
    ("M07", "Controllo pezzi di classe 1", "CMM", "processo", "Addetto collaudo",
     [("C11", "U", "B"), ("C14", "U", "B"), ("C15", "U", "B")]),
    ("M08", "Collaudo da banco", "CMM", "processo", "Addetto collaudo",
     [("C01", "L", "I"), ("C16", "U", "B"), ("C13", "L", "U")]),
    ("M09", "Passivazione", "TRT", "processo", "Addetto trattamenti",
     [("C17", "U", "B"), ("C18", "U", "B"), ("C19", "L", "I")]),
    ("M10", "Controllo con liquidi penetranti", "TRT", "processo", "Addetto trattamenti",
     [("C20", "U", "B"), ("C21", "U", "B"), ("C19", "L", "I")]),
    ("M11", "Manutenzione meccanica", "MAN", "processo", "Manutentore",
     [("C22", "U", "B"), ("C23", "L", "I"), ("C24", "U", "B")]),
    ("M12", "Sbavatura e finitura", "CN5", "processo", "Operatore macchine utensili",
     [("C26", "U", "B"), ("C01", "L", "I"), ("C06", "U", "B")]),
    ("M13", "Marcatura e imballaggio", "TRT", "processo", "Addetto trattamenti",
     [("C27", "U", "I"), ("C28", "L", "U"), ("C06", "U", "B")]),
    ("M14", "Movimentazione con carrello", "MAN", "processo", "Carrellista",
     [("C25", "U", "B")]),
]

NOMI = [
    ("Marco", "Rinaldi", "CN5"), ("Giulia", "Ferrante", "CN5"), ("Aldo", "Bianchetti", "CN5"),
    ("Sara", "Colombini", "CMM"), ("Piero", "Lombardini", "CN5"), ("Elena", "Marchesin", "CN5"),
    ("Davide", "Fontanari", "CN5"), ("Luca", "Bertolazzi", "CN5"), ("Chiara", "Montanaro", "CN5"),
    ("Stefano", "Guidotti", "CN5"), ("Paolo", "Vercellin", "TOR"), ("Anna", "Castellani", "TOR"),
    ("Roberto", "Zanardelli", "TOR"), ("Matteo", "Silvestrin", "TOR"), ("Federica", "Pagnotta", "TOR"),
    ("Giorgio", "Tessarolo", "TOR"), ("Laura", "Benedettin", "CMM"), ("Simone", "Gavazzeni", "CMM"),
    ("Irene", "Caprioli", "CMM"), ("Tommaso", "Ruggerini", "CMM"), ("Nicola", "Salvaterra", "TRT"),
    ("Silvia", "Morandini", "TRT"), ("Andrea", "Pellizzon", "TRT"), ("Marta", "Giacomelli", "TRT"),
    ("Enrico", "Baldassari", "TRT"), ("Fabio", "Cortinovis", "MAN"), ("Claudio", "Spinazzola", "MAN"),
    ("Valentina", "Orsenigo", "MAN"), ("Giovanni", "Trevisanato", "MAN"), ("Alessia", "Brambillasca", "CN5"),
    ("Riccardo", "Fumagallini", "TOR"), ("Monica", "Scarpellin", "CMM"),
]
CAPI = {"CN5": "P03", "TOR": "P11", "CMM": "P17", "TRT": "P21", "MAN": "P26"}


def mesi_fa(n: float) -> str:
    return (OGGI - timedelta(days=round(n * 30.44))).isoformat()


def fra_giorni(n: int) -> str:
    return (OGGI + timedelta(days=n)).isoformat()


def costruisci() -> dict:
    rnd = random.Random(2027)
    comp = {c[0]: {"id": c[0], "nome": c[1],
                   "requisito": ({"tipo": c[2][0], "nome": c[2][1], "validita_mesi": c[2][2]} if c[2] else None),
                   "esercizio_critico": c[3]} for c in COMPETENZE}
    mans = {m[0]: {"id": m[0], "nome": m[1], "reparto": m[2], "tipo": m[3], "mansione_rischio": m[4], "versione": 1,
                   "requisiti": [{"competenza": c, "minimo": lv, "criticita": k} for c, lv, k in m[5]]}
            for m in MANSIONI}
    per_reparto: dict[str, list[str]] = {}
    for m in mans.values():
        per_reparto.setdefault(m["reparto"], []).append(m["id"])

    persone = []
    for i, (nome, cognome, rep) in enumerate(NOMI, start=1):
        pid = f"P{i:02d}"
        capo = CAPI[rep] == pid
        candidati = per_reparto[rep]
        n = 3 if capo else rnd.choice([1, 2, 2, 3])
        scelte = candidati[:] if len(candidati) <= n else sorted(rnd.sample(candidati, n))
        anzianita = rnd.choice([1, 2, 4, 6, 9, 14, 20]) if not capo else 18
        base = 4 if capo else (3 if anzianita >= 4 else 2 if anzianita >= 2 else 1)
        livelli, mansioni = {}, []
        for mid in scelte:
            avviata = base == 1
            mansioni.append({"mansione": mid, "stato": "AVVIATA" if avviata else "EFFETTIVA",
                             "dal": mesi_fa(2 if avviata else rnd.choice([8, 14, 30, 60])),
                             "ram": f"RAM-2027-{rnd.randint(1, 40):04d}" if avviata else "impianto"})
            for r in mans[mid]["requisiti"]:
                c = r["competenza"]
                if c in livelli:
                    continue
                delta = rnd.choice([0, 0, 0, 0, 0, 0, 0, 1, 1, -1]) if base > 1 else rnd.choice([0, 0, 1])
                lv = max(1, min(4, base + delta))
                req = comp[c]["requisito"]
                scad = None
                if req:
                    scad = fra_giorni(rnd.choice([-45, -12, 20, 20, 55, 55, 85, 85] + [200] * 6 + [400] * 9 + [700] * 9)) if req["validita_mesi"] else None
                livelli[c] = {
                    "livello": DA_ORD[lv],
                    "valutato_il": mesi_fa(rnd.choice([1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 5, 7])),
                    "valutato_da": CAPI[rep],
                    "modalita": "P" if base > 1 else rnd.choice(["A", "C"]),
                    "sf": "SF-2027-0001" if base > 1 else f"SF-2027-{rnd.randint(2, 60):04d}",
                    "requisito_scadenza": scad,
                    "requisito_presente": bool(req) and (rnd.random() > 0.03),
                    "ultimo_esercizio": mesi_fa(rnd.choice([0.5, 1, 1, 2, 2, 3, 3, 6, 6, 10, 13])) if comp[c]["esercizio_critico"] else None,
                }
        if capo:
            for c in ("C29", "C30"):
                livelli[c] = {"livello": "O", "valutato_il": mesi_fa(2), "valutato_da": "RDD", "modalita": "P",
                              "sf": "SF-2027-0001", "requisito_scadenza": None, "requisito_presente": False,
                              "ultimo_esercizio": None}
        persone.append({"id": pid, "nome": nome, "cognome": cognome, "reparto": rep,
                        "ruolo": "Caporeparto" if capo else {"CN5": "Operatore macchina utensile",
                                                             "TOR": "Operatore macchina utensile",
                                                             "CMM": "Collaudatore", "TRT": "Operatore trattamenti",
                                                             "MAN": "Manutentore"}[rep],
                        "assunto_il": mesi_fa(anzianita * 12), "mansioni": mansioni, "livelli": livelli,
                        "deroghe": []})

    p = {x["id"]: x for x in persone}

    def lv(livello, mesi=2, modalita="P", sf="SF-2027-0001", scad=None, presente=False, esercizio=None, da="P03"):
        return {"livello": livello, "valutato_il": mesi_fa(mesi), "valutato_da": da, "modalita": modalita, "sf": sf,
                "requisito_scadenza": scad, "requisito_presente": presente, "ultimo_esercizio": esercizio}

    # ── Quattro persone tipo, fissate a mano (casi d'esempio del documento) ──
    # P01 Marco Rinaldi: effettivo su DM3; ha maturato parte delle competenze di DM6.
    p["P01"].update(assunto_il="2019-09-02", mansioni=[{"mansione": "M01", "stato": "EFFETTIVA", "dal": mesi_fa(30), "ram": "impianto"}],
                    livelli={"C01": lv("U"), "C02": lv("U"), "C04": lv("U"), "C05": lv("L"),
                             "C06": lv("U", scad=fra_giorni(400), presente=True)})
    # P02 Giulia Ferrante: assunta a gennaio 2027, DM3 avviata.
    p["P02"].update(assunto_il="2027-01-11",
                    mansioni=[{"mansione": "M01", "stato": "AVVIATA", "dal": "2027-01-11", "ram": "RAM-2027-0001"}],
                    livelli={"C01": lv("L", 2, "P", "SF-2027-0002"), "C02": lv("L", 0.2, "A", "SF-2027-0019"),
                             "C04": lv("I", 2, "P", "SF-2027-0002"), "C05": lv("I", 2, "P", "SF-2027-0002"),
                             "C06": lv("U", 1, "C", "SF-2027-0011", scad=fra_giorni(700), presente=True)})
    # P03 Aldo Bianchetti: caporeparto, esperto su DM6; il corso FOD scade ad agosto 2027.
    p["P03"].update(assunto_il="2009-03-16", mansioni=[{"mansione": "M02", "stato": "EFFETTIVA", "dal": mesi_fa(60), "ram": "impianto"},
                              {"mansione": "M01", "stato": "EFFETTIVA", "dal": mesi_fa(60), "ram": "impianto"}],
                    livelli={"C01": lv("O", da="RDD"), "C02": lv("O", da="RDD"), "C03": lv("O", da="RDD"),
                             "C04": lv("O", da="RDD"), "C05": lv("U", da="RDD"),
                             "C06": lv("O", da="RDD", scad="2027-08-20", presente=True),
                             "C29": lv("O", da="RDD"), "C30": lv("O", da="RDD")})
    # P04 Sara Colombini: classe 1, ultima esecuzione a gennaio 2027.
    p["P04"].update(assunto_il="2018-05-07", mansioni=[{"mansione": "M06", "stato": "EFFETTIVA", "dal": mesi_fa(40), "ram": "impianto"},
                              {"mansione": "M07", "stato": "EFFETTIVA", "dal": mesi_fa(24), "ram": "impianto"}],
                    livelli={"C01": lv("U", da="P17"), "C11": lv("U", da="P17"), "C12": lv("U", da="P17"),
                             "C13": lv("U", da="P17"), "C14": lv("U", da="P17", esercizio="2027-01-20"),
                             "C15": lv("U", da="P17", scad=fra_giorni(200), presente=True)})
    # P05 Piero Lombardini: corso FOD scaduto da 45 giorni, deroga di 30 giorni approvata da RDD.
    p["P05"].update(assunto_il="2021-10-04", mansioni=[{"mansione": "M02", "stato": "EFFETTIVA", "dal": mesi_fa(14), "ram": "impianto"}],
                    livelli={"C01": lv("U"), "C02": lv("U"), "C03": lv("L"), "C04": lv("U"), "C05": lv("L"),
                             "C06": lv("U", scad=fra_giorni(-45), presente=True)},
                    deroghe=[{"competenza": "C06", "motivo": "Corso FOD prenotato per il 02/04/2027",
                              "approvata_da": "RDD", "dal": fra_giorni(-10), "fino_al": fra_giorni(20)}])
    return {"oggi": OGGI.isoformat(), "parametri": PARAMETRI, "reparti": REPARTI, "capi": CAPI,
            "competenze": list(comp.values()), "mansioni": list(mans.values()), "persone": persone}


# ══════════════════════════════════════════════════════════════════════════
# Motore di riferimento (modello ibrido raccomandato)
# ══════════════════════════════════════════════════════════════════════════

def _d(s):
    return date.fromisoformat(s) if s else None


def validita(dati, persona, comp, oggi=OGGI):
    """Stato di validità di una competenza posseduta: (stato, motivo, scadenza)."""
    par = dati["parametri"]
    c = next(x for x in dati["competenze"] if x["id"] == comp)
    l = persona["livelli"].get(comp)
    if not l:
        return ("ASSENTE", "mai valutata", None)
    deroga = next((d for d in persona.get("deroghe", []) if d["competenza"] == comp
                   and _d(d["dal"]) <= oggi <= _d(d["fino_al"])), None)
    req = c["requisito"]
    if req:
        if not l["requisito_presente"]:
            return ("SOSPESA", f"manca {req['nome']}", None)
        scad = _d(l["requisito_scadenza"])
        if scad:
            giorni = (scad - oggi).days
            if giorni < 0:
                if deroga:
                    return ("IN_DEROGA", f"{req['nome']} scaduto, deroga fino al {_d(deroga['fino_al']):%d/%m/%Y}", scad)
                if -giorni <= par["grazia_requisito_giorni"]:
                    return ("DA_CONFERMARE", f"{req['nome']} scaduto da {-giorni} giorni (periodo di grazia)", scad)
                return ("SOSPESA", f"{req['nome']} scaduto da {-giorni} giorni", scad)
    if c["esercizio_critico"] and l["ultimo_esercizio"]:
        mesi = (oggi - _d(l["ultimo_esercizio"])).days / 30.44
        if mesi > par["finestra_esercizio_mesi"]:
            return ("SOSPESA", f"nessuna esecuzione da {mesi:.0f} mesi", None)
        if mesi >= par["preavviso_esercizio_mesi"]:
            return ("DA_CONFERMARE", f"nessuna esecuzione da {mesi:.0f} mesi", None)
    mesi_val = (oggi - _d(l["valutato_il"])).days / 30.44
    if mesi_val > par["conferma_periodica_mesi"]:
        return ("DA_CONFERMARE", f"conferma periodica scaduta ({mesi_val:.0f} mesi)", None)
    scad = _d(l["requisito_scadenza"]) if req else None
    return ("VALIDA", "", scad)


def livello_efficace(dati, persona, comp, oggi=OGGI):
    st, _, _ = validita(dati, persona, comp, oggi)
    if st == "ASSENTE":
        return ""
    if st == "SOSPESA" and dati["parametri"].get("modalita_validita") == "BLOCCO":
        return "I"
    return persona["livelli"][comp]["livello"]


def requisiti_effettivi(dati, persona, mansioni_ids=None):
    """Unione dei requisiti di tutte le mansioni: per competenza vince il livello più alto e la criticità più alta."""
    peso = {"U": 1, "I": 2, "B": 3}
    out = {}
    ids = mansioni_ids if mansioni_ids is not None else [a["mansione"] for a in persona["mansioni"]]
    mm = {m["id"]: m for m in dati["mansioni"]}
    for mid in ids:
        for r in mm[mid]["requisiti"]:
            e = out.setdefault(r["competenza"], {"competenza": r["competenza"], "minimo": r["minimo"],
                                                 "criticita": r["criticita"], "fonti": []})
            if ORD[r["minimo"]] > ORD[e["minimo"]]:
                e["minimo"] = r["minimo"]
            if peso[r["criticita"]] > peso[e["criticita"]]:
                e["criticita"] = r["criticita"]
            e["fonti"].append({"mansione": mid, "nome": mm[mid]["nome"], "minimo": r["minimo"],
                               "criticita": r["criticita"]})
    return out


def valuta_mansione(dati, persona, mansione, stato_assegnazione="EFFETTIVA", oggi=OGGI):
    """Conformità della persona rispetto a UNA mansione."""
    righe, bloccanti_gap, importanti_gap, utili_gap, sospese_bloccanti, riserve = [], 0, 0, 0, 0, 0
    blocco = dati["parametri"].get("modalita_validita") == "BLOCCO"
    segnalazioni = 0
    ordinali, ord_bloccanti = [], []
    for r in mansione["requisiti"]:
        st, motivo, scad = validita(dati, persona, r["competenza"], oggi)
        eff = livello_efficace(dati, persona, r["competenza"], oggi)
        gap = max(0, ORD[r["minimo"]] - ORD[eff])
        ordinali.append(ORD[eff])
        if r["criticita"] == "B":
            ord_bloccanti.append(ORD[eff])
        if gap:
            if r["criticita"] == "B":
                bloccanti_gap += 1
                if st == "SOSPESA":
                    sospese_bloccanti += 1
            elif r["criticita"] == "I":
                importanti_gap += 1
            else:
                utili_gap += 1
        if st in ("DA_CONFERMARE", "IN_DEROGA"):
            riserve += 1
        if st == "SOSPESA":
            segnalazioni += 1
            if not blocco:
                riserve += 1
        valutato = persona["livelli"].get(r["competenza"], {}).get("livello", "")
        righe.append({**r, "valutato": valutato, "efficace": eff, "validita": st, "motivo": motivo,
                      "scadenza": scad.isoformat() if scad else None, "gap": gap})
    # Livello sulla mansione: il più basso fra le competenze bloccanti (se non ce ne sono, fra tutte).
    livello_m = DA_ORD[min(ord_bloccanti) if ord_bloccanti else (min(ordinali) if ordinali else 0)]
    if sospese_bloccanti or (bloccanti_gap and stato_assegnazione == "EFFETTIVA"):
        stato = "NON_CONFORME"
    elif bloccanti_gap or importanti_gap:
        stato = "SOTTO_SUPERVISIONE"
    elif utili_gap or riserve:
        stato = "CON_RISERVA"
    else:
        stato = "CONFORME"
    opera = stato in ("CONFORME", "CON_RISERVA")
    soglia = ORD[dati["parametri"]["soglia_operativa"]]
    return {"stato": stato, "livello_m": livello_m, "righe": righe,
            "opera_da_solo": opera, "puo_firmare": opera and ORD[livello_m] >= soglia,
            "puo_formare": stato == "CONFORME" and livello_m == "O",
            "gap": bloccanti_gap + importanti_gap + utili_gap, "segnalazioni": segnalazioni}


def potenziali(dati, persona, oggi=OGGI):
    """Mansioni non assegnate i cui requisiti risultano soddisfatti (o in buona parte)."""
    assegnate = {a["mansione"] for a in persona["mansioni"]}
    out = []
    for m in dati["mansioni"]:
        if m["id"] in assegnate:
            continue
        ok = sum(1 for r in m["requisiti"]
                 if ORD[livello_efficace(dati, persona, r["competenza"], oggi)] >= ORD[r["minimo"]])
        tot = len(m["requisiti"])
        mancano_bi = sum(1 for r in m["requisiti"] if r["criticita"] in ("B", "I")
                         and ORD[livello_efficace(dati, persona, r["competenza"], oggi)] < ORD[r["minimo"]])
        if mancano_bi == 0:
            out.append({"mansione": m["id"], "nome": m["nome"], "esito": "SODDISFATTA", "ok": ok, "tot": tot})
        elif ok / tot >= dati["parametri"]["soglia_potenziale_parziale"] and ok > 0:
            out.append({"mansione": m["id"], "nome": m["nome"], "esito": "PARZIALE", "ok": ok, "tot": tot})
    return out


def quadro(dati, oggi=OGGI):
    mm = {m["id"]: m for m in dati["mansioni"]}
    stati = {"CONFORME": 0, "CON_RISERVA": 0, "SOTTO_SUPERVISIONE": 0, "NON_CONFORME": 0}
    per_reparto = {r: {"assegnazioni": 0, "conformi": 0} for r in dati["reparti"]}
    scad = {30: 0, 60: 0, 90: 0, "scadute": 0}
    gap_tot = da_valutare = sospese = pot_s = pot_p = segn = 0
    persone_non_conformi = set()
    for p in dati["persone"]:
        for a in p["mansioni"]:
            v = valuta_mansione(dati, p, mm[a["mansione"]], a["stato"], oggi)
            stati[v["stato"]] += 1
            gap_tot += v["gap"]
            segn += v["segnalazioni"] > 0
            rep = mm[a["mansione"]]["reparto"]
            per_reparto[rep]["assegnazioni"] += 1
            per_reparto[rep]["conformi"] += v["stato"] in ("CONFORME", "CON_RISERVA")
            if v["stato"] == "NON_CONFORME":
                persone_non_conformi.add(p["id"])
        for c, l in p["livelli"].items():
            st, _, s = validita(dati, p, c, oggi)
            if st == "SOSPESA":
                sospese += 1
            if st == "DA_CONFERMARE":
                da_valutare += 1
            s = _d(l["requisito_scadenza"])
            if s and l["requisito_presente"]:
                g = (s - oggi).days
                if g < 0:
                    scad["scadute"] += 1
                elif g <= 30:
                    scad[30] += 1
                elif g <= 60:
                    scad[60] += 1
                elif g <= 90:
                    scad[90] += 1
        for x in potenziali(dati, p, oggi):
            pot_s += x["esito"] == "SODDISFATTA"
            pot_p += x["esito"] == "PARZIALE"
    return {"persone": len(dati["persone"]), "mansioni": len(dati["mansioni"]), "competenze": len(dati["competenze"]),
            "assegnazioni": sum(stati.values()), "stati": stati, "gap": gap_tot,
            "assegnazioni_con_segnalazione": segn, "competenze_sospese": sospese, "competenze_da_confermare": da_valutare,
            "persone_non_conformi": len(persone_non_conformi), "scadenze": scad,
            "potenziali_soddisfatte": pot_s, "potenziali_parziali": pot_p,
            "per_reparto": per_reparto}


def impatto_revisione(dati, mansione_id, competenza, nuovo_minimo, nuova_criticita=None):
    """Anteprima: chi cambia stato se il requisito della mansione viene modificato."""
    import copy
    dopo = copy.deepcopy(dati)
    m = next(x for x in dopo["mansioni"] if x["id"] == mansione_id)
    r = next((x for x in m["requisiti"] if x["competenza"] == competenza), None)
    if r is None:
        m["requisiti"].append({"competenza": competenza, "minimo": nuovo_minimo, "criticita": nuova_criticita or "I"})
    else:
        r["minimo"] = nuovo_minimo
        if nuova_criticita:
            r["criticita"] = nuova_criticita
    prima_m = next(x for x in dati["mansioni"] if x["id"] == mansione_id)
    cambi = []
    titolari = 0
    for p, q in zip(dati["persone"], dopo["persone"]):
        a = next((x for x in p["mansioni"] if x["mansione"] == mansione_id), None)
        if not a:
            continue
        titolari += 1
        s1 = valuta_mansione(dati, p, prima_m, a["stato"])["stato"]
        s2 = valuta_mansione(dopo, q, m, a["stato"])["stato"]
        if s1 != s2:
            cambi.append({"persona": p["id"], "nome": f"{p['nome']} {p['cognome']}", "prima": s1, "dopo": s2})
    return {"titolari": titolari, "cambi": cambi}


def simula_cambio(dati, persona_id, mansione_id):
    """What-if: aggiungere una mansione a una persona. Requisiti nuovi, già coperti, gap."""
    p = next(x for x in dati["persone"] if x["id"] == persona_id)
    m = next(x for x in dati["mansioni"] if x["id"] == mansione_id)
    v = valuta_mansione(dati, p, m, "AVVIATA")
    coperti = [r for r in v["righe"] if r["gap"] == 0]
    mancanti = [r for r in v["righe"] if r["gap"] > 0]
    return {"persona": persona_id, "mansione": mansione_id, "requisiti": len(v["righe"]),
            "coperti": len(coperti), "mancanti": [(r["competenza"], r["efficace"] or "—", r["minimo"], r["criticita"])
                                                   for r in mancanti],
            "stato_se_avviata": v["stato"], "serve_sf": bool(mancanti)}


if __name__ == "__main__":
    dati = costruisci()
    (RADICE / "prototipo" / "dati").mkdir(parents=True, exist_ok=True)
    (RADICE / "prototipo" / "dati" / "dataset.json").write_text(
        json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    mm = {m["id"]: m for m in dati["mansioni"]}
    pp = {p["id"]: p for p in dati["persone"]}
    q = quadro(dati)
    import copy
    dati_blocco = copy.deepcopy(dati)
    dati_blocco["parametri"]["modalita_validita"] = "BLOCCO"
    qb = quadro(dati_blocco)
    print("QUADRO_BLOCCO", json.dumps({k: qb[k] for k in ("stati", "gap", "persone_non_conformi", "potenziali_soddisfatte", "potenziali_parziali")}, ensure_ascii=False))
    ris = {"quadro": q, "quadro_blocco": qb, "casi": {}}
    print("QUADRO", json.dumps(q, ensure_ascii=False))
    for pid in ("P01", "P02", "P03", "P04", "P05"):
        p = pp[pid]
        riga = {"mansioni": {a["mansione"]: {k: v for k, v in valuta_mansione(dati, p, mm[a["mansione"]], a["stato"]).items()
                                             if k != "righe"} for a in p["mansioni"]},
                "potenziali": potenziali(dati, p)}
        ris["casi"][pid] = riga
        print(pid, p["nome"], p["cognome"], json.dumps(riga, ensure_ascii=False))
    for pid, mid in (("P01", "M02"), ("P02", "M02"), ("P04", "M08")):
        s = simula_cambio(dati, pid, mid)
        ris["casi"][f"cambio_{pid}_{mid}"] = s
        print("CAMBIO", json.dumps(s, ensure_ascii=False))
    print("TITOLARI", {m["id"]: sum(1 for p in dati["persone"] if any(a["mansione"] == m["id"] for a in p["mansioni"])) for m in dati["mansioni"]})
    for args in (("M02", "C03", "U", None), ("M02", "C03", "U", "B"), ("M01", "C04", "O", None), ("M01", "C05", "U", "I"), ("M04", "C09", "U", None), ("M04", "C09", "U", "B"), ("M06", "C13", "U", None), ("M06", "C13", "U", "B"), ("M01", "C03", "L", "I")):
        imp = impatto_revisione(dati, *args)
        ris["casi"]["impatto_" + "_".join(str(a) for a in args)] = imp
        print("IMPATTO", args, imp["titolari"], "titolari,", len(imp["cambi"]), "cambiano:",
              [(c["persona"], c["prima"], c["dopo"]) for c in imp["cambi"]])
    # Conflitto di livelli: C01 richiesto a livelli diversi da mansioni diverse
    for pid in ("P03", "P04"):
        re = requisiti_effettivi(dati, pp[pid])
        print("REQ", pid, {c: (e["minimo"], e["criticita"], len(e["fonti"])) for c, e in re.items()})
    # P05: deroga e dettaglio
    v = valuta_mansione(dati, pp["P05"], mm["M02"])
    print("P05 righe", [(r["competenza"], r["valutato"], r["efficace"], r["validita"], r["motivo"]) for r in v["righe"]])
    v = valuta_mansione(dati, pp["P02"], mm["M01"], "AVVIATA")
    print("P02 righe", [(r["competenza"], r["valutato"], r["minimo"], r["criticita"], r["gap"]) for r in v["righe"]])
    (RADICE / "build" / "risultati.json").write_text(json.dumps(ris, ensure_ascii=False, indent=1), encoding="utf-8")
