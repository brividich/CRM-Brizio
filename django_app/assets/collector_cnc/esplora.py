"""``--browse``: esplora lo spazio indirizzi OPC UA di una macchina e propone i nodi da leggere.

Parte da ``Objects`` (escluso ``Objects/Server``), scende fino a ``profondita`` livelli e al massimo
``max_nodi`` nodi; legge nome, classe e valore corrente (solo letture, a blocchi, con la stessa
whitelist del collector) e salva un TSV: ``nodeid, percorso, classe, tipo, valore``.

Per ogni campo normalizzato stampa i 5 nodi candidati più probabili (parole chiave sul percorso) e uno
snippet JSON da incollare in ``machines.json`` (chiave ``nodes``). Riconosce i modelli più comuni:
OPC 40501 / umati (Machine Tools), un modello derivato da MTConnect, DMG MORI BasicDataSet.
"""
from __future__ import annotations

import asyncio
import csv
import json
from pathlib import Path
from typing import Any, TextIO

from asyncua import ua
from asyncua.ua.uaerrors import UaError
from asyncua.ua.attribute_ids import AttributeIds
from asyncua.ua.object_ids import ObjectIds

try:
    from .drivers import opcua
except ImportError:   # sul PC dell'officina
    from drivers import opcua  # type: ignore[no-redef]

SERVER = "i=2253"
BLOCCO = 200
TIMEOUT = 10.0
VALORE_MAX = 120

# campo normalizzato -> (chiave in "nodes", parole chiave dalla più alla meno probabile)
CAMPI: dict[str, tuple[str, tuple[str, ...]]] = {
    "program": ("program", ("CurrentNcProgram", "ActiveProgramName", "ProgramName", "ActiveProgram", "NcProgram",
                            "MainProgram", "Program")),
    "execution": ("exec", ("ChannelState", "ExecutionState", "Execution", "ProgramState", "RunState", "ControllerState",
                           "State")),
    "mode": ("mode", ("ChannelMode", "ControllerMode", "OperationMode", "OperatingMode", "Mode")),
    "feed_ovr": ("feed_ovr", ("FeedOverride", "PathFeedrateOverride", "FeedrateOverride", "FeedRateOverride")),
    "spindle_ovr": ("spindle_ovr", ("SpindleOverride", "SpindleSpeedOverride", "RotaryVelocityOverride",
                                    "SpeedOverride")),
    "rapid_ovr": ("rapid_ovr", ("RapidOverride", "RapidTraverseOverride", "PathFeedrateOverrideRapid")),
    "part_count": ("part_counter", ("PartCounter", "PartCount", "PartsProduced", "PartCountAll", "PartsProducedInLifetime",
                                    "PartCounterOverall")),
    "alarm": ("n_alarms", ("NumberOfActiveAlarms", "ActiveAlarms", "AlarmCount", "Alarm", "Condition")),
    "estop": ("estop", ("EmergencyStopTriggered", "EmergencyStop", "EStop")),
    "operation_time": ("operation_time", ("OperationTimeOverall", "OperationDuration", "OperatingTime", "RunTime")),
}
CANALE = ("channel_1", "channel", "path", "controller")


def modello(nsarr: list[str]) -> str:
    """Il modello dati probabile dal namespace array del server."""
    basso = [u.lower() for u in nsarr]
    if opcua.UMATI_URI in nsarr:
        return "OPC 40501 Machine Tools (umati)"
    if any("mtconnect" in u for u in basso):
        return "derivato da MTConnect"
    if any(opcua.DMG_MACHINE_URI.lower() in u for u in basso):
        return "DMG MORI BasicDataSet"
    return "sconosciuto"


def punteggio(parole: tuple[str, ...], riga: dict[str, Any], campo: str) -> int:
    nome = riga["percorso"].rsplit("/", 1)[-1].lower()
    percorso = riga["percorso"].lower()
    if riga["classe"] != "Variable" and campo != "alarm":
        return 0
    migliore = 0
    for i, parola in enumerate(parole):
        p = parola.lower()
        if nome == p or nome.endswith("-" + p) or nome.endswith("_" + p):
            migliore = max(migliore, 100 - i)
        elif p in nome:
            migliore = max(migliore, 60 - i)
        elif p in percorso:
            migliore = max(migliore, 25 - i)
    if not migliore:
        return 0
    if campo in ("execution", "mode", "program", "feed_ovr", "spindle_ovr", "rapid_ovr") and any(c in percorso for c in CANALE):
        migliore += 5
    if riga["valore"] not in ("", "None"):
        migliore += 2
    return migliore


