from __future__ import annotations

import logging
import os
from urllib.parse import quote, unquote
from uuid import uuid4

import requests
from django.conf import settings
from django.utils import timezone

from config.env_config import get_first_env_value
from core.graph_utils import acquire_graph_token

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_TIMEOUT_SECONDS = 20


class SharePointPublicLinkError(RuntimeError):
    pass


def _clean(value: object) -> str:
    return str(value or "").strip()


def _env_or_setting(key: str, default: object = "") -> str:
    value = os.getenv(key)
    if value is not None:
        return _clean(value)
    return _clean(getattr(settings, key, default))


def _env_bool_or_setting(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return bool(getattr(settings, key, default))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _graph_credentials() -> dict[str, str]:
    return {
        "tenant_id": get_first_env_value("GRAPH_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": get_first_env_value("GRAPH_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": get_first_env_value("GRAPH_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
    }


def _asset_public_settings() -> dict[str, str]:
    return {
        "allowed_root_name": _env_or_setting("SHAREPOINT_ASSET_ALLOWED_ROOT_NAME", "ASSET CN") or "ASSET CN",
        "allowed_root_drive_id": _env_or_setting("SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID", ""),
        "allowed_root_item_id": _env_or_setting("SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID", ""),
        "site_id": _env_or_setting("SHAREPOINT_ASSET_SITE_ID", "") or get_first_env_value("GRAPH_SITE_ID"),
        "drive_id": _env_or_setting("SHAREPOINT_ASSET_DRIVE_ID", ""),
    }


def _graph_headers() -> dict[str, str]:
    credentials = _graph_credentials()
    if not all(credentials.values()):
        raise SharePointPublicLinkError("Configurazione Graph incompleta.")
    token = acquire_graph_token(credentials["tenant_id"], credentials["client_id"], credentials["client_secret"])
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _graph_error_message(response: requests.Response) -> str:
    retry = _clean(response.headers.get("Retry-After")) if hasattr(response, "headers") else ""
    body = _clean(getattr(response, "text", ""))[:500]
    message = f"Graph HTTP {response.status_code}"
    if retry:
        message = f"{message} (Retry-After {retry}s)"
    if body:
        message = f"{message}: {body}"
    return message


def _drive_base_url_for_resolution() -> str:
    cfg = _asset_public_settings()
    if cfg["drive_id"]:
        return f"{GRAPH_BASE_URL}/drives/{quote(cfg['drive_id'], safe='')}"
    if cfg["site_id"]:
        return f"{GRAPH_BASE_URL}/sites/{quote(cfg['site_id'], safe='')}/drive"
    raise SharePointPublicLinkError("SHAREPOINT_ASSET_DRIVE_ID o SHAREPOINT_ASSET_SITE_ID non configurato.")


def _graph_get_drive_item(drive_id: str, item_id: str) -> dict:
    url = f"{GRAPH_BASE_URL}/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}"
    response = requests.get(
        f"{url}?$select=id,name,folder,parentReference,webUrl",
        headers=_graph_headers(),
        timeout=GRAPH_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise SharePointPublicLinkError(_graph_error_message(response))
    return response.json()


def _graph_get_drive_item_by_path(path: str) -> dict:
    normalized = normalize_sharepoint_path(path)
    if not normalized:
        raise SharePointPublicLinkError("Percorso SharePoint asset mancante.")
    url = f"{_drive_base_url_for_resolution()}/root:/{quote(normalized, safe='/')}"
    response = requests.get(
        f"{url}?$select=id,name,folder,parentReference,webUrl",
        headers=_graph_headers(),
        timeout=GRAPH_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise SharePointPublicLinkError(_graph_error_message(response))
    return response.json()


def normalize_sharepoint_path(value: object) -> str:
    text = _clean(value).replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.strip("/")


def _path_segments_from_parent_reference(parent_reference: dict, item_name: str = "") -> list[str]:
    raw_path = unquote(_clean(parent_reference.get("path")))
    path = ""
    if "root:" in raw_path:
        path = raw_path.split("root:", 1)[1]
    elif ":/" in raw_path:
        path = raw_path.split(":/", 1)[1]
    segments = [part for part in normalize_sharepoint_path(path).split("/") if part]
    name = _clean(item_name)
    if name:
        segments.append(name)
    return segments


def _asset_path_is_under_allowed_root(asset) -> bool:
    root_name = _asset_public_settings()["allowed_root_name"].casefold()
    segments = [part for part in normalize_sharepoint_path(getattr(asset, "sharepoint_folder_path", "")).split("/") if part]
    return bool(segments and segments[0].casefold() == root_name)


def _item_is_descendant_of_root(drive_id: str, item: dict, root_item_id: str) -> bool:
    parent_id = _clean((item.get("parentReference") or {}).get("id"))
    seen: set[str] = set()
    for _ in range(50):
        if not parent_id or parent_id in seen:
            return False
        if parent_id == root_item_id:
            return True
        seen.add(parent_id)
        parent = _graph_get_drive_item(drive_id, parent_id)
        parent_id = _clean((parent.get("parentReference") or {}).get("id"))
    return False


def create_anonymous_view_link_for_drive_item(drive_id: str, item_id: str) -> dict:
    drive_id = _clean(drive_id)
    item_id = _clean(item_id)
    if not drive_id or not item_id:
        raise SharePointPublicLinkError("drive_id e item_id sono obbligatori.")
    url = f"{GRAPH_BASE_URL}/drives/{quote(drive_id, safe='')}/items/{quote(item_id, safe='')}/createLink"
    payload = {
        "type": "view",
        "scope": "anonymous",
        "retainInheritedPermissions": True,
    }
    response = requests.post(
        url,
        headers=_graph_headers(),
        json=payload,
        timeout=GRAPH_TIMEOUT_SECONDS,
    )
    if response.status_code not in (200, 201):
        raise SharePointPublicLinkError(_graph_error_message(response))
    data = response.json() if _clean(response.text) else {}
    public_url = _clean((data.get("link") or {}).get("webUrl"))
    if not public_url:
        raise SharePointPublicLinkError("Graph non ha restituito link.webUrl per il link pubblico.")
    return {
        "ok": True,
        "public_url": public_url,
        "permission_id": _clean(data.get("id")),
        "raw": data,
    }


def resolve_asset_drive_item_ids(asset, *, save: bool = False) -> dict:
    if _clean(getattr(asset, "sharepoint_drive_id", "")) and _clean(getattr(asset, "sharepoint_item_id", "")):
        return {"ok": True, "status": "existing", "drive_id": asset.sharepoint_drive_id, "item_id": asset.sharepoint_item_id}
    if not _asset_path_is_under_allowed_root(asset):
        return {"ok": False, "status": "not_in_asset_cn", "error": "Percorso fuori dalla root SharePoint consentita."}
    item = _graph_get_drive_item_by_path(getattr(asset, "sharepoint_folder_path", ""))
    parent_reference = item.get("parentReference") or {}
    drive_id = _clean(parent_reference.get("driveId")) or _asset_public_settings()["drive_id"]
    item_id = _clean(item.get("id"))
    if not drive_id or not item_id:
        return {"ok": False, "status": "missing_drive_item", "error": "driveId/itemId non disponibili dalla risposta Graph."}
    if save:
        asset.sharepoint_drive_id = drive_id
        asset.sharepoint_item_id = item_id
        asset.save(update_fields=["sharepoint_drive_id", "sharepoint_item_id", "updated_at"])
    return {"ok": True, "status": "resolved", "drive_id": drive_id, "item_id": item_id}


def validate_asset_inside_allowed_root(asset) -> dict:
    drive_id = _clean(getattr(asset, "sharepoint_drive_id", ""))
    item_id = _clean(getattr(asset, "sharepoint_item_id", ""))
    if not drive_id or not item_id:
        return {"ok": False, "status": "missing_drive_item", "error": "Asset senza drive_id/item_id SharePoint."}
    cfg = _asset_public_settings()
    if cfg["allowed_root_drive_id"] and drive_id != cfg["allowed_root_drive_id"]:
        return {"ok": False, "status": "not_in_asset_cn", "error": "Drive SharePoint diverso dalla root consentita."}
    try:
        item = _graph_get_drive_item(drive_id, item_id)
    except SharePointPublicLinkError as exc:
        return {"ok": False, "status": "graph_error", "error": str(exc)}
    if "folder" not in item:
        return {"ok": False, "status": "not_folder", "error": "Il driveItem SharePoint non e una cartella."}
    parent_reference = item.get("parentReference") or {}
    if cfg["allowed_root_item_id"]:
        if not _item_is_descendant_of_root(drive_id, item, cfg["allowed_root_item_id"]):
            return {"ok": False, "status": "not_in_asset_cn", "error": "Cartella fuori dalla root item consentita."}
    else:
        segments = _path_segments_from_parent_reference(parent_reference, _clean(item.get("name")))
        if not segments or segments[0].casefold() != cfg["allowed_root_name"].casefold():
            return {"ok": False, "status": "not_in_asset_cn", "error": "Cartella fuori dalla root ASSET CN."}
    return {"ok": True, "status": "eligible", "item": item}


def ensure_asset_public_share_link(asset, *, save: bool = True, force: bool = False) -> dict:
    now = timezone.now()
    if not _env_bool_or_setting("SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED", False):
        return {"ok": False, "status": "feature_disabled", "error": "Feature link pubblici SharePoint disattivata."}
    if not _clean(getattr(asset, "sharepoint_drive_id", "")) or not _clean(getattr(asset, "sharepoint_item_id", "")):
        return {"ok": False, "status": "missing_drive_item", "error": "Asset senza drive_id/item_id SharePoint."}
    if _clean(getattr(asset, "sharepoint_public_url", "")) and not force:
        return {"ok": True, "status": "existing", "public_url": asset.sharepoint_public_url}
    validation = validate_asset_inside_allowed_root(asset)
    if not validation["ok"]:
        if save:
            asset.sharepoint_public_error = validation.get("error", "Validazione root SharePoint fallita.")
            asset.sharepoint_public_last_checked_at = now
            asset.save(update_fields=["sharepoint_public_error", "sharepoint_public_last_checked_at", "updated_at"])
        return validation
    try:
        created = create_anonymous_view_link_for_drive_item(asset.sharepoint_drive_id, asset.sharepoint_item_id)
    except Exception as exc:
        logger.warning("Creazione link pubblico SharePoint fallita per asset_id=%s: %s", getattr(asset, "pk", ""), exc)
        if save:
            asset.sharepoint_public_error = str(exc)[:1000]
            asset.sharepoint_public_last_checked_at = now
            asset.save(update_fields=["sharepoint_public_error", "sharepoint_public_last_checked_at", "updated_at"])
        return {"ok": False, "status": "error", "error": str(exc)}
    if save:
        if not asset.public_qr_token:
            asset.public_qr_token = uuid4().hex
        asset.sharepoint_public_url = created["public_url"]
        asset.sharepoint_public_link_id = created["permission_id"]
        asset.sharepoint_public_enabled = True
        if not asset.sharepoint_public_created_at:
            asset.sharepoint_public_created_at = now
        asset.sharepoint_public_last_checked_at = now
        asset.sharepoint_public_error = ""
        asset.save(
            update_fields=[
                "sharepoint_public_url",
                "sharepoint_public_link_id",
                "sharepoint_public_enabled",
                "sharepoint_public_created_at",
                "sharepoint_public_last_checked_at",
                "sharepoint_public_error",
                "public_qr_token",
                "updated_at",
            ]
        )
    return {"ok": True, "status": "created", "public_url": created["public_url"], "permission_id": created["permission_id"]}
