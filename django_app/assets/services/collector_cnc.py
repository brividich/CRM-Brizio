"""Collector OPC UA delle CNC gestito dal portale: token, rete ammessa, macchine da leggere.

Due modalità, scelte nella stessa pagina (``modalita``): **sul server del portale** il collector gira
dentro il portale (``manage.py collector_cnc``, attività di Windows all'avvio) e scrive direttamente
nel database; **su un PC dell'officina** parla con il portale via HTTP con il suo token. Una esclude
l'altra: con il collector sul server, l'elenco dato al PC è vuoto.

Tutto da «Asset › Configurazione › Macchine collegate» (amministratori del modulo Asset):

- **token del collector** (``MeterIngestClient``): creato o rigenerato qui, mostrato una volta
  sola; a DB solo l'hash. Ogni collector ha i suoi **IP ammessi** (oltre a quelli del .env);
- **macchine** (``CollegamentoMTConnect`` con fonte ``collector_opcua``): host e porta OPC UA,
  codice breve (es. DM6), utente e password OPC UA facoltativi (password cifrata con
  ``secret_box``). Il collector le scarica da ``GET /api/assets/contatori/ingest/config/``:
  sul suo PC restano solo indirizzo del portale e token.
"""
from __future__ import annotations

import ipaddress
import re

PURPOSE_OPCUA = "opcua-collector"
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")
_CODICE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")


# --- password OPC UA ---------------------------------------------------------------------------

def cifra(password: str) -> str:
    from security.services import secret_box

    return secret_box.encrypt(password, PURPOSE_OPCUA) if password else ""


def decifra(valore: str) -> str:
    from security.services import secret_box

    return secret_box.decrypt(valore, PURPOSE_OPCUA) if valore else ""


# --- validazioni -------------------------------------------------------------------------------

def valida_ips(testo: str) -> tuple[list[str], list[str]]:
    """(voci valide, errori) da un elenco di IP o reti CIDR separati da virgole, spazi o a capo."""
    voci, errori = [], []
    for voce in [v for v in re.split(r"[\s,;]+", testo or "") if v]:
        try:
            ipaddress.ip_network(voce, strict=False) if "/" in voce else ipaddress.ip_address(voce)
        except ValueError:
            errori.append(f"«{voce}» non è un IP o una rete (es. 192.168.23.50 o 192.168.23.0/24).")
            continue
        voci.append(voce)
    return voci[:50], errori


def valida_macchina(host: str, porta, codice: str) -> list[str]:
    errori = []
    if not _HOST_RE.match(host or ""):
        errori.append("Indirizzo OPC UA non valido: IP o nome della macchina (es. 192.168.23.115).")
    try:
        if not 1 <= int(porta) <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        errori.append("Porta OPC UA non valida (di solito 4840).")
    if codice and not _CODICE_RE.match(codice):
        errori.append("Codice non valido: lettere, cifre, punto, trattino (es. DM6).")
    return errori


# --- token -------------------------------------------------------------------------------------

def nuovo_token(client) -> str:
    """Genera e imposta un token nuovo; ritorna quello in chiaro (da mostrare una volta sola)."""
    token = client.issue_token()
    client.set_token(token)
    return token


# --- configurazione per il collector -------------------------------------------------------------

def nome_macchina(coll) -> str:
    return coll.codice or (coll.asset.internal_number or "").strip() or coll.asset.asset_tag


def macchine_per(client) -> list[dict]:
    """Le macchine che il collector deve leggere, nel formato di machines.json (client None = tutte)."""
    from assets.models import CollegamentoMTConnect

    qs = (CollegamentoMTConnect.objects.filter(fonte=CollegamentoMTConnect.FONTE_COLLECTOR, attivo=True)
          .exclude(opcua_host="").select_related("asset").order_by("codice", "asset__name"))
    if client is not None and not client.all_meter_assets:
        qs = qs.filter(asset__in=client.allowed_assets.all())
    out = []
    for coll in qs:
        asset = coll.asset
        out.append({
            "name": nome_macchina(coll),
            "ip": coll.opcua_host,
            "port": coll.opcua_porta or 4840,
            "serial": asset.serial_number or "",
            "model": asset.model or "",
            "department": asset.reparto or "",
            "asset_tag": asset.asset_tag,
            "username": coll.opcua_utente or "",
            "password": decifra(coll.opcua_password),
        })
    return out


