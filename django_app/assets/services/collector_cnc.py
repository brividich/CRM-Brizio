"""Collector OPC UA delle CNC gestito dal portale: token, rete ammessa, macchine da leggere.

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
    """Le macchine che questo collector deve leggere, nel formato di machines.json."""
    from assets.models import CollegamentoMTConnect

    qs = (CollegamentoMTConnect.objects.filter(fonte=CollegamentoMTConnect.FONTE_COLLECTOR, attivo=True)
          .exclude(opcua_host="").select_related("asset").order_by("codice", "asset__name"))
    if not client.all_meter_assets:
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
