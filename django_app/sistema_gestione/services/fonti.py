"""Estrazione conservativa Turtle: proposte inattive e fonti verificabili."""
import hashlib
import re
from pathlib import Path
import fitz


def estrai_turtle(path):
    path = Path(path)
    match = re.search(r"\b(TD[A-Z])\b", path.stem, re.I)
    if not match:
        raise ValueError("Codice Turtle non riconosciuto nel nome file.")
    data = path.read_bytes()
    with fitz.open(stream=data, filetype="pdf") as pdf:
        testo = "\n".join(p.get_text() for p in pdf)
    if len(testo.strip()) < 100:
        raise ValueError("Testo insufficiente: serve verifica visiva/OCR.")
    labels = {"CON COSA": "risorse", "INPUT": "input", "COME": "procedure", "CON CHI": "enti", "OUTPUT": "output", "PERFORMANCE INDICATOR": "indicatori"}
    righe = [r.strip() for r in testo.splitlines() if r.strip() and r.strip() not in ["-", "\u2022"]]
    titoli = [(i, next((k for k in labels if r.startswith(k)), None)) for i,r in enumerate(righe)]
    titoli = [(i,k) for i,k in titoli if k]
    campi = {}
    # Nei diagrammi con intestazione iniziale ogni titolo precede il contenuto;
    # negli altri lo segue. La provenienza rimane sempre da validare.
    prima = bool(titoli and titoli[0][0] == 0)
    for n,(i,k) in enumerate(titoli):
        start = i+1 if prima else (titoli[n-1][0]+1 if n else 0)
        stop = (titoli[n+1][0] if n+1<len(titoli) else len(righe)) if prima else i
        valore = "\n".join(righe[start:stop])
        campi[labels[k]] = valore.split("Turtle Diagram")[0].strip()
    nome = re.split(r"\b"+match.group(1)+r"\b", path.stem, flags=re.I)[-1]
    nome = re.sub(r"[ _-]*Rev[ .]*\d+.*$", "", nome, flags=re.I).strip(" -_")
    return {"codice": match.group(1).upper(), "nome": nome[:200] or match.group(1).upper(),
            "input": campi.get("input", ""), "output": campi.get("output", ""),
            "enti": campi.get("enti", "")[:255], "procedure": campi.get("procedure", ""),
            "indicatori": campi.get("indicatori", ""), "attivo": False,
            "fonte_documentale": f"DA VALIDARE: {path.name}; SHA-256 {hashlib.sha256(data).hexdigest()}. Verificare codici, revisioni, owner e KPI con la Master List. Risorse: " + campi.get("risorse", "")}