def crea_contatori(asset) -> list[str]:
    """Crea i contatori Ore e Cicli che mancano sull'asset; ritorna i nomi di quelli creati."""
    from assets.models import AssetMeter

    creati = []
    for tipo, unita, nome in ((AssetMeter.METER_HOURS, "h", "Ore"), (AssetMeter.METER_CYCLES, "pezzi", "Cicli")):
        _meter, nuovo = AssetMeter.objects.get_or_create(
            asset=asset, meter_type=tipo,
            defaults={"unit_label": unita, "source": AssetMeter.SOURCE_OPCUA,
                      "notes": "Creato da Macchine collegate: lo aggiorna il collector OPC UA."})
        if nuovo:
            creati.append(nome)
    return creati



# --- dove gira il collector ----------------------------------------------------------------------

MODALITA_KEY = "assets.collector_cnc.modalita"
BATTITO_KEY = "assets.collector_cnc.battito"
MODALITA = {"pc": "Su un PC dell'officina", "server": "Sul server del portale"}
BATTITO_VECCHIO_MINUTI = 5


def modalita() -> str:
    from core.models import SiteConfig

    valore = SiteConfig.objects.filter(chiave=MODALITA_KEY).values_list("valore", flat=True).first()
    return valore if valore in MODALITA else "pc"


def imposta_modalita(valore: str) -> None:
    from core.models import SiteConfig

    if valore not in MODALITA:
        raise ValueError(valore)
    SiteConfig.objects.update_or_create(chiave=MODALITA_KEY, defaults={
        "valore": valore, "descrizione": "Dove gira il collector OPC UA delle CNC (pc | server)"})


def registra_battito(macchine: int, errore: str = "") -> None:
    """Il collector integrato è vivo: lo dice ogni minuto (pagina Macchine collegate, controllo infrastruttura)."""
    import json

    from django.utils import timezone

    from core.models import SiteConfig

    SiteConfig.objects.update_or_create(chiave=BATTITO_KEY, defaults={
        "valore": json.dumps({"at": timezone.now().isoformat(), "macchine": macchine, "errore": errore[:300]}),
        "descrizione": "Ultimo segnale del collector OPC UA integrato nel portale"})


def battito() -> dict:
    """``{"at": datetime|None, "macchine": int, "errore": str, "vivo": bool}`` del collector integrato."""
    import json
    from datetime import timedelta

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from core.models import SiteConfig

    valore = SiteConfig.objects.filter(chiave=BATTITO_KEY).values_list("valore", flat=True).first()
    try:
        dati = json.loads(valore) if valore else {}
    except ValueError:
        dati = {}
    at = parse_datetime(str(dati.get("at") or "")) if dati.get("at") else None
    vivo = bool(at and timezone.now() - at <= timedelta(minutes=BATTITO_VECCHIO_MINUTI))
    return {"at": at, "macchine": int(dati.get("macchine") or 0), "errore": str(dati.get("errore") or ""), "vivo": vivo}


# --- letture e stati: stessa logica per l'API (collector sul PC) e per il collector integrato ------

def _riga(index, row, status, reason="", **extra):
    return {"index": index, "asset_tag": str(row.get("asset_tag") or ""), **extra, "status": status, "reason": reason}


def _assets_e_consentiti(righe, client):
    from assets.models import Asset

    tags = {str(row.get("asset_tag") or "").strip() for row in righe if isinstance(row, dict)}
    assets = {asset.asset_tag: asset for asset in Asset.objects.filter(asset_tag__in=[t for t in tags if t])}
    consentiti = None if client is None or client.all_meter_assets else set(client.allowed_assets.values_list("id", flat=True))
    return assets, consentiti


