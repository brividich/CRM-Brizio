"""Dalla matrice della Qualità al file che il portale sa già importare.

Legge ``bozza_qualita.json`` (estratto da ``estrai_bozza_qualita.py``) e scrive un
Excel con il foglio «Competenze» nel formato di Mansionario → Struttura → Importa
(``anagrafica/services/struttura_excel.py``): una riga per ogni «Sì» della matrice.

    python costruisci_carico_matrice.py [bozza_qualita.json] [uscita.xlsx]

Regole:
- livello minimo U per tutte (legenda della Qualità), non bloccante;
- l'ordine è quello delle colonne del foglio della Qualità;
- la mansione si abbina per nome: il portale ha già la struttura (v8);
- «Responsabilità del reparto» diventa la mansione di responsabilità del portale
  (``RESPONSABILITA``); dove il portale non ne ha una, la riga resta fuori;
- una mansione rinominata fra v8 e v9 si abbina col nome di oggi nel portale
  (``RINOMINATE``): è una proposta, da confermare con la Qualità.

Nessun nome di persona: solo mansioni, reparti e competenze.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

QUI = Path(__file__).resolve().parent
RADICE = QUI.parent

COLONNE = ["Chiave mansione", "Mansione", "Competenza", "Livello minimo", "Bloccante", "Corso", "Qualifica",
           "Processo MOD.128", "Ordine", "Attiva"]

# Reparto del file della Qualità → mansione di responsabilità già presente nel portale.
RESPONSABILITA = {
    "UFFICIO ACQUISTI": "Responsabilità dell'area ACQUISTI",
    "UFFICIO COMMERCIALE": "Responsabilità dell'area COMMERCIALE",
    "UFFICIO SISTEMA QUALITA": "Responsabilità dell'area QUALITA",
}
# Reparti del file senza una mansione di responsabilità nel portale: l'area non ha un ruolo responsabile.
SENZA_RESPONSABILE = {"UFFICIO TECNICO (ING)", "UFFICIO TECNICO (CAM)", "UFFICIO FAI"}

# Nome nel file v9 → nome di oggi nel portale (v8). Proposta da confermare.
RINOMINATE = {
    "Gestione e mantenimento del Sistema di Gestione Integrato":
        "Governance e mantenimento del Sistema di Gestione Integrato",
}


def norm(t) -> str:
    return " ".join(str(t or "").split()).casefold()


def pulito(t) -> str:
    return " ".join(str(t or "").split())


def righe(dati: dict):
    """(righe del foglio Competenze, righe lasciate fuori, riepilogo per foglio)."""
    dentro, fuori, riepilogo = [], [], []
    for foglio in dati["fogli"]:
        ordine = {norm(c["nome"]): i for i, c in enumerate(foglio["competenze"], 1)}
        n_mans = n_si = 0
        for m in foglio["mansioni"]:
            celle = m["celle"]
            if not celle:
                continue
            nome, reparto = pulito(m["mansione"]), pulito(m["reparto"])
            si = [pulito(k) for k, v in celle.items() if norm(v) in ("sì", "si")]
            dubbi = [pulito(k) for k, v in celle.items() if norm(v) == "?"]
            for d in dubbi:
                fuori.append([foglio["foglio"], reparto, nome, d, "cella con «?»: punto aperto della Qualità"])
            if norm(nome).startswith("responsabilit"):
                if reparto in SENZA_RESPONSABILE:
                    fuori.append([foglio["foglio"], reparto, nome, f"{len(si)} competenze",
                                  "nel portale l'area non ha un ruolo responsabile: la mansione non esiste"])
                    continue
                portale = RESPONSABILITA.get(reparto)
                if portale is None:
                    fuori.append([foglio["foglio"], reparto, nome, f"{len(si)} competenze",
                                  "mansione di responsabilità non abbinata"])
                    continue
            else:
                portale = RINOMINATE.get(nome, nome)
            n_mans += 1
            n_si += len(si)
            for c in si:
                dentro.append(["", portale, c[:150], "U", "NO", "", "", "", ordine.get(norm(c), 0), "SI"])
        if n_mans:
            riepilogo.append([foglio["foglio"], n_mans, n_si])
    return dentro, fuori, riepilogo


def scrivi(dentro, fuori, riepilogo, uscita: Path, fonte: str):
    wb = Workbook()
    ws = wb.active
    ws.title = "Leggimi"
    testo = [
        "Carico delle competenze richieste da ogni mansione (matrice della Qualità).",
        fonte,
        "",
        "Come si usa: Anagrafica → Mansionario → Struttura → Importa. Prima il portale mostra la prova riga per riga;",
        "solo la conferma scrive. Non cancella niente e si può ricaricare: le righe già presenti restano «invariate».",
        "",
        "Il portale legge solo il foglio «Competenze». «Non caricate» e «Riepilogo» sono per chi controlla.",
        "Livello minimo U per tutte, non bloccante: è la regola della legenda della Qualità.",
    ]
    for i, t in enumerate(testo, 1):
        c = ws.cell(row=i, column=1, value=t)
        if i == 1:
            c.font = Font(bold=True)
    ws.column_dimensions["A"].width = 120

    testata = PatternFill("solid", fgColor="1E3A5F")

    def foglio(nome, colonne, dati):
        w = wb.create_sheet(nome)
        for j, col in enumerate(colonne, 1):
            c = w.cell(row=1, column=j, value=col)
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = testata
            c.alignment = Alignment(vertical="center")
        for i, riga in enumerate(dati, 2):
            for j, v in enumerate(riga, 1):
                w.cell(row=i, column=j, value=v)
        for j, col in enumerate(colonne, 1):
            lungh = max([len(str(col))] + [len(str(r[j - 1] or "")) for r in dati[:500]])
            w.column_dimensions[get_column_letter(j)].width = min(max(lungh + 2, 10), 70)
        w.freeze_panes = "A2"
        w.auto_filter.ref = f"A1:{get_column_letter(len(colonne))}{max(len(dati) + 1, 2)}"

    foglio("Competenze", COLONNE, dentro)
    foglio("Non caricate", ["Foglio della Qualità", "Reparto", "Mansione", "Che cosa", "Perché"], fuori)
    foglio("Riepilogo", ["Foglio della Qualità", "Mansioni", "Competenze richieste"], riepilogo)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    wb.save(uscita)


def main():
    sorgente = Path(sys.argv[1]) if len(sys.argv) > 1 else QUI / "bozza_qualita.json"
    uscita = Path(sys.argv[2]) if len(sys.argv) > 2 else RADICE / "carico" / "Carico_competenze_mansioni.xlsx"
    dati = json.loads(sorgente.read_text(encoding="utf-8"))
    dentro, fuori, riepilogo = righe(dati)
    scrivi(dentro, fuori, riepilogo, uscita, pulito(dati.get("fonte", "")))
    mansioni = {r[1] for r in dentro}
    competenze = {norm(r[2]) for r in dentro}
    print(f"righe {len(dentro)} | mansioni {len(mansioni)} | competenze distinte {len(competenze)} | fuori {len(fuori)}")
    for r in riepilogo:
        print("  ", r)
    for r in fuori:
        print("   fuori:", r)
    print("legenda:", dati.get("legenda", ""))
    governance = [e["mansione"] for e in dati["elenco"] if "sistema di gestione integrato" in norm(e["mansione"])]
    print("mansioni «Sistema di Gestione Integrato» nell'elenco v9:", governance)
    print("scritto:", uscita)


if __name__ == "__main__":
    main()
