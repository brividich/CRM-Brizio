"""Genera il catalogo OID del modulo Contatori dalle MIB ufficiali dei produttori.

Uso (dalla root del repo):
    python tools/snmp/genera_catalogo_mib.py <cartella_mib> [--out django_app/contatori/data/oid_mib.json]

La cartella contiene i file MIB (es. scaricati da github.com/librenms/librenms,
cartella mibs/). Il parser e' volutamente semplice (SMIv1/SMIv2 dei produttori):
risolve gli OID numerici, distingue scalari (GET .0) e colonne di tabella (WALK),
legge UNITS, enumerazioni e la prima frase della DESCRIPTION. Nessuna rete.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RADICI = {
    "iso": "1", "org": "1.3", "dod": "1.3.6", "internet": "1.3.6.1", "directory": "1.3.6.1.1",
    "mgmt": "1.3.6.1.2", "mib-2": "1.3.6.1.2.1", "transmission": "1.3.6.1.2.1.10",
    "experimental": "1.3.6.1.3", "private": "1.3.6.1.4", "enterprises": "1.3.6.1.4.1",
    "security": "1.3.6.1.5", "snmpV2": "1.3.6.1.6", "snmpModules": "1.3.6.1.6.3",
    "system": "1.3.6.1.2.1.1", "interfaces": "1.3.6.1.2.1.2", "ifIndex": "1.3.6.1.2.1.2.2.1.1",
}
LEGGIBILI = {"read-only", "read-write", "read-create", "accessible-for-notify"}
TIPI_DEF = r"OBJECT-TYPE|OBJECT IDENTIFIER|MODULE-IDENTITY|OBJECT-IDENTITY|NOTIFICATION-TYPE|TRAP-TYPE|OBJECT-GROUP|NOTIFICATION-GROUP|MODULE-COMPLIANCE|AGENT-CAPABILITIES"


def _pulisci(testo: str):
    """Toglie i commenti e sostituisce le stringhe con segnaposto."""
    stringhe = []

    def _salva(m):
        stringhe.append(m.group(1))
        return f'"§{len(stringhe) - 1}§"'

    testo = re.sub(r'"([^"]*)"', _salva, testo)
    testo = re.sub(r"--[^\n]*?(--|$)", " ", testo, flags=re.MULTILINE)
    return testo, stringhe


def _stringa(segnaposto: str, stringhe) -> str:
    m = re.fullmatch(r'"§(\d+)§"', segnaposto or "")
    return stringhe[int(m.group(1))] if m else ""


def _prima_frase(testo: str, limite=200) -> str:
    testo = " ".join(testo.split())
    m = re.match(r"(.+?[.;])(\s|$)", testo)
    frase = m.group(1) if m else testo
    return frase[:limite]


def _enum(syntax: str) -> str:
    voci = re.findall(r"([A-Za-z][\w-]*)\s*\(\s*(-?\d+)\s*\)", syntax)
    return ", ".join(f"{n}={nome}" for nome, n in voci)[:500]


def leggi_cartella(cartella: Path):
    definizioni = {}   # nome -> (genitore, numeri, modulo, tipo, corpo, stringhe)
    convenzioni = {}   # tipo TC -> sintassi
    for file in sorted(cartella.iterdir()):
        if not file.is_file():
            continue
        grezzo = file.read_text(encoding="latin-1")
        testo, stringhe = _pulisci(grezzo)
        modulo = (re.match(r"\s*([A-Za-z][\w-]*)\s+DEFINITIONS", testo) or [None, file.name])[1]
        for m in re.finditer(r"\b([A-Z][\w-]*)\s*::=\s*(?:TEXTUAL-CONVENTION.*?SYNTAX\s+)?(INTEGER\s*\{[^}]*\})", testo, re.DOTALL):
            convenzioni.setdefault(m.group(1), m.group(2))
        for m in re.finditer(rf"\b([a-z][\w-]*)\s+({TIPI_DEF})\b(.*?)::=\s*\{{([^}}]*)\}}", testo, re.DOTALL):
            nome, tipo, corpo, valore = m.groups()
            parti = valore.split()
            if not parti:
                continue
            numeri = [re.sub(r"^.*\((\d+)\)$", r"\1", p) for p in parti[1:]]
            genitore = re.sub(r"\(\d+\)$", "", parti[0])
            if parti[0][0].isdigit():
                genitore, numeri = "", parti
            if not all(n.isdigit() for n in numeri):
                continue
            definizioni.setdefault(nome, (genitore, numeri, modulo, tipo, corpo, stringhe))
    return definizioni, convenzioni


def risolvi(definizioni):
    oid = dict(RADICI)
    cambiato = True
    while cambiato:
        cambiato = False
        for nome, (genitore, numeri, *_rest) in definizioni.items():
            if nome in oid:
                continue
            base = oid.get(genitore) if genitore else ""
            if genitore and base is None:
                continue
            oid[nome] = ".".join(filter(None, [base, *numeri]))
            cambiato = True
    mancanti = sorted({d[0] for n, d in definizioni.items() if n not in oid and d[0]})
    return oid, mancanti


def catalogo(definizioni, convenzioni, oid):
    sintassi = {}
    for nome, (_g, _n, _m, tipo, corpo, _s) in definizioni.items():
        if tipo == "OBJECT-TYPE":
            s = re.search(r"SYNTAX\s+(.*?)\s+(?:UNITS|MAX-ACCESS|ACCESS)\b", corpo, re.DOTALL)
            sintassi[nome] = s.group(1).strip() if s else ""
    voci = {}
    for nome, (genitore, _n, modulo, tipo, corpo, stringhe) in definizioni.items():
        if tipo != "OBJECT-TYPE" or nome not in oid:
            continue
        accesso = re.search(r"\b(?:MAX-ACCESS|ACCESS)\s+([\w-]+)", corpo)
        if not accesso or accesso.group(1) not in LEGGIBILI:
            continue
        syn = sintassi.get(nome, "")
        if syn.startswith("SEQUENCE"):
            continue
        colonna = sintassi.get(genitore, "") and not sintassi.get(genitore, "").startswith("SEQUENCE") \
            and genitore in sintassi and re.search(r"\bINDEX\b|\bAUGMENTS\b", definizioni[genitore][4] or "")
        unita = re.search(r"\bUNITS\s+(\"§\d+§\")", corpo)
        descr = re.search(r"\bDESCRIPTION\s+(\"§\d+§\")", corpo)
        tipo_base = syn.split("(")[0].split("{")[0].strip()
        etichette = _enum(syn) or _enum(convenzioni.get(tipo_base, ""))
        chiave = oid[nome] if colonna else oid[nome] + ".0"
        voci[chiave] = {
            "nome": nome,
            "modulo": modulo,
            "modalita": "WALK" if colonna else "GET",
            "unita": _stringa(unita.group(1), stringhe)[:24] if unita else "",
            "etichette": etichette,
            "descrizione": _prima_frase(_stringa(descr.group(1), stringhe)) if descr else "",
            "sintassi": tipo_base[:40],
        }
    return dict(sorted(voci.items(), key=lambda kv: [int(p) for p in kv[0].split(".")]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cartella", type=Path)
    parser.add_argument("--out", type=Path, default=Path("django_app/contatori/data/oid_mib.json"))
    args = parser.parse_args(argv)
    definizioni, convenzioni = leggi_cartella(args.cartella)
    oid, mancanti = risolvi(definizioni)
    voci = catalogo(definizioni, convenzioni, oid)
    if mancanti:
        print("Genitori non risolti (MIB mancanti):", ", ".join(mancanti[:30]), file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(voci, ensure_ascii=False, indent=0, sort_keys=False) + "\n", encoding="utf-8")
    moduli = sorted({v["modulo"] for v in voci.values()})
    print(f"{len(voci)} OID da {len(moduli)} MIB: {', '.join(moduli)}")


if __name__ == "__main__":
    main()
