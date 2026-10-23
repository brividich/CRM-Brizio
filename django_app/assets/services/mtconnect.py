"""Stato reale delle macchine CNC dagli agent MTConnect (standard ANSI/MTC1.4, HTTP + XML), in sola lettura.

Ogni 2 minuti (schedule ``mtconnect_poll``) il portale chiede ``/current`` a ogni agent
collegato (``CollegamentoMTConnect``) e ne ricava:

- **stato**: spenta (``Availability`` = UNAVAILABLE), in allarme (una ``Condition`` in
  Fault o l'emergenza premuta), in lavoro (``Execution`` = ACTIVE), programma interrotto
  (FEED_HOLD, INTERRUPTED, STOPPED, …), altrimenti pronta; agent che non risponde = non
  raggiungibile. Ogni cambio apre un ``PeriodoStatoMacchina``: da lì le ore in lavoro;
- programma, modalità, pezzi (``PartCount``), allarmi e avvisi attivi (tipo, codice, testo);
- **contatori**: le ore di lavoro (``EquipmentTimer`` OPERATING, poi WORKING, poi POWERED,
  poi ``AccumulatedTime``) e i pezzi avanzano i contatori dell'asset scelti nel
  collegamento, per differenza tra due letture (un contatore azzerato sulla CNC riparte
  da zero senza far scendere quello del portale) e al massimo una registrazione all'ora.

Solo indirizzi della rete interna (privati o locali), niente redirect, risposta al massimo
2 MB, XML letto con ``defusedxml``. Le letture di rete vanno in parallelo; le scritture sul
database restano nel processo principale.
"""
from __future__ import annotations

import ipaddress
import logging
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote, urlparse

from django.utils import timezone

logger = logging.getLogger(__name__)

TIMEOUT = (3, 6)
MAX_BYTES = 2 * 1024 * 1024
MAX_THREADS = 8
INTERVALLO_CONTATORI = timedelta(hours=1)
VECCHIO_DOPO = timedelta(minutes=15)  # oltre, lo stato salvato non si mostra come «attuale»
_NOME_DISPOSITIVO = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
_ESECUZIONE_FERMA = {"FEED_HOLD", "INTERRUPTED", "STOPPED", "PROGRAM_STOPPED", "OPTIONAL_STOP", "WAIT"}
_TIMER_PREFERITI = ("OPERATING", "WORKING", "POWERED")
_PEZZI_IGNORATI = {"TARGET", "BAD", "REMAINING", "ABORTED", "FAILED", "REJECT"}

STATO_ETICHETTE = {
    "in_lavoro": "In lavoro",
    "setup": "Lavoro MDI/manuale",
    "pronta": "Ferma",
    "ferma": "Interrotta",
    "allarme": "In allarme",
    "emergenza": "Emergenza",
    "spenta": "Offline",
    "non_raggiungibile": "Non raggiungibile",
    "mai": "Mai letta",
}
STATI_ALLARME = {"allarme", "emergenza"}
# Dal collector OPC UA (django_app/assets/collector_cnc): stessi stati, stesse parole di Messenger.
STATI_COLLECTOR = {
    "LAVORO": "in_lavoro", "SETUP": "setup", "INTERROTTA": "ferma", "FERMA": "pronta",
    "ALLARME": "allarme", "EMERGENZA": "emergenza", "OFFLINE": "spenta",
}
SEVERITA_ALLARME = 801  # da questa severità OPC UA un messaggio è un allarme vero (come nel collector)
_MODALITA_MANUALE = {"MANUAL", "MANUAL_DATA_INPUT", "MDI", "JOG", "EDIT"}


class MTConnectError(RuntimeError):
    pass


# --- Indirizzi --------------------------------------------------------------------------------


def valida_url(url: str) -> str:
    """URL dell'agent normalizzato; solleva se non è http(s) verso la rete interna."""
    url = str(url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise MTConnectError("Indirizzo non valido: serve http:// o https:// seguito dal nome o dall'IP dell'agent.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise MTConnectError("Indirizzo non valido: niente credenziali, parametri o frammenti nell'URL.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MTConnectError("Porta non valida nell'indirizzo dell'agent.") from exc
    try:
        indirizzi = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, port or 80, proto=socket.IPPROTO_TCP)}
    except socket.gaierror as exc:
        raise MTConnectError(f"Nome «{parsed.hostname}» non risolto dal server del portale.") from exc
    for addr in indirizzi:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise MTConnectError("Solo agent della rete interna: l'indirizzo punta fuori dall'azienda.")
    return url


