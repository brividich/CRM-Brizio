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
    """Definizioni per (modulo, nome): nomi uguali in MIB diverse non si confondono."""
    definizioni = {}   # (modulo, nome) -> (genitore, numeri, tipo, corpo, stringhe)
    importati = {}     # modulo -> {nome: modulo di origine}
    convenzioni = {}   # (modulo, tipo TC) -> sintassi
    file_mib = sorted(f for f in cartella.iterdir() if f.is_file())
    nomi_file = {f.stem for f in file_mib}
    for file in file_mib:
        testo, stringhe = _pulisci(file.read_text(encoding="latin-1"))
        modulo = (re.match(r"\s*([A-Za-z][\w-]*)\s+DEFINITIONS", testo) or [None, file.stem])[1]
        if modulo != file.stem and modulo in nomi_file:
            # File che dichiara il nome di un altro modulo (copia-incolla nei MIB dei produttori).
            modulo = file.stem
        imp = re.search(r"\bIMPORTS\b(.*?);", testo, re.DOTALL)
        mappa = {}
        if imp:
            for nomi, origine in re.findall(r"(.*?)\bFROM\s+([A-Za-z][\w-]*)", imp.group(1), re.DOTALL):
                for n in re.split(r"[\s,]+", nomi.strip()):
                    if n:
                        mappa[n] = origine
        importati[modulo] = mappa
        for m in re.finditer(r"\b([A-Z][\w-]*)\s*::=\s*(?:TEXTUAL-CONVENTION.*?SYNTAX\s+)?(INTEGER\s*\{[^}]*\})", testo, re.DOTALL):
            convenzioni.setdefault((modulo, m.group(1)), m.group(2))
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
            definizioni.setdefault((modulo, nome), (genitore, numeri, tipo, corpo, stringhe))
    return definizioni, importati, convenzioni


def _trova(nome, modulo, definizioni, importati, per_nome):
    """Chiave della definizione di ``nome`` vista dal modulo: stesso modulo, poi IMPORTS, poi unica."""
    if (modulo, nome) in definizioni:
        return (modulo, nome)
    origine = importati.get(modulo, {}).get(nome)
    if origine and (origine, nome) in definizioni:
        return (origine, nome)
    candidati = per_nome.get(nome, [])
    return candidati[0] if len(candidati) == 1 else None


def risolvi(definizioni, importati):
    per_nome = {}
    for chiave in definizioni:
        per_nome.setdefault(chiave[1], []).append(chiave)
    oid = {}
    cambiato = True
    while cambiato:
        cambiato = False
        for chiave, (genitore, numeri, *_rest) in definizioni.items():
            if chiave in oid:
                continue
            base = ""
            if genitore:
                fonte = _trova(genitore, chiave[0], definizioni, importati, per_nome)
                base = oid.get(fonte) if fonte else RADICI.get(genitore)
                if base is None and fonte is None:
                    base = RADICI.get(genitore)
                if base is None:
                    continue
            oid[chiave] = ".".join(filter(None, [base, *numeri]))
            cambiato = True
    mancanti = sorted({d[0] for k, d in definizioni.items() if k not in oid and d[0]})
    return oid, mancanti, per_nome


def catalogo(definizioni, importati, convenzioni, oid, per_nome):
    sintassi = {}
    for chiave, (_g, _n, tipo, corpo, _s) in definizioni.items():
        if tipo == "OBJECT-TYPE":
            s = re.search(r"SYNTAX\s+(.*?)\s+(?:UNITS|MAX-ACCESS|ACCESS)\b", corpo, re.DOTALL)
            sintassi[chiave] = s.group(1).strip() if s else ""
    voci = {}
    for chiave, (genitore, _n, tipo, corpo, stringhe) in definizioni.items():
        modulo, nome = chiave
        if tipo != "OBJECT-TYPE" or chiave not in oid:
            continue
        accesso = re.search(r"\b(?:MAX-ACCESS|ACCESS)\s+([\w-]+)", corpo)
        if not accesso or accesso.group(1) not in LEGGIBILI:
            continue
        syn = sintassi.get(chiave, "")
        if syn.startswith("SEQUENCE"):
            continue
        padre = _trova(genitore, modulo, definizioni, importati, per_nome)
        colonna = bool(padre and padre in sintassi and not sintassi[padre].startswith("SEQUENCE")
                       and re.search(r"\bINDEX\b|\bAUGMENTS\b", definizioni[padre][3] or ""))
        unita = re.search(r"\bUNITS\s+(\"§\d+§\")", corpo)
        descr = re.search(r"\bDESCRIPTION\s+(\"§\d+§\")", corpo)
        tipo_base = syn.split("(")[0].split("{")[0].strip()
        tc = _trova(tipo_base, modulo, {k: 1 for k in convenzioni}, importati,
                    {}) if tipo_base else None
        sintassi_tc = convenzioni.get(tc) or next(
            (v for (m, n), v in convenzioni.items() if n == tipo_base), "")
        etichette = _enum(syn) or _enum(sintassi_tc)
        chiave_oid = oid[chiave] if colonna else oid[chiave] + ".0"
        voci[chiave_oid] = {
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
    definizioni, importati, convenzioni = leggi_cartella(args.cartella)
    oid, mancanti, per_nome = risolvi(definizioni, importati)
    voci = catalogo(definizioni, importati, convenzioni, oid, per_nome)
    if mancanti:
        print("Genitori non risolti (MIB mancanti):", ", ".join(mancanti[:30]), file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(voci, ensure_ascii=False, indent=0, sort_keys=False) + "\n", encoding="utf-8")
    moduli = sorted({v["modulo"] for v in voci.values()})
    print(f"{len(voci)} OID da {len(moduli)} MIB: {', '.join(moduli)}")


if __name__ == "__main__":
    main()
