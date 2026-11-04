"""Impostazioni del modulo (SiteConfig) e pubblicazione del PDF su SharePoint.

La pubblicazione sostituisce l'upload di ``sharepoint_uploader.py`` dello script
sul diskstation: stesso file (``CN-PRESENZE.pdf``) nella stessa raccolta, caricato
con le credenziali Graph del portale (``GRAPH_*`` nel ``.env``; l'app deve avere
``Sites.ReadWrite.All`` o ``Sites.Selected`` con scrittura sul sito).
"""
from __future__ import annotations

import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# chiave SiteConfig: (predefinito, descrizione)
CAMPI = {
    "presenti_sp_attivo": ("0", "Presenti: pubblica il PDF su SharePoint (1/0)"),
    "presenti_sp_hostname": ("costruzioninovicrom.sharepoint.com", "Presenti: hostname SharePoint"),
    "presenti_sp_sito": ("", "Presenti: percorso del sito (/sites/Nome, vuoto = sito radice)"),
    "presenti_sp_raccolta": ("CN Documentazione", "Presenti: raccolta documenti"),
    "presenti_sp_cartella": ("", "Presenti: cartella nella raccolta (vuoto = radice)"),
    "presenti_sp_nome_file": ("CN-PRESENZE.pdf", "Presenti: nome del file pubblicato"),
    "presenti_avviso_uscite_attivo": ("1", "Presenti: avvisa il capo delle uscite non timbrate (1/0)"),
    "presenti_sp_ultimo_esito": ("", "Presenti: esito dell'ultima pubblicazione"),
}

VERI = {"1", "true", "on", "si", "sì"}


def leggi(chiave: str) -> str:
    from core.models import SiteConfig

    predefinito = CAMPI[chiave][0]
    valore = SiteConfig.get(chiave, None)
    return predefinito if valore is None else str(valore).strip()


def scrivi(chiave: str, valore: str) -> None:
    from core.models import SiteConfig

    SiteConfig.set(chiave, str(valore or "").strip(), CAMPI[chiave][1])


def attivo(chiave: str) -> bool:
    return leggi(chiave).lower() in VERI


def tutte() -> dict[str, str]:
    return {k: leggi(k) for k in CAMPI}


def _intestazioni() -> dict[str, str]:
    from config.env_config import get_first_env_value
    from core.graph_utils import acquire_graph_token, is_placeholder_value

    tenant = get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID")
    client = get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID")
    segreto = get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
    if any(is_placeholder_value(v) for v in (tenant, client, segreto)):
        raise ValueError("Credenziali Microsoft Graph non configurate sul server.")
    return {"Authorization": f"Bearer {acquire_graph_token(tenant, client, segreto)}"}


def pubblica_su_sharepoint(contenuto: bytes, timeout: int = 60) -> str:
    """Carica il PDF nella raccolta configurata. Ritorna il ``webUrl`` del file."""
    import requests

    host = leggi("presenti_sp_hostname")
    sito = leggi("presenti_sp_sito").strip("/")
    raccolta = leggi("presenti_sp_raccolta")
    cartella = leggi("presenti_sp_cartella").strip("/")
    nome = leggi("presenti_sp_nome_file") or "CN-PRESENZE.pdf"
    if not host or not raccolta:
        raise ValueError("Hostname o raccolta SharePoint non impostati.")
    h = _intestazioni()

    url_sito = f"{GRAPH_BASE}/sites/{host}:/{quote(sito)}" if sito else f"{GRAPH_BASE}/sites/{host}"
    r = requests.get(url_sito, headers=h, timeout=timeout)
    r.raise_for_status()
    sito_id = r.json()["id"]

    r = requests.get(f"{GRAPH_BASE}/sites/{sito_id}/drives", headers=h, timeout=timeout)
    r.raise_for_status()
    drive_id = next((d["id"] for d in r.json().get("value", []) if d.get("name") == raccolta), None)
    if not drive_id:
        raise ValueError(f"Raccolta «{raccolta}» non trovata nel sito.")

    percorso = f"{cartella}/{nome}" if cartella else nome
    r = requests.put(
        f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(percorso)}:/content",
        headers={**h, "Content-Type": "application/pdf"}, data=contenuto, timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("webUrl", "")
