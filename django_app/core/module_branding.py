from __future__ import annotations

import os
from urllib.parse import urlsplit

from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from core.audit import log_action
from core.models import SiteConfig
from core.module_registry import (
    get_module_branding,
    get_module_definition,
    module_branding_siteconfig_keys,
    resolve_module_label,
)
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime


_LOGO_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
_LOGO_ALLOWED_MIMES = {"image/png", "image/jpeg", "image/svg+xml", "image/webp"}
_LOGO_MAX_BYTES = 512 * 1024


def _module_default_label(module_key: str, *, fallback: str = "") -> str:
    definition = get_module_definition(module_key)
    if definition is not None:
        return definition.default_label
    return fallback or str(module_key or "").replace("_", " ").title() or "Modulo"


def resolve_module_logo(module_key: str, *, legacy_logo_keys: tuple[str, ...] = ()) -> str:
    branding = get_module_branding(module_key)
    if branding and branding.logo_url:
        return str(branding.logo_url).strip()

    if not legacy_logo_keys:
        return ""

    fallback_values = SiteConfig.get_many({key: "" for key in legacy_logo_keys})
    for key in legacy_logo_keys:
        value = str(fallback_values.get(key) or "").strip()
        if value:
            return value
    return ""


def get_module_branding_context(
    module_key: str,
    *,
    fallback_label: str = "",
    legacy_logo_keys: tuple[str, ...] = (),
) -> dict[str, object]:
    default_label = _module_default_label(module_key, fallback=fallback_label)
    display_label = resolve_module_label(module_key, fallback=default_label, surface="display")
    logo_url = resolve_module_logo(module_key, legacy_logo_keys=legacy_logo_keys)
    return {
        "module_branding_key": module_key,
        "module_branding_default_label": default_label,
        "module_branding_display_label": display_label,
        "module_branding_logo_url": logo_url or "",
        "module_branding_has_logo": bool(logo_url),
    }


def handle_module_branding_post(
    request: HttpRequest,
    *,
    module_key: str,
    redirect_to: str,
    audit_module: str,
    legacy_logo_keys: tuple[str, ...] = (),
    sync_legacy_logo_keys: tuple[str, ...] = (),
    fallback_label: str = "",
) -> HttpResponse | None:
    action = str(request.POST.get("action") or "").strip()
    if action not in {"save_module_branding", "remove_module_branding"}:
        return None

    config_keys = module_branding_siteconfig_keys(module_key)
    default_label = _module_default_label(module_key, fallback=fallback_label)

    if action == "remove_module_branding":
        SiteConfig.set(config_keys["logo_url"], "", f"Logo modulo {default_label}")
        for legacy_key in sync_legacy_logo_keys:
            SiteConfig.set(legacy_key, "", f"Legacy logo modulo {default_label}")
        for ext in _LOGO_ALLOWED_EXTS:
            save_path = f"module_branding/{module_key}/logo{ext}"
            if default_storage.exists(save_path):
                default_storage.delete(save_path)
        log_action(request, "remove_module_branding_logo", audit_module, {"module_key": module_key})
        messages.success(request, "Logo modulo rimosso.")
        return redirect(redirect_to)

    display_label = str(request.POST.get("branding_display_label") or "").strip()
    logo_url = str(request.POST.get("branding_logo_url") or "").strip()
    logo_file = request.FILES.get("branding_logo_file")

    SiteConfig.set(
        config_keys["display_label"],
        display_label,
        f"Nome modulo {default_label}",
    )

    saved_logo_url = ""
    if logo_file:
        if logo_file.size > _LOGO_MAX_BYTES:
            messages.error(request, "Immagine troppo grande (max 512 KB).")
            return redirect(redirect_to)
        try:
            validate_extension_and_mime(
                logo_file,
                allowed_extensions=_LOGO_ALLOWED_EXTS,
                allowed_mimes=_LOGO_ALLOWED_MIMES,
                max_bytes=None,
                label="Logo modulo",
            )
        except UploadMimeValidationError as exc:
            messages.error(request, str(exc))
            return redirect(redirect_to)

        raw_ext = os.path.splitext(logo_file.name)[1].lower()
        ext = raw_ext if raw_ext in _LOGO_ALLOWED_EXTS else ".png"
        for old_ext in _LOGO_ALLOWED_EXTS:
            save_path = f"module_branding/{module_key}/logo{old_ext}"
            if default_storage.exists(save_path):
                default_storage.delete(save_path)
        saved_path = default_storage.save(f"module_branding/{module_key}/logo{ext}", logo_file)
        saved_logo_url = default_storage.url(saved_path)
    elif logo_url:
        parsed = urlsplit(logo_url)
        if parsed.scheme not in ("http", "https") and not logo_url.startswith("/"):
            messages.error(request, "L'URL del logo deve iniziare con http://, https:// o /")
            return redirect(redirect_to)
        saved_logo_url = logo_url

    if saved_logo_url:
        SiteConfig.set(config_keys["logo_url"], saved_logo_url, f"Logo modulo {default_label}")
        for legacy_key in sync_legacy_logo_keys:
            SiteConfig.set(legacy_key, saved_logo_url, f"Legacy logo modulo {default_label}")

    log_action(
        request,
        "save_module_branding",
        audit_module,
        {"module_key": module_key, "display_label": display_label or default_label, "logo_updated": bool(saved_logo_url)},
    )
    messages.success(request, "Branding modulo salvato.")
    return redirect(redirect_to)