def suggerisci(righe: list[dict[str, Any]], quanti: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Per ogni campo i ``quanti`` nodi più probabili, dal più probabile."""
    esito: dict[str, list[dict[str, Any]]] = {}
    for campo, (_chiave, parole) in CAMPI.items():
        candidati = [(punteggio(parole, r, campo), r) for r in righe]
        candidati = [c for c in candidati if c[0] > 0]
        candidati.sort(key=lambda c: (-c[0], len(c[1]["percorso"])))
        esito[campo] = [{**r, "punteggio": p} for p, r in candidati[:quanti]]
    return esito


def _testo(v: Any) -> str:
    t = getattr(v, "Text", None)
    s = str(t if t is not None else v)
    return s.replace("\t", " ").replace("\n", " ")[:VALORE_MAX]


async def _attributi(client: Any, nodi: list[Any], attributo: Any) -> list[Any]:
    return list(await asyncio.wait_for(client.read_attributes(nodi, attributo), TIMEOUT))


async def esplora(m: dict[str, Any], tsv: Path, profondita: int = 8, max_nodi: int = 20000) -> dict[str, Any]:
    """Esplora e salva il TSV; ritorna modello, numero di nodi, suggerimenti e snippet."""
    import os

    porta = int(m.get("port") or 4840)
    password = m.get("password") or (os.environ.get(str(m["password_env"])) if m.get("password_env") else None)
    url = f"opc.tcp://{m['ip']}:{porta}"
    righe: list[dict[str, Any]] = []
    async with opcua.sessione(url, m.get("username") or None, password, str(m.get("name"))) as client:
        nsarr = list(await client.get_namespace_array())
        radice = client.get_node(ua.NodeId(ObjectIds.ObjectsFolder, 0))  # type: ignore[arg-type]
        livello: list[tuple[Any, str]] = [(radice, "Objects")]
        visti: set[str] = {"i=85"}
        troncato = False
        for _ in range(max(1, profondita)):
            prossimo: list[tuple[Any, str]] = []
            for nodo, percorso in livello:
                if len(righe) >= max_nodi:
                    troncato = True
                    break
                try:
                    figli = await asyncio.wait_for(nodo.get_children(), TIMEOUT)
                except (asyncio.TimeoutError, OSError, UaError):
                    continue
                nuovi = []
                for f in figli:
                    chiave = f.nodeid.to_string()
                    if chiave in visti or chiave == SERVER:
                        continue
                    visti.add(chiave)
                    nuovi.append(f)
                nuovi = nuovi[: max(0, max_nodi - len(righe))]
                for i in range(0, len(nuovi), BLOCCO):
                    blocco = nuovi[i:i + BLOCCO]
                    nomi = await _attributi(client, blocco, AttributeIds.BrowseName)
                    classi = await _attributi(client, blocco, AttributeIds.NodeClass)
                    valori = await _attributi(client, blocco, AttributeIds.Value)
                    for f, dn, dc, dv in zip(blocco, nomi, classi, valori, strict=True):
                        nome = getattr(dn.Value.Value, "Name", "") if dn.Value is not None else ""
                        classe_val = dc.Value.Value if dc.Value is not None else None
                        try:
                            classe = ua.NodeClass(classe_val).name if classe_val is not None else ""
                        except ValueError:
                            classe = str(classe_val)
                        valore, tipo = "", ""
                        if classe == "Variable" and dv.Value is not None and dv.StatusCode.is_good():
                            valore = _testo(dv.Value.Value)
                            tipo = getattr(dv.Value.VariantType, "name", "")
                        righe.append({"nodeid": f.nodeid.to_string(), "percorso": f"{percorso}/{nome}",
                                      "classe": classe, "tipo": tipo, "valore": valore})
                        prossimo.append((f, f"{percorso}/{nome}"))
                    await asyncio.sleep(0)   # cede il passo: esplorazione gentile con il server
            livello = prossimo
            if not livello or troncato:
                break
    tsv.parent.mkdir(parents=True, exist_ok=True)
    with tsv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["nodeid", "percorso", "classe", "tipo", "valore"])
        for r in righe:
            w.writerow([r["nodeid"], r["percorso"], r["classe"], r["tipo"], r["valore"]])
    suggerimenti = suggerisci(righe)
    nodi = {CAMPI[campo][0]: lista[0]["nodeid"] for campo, lista in suggerimenti.items() if lista}
    snippet = {"name": m.get("name"), "driver": "opcua", "ip": m["ip"], "port": porta, "nodes": nodi}
    return {"modello": modello(nsarr), "nodi": len(righe), "troncato": troncato, "tsv": str(tsv),
            "suggerimenti": suggerimenti, "snippet": snippet}


def stampa_esplorazione(esito: dict[str, Any], out: TextIO) -> None:
    out.write(f"Modello dati: {esito['modello']}\n")
    out.write(f"Nodi letti: {esito['nodi']}{' (limite raggiunto: aumenta --max-nodi)' if esito['troncato'] else ''}\n")
    out.write(f"Elenco completo: {esito['tsv']}\n\n")
    for campo, lista in esito["suggerimenti"].items():
        out.write(f"{campo}:\n")
        if not lista:
            out.write("  (nessun candidato)\n")
        for c in lista:
            out.write(f"  [{c['punteggio']:3d}] {c['nodeid']}  {c['percorso']}  = {c['valore']}\n")
    if esito["modello"] in ("OPC 40501 Machine Tools (umati)", "DMG MORI BasicDataSet") and "DMG" in json.dumps(esito["snippet"]).upper():
        out.write("\nNota: modello DMG MORI già noto al collector, la mappa «nodes» non serve.\n")
    out.write("\nSnippet da incollare in machines.json (controlla i nodi prima di usarlo):\n")
    out.write(json.dumps(esito["snippet"], indent=2, ensure_ascii=False) + "\n")
