"""Estrae la bozza della Qualità (ricevuta il 22/11/2026) in build/bozza_qualita.json.

I due file di partenza restano fuori dal repository. Si riportano solo struttura e valori «Sì / No / ?»:
niente colonne di commento, niente storico delle versioni, nessun nominativo.

    python build/estrai_bozza_qualita.py <matrice per reparto .xlsx> <elenco mansioni v9 .xlsx>
"""
import json
import sys
from pathlib import Path

from openpyxl import load_workbook

QUI = Path(__file__).resolve().parent
MATRICE, ELENCO = sys.argv[1], sys.argv[2]


def t(v):
    return "" if v is None else " ".join(str(v).split())


fogli = []
for ws in load_workbook(MATRICE, data_only=True).worksheets:
    if not ws.title.startswith("MX_"):
        continue
    righe = [[t(c.value) for c in r] for r in ws.iter_rows()]
    ih = next(i for i, r in enumerate(righe) if r and r[0] == "RUOLO")
    testa = righe[ih]
    ha_abil = "ABIL. (MEGA)" in testa
    c0 = testa.index("MANSIONE") + (2 if ha_abil else 1)
    cols = [(j, n) for j, n in enumerate(testa) if j >= c0 and n and not n.startswith("N. competenze")]
    tipo = origine = None
    mansioni = []
    for r in righe[ih + 1:]:
        if r and r[0] == "TIPO":
            tipo = r
        elif r and r[0] == "ORIGINE":
            origine = r
        elif r and r[0] and r[2]:
            mansioni.append({
                "ruolo": r[0], "reparto": r[1], "mansione": r[2], "abilitazione": bool(ha_abil and r[3]),
                "celle": {n: r[j] for j, n in cols if j < len(r) and r[j]},
            })
    fogli.append({
        "foglio": ws.title,
        "competenze": [{"nome": n, "tipo": tipo[j] if tipo else "", "origine": origine[j] if origine else ""}
                       for j, n in cols],
        "mansioni": mansioni,
    })

ws = load_workbook(ELENCO, data_only=True)["MEGA MANSIONI"]
testa = [t(c.value) for c in ws[1]]
CAMPI = {"PROCESSO": "processo", "OWNER PROCESSO": "owner", "RUOLO": "ruolo", "REPARTO": "reparto",
         "CENTRO DI COSTO": "centro_di_costo", "MANSIONE": "mansione", "RESPONSABILE": "responsabile",
         "Abilitazione": "abilitazione"}
elenco = []
for r in ws.iter_rows(min_row=2):
    d = {CAMPI[testa[j]]: t(c.value) for j, c in enumerate(r) if j < len(testa) and testa[j] in CAMPI}
    if d.get("mansione"):
        d["responsabile"] = bool(d["responsabile"])
        d["abilitazione"] = bool(d["abilitazione"])
        elenco.append(d)

uscita = QUI / "bozza_qualita.json"
uscita.write_text(json.dumps({
    "fonte": "Bozza della Qualità ricevuta il 22/11/2026: matrice delle competenze per reparto ed elenco delle "
             "mansioni v9. Solo struttura e valori, nessun nominativo.",
    "legenda": "Sì = richiesta per la mansione; No = non richiesta; ? = punto aperto. Livello richiesto proposto: U.",
    "elenco": elenco, "fogli": fogli,
}, ensure_ascii=False, indent=1), encoding="utf-8")
celle = sum(len(f["mansioni"]) * len(f["competenze"]) for f in fogli)
piene = sum(len(m["celle"]) for f in fogli for m in f["mansioni"])
print(uscita.name, "· mansioni in elenco", len(elenco), "· fogli", len(fogli), "· celle", celle, "· compilate", piene)