def applica_letture(readings, client=None, nota: str = "", source: str = "") -> dict:
    """Letture dei contatori ``[{asset_tag, meter_type, value, read_at}]``: esito per riga."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from assets.models import AssetMeter

    from .meters import MeterReadingOlder, MeterReadingRejected, record_meter_reading

    assets, consentiti = _assets_e_consentiti(readings, client)
    tipi = dict(AssetMeter.METER_TYPE_CHOICES)
    source = source or AssetMeter.SOURCE_OPCUA
    results = []
    for index, row in enumerate(readings):
        if not isinstance(row, dict):
            results.append(_riga(index, {}, "rejected", "riga non valida", meter_type=""))
            continue
        meter_type = str(row.get("meter_type") or "").strip().upper()
        extra = {"meter_type": str(row.get("meter_type") or "")}
        asset = assets.get(str(row.get("asset_tag") or "").strip())
        if asset is None:
            results.append(_riga(index, row, "rejected", "asset sconosciuto", **extra))
            continue
        if consentiti is not None and asset.id not in consentiti:
            results.append(_riga(index, row, "rejected", "asset non consentito a questo collector", **extra))
            continue
        if meter_type not in tipi:
            results.append(_riga(index, row, "rejected", "tipo di contatore non valido", **extra))
            continue
        meter = AssetMeter.objects.filter(asset=asset, meter_type=meter_type).first()
        if meter is None:
            results.append(_riga(index, row, "rejected", "contatore non configurato sull'asset", **extra))
            continue
        read_at = parse_datetime(str(row.get("read_at"))) if row.get("read_at") else None
        if read_at is None or timezone.is_naive(read_at):
            results.append(_riga(index, row, "rejected", "read_at mancante o senza fuso orario (ISO 8601 con offset)", **extra))
            continue
        try:
            record_meter_reading(meter, row.get("value"), read_at=read_at, source=source, user=None, note=nota)
        except MeterReadingOlder as exc:
            results.append(_riga(index, row, "ignored_older", str(exc), **extra))
        except MeterReadingRejected as exc:
            results.append(_riga(index, row, "rejected", str(exc), **extra))
        else:
            results.append(_riga(index, row, "accepted", **extra))
    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("accepted", "ignored_older", "rejected")}
    return {"results": results, **summary}


def applica_stati(macchine, client=None) -> dict:
    """Stato delle CNC ``[{asset_tag, stato, dal, programma, …}]``: esito per riga."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from assets.models import CollegamentoMTConnect

    from . import mtconnect

    assets, consentiti = _assets_e_consentiti(macchine, client)
    ora = timezone.now()
    results = []
    for index, row in enumerate(macchine):
        if not isinstance(row, dict):
            results.append(_riga(index, {}, "rejected", "riga non valida"))
            continue
        asset = assets.get(str(row.get("asset_tag") or "").strip())
        if asset is None:
            results.append(_riga(index, row, "rejected", "asset sconosciuto"))
            continue
        if consentiti is not None and asset.id not in consentiti:
            results.append(_riga(index, row, "rejected", "asset non consentito a questo collector"))
            continue
        stato = str(row.get("stato") or "").strip().upper()
        if stato not in mtconnect.STATI_COLLECTOR:
            results.append(_riga(index, row, "rejected", "stato non valido"))
            continue
        dal = parse_datetime(str(row.get("dal") or "")) if row.get("dal") else None
        if dal is not None and timezone.is_naive(dal):
            results.append(_riga(index, row, "rejected", "dal senza fuso orario (ISO 8601 con offset)"))
            continue
        coll = CollegamentoMTConnect.objects.filter(asset=asset).first()
        if coll is None:
            coll = CollegamentoMTConnect(asset=asset, fonte=CollegamentoMTConnect.FONTE_COLLECTOR)
        elif coll.fonte != CollegamentoMTConnect.FONTE_COLLECTOR:
            if coll.attivo:
                results.append(_riga(index, row, "rejected", "macchina letta dal portale via MTConnect"))
                continue
            coll.fonte = CollegamentoMTConnect.FONTE_COLLECTOR
        elif not coll.attivo:
            results.append(_riga(index, row, "ignored", "lettura sospesa nel portale"))
            continue
        mtconnect.applica_stato_collector(coll, {**row, "stato": stato}, dal or ora, ora)
        results.append(_riga(index, row, "accepted"))
    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("accepted", "ignored", "rejected")}
    return {"results": results, **summary}
