"""Riga di comando del collector CNC (``py collector.py`` o ``py cli.py``), in sola lettura.

  py collector.py --config machines.json                 servizio (silenzioso: log solo su file)
  py collector.py --config machines.json -v              servizio con il log anche a schermo
  py collector.py --config machines.json --check-config  valida la configurazione senza connettersi
  py collector.py --config machines.json --once [DM6]    una lettura per macchina, JSON a schermo, poi esce
  py collector.py --config machines.json --browse DM6-MDC  esplora lo spazio OPC UA e propone i nodi
  py collector.py --config machines.json --jsonl dati    anche record JSONL per macchina e status.json

Configurazione (``machines.json``)::

  {"collector": {"poll_seconds": 5, "heartbeat_seconds": 300, "log_file": "collector.log"},
   "machines": [{"name": "AGV1", "driver": "lsv2", "ip": "192.168.23.105"}, ...]}

Password OPC UA: mai nel file; ``"password_env": "CNC_DM7_PASSWORD"`` e la variabile d'ambiente
(lo script ``avvia_collector.ps1`` la legge da ``collector.env``). Con ``PORTALE_URL`` e
``PORTALE_TOKEN`` impostati il collector manda anche al portale; senza, lavora solo in locale.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import ipaddress
import json
import logging
import logging.handlers
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any

try:   # dentro il portale
    from . import collector, lavoratore
    from .archivio import DB
    from .drivers import opcua
    from .esplora import esplora, stampa_esplorazione
    from .portale import Portale
    from .sink import CartellaJsonl, Sink
    from .stati import ESECUZIONI
except ImportError:   # sul PC dell'officina
    import collector  # type: ignore[no-redef]
    import lavoratore  # type: ignore[no-redef]
    from archivio import DB  # type: ignore[no-redef]
    from drivers import opcua  # type: ignore[no-redef]
    from esplora import esplora, stampa_esplorazione  # type: ignore[no-redef]
    from portale import Portale  # type: ignore[no-redef]
    from sink import CartellaJsonl, Sink  # type: ignore[no-redef]
    from stati import ESECUZIONI  # type: ignore[no-redef]

LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_FILE_TENUTI = 5
ESTERNE = ("asyncua", "asyncio", "pyLSV2", "LSV2 Client")
# pyLSV2 scrive un ERROR a ogni tentativo di connessione fallito: il collector segnala già il cambio di stato
# (una riga, con macchina e host), quindi il trasporto di pyLSV2 resta muto per non ripetersi a ogni giro.
MUTE = ("LSV2 TCP",)
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")
_NOME = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
_NODEID = re.compile(r"^(ns=\d+;)?[isgb]=.+$")
CHIAVI_COLLECTOR = {"poll_seconds", "heartbeat_seconds", "log_file", "output_dir", "fwlib_path"}

log = logging.getLogger("collector")


# ----------------------------------------------------------------------------
# Configurazione
# ----------------------------------------------------------------------------
def carica(path: Path) -> dict[str, Any]:
    """machines.json -> ``{"collector": {...}, "machines": [...]}`` con i valori di default applicati."""
    dati = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(dati, dict):
        raise ValueError("il file deve contenere un oggetto JSON con «machines»")
    generale = dati.get("collector") or {}
    macchine = dati.get("machines")
    if not isinstance(macchine, list):
        raise ValueError("manca l'elenco «machines»")
    for m in macchine:
        if isinstance(m, dict):
            m.setdefault("poll_seconds", generale.get("poll_seconds", lavoratore.POLL_DEFAULT))
            if generale.get("fwlib_path") and m.get("driver") == "focas":
                m.setdefault("fwlib_path", generale["fwlib_path"])
    return {"collector": generale, "machines": macchine}


def attiva(m: dict[str, Any]) -> bool:
    return bool(m.get("enabled", True))


def verifica(config: dict[str, Any], librerie: bool = True) -> tuple[list[str], list[str]]:
    """``(errori, avvisi)``. Con errori il servizio non parte: niente avvio parziale silenzioso."""
    errori: list[str] = []
    avvisi: list[str] = []
    generale = config.get("collector") or {}
    for chiave in generale:
        if chiave not in CHIAVI_COLLECTOR:
            avvisi.append(f"collector: chiave «{chiave}» sconosciuta, ignorata")
    nomi: set[str] = set()
    indirizzi: dict[tuple[str, int], str] = {}
    driver_usati: set[str] = set()
    for i, m in enumerate(config.get("machines") or []):
        dove = f"macchina {i + 1}"
        if not isinstance(m, dict):
            errori.append(f"{dove}: non è un oggetto JSON")
            continue
        nome = str(m.get("name") or "")
        dove = f"«{nome}»" if nome else dove
        if not _NOME.match(nome):
            errori.append(f"{dove}: nome mancante o non valido (lettere, cifre, punto, trattino, max 40)")
        elif nome in nomi:
            errori.append(f"{dove}: nome duplicato")
        nomi.add(nome)
        driver = str(m.get("driver") or "opcua")
        if driver not in collector.DRIVER_NOTI:
            errori.append(f"{dove}: driver «{driver}» sconosciuto (ammessi: {', '.join(collector.DRIVER_NOTI)})")
            continue
        host = str(m.get("ip") or "")
        if not _HOST.match(host):
            errori.append(f"{dove}: indirizzo «{host}» mancante o non valido")
        else:
            try:
                ipaddress.ip_address(host)
            except ValueError:
                avvisi.append(f"{dove}: «{host}» non è un indirizzo IP: verrà risolto dal DNS")
        try:
            porta = int(m.get("port") or collector.PORTE_DEFAULT[driver])
            if not 1 <= porta <= 65535:
                raise ValueError
        except (TypeError, ValueError):
            errori.append(f"{dove}: porta non valida")
            porta = 0
        poll = m.get("poll_seconds", lavoratore.POLL_DEFAULT)
        if not isinstance(poll, (int, float)) or isinstance(poll, bool):
            errori.append(f"{dove}: poll_seconds non è un numero")
        elif poll < lavoratore.POLL_MINIMO:
            errori.append(f"{dove}: poll_seconds {poll} sotto il minimo di {lavoratore.POLL_MINIMO:g} s")
        timeout = m.get("timeout", 5)
        if not isinstance(timeout, (int, float)) or not 0 < timeout <= 60:
            errori.append(f"{dove}: timeout deve essere tra 0 e 60 s")
        if m.get("password"):
            errori.append(f"{dove}: password in chiaro nel file: usa «password_env» con il nome di una variabile d'ambiente")
        if m.get("password_env") and attiva(m) and not os.environ.get(str(m["password_env"])):
            errori.append(f"{dove}: variabile d'ambiente {m['password_env']} non impostata (password OPC UA)")
        if m.get("asset_tag") and not _NOME.match(str(m["asset_tag"])):
            errori.append(f"{dove}: asset_tag non valido")
        if m.get("nodes") is not None:
            if driver != "opcua" or not isinstance(m["nodes"], dict):
                errori.append(f"{dove}: «nodes» vale solo per il driver opcua ed è un oggetto chiave -> NodeId")
            else:
                for chiave, nodeid in m["nodes"].items():
                    if chiave not in opcua.CAMPI_NODI:
                        errori.append(f"{dove}: nodes.{chiave} sconosciuto (ammessi: {', '.join(opcua.CAMPI_NODI)})")
                    elif not isinstance(nodeid, str) or not _NODEID.match(nodeid):
                        errori.append(f"{dove}: nodes.{chiave} = {nodeid!r} non è un NodeId (es. ns=2;s=Nome)")
                if "exec" not in m["nodes"]:
                    errori.append(f"{dove}: nodes senza «exec»: lo stato non si può calcolare")
        for chiave in ("execution_map",):
            for codice, valore in (m.get(chiave) or {}).items():
                if str(valore).upper() not in ESECUZIONI:
                    errori.append(f"{dove}: {chiave}.{codice} = {valore!r} (ammessi: {', '.join(sorted(ESECUZIONI))})")
        if attiva(m) and porta and _HOST.match(host):
            chiave_h = (host.lower(), porta)
            if chiave_h in indirizzi:
                errori.append(f"{dove}: stesso indirizzo e porta di «{indirizzi[chiave_h]}» ({host}:{porta})")
            indirizzi[chiave_h] = nome
        if attiva(m):
            driver_usati.add(driver)
            if driver == "focas":
                from_cfg = m.get("fwlib_path") or generale.get("fwlib_path")
                file = _percorso_fwlib(from_cfg)
                if os.path.sep in file or "/" in file:
                    if not os.path.exists(file):
                        errori.append(f"{dove}: libreria Fwlib non trovata: {file} (CNC_FWLIB_PATH o fwlib_path)")
                else:
                    avvisi.append(f"{dove}: libreria Fwlib «{file}» cercata nel PATH di sistema (meglio CNC_FWLIB_PATH)")
    if not any(attiva(m) for m in config.get("machines") or [] if isinstance(m, dict)):
        avvisi.append("nessuna macchina abilitata")
    if librerie:
        for driver, modulo in (("opcua", "asyncua"), ("lsv2", "pyLSV2")):
            if driver in driver_usati and importlib.util.find_spec(modulo) is None:
                errori.append(f"libreria {modulo} non installata (serve al driver {driver}): pip install -r requirements-collector.txt")
    return errori, avvisi


def _percorso_fwlib(percorso: str | None) -> str:
    try:
        from .drivers.focas import percorso_libreria
    except ImportError:
        from drivers.focas import percorso_libreria  # type: ignore[no-redef]
    return percorso_libreria(percorso)


# ----------------------------------------------------------------------------
# Log
# ----------------------------------------------------------------------------
def configura_log(file: Path | None, verbose: bool = False, debug: bool = False) -> None:
    """Silenzioso di default: log su file a rotazione (5 MB × 5); a schermo solo con ``-v``.
    Le librerie esterne (asyncua, pyLSV2) solo a livello ERROR."""
    radice = logging.getLogger()
    for h in list(radice.handlers):
        radice.removeHandler(h)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S")
    radice.setLevel(logging.DEBUG if debug else logging.INFO)
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_FILE_TENUTI, encoding="utf-8")
        h.setFormatter(formato)
        radice.addHandler(h)
    if verbose:
        s = logging.StreamHandler(sys.stderr)
        s.setFormatter(formato)
        radice.addHandler(s)
    if not radice.handlers:
        radice.addHandler(logging.NullHandler())
    for nome in ESTERNE:
        logging.getLogger(nome).setLevel(logging.ERROR)
    for nome in MUTE:
        logging.getLogger(nome).setLevel(logging.CRITICAL)


# ----------------------------------------------------------------------------
# --once
# ----------------------------------------------------------------------------
async def una_lettura(m: dict[str, Any]) -> dict[str, Any]:
    """Una lettura di una macchina, senza scrivere niente su disco: il record normalizzato."""
    db = DB(":memory:")
    macchina = collector.nuova_macchina(m, db)
    try:
        if isinstance(macchina, collector.MacchinaSincrona):
            return await asyncio.to_thread(_una_lettura_sincrona, macchina)
        try:
            async with opcua.sessione(macchina.url, macchina.username, macchina.password, macchina.name, macchina.log) as client:
                drv = await opcua.DriverOpcUa.rileva(client, macchina.name, macchina.log, macchina.cfg)
                record = await asyncio.wait_for(macchina.una_lettura(drv), 30)
                record["raw"]["modello_dati"] = drv.data_model
                record["raw"]["matricola"] = drv.found_serial
                return record
        except Exception as e:  # noqa: BLE001 - --once riporta l'errore nel record invece di uscire
            macchina.errore = f"{type(e).__name__}: {e}"[:300]
            macchina.update_state(online=False)
            return macchina.record()
    finally:
        db.chiudi()


def _una_lettura_sincrona(m: collector.MacchinaSincrona) -> dict[str, Any]:
    drv = m.crea_driver()
    try:
        drv.connetti()
        m.applica(drv.leggi())
    except Exception as e:  # noqa: BLE001 - --once riporta l'errore nel record invece di uscire
        stato = collector.NON_LEGGIBILE if type(e).__name__ in ("LoginRifiutato", "LibreriaAssente") else collector.OFFLINE
        m.applica(lavoratore.lettura_fuori_linea(m.name, m.driver_nome, stato, f"{type(e).__name__}: {e}"[:300]))
    finally:
        drv.chiudi()
    record = m.record()
    if m.lettura is not None:
        record["raw"] = {**record.get("raw", {}), **m.lettura.raw}
    return record


# ----------------------------------------------------------------------------
# Esecuzione
# ----------------------------------------------------------------------------
def argomenti(argv: list[str] | None = None) -> argparse.Namespace:
    qui = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(prog="collector", description="Collector delle CNC in sola lettura (OPC UA, LSV2, FOCAS)")
    ap.add_argument("config_pos", nargs="?", help="file di configurazione (in alternativa a --config)")
    ap.add_argument("--config", default=None, help="machines.json (default: accanto allo script)")
    ap.add_argument("--db", default=None, help="machines.db (default: accanto alla configurazione)")
    ap.add_argument("--log-file", default=None, help="file di log a rotazione 5 MB x 5 (default: collector.log)")
    ap.add_argument("-v", "--verbose", action="store_true", help="log anche a schermo")
    ap.add_argument("--debug", action="store_true", help="log di dettaglio")
    ap.add_argument("--jsonl", metavar="DIR", default=None, help="scrive anche <DIR>/<macchina>/<giorno>.jsonl e status.json")
    ap.add_argument("--durata-ore", type=float, default=0, help="servizio: si ferma da solo dopo queste ore (0 = mai)")
    gruppo = ap.add_mutually_exclusive_group()
    gruppo.add_argument("--check-config", action="store_true", help="valida la configurazione senza connettersi")
    gruppo.add_argument("--once", nargs="?", const="*", metavar="MACCHINA", help="una lettura per macchina, JSON a schermo")
    gruppo.add_argument("--browse", metavar="MACCHINA", help="esplora lo spazio OPC UA di una macchina")
    ap.add_argument("--profondita", type=int, default=8, help="--browse: profondità massima (default 8)")
    ap.add_argument("--max-nodi", type=int, default=20000, help="--browse: nodi al massimo (default 20000)")
    args = ap.parse_args(argv)
    args.config = Path(args.config or args.config_pos or qui / "machines.json")
    return args


def _macchina(config: dict[str, Any], nome: str) -> dict[str, Any] | None:
    return next((m for m in config["machines"] if isinstance(m, dict) and m.get("name") == nome), None)


def esegui(argv: list[str] | None = None) -> int:
    """Codici di uscita: 0 ok, 1 errore di configurazione o di lettura, 2 servizio non avviato."""
    args = argomenti(argv)
    try:
        config = carica(args.config)
    except (OSError, ValueError) as e:
        print(f"Configurazione non leggibile ({args.config}): {e}", file=sys.stderr)
        return 1
    generale = config["collector"]
    base = args.config.resolve().parent
    log_file = Path(args.log_file or generale.get("log_file") or "collector.log")
    log_file = log_file if log_file.is_absolute() else base / log_file
    errori, avvisi = verifica(config)

    if args.check_config:
        for a in avvisi:
            print(f"AVVISO  {a}")
        for err in errori:
            print(f"ERRORE  {err}")
        abilitate = [m for m in config["machines"] if isinstance(m, dict) and attiva(m)]
        print(f"{len(abilitate)} macchine abilitate, {len(errori)} errori, {len(avvisi)} avvisi: "
              + ("configurazione valida." if not errori else "da correggere."))
        return 1 if errori else 0

    if args.once is not None:
        configura_log(None, verbose=args.verbose, debug=args.debug)
        if args.once == "*":
            scelte = [m for m in config["machines"] if isinstance(m, dict) and attiva(m)]
        else:
            m = _macchina(config, args.once)
            if m is None:
                print(f"Macchina «{args.once}» non trovata in {args.config}", file=sys.stderr)
                return 1
            scelte = [m]
        if errori:
            for err in errori:
                print(f"ERRORE  {err}", file=sys.stderr)
            if any(any(f"«{m.get('name')}»" in err for err in errori) for m in scelte):
                return 1

        async def tutte() -> list[dict[str, Any]]:
            return list(await asyncio.gather(*(una_lettura(dict(m)) for m in scelte)))

        records = asyncio.run(tutte())
        print(json.dumps(records, indent=2, ensure_ascii=False, default=str))
        return 0 if all(r.get("online") for r in records) else 1

    if args.browse:
        configura_log(None, verbose=args.verbose, debug=args.debug)
        m = _macchina(config, args.browse)
        if m is None or (m.get("driver") or "opcua") != "opcua":
            print(f"«{args.browse}»: serve una macchina con driver opcua in {args.config}", file=sys.stderr)
            return 1
        tsv = base / f"browse_{args.browse}.tsv"
        esito = asyncio.run(esplora(m, tsv, args.profondita, args.max_nodi))
        stampa_esplorazione(esito, sys.stdout)
        return 0

    # servizio
    configura_log(log_file, verbose=args.verbose, debug=args.debug)
    for a in avvisi:
        log.warning("configurazione: %s", a)
    if errori:
        for err in errori:
            log.error("configurazione: %s", err)
        log.error("collector NON avviato: %d errori nella configurazione (prova con --check-config)", len(errori))
        if not args.verbose:
            print(f"Collector non avviato: {len(errori)} errori nella configurazione, vedi --check-config", file=sys.stderr)
        return 2
    db_path = Path(args.db) if args.db else base / "machines.db"
    uscite: list[Sink] = []
    cartella_jsonl = args.jsonl or generale.get("output_dir")
    if cartella_jsonl:
        cartella = Path(cartella_jsonl)
        uscite.append(CartellaJsonl(cartella if cartella.is_absolute() else base / cartella))
    collector.HEARTBEAT_USCITE = float(generale.get("heartbeat_seconds") or collector.HEARTBEAT_USCITE)

    async def principale() -> None:
        task = asyncio.current_task()
        if task is not None and not sys.platform.startswith("win"):
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
        if task is not None and args.durata_ore > 0:
            def scaduta() -> None:
                log.info("durata richiesta di %g ore raggiunta: fermo il collector", args.durata_ore)
                task.cancel()

            asyncio.get_running_loop().call_later(args.durata_ore * 3600, scaduta)
        await collector.avvia(Portale.da_ambiente([], collector.prog_name), str(db_path), args.config,
                              args.config.with_name("machines.portale.json"), uscite=uscite,
                              elenco_iniziale=config["machines"])

    try:
        asyncio.run(principale())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(esegui())
