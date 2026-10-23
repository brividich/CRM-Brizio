"""Ingest delle letture dei contatori dai collector (es. OPC UA delle CNC DMG MORI).

``POST /api/assets/contatori/ingest/`` — JSON, **solo rete interna**:

* autenticazione per collector: ``Authorization: Bearer <token>``; a DB c'e' solo
  l'hash SHA-256 (``MeterIngestClient``), confronto con ``hmac.compare_digest``;
* client IP ammessi: quelli del collector scritti nel portale (Macchine collegate) più
  ``ASSETS_METER_INGEST_ALLOWED_IPS`` del .env (IP o reti CIDR);
* al massimo 500 letture per chiamata (413 oltre), esito per riga:
  ``accepted`` / ``ignored_older`` / ``rejected`` con il motivo.

``POST /api/assets/contatori/ingest/stato/`` — stato reale delle CNC dallo stesso collector
(stessa autenticazione, stessa rete, stessi asset consentiti), vedi ``ingest_stato``.

``GET /api/assets/contatori/ingest/config/`` — le macchine che il collector deve leggere,
scritte nel portale (host e porta OPC UA, codice, credenziali OPC UA), vedi ``ingest_config``.

Il percorso e' in ``MIDDLEWARE_EXEMPT_PREFIXES`` (niente sessione: e' una macchina
a chiamare), quindi l'unica protezione e' qui. Non pubblicarlo su Entra
Application Proxy (vedi docs/ai/05_SECURITY_BOUNDARIES.md). Contratto e esempi:
docs/moduli/assets_contatori_ingest.md.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
from typing import Any, List

from django.conf import settings
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import HttpBearer

from core.net import client_ip

from .models import AssetMeter, MeterIngestClient

logger = logging.getLogger(__name__)

MAX_READINGS = 500

SOURCE_BY_CLIENT_DEFAULT = AssetMeter.SOURCE_OPCUA


def _ip_allowed(ip: str | None, client: MeterIngestClient | None = None) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    voci = list(getattr(settings, "ASSETS_METER_INGEST_ALLOWED_IPS", ["127.0.0.1", "::1"]) or [])
    if client is not None:
        voci += client.allowed_ips_list
    for entry in voci:
        entry = str(entry).strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if address in ipaddress.ip_network(entry, strict=False):
                    return True
            elif address == ipaddress.ip_address(entry):
                return True
        except ValueError:
            logger.warning("ASSETS_METER_INGEST_ALLOWED_IPS: voce non valida %r", entry)
    return False


class CollectorAuth(HttpBearer):
    """Bearer token del collector. Token errato = 401, rete non ammessa per quel collector = 403.

    Gli IP ammessi sono per collector (scritti nel portale) più quelli del .env: per questo il
    token si controlla prima della rete.
    """

    def authenticate(self, request, token):
        token = (token or "").strip()
        if not token:
            return None
        digest = MeterIngestClient.hash_token(token)
        client = MeterIngestClient.objects.filter(token_hash=digest, is_active=True).first()
        if client is None or not hmac.compare_digest(client.token_hash, digest):
            return None
        if not _ip_allowed(client_ip(request), client):
            raise HttpError(403, "Rete non autorizzata per questo collector.")
        return client


api = NinjaAPI(
    title="Contatori asset — ingest",
    version="1.0.0",
    urls_namespace="assets_meters_api",
    auth=CollectorAuth(),
    docs_url=None,
    openapi_url=None,
)


class IngestPayload(Schema):
    # Righe lasciate «grezze»: ogni riga ha il suo esito, una riga sbagliata non
    # fa rifiutare tutto il lotto.
    readings: List[dict[str, Any]]


@api.post("/ingest/")
def ingest(request, payload: IngestPayload):
    from .services.collector_cnc import applica_letture

    client: MeterIngestClient = request.auth
    if len(payload.readings) > MAX_READINGS:
        raise HttpError(413, f"Al massimo {MAX_READINGS} letture per chiamata.")
    esito = applica_letture(payload.readings, client, nota=f"Collector «{client.name}»", source=SOURCE_BY_CLIENT_DEFAULT)
    MeterIngestClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
    return esito


# --- Stato delle macchine dal collector OPC UA ---------------------------------------------------

MAX_MACCHINE = 100


class StatoPayload(Schema):
    macchine: List[dict[str, Any]]


@api.post("/ingest/stato/")
def ingest_stato(request, payload: StatoPayload):
    """Stato reale delle CNC dal collector OPC UA (``assets/collector_cnc``): stessa autenticazione,
    stessa rete e stessi asset consentiti delle letture dei contatori.

    Una riga per macchina: ``asset_tag``, ``stato`` (LAVORO, SETUP, INTERROTTA, FERMA, ALLARME,
    EMERGENZA, OFFLINE), ``dal`` (inizio dello stato, ISO 8601 con fuso), facoltativi
    ``programma``, ``modalita``, ``esecuzione``, ``pezzi``, ``allarmi`` [{codice, testo, severita, dal}].
    La macchina compare in «Macchine collegate» al primo invio.
    """
    from .services.collector_cnc import applica_stati

    client: MeterIngestClient = request.auth
    if len(payload.macchine) > MAX_MACCHINE:
        raise HttpError(413, f"Al massimo {MAX_MACCHINE} macchine per chiamata.")
    esito = applica_stati(payload.macchine, client)
    MeterIngestClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
    return esito


@api.get("/ingest/config/")
def ingest_config(request):
    """Le macchine che questo collector deve leggere (host/porta OPC UA, codice, credenziali OPC UA),
    scritte in «Macchine collegate». Solo quelle con fonte «Collector OPC UA», attive, con l'host
    e consentite al collector. La password OPC UA viaggia in chiaro solo qui, verso il collector
    autenticato dalla rete ammessa (in HTTPS)."""
    from .services.collector_cnc import macchine_per, modalita

    client: MeterIngestClient = request.auth
    MeterIngestClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
    # Con il collector integrato nel portale, quello del PC non legge niente: mai due letture.
    macchine = macchine_per(client) if modalita() == "pc" else []
    return {"collector": client.name, "modalita": modalita(), "machines": macchine}
