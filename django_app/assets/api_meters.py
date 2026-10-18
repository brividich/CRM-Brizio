"""Ingest delle letture dei contatori dai collector (es. OPC UA delle CNC DMG MORI).

``POST /api/assets/contatori/ingest/`` — JSON, **solo rete interna**:

* autenticazione per collector: ``Authorization: Bearer <token>``; a DB c'e' solo
  l'hash SHA-256 (``MeterIngestClient``), confronto con ``hmac.compare_digest``;
* client IP ammessi in ``ASSETS_METER_INGEST_ALLOWED_IPS`` (IP o reti CIDR);
* al massimo 500 letture per chiamata (413 oltre), esito per riga:
  ``accepted`` / ``ignored_older`` / ``rejected`` con il motivo.

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
from django.utils.dateparse import parse_datetime
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError
from ninja.security import HttpBearer

from core.net import client_ip

from .models import Asset, AssetMeter, MeterIngestClient
from .services.meters import MeterReadingOlder, MeterReadingRejected, record_meter_reading

logger = logging.getLogger(__name__)

MAX_READINGS = 500

SOURCE_BY_CLIENT_DEFAULT = AssetMeter.SOURCE_OPCUA


def _ip_allowed(ip: str | None) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in getattr(settings, "ASSETS_METER_INGEST_ALLOWED_IPS", ["127.0.0.1", "::1"]) or []:
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
    """Bearer token del collector. Rete non ammessa = 403, token errato = 401."""

    def authenticate(self, request, token):
        if not _ip_allowed(client_ip(request)):
            raise HttpError(403, "Rete non autorizzata per l'invio delle letture.")
        token = (token or "").strip()
        if not token:
            return None
        digest = MeterIngestClient.hash_token(token)
        client = MeterIngestClient.objects.filter(token_hash=digest, is_active=True).first()
        if client is None or not hmac.compare_digest(client.token_hash, digest):
            return None
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


def _row_result(index: int, row: dict, status: str, reason: str = "") -> dict:
    return {
        "index": index,
        "asset_tag": str(row.get("asset_tag") or ""),
        "meter_type": str(row.get("meter_type") or ""),
        "status": status,
        "reason": reason,
    }


@api.post("/ingest/")
def ingest(request, payload: IngestPayload):
    client: MeterIngestClient = request.auth
    readings = payload.readings
    if len(readings) > MAX_READINGS:
        raise HttpError(413, f"Al massimo {MAX_READINGS} letture per chiamata.")

    tags = {str(row.get("asset_tag") or "").strip() for row in readings if isinstance(row, dict)}
    assets = {asset.asset_tag: asset for asset in Asset.objects.filter(asset_tag__in=[t for t in tags if t])}
    allowed_ids = None if client.all_meter_assets else set(client.allowed_assets.values_list("id", flat=True))
    meter_types = dict(AssetMeter.METER_TYPE_CHOICES)

    results = []
    for index, row in enumerate(readings):
        if not isinstance(row, dict):
            results.append(_row_result(index, {}, "rejected", "riga non valida"))
            continue
        tag = str(row.get("asset_tag") or "").strip()
        meter_type = str(row.get("meter_type") or "").strip().upper()
        asset = assets.get(tag)
        if asset is None:
            results.append(_row_result(index, row, "rejected", "asset sconosciuto"))
            continue
        if allowed_ids is not None and asset.id not in allowed_ids:
            results.append(_row_result(index, row, "rejected", "asset non consentito a questo collector"))
            continue
        if meter_type not in meter_types:
            results.append(_row_result(index, row, "rejected", "tipo di contatore non valido"))
            continue
        meter = AssetMeter.objects.filter(asset=asset, meter_type=meter_type).first()
        if meter is None:
            results.append(_row_result(index, row, "rejected", "contatore non configurato sull'asset"))
            continue
        raw_read_at = row.get("read_at")
        read_at = parse_datetime(str(raw_read_at)) if raw_read_at else None
        if read_at is None or timezone.is_naive(read_at):
            results.append(_row_result(index, row, "rejected", "read_at mancante o senza fuso orario (ISO 8601 con offset)"))
            continue
        try:
            record_meter_reading(
                meter,
                row.get("value"),
                read_at=read_at,
                source=SOURCE_BY_CLIENT_DEFAULT,
                user=None,
                note=f"Collector «{client.name}»",
            )
        except MeterReadingOlder as exc:
            results.append(_row_result(index, row, "ignored_older", str(exc)))
        except MeterReadingRejected as exc:
            results.append(_row_result(index, row, "rejected", str(exc)))
        else:
            results.append(_row_result(index, row, "accepted"))

    MeterIngestClient.objects.filter(pk=client.pk).update(last_seen_at=timezone.now())
    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("accepted", "ignored_older", "rejected")}
    return {"results": results, **summary}