def _percorso(dispositivo: str, risorsa: str) -> str:
    if not dispositivo:
        return f"/{risorsa}"
    if not _NOME_DISPOSITIVO.match(dispositivo):
        raise MTConnectError("Nome del dispositivo non valido (lettere, cifre, punto, trattino, trattino basso).")
    return f"/{quote(dispositivo)}/{risorsa}"


def scarica(url: str, dispositivo: str = "", risorsa: str = "current") -> bytes:
    import requests

    base = valida_url(url)
    try:
        resp = requests.get(base + _percorso(dispositivo, risorsa), timeout=TIMEOUT, allow_redirects=False, stream=True,
                            headers={"Accept": "application/xml, text/xml"})
    except requests.exceptions.RequestException as exc:
        raise MTConnectError(f"Agent non raggiungibile ({type(exc).__name__}).") from exc
    try:
        if resp.status_code != 200:
            raise MTConnectError(f"L'agent ha risposto {resp.status_code}.")
        data = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    finally:
        resp.close()
    if len(data) > MAX_BYTES:
        raise MTConnectError("Risposta dell'agent troppo grande (oltre 2 MB).")
    return data


# --- Lettura dell'XML -------------------------------------------------------------------------


def _locale(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _radice(xml: bytes):
    from defusedxml import ElementTree

    try:
        root = ElementTree.fromstring(xml)
    except Exception as exc:  # noqa: BLE001 - XML malformato o vietato (entità, DTD)
        raise MTConnectError("Risposta dell'agent non leggibile (XML non valido).") from exc
    if _locale(root.tag) == "MTConnectError":
        testo = " ".join((e.text or "").strip() for e in root.iter() if _locale(e.tag) == "Error")
        raise MTConnectError(f"L'agent ha risposto con un errore: {testo[:200] or 'senza dettagli'}.")
    return root


def _numero(testo) -> Decimal | None:
    try:
        valore = Decimal(str(testo).strip())
    except (InvalidOperation, ValueError):
        return None
    return valore if valore.is_finite() and valore >= 0 else None


def leggi_current(xml: bytes, dispositivo: str = "") -> dict:
    """Dati utili di un dispositivo da una risposta ``/current``."""
    root = _radice(xml)
    devices = [e for e in root.iter() if _locale(e.tag) == "DeviceStream"]
    if not devices:
        raise MTConnectError("L'agent non ha restituito nessun dispositivo.")
    if dispositivo:
        dev = next((d for d in devices if dispositivo in (d.get("name"), d.get("uuid"))), None)
        if dev is None:
            nomi = ", ".join(d.get("name") or "?" for d in devices)
            raise MTConnectError(f"Dispositivo «{dispositivo}» non trovato nell'agent (presenti: {nomi}).")
    else:
        dev = devices[0]

    valori: dict[str, list[str]] = {}
    timer: dict[str, list[Decimal]] = {}
    pezzi: list[Decimal] = []
    allarmi: list[dict] = []
    for gruppo in dev.iter():
        nome_gruppo = _locale(gruppo.tag)
        if nome_gruppo in ("Events", "Samples"):
            for item in gruppo:
                tipo, testo = _locale(item.tag), (item.text or "").strip()
                if tipo != "Availability" and testo.upper() == "UNAVAILABLE":
                    continue
                if tipo == "EquipmentTimer":
                    numero = _numero(testo)
                    if numero is not None:
                        timer.setdefault((item.get("subType") or "").upper(), []).append(numero)
                elif tipo == "AccumulatedTime":
                    numero = _numero(testo)
                    if numero is not None:
                        timer.setdefault("ACCUMULATED", []).append(numero)
                elif tipo == "PartCount":
                    numero = _numero(testo)
                    if numero is not None and (item.get("subType") or "").upper() not in _PEZZI_IGNORATI:
                        pezzi.append(numero)
                elif testo:
                    valori.setdefault(tipo, []).append(testo)
        elif nome_gruppo == "Condition":
            for item in gruppo:
                livello = _locale(item.tag)
                if livello in ("Fault", "Warning"):
                    allarmi.append({
                        "livello": "allarme" if livello == "Fault" else "avviso",
                        "tipo": (item.get("type") or "")[:60],
                        "codice": (item.get("nativeCode") or "")[:60],
                        "testo": " ".join((item.text or "").split())[:200],
                        "dal": (item.get("timestamp") or "")[:40],
                    })

    def primo(tipo):
        return next(iter(valori.get(tipo) or []), "")

    esecuzioni = [v.upper() for v in valori.get("Execution") or []]
    # Più path (testa, contromandrino): uno in lavoro basta; poi un programma interrotto; poi il primo.
    esecuzione = "ACTIVE" if "ACTIVE" in esecuzioni else next(
        (e for e in esecuzioni if e in _ESECUZIONE_FERMA), next(iter(esecuzioni), ""))
    secondi = next((max(timer[k]) for k in (*_TIMER_PREFERITI, "ACCUMULATED") if timer.get(k)), None)
    return {
        "dispositivo": dev.get("name") or "",
        "disponibilita": primo("Availability").upper(),
        "esecuzione": esecuzione,
        "modalita": primo("ControllerMode").upper(),
        "emergenza": primo("EmergencyStop").upper(),
        "programma": primo("Program")[:200],
        "pezzi": max(pezzi) if pezzi else None,
        "ore": (secondi / Decimal(3600)).quantize(Decimal("0.01")) if secondi is not None else None,
        "allarmi": allarmi[:20],
    }


def stato_da(dati: dict) -> str:
    if dati.get("disponibilita") == "UNAVAILABLE":
        return "spenta"
    if dati.get("emergenza") == "TRIGGERED":
        return "emergenza"
    if any(a["livello"] == "allarme" for a in dati.get("allarmi") or []):
        return "allarme"
    if dati.get("esecuzione") == "ACTIVE":
        return "setup" if dati.get("modalita") in _MODALITA_MANUALE else "in_lavoro"
    if dati.get("esecuzione") in _ESECUZIONE_FERMA:
        return "ferma"
    return "pronta"


def leggi_probe(xml: bytes) -> list[dict]:
    """Dispositivi e tipi di dato di un agent (per la prova del collegamento)."""
    root = _radice(xml)
    out = []
    for dev in (e for e in root.iter() if _locale(e.tag) == "Device"):
        tipi = sorted({(item.get("type") or "") for item in dev.iter() if _locale(item.tag) == "DataItem"} - {""})
        out.append({"nome": dev.get("name") or "", "uuid": dev.get("uuid") or "", "tipi": tipi})
    if not out:
        raise MTConnectError("L'agent non ha descritto nessun dispositivo (/probe).")
    return out


# --- Aggiornamento ----------------------------------------------------------------------------


def _cambia_stato(coll, nuovo: str, ora) -> None:
    from assets.models import PeriodoStatoMacchina

    if coll.stato == nuovo and coll.stato_dal:
        return
    if coll.stato_dal and ora < coll.stato_dal:
        ora = coll.stato_dal  # mai un periodo che finisce prima di cominciare
    PeriodoStatoMacchina.objects.filter(collegamento=coll, al__isnull=True).update(al=ora)
    PeriodoStatoMacchina.objects.create(collegamento=coll, stato=nuovo, dal=ora)
    coll.stato, coll.stato_dal = nuovo, ora


def _avanza_contatore(coll, campo: str, nuovo: Decimal | None, meter, ora, etichetta: str) -> str:
    """Accumula la differenza dall'ultima lettura e la registra sul contatore al massimo una volta all'ora."""
    from assets.models import AssetMeter

    from .meters import MeterReadingError, record_meter_reading

    if nuovo is None:
        return ""
    precedente = getattr(coll, f"{campo}_grezzo")
    setattr(coll, f"{campo}_grezzo", nuovo)
    if precedente is None:
        return ""  # prima lettura: è la base di partenza
    delta = nuovo - precedente if nuovo >= precedente else nuovo  # azzerato sulla CNC: riparte da zero
    sospeso = (coll.sospesi or {}).get(campo)
    sospeso = (Decimal(str(sospeso)) if sospeso else Decimal(0)) + delta
    coll.sospesi = {**(coll.sospesi or {}), campo: str(sospeso)}
    if meter is None or sospeso <= 0:
        return ""
    if meter.read_at is not None and ora - meter.read_at < INTERVALLO_CONTATORI:
        return ""
    try:
        record_meter_reading(meter, meter.current_value + sospeso, read_at=ora, source=AssetMeter.SOURCE_MTCONNECT,
                             note=f"MTConnect: {etichetta}")
    except MeterReadingError as exc:
        return f"Contatore {etichetta} non aggiornato: {exc}"[:300]
    coll.sospesi = {**coll.sospesi, campo: "0"}
    return ""


def applica_lettura(coll, dati: dict | None, errore: str = "", ora=None) -> None:
    """Salva l'esito di una lettura (dati) o di un errore di rete (errore)."""
    ora = ora or timezone.now()
    coll.controllato_il = ora
    if dati is None:
        coll.errore = errore[:300]
        _cambia_stato(coll, "non_raggiungibile", ora)
        coll.save()
        return
    coll.disponibilita = dati["disponibilita"][:30]
    coll.esecuzione = dati["esecuzione"][:30]
    coll.modalita = dati["modalita"][:30]
    coll.emergenza = dati["emergenza"][:30]
    coll.programma = dati["programma"]
    coll.allarmi = dati["allarmi"]
    coll.letto_il = ora
    avvisi = [
        _avanza_contatore(coll, "ore", dati["ore"], coll.contatore_ore, ora, "ore di lavoro"),
        _avanza_contatore(coll, "pezzi", dati["pezzi"], coll.contatore_pezzi, ora, "pezzi"),
    ]
    coll.errore = " · ".join(a for a in avvisi if a)[:300]
    _cambia_stato(coll, stato_da(dati), ora)
    coll.save()


def _leggi(coll) -> tuple[int, dict | None, str]:
    try:
        return coll.pk, leggi_current(scarica(coll.url_agent, coll.dispositivo), coll.dispositivo), ""
    except MTConnectError as exc:
        return coll.pk, None, str(exc)
    except Exception as exc:  # noqa: BLE001 - un agent strano non deve fermare gli altri
        logger.warning("MTConnect: lettura %s non riuscita", coll.url_agent, exc_info=True)
        return coll.pk, None, f"Lettura non riuscita ({type(exc).__name__})."


def leggi_tutti(ora=None) -> dict:
    from assets.models import CollegamentoMTConnect

    ora = ora or timezone.now()
    collegamenti = {c.pk: c for c in CollegamentoMTConnect.objects.filter(
        attivo=True, fonte=CollegamentoMTConnect.FONTE_MTCONNECT).select_related(
        "asset", "contatore_ore", "contatore_pezzi")}
    if not collegamenti:
        return {"collegamenti": 0}
    with ThreadPoolExecutor(max_workers=min(MAX_THREADS, len(collegamenti))) as pool:
        esiti = list(pool.map(_leggi, collegamenti.values()))
    conteggi: dict[str, int] = {}
    for pk, dati, errore in esiti:
        coll = collegamenti[pk]
        applica_lettura(coll, dati, errore, ora)
        conteggi[coll.stato] = conteggi.get(coll.stato, 0) + 1
    return {"collegamenti": len(collegamenti), **conteggi}


# --- Dal collector OPC UA ------------------------------------------------------------------------


def _allarmi_collector(righe) -> list[dict]:
    out = []
    for a in righe or []:
        if not isinstance(a, dict):
            continue
        try:
            severita = int(a.get("severita") or 0)
        except (TypeError, ValueError):
            severita = 0
        out.append({
            "livello": "allarme" if severita >= SEVERITA_ALLARME else "avviso",
            "tipo": str(a.get("tipo") or "")[:60],
            "codice": str(a.get("codice") or "")[:60],
            "testo": " ".join(str(a.get("testo") or "").split())[:200],
            "dal": str(a.get("dal") or "")[:40],
            "severita": severita,
        })
    out.sort(key=lambda a: -a["severita"])
    return out[:20]


def applica_stato_collector(coll, dati: dict, quando, ora=None) -> None:
    """Stato inviato dal collector OPC UA: ``quando`` è l'inizio dello stato sulla macchina."""
    ora = ora or timezone.now()
    coll.controllato_il = ora
    coll.letto_il = ora
    coll.errore = ""
    coll.programma = str(dati.get("programma") or "")[:200]
    coll.modalita = str(dati.get("modalita") or "")[:30]
    coll.esecuzione = str(dati.get("esecuzione") or "")[:30]
    coll.allarmi = _allarmi_collector(dati.get("allarmi"))
    pezzi = _numero(dati.get("pezzi")) if dati.get("pezzi") is not None else None
    coll.pezzi_grezzo = pezzi.quantize(Decimal("0.01")) if pezzi is not None else None
    if coll.pk is None:
        coll.save()  # primo invio: il periodo di stato ha bisogno del collegamento salvato
    _cambia_stato(coll, STATI_COLLECTOR[dati["stato"]], min(quando, ora))
    coll.save()


# --- Lettura per le pagine ----------------------------------------------------------------------


def ore_in_lavoro_oggi(coll, ora=None) -> Decimal:
    from assets.models import PeriodoStatoMacchina

    ora = ora or timezone.now()
    inizio = timezone.localtime(ora).replace(hour=0, minute=0, second=0, microsecond=0)
    totale = timedelta(0)
    for dal, al in PeriodoStatoMacchina.objects.filter(collegamento=coll, stato="in_lavoro").filter(
        dal__lt=ora).exclude(al__lt=inizio).values_list("dal", "al"):
        totale += min(al or ora, ora) - max(dal, inizio)
    return (Decimal(totale.total_seconds()) / Decimal(3600)).quantize(Decimal("0.1"))


def attuale(coll, ora=None) -> bool:
    ora = ora or timezone.now()
    return bool(coll.controllato_il and ora - coll.controllato_il <= VECCHIO_DOPO)


BADGE_STATO = {
    "in_lavoro": "ok", "setup": "ok", "pronta": "warn", "ferma": "warn",
    "allarme": "danger", "emergenza": "danger",
}


def _durata(intervallo: timedelta) -> str:
    minuti = max(int(intervallo.total_seconds() // 60), 0)
    if minuti < 60:
        return f"{minuti} min"
    ore, minuti = divmod(minuti, 60)
    if ore < 24:
        return f"{ore} h {minuti:02d} min"
    return f"{ore // 24} g {ore % 24} h"


def per_scheda(asset_id: int, ora=None) -> dict | None:
    """Riquadro «Dal controllo della macchina» nella scheda dell'asset: lo stesso stato della mappa
    officina più gli ultimi cambi di stato. None se l'asset non ha un collegamento attivo."""
    from assets.models import PeriodoStatoMacchina

    ora = ora or timezone.now()
    dati = per_mappa([asset_id], ora).get(asset_id)
    if dati is None:
        return None
    periodi = []
    for p in PeriodoStatoMacchina.objects.filter(collegamento__asset_id=asset_id, collegamento__attivo=True)[:10]:
        periodi.append({
            "label": STATO_ETICHETTE.get(p.stato, p.stato),
            "badge": BADGE_STATO.get(p.stato, "muted"),
            "dal": timezone.localtime(p.dal).strftime("%d/%m %H:%M"),
            "al": timezone.localtime(p.al).strftime("%d/%m %H:%M") if p.al else "",
            "durata": _durata((p.al or ora) - p.dal),
        })
    return {**dati, "badge": BADGE_STATO.get(dati["stato"], "muted"), "periodi": periodi}


def per_mappa(asset_ids, ora=None) -> dict[int, dict]:
    """asset_id → stato dal controllo per la mappa officina (solo collegamenti attivi)."""
    from assets.models import CollegamentoMTConnect

    ora = ora or timezone.now()
    out = {}
    for coll in CollegamentoMTConnect.objects.filter(asset_id__in=list(asset_ids), attivo=True):
        fresco = attuale(coll, ora)
        out[coll.asset_id] = {
            "fonte": coll.get_fonte_display(),
            "allarme": fresco and coll.stato in STATI_ALLARME,
            "stato": coll.stato if fresco else "vecchio",
            "label": STATO_ETICHETTE.get(coll.stato, coll.stato) if fresco else "Dato non aggiornato",
            "programma": coll.programma,
            "modalita": coll.modalita,
            "pezzi": str(coll.pezzi_grezzo.normalize()) if coll.pezzi_grezzo is not None else "",
            "allarmi": coll.allarmi if fresco else [],
            "dal": timezone.localtime(coll.stato_dal).strftime("%d/%m %H:%M") if coll.stato_dal else "",
            "letto": timezone.localtime(coll.controllato_il).strftime("%d/%m %H:%M") if coll.controllato_il else "",
            "ore_oggi": str(ore_in_lavoro_oggi(coll, ora)).replace(".", ","),
            "errore": coll.errore,
        }
    return out
