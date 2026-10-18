"""Viste del Pannello di amministrazione — Branding: login, loghi/sfondi, favicon, template PDF.

Spacchettamento di ``admin_portale/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging
import os
import re
from collections import deque
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, get_connection  # noqa: F401 — EmailMultiAlternatives e' bersaglio di mock.patch nei test
from django.core.files.storage import default_storage
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer

from core.branding import get_portal_branding
from core.pdf import (
    PDF_TEMPLATE_DEFAULTS,
    PdfTheme,
    build_styles,
    data_table,
    header_footer_callback,
    make_document,
    section_heading,
)
from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime
from core.models import (
    LoginBanner,
    SiteConfig,
)

from ..decorators import legacy_admin_required

from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Login Config
# ---------------------------------------------------------------------------

_LOGIN_CONFIG_KEYS = [
    ("login_titolo",       "Titolo pagina",          "Portale Applicativo"),
    ("login_sottotitolo",  "Sottotitolo / azienda",  "Example Organization"),
    ("login_sso_visibile", "Bottone SSO visibile",   "1"),
    ("login_sso_label",    "Etichetta bottone SSO",  "Accedi con credenziali Windows"),
]

_LOGO_UPLOAD_DIR = "site"
_ALLOWED_LOGO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}  # niente SVG (audit A9)
_ALLOWED_LOGO_MIMES = {"image/png", "image/jpeg", "image/webp"}
_LOGO_UPLOAD_MAX_BYTES = 1024 * 1024
_LOGIN_BRANDING_DEFAULTS = {
    "portal_name": "Portale Novicrom",
    "portal_subtitle": "",
    "brand_logo_full": "",
    "brand_logo_compact": "",
    "brand_logo_remove_white_bg": "0",
    "brand_landing_image": "",
    "brand_landing_fit_mode": "cover",
    "brand_logo_full_height": "40",
    "brand_logo_full_max_width": "140",
    "brand_logo_compact_size": "32",
    "brand_sidebar_logo_scale": "100",
    "brand_login_form_x": "78",
    "brand_login_form_y": "50",
}
_LOGIN_BRANDING_TEXT_KEYS = {
    "portal_name": "Nome portale globale.",
    "portal_subtitle": "Sottotitolo branding globale.",
    "brand_logo_full": "URL logo sidebar espansa.",
    "brand_logo_compact": "URL logo sidebar compressa.",
    "brand_landing_image": "Immagine di sfondo pagina login.",
    "brand_logo_remove_white_bg": "Rimozione automatica sfondo bianco dai loghi caricati.",
}
_LOGIN_LANDING_FIT_MODES = {"cover", "contain", "stretch", "center"}
_LOGIN_BRANDING_DIMENSIONS: dict[str, dict[str, int]] = {
    "brand_logo_full_height": {"default": 40, "min": 28, "max": 96},
    "brand_logo_full_max_width": {"default": 140, "min": 80, "max": 360},
    "brand_logo_compact_size": {"default": 32, "min": 24, "max": 80},
    "brand_sidebar_logo_scale": {"default": 100, "min": 60, "max": 260},
    "brand_login_form_x": {"default": 78, "min": 0, "max": 100},
    "brand_login_form_y": {"default": 50, "min": 0, "max": 100},
}
_LANDING_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
_LOGIN_WHITE_BG_STRIP_KEYS = {"brand_logo_full", "brand_logo_compact"}
_LOGIN_BG_FLOOD_MIN_CHANNEL = 205
_LOGIN_BG_FLOOD_MAX_CHROMA = 36
_LOGIN_BG_GLOBAL_MIN_CHANNEL = 230
_LOGIN_BG_GLOBAL_MAX_CHROMA = 20
_LOGIN_BG_GLOBAL_MIN_COVERAGE = 0.12
_LOGIN_BRAND_ASSETS = {
    "brand_logo_full": {
        "slot": "logo_full",
        "file_field": "brand_logo_full_file",
        "clear_field": "clear_brand_logo_full",
        "label": "Logo sidebar espansa",
        "allowed_extensions": _ALLOWED_LOGO_EXTENSIONS,
        "allowed_mimes": _ALLOWED_LOGO_MIMES,
        "max_bytes": _LOGO_UPLOAD_MAX_BYTES,
    },
    "brand_logo_compact": {
        "slot": "logo_compact",
        "file_field": "brand_logo_compact_file",
        "clear_field": "clear_brand_logo_compact",
        "label": "Logo sidebar compressa",
        "allowed_extensions": _ALLOWED_LOGO_EXTENSIONS,
        "allowed_mimes": _ALLOWED_LOGO_MIMES,
        "max_bytes": _LOGO_UPLOAD_MAX_BYTES,
    },
    "brand_landing_image": {
        "slot": "landing",
        "file_field": "brand_landing_image_file",
        "clear_field": "clear_brand_landing_image",
        "label": "Immagine landing login",
        "allowed_extensions": _ALLOWED_LOGO_EXTENSIONS,
        "allowed_mimes": _ALLOWED_LOGO_MIMES,
        "max_bytes": _LANDING_UPLOAD_MAX_BYTES,
    },
}


def _normalize_checkbox_flag(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    return "1" if cleaned in {"1", "true", "on", "yes"} else "0"


def _clean_login_landing_fit_mode(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    if not cleaned:
        return _LOGIN_BRANDING_DEFAULTS["brand_landing_fit_mode"]
    if cleaned in _LOGIN_LANDING_FIT_MODES:
        return cleaned
    raise ValueError("Modalita sfondo login non valida. Usa: riempi, adatta, stira o centrata.")


def _clean_login_dimension(value: str, *, field_name: str) -> str:
    rules = _LOGIN_BRANDING_DIMENSIONS[field_name]
    cleaned = str(value or "").strip()
    if not cleaned:
        return str(rules["default"])
    try:
        parsed = int(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field_name}: inserisci un numero intero.") from exc
    if parsed < rules["min"] or parsed > rules["max"]:
        raise ValueError(f"{field_name}: valore ammesso tra {rules['min']} e {rules['max']}.")
    return str(parsed)


def _strip_white_background_image(uploaded_file):
    try:
        uploaded_file.seek(0)
    except Exception:
        pass

    try:
        with Image.open(uploaded_file) as img:
            rgba = img.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError):
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return None

    width, height = rgba.size
    pixels = list(rgba.getdata())
    visited = bytearray(width * height)
    queue: deque[int] = deque()
    to_clear: set[int] = set()

    def _is_edge_background(px: tuple[int, int, int, int]) -> bool:
        red, green, blue, alpha = px
        if alpha == 0:
            return False
        high = max(red, green, blue)
        low = min(red, green, blue)
        return low >= _LOGIN_BG_FLOOD_MIN_CHANNEL and (high - low) <= _LOGIN_BG_FLOOD_MAX_CHROMA

    for x in range(width):
        queue.append(x)
        queue.append((height - 1) * width + x)
    for y in range(height):
        queue.append(y * width)
        queue.append(y * width + (width - 1))

    while queue:
        idx = queue.popleft()
        if idx < 0 or idx >= width * height:
            continue
        if visited[idx]:
            continue
        visited[idx] = 1
        if not _is_edge_background(pixels[idx]):
            continue
        to_clear.add(idx)
        x = idx % width
        y = idx // width
        if x > 0:
            queue.append(idx - 1)
        if x < width - 1:
            queue.append(idx + 1)
        if y > 0:
            queue.append(idx - width)
        if y < height - 1:
            queue.append(idx + width)

    global_candidates: list[int] = []
    for idx, (red, green, blue, alpha) in enumerate(pixels):
        if alpha == 0:
            continue
        high = max(red, green, blue)
        low = min(red, green, blue)
        if low >= _LOGIN_BG_GLOBAL_MIN_CHANNEL and (high - low) <= _LOGIN_BG_GLOBAL_MAX_CHROMA:
            global_candidates.append(idx)
    if global_candidates and (len(global_candidates) / (width * height)) >= _LOGIN_BG_GLOBAL_MIN_COVERAGE:
        to_clear.update(global_candidates)

    if not to_clear:
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
        return None

    for idx in to_clear:
        red, green, blue, _ = pixels[idx]
        pixels[idx] = (red, green, blue, 0)

    rgba.putdata(pixels)
    output = BytesIO()
    rgba.save(output, format="PNG", optimize=True)
    output.seek(0)
    return ContentFile(output.getvalue(), name=f"{Path(uploaded_file.name).stem}.png")


def _delete_login_brand_asset(slot: str, allowed_extensions: set[str]) -> None:
    for ext in allowed_extensions:
        path = f"portal_branding/{slot}{ext}"
        try:
            if default_storage.exists(path):
                default_storage.delete(path)
        except Exception:
            continue


def _save_login_brand_asset(
    uploaded_file,
    *,
    meta: dict[str, object],
    strip_white_background: bool = False,
) -> str:
    label = str(meta["label"])
    allowed_extensions = set(meta["allowed_extensions"])
    allowed_mimes = set(meta["allowed_mimes"])
    max_bytes = int(meta.get("max_bytes") or _LOGO_UPLOAD_MAX_BYTES)
    validate_extension_and_mime(
        uploaded_file,
        allowed_extensions=allowed_extensions,
        allowed_mimes=allowed_mimes,
        max_bytes=max_bytes,
        label=label,
    )
    raw_ext = os.path.splitext(uploaded_file.name)[1].lower()
    ext = raw_ext if raw_ext in allowed_extensions else ".png"
    file_to_save = uploaded_file
    if strip_white_background and ext in {".png", ".jpg", ".jpeg", ".webp"}:
        processed_file = _strip_white_background_image(uploaded_file)
        if processed_file is not None:
            file_to_save = processed_file
            ext = ".png"
    try:
        file_to_save.seek(0)
    except Exception:
        pass
    slot = str(meta["slot"])
    _delete_login_brand_asset(slot, allowed_extensions)
    saved_path = default_storage.save(f"portal_branding/{slot}{ext}", file_to_save)
    return default_storage.url(saved_path)


def _delete_login_landing_files() -> None:
    for ext in _ALLOWED_LOGO_EXTENSIONS:
        try:
            legacy_path = os.path.join(_LOGO_UPLOAD_DIR, f"login_landing{ext}")
            if default_storage.exists(legacy_path):
                default_storage.delete(legacy_path)
            portal_path = f"portal_branding/landing{ext}"
            if default_storage.exists(portal_path):
                default_storage.delete(portal_path)
        except Exception:
            continue


_PDF_TEMPLATE_UPLOAD_DIR = "pdf_template"
_PDF_TEMPLATE_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
_PDF_TEMPLATE_ALLOWED_MIMES = {"image/png", "image/jpeg"}
_PDF_TEMPLATE_LOGO_MAX_BYTES = 1024 * 1024
_HEX_COLOR_FIELD_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_pdf_template_color(value: str, *, label: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if not _HEX_COLOR_FIELD_RE.match(cleaned):
        raise ValueError(f"{label}: usa un colore nel formato #RRGGBB.")
    return cleaned.lower()


def _clean_pdf_template_logo_url(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    if not cleaned.startswith("/media/"):
        raise ValueError("Logo PDF: carica un file o usa un percorso /media/... PNG/JPG.")
    if os.path.splitext(cleaned.split("?", 1)[0])[1].lower() not in _PDF_TEMPLATE_ALLOWED_EXTENSIONS:
        raise ValueError("Logo PDF: sono ammessi solo file PNG o JPG.")
    return cleaned


def _clean_pdf_template_footer_text(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) > 120:
        raise ValueError("Testo footer PDF: massimo 120 caratteri.")
    return cleaned


def _delete_pdf_template_logo_files() -> None:
    for ext in _PDF_TEMPLATE_ALLOWED_EXTENSIONS:
        path = f"{_PDF_TEMPLATE_UPLOAD_DIR}/logo{ext}"
        try:
            if default_storage.exists(path):
                default_storage.delete(path)
        except Exception:
            continue


def _save_pdf_template_logo(uploaded_file) -> str:
    validate_extension_and_mime(
        uploaded_file,
        allowed_extensions=_PDF_TEMPLATE_ALLOWED_EXTENSIONS,
        allowed_mimes=_PDF_TEMPLATE_ALLOWED_MIMES,
        max_bytes=_PDF_TEMPLATE_LOGO_MAX_BYTES,
        label="Logo PDF",
    )
    raw_ext = os.path.splitext(uploaded_file.name)[1].lower()
    ext = raw_ext if raw_ext in _PDF_TEMPLATE_ALLOWED_EXTENSIONS else ".png"
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    _delete_pdf_template_logo_files()
    saved_path = default_storage.save(f"{_PDF_TEMPLATE_UPLOAD_DIR}/logo{ext}", uploaded_file)
    return default_storage.url(saved_path)


@legacy_admin_required
@require_GET
def login_config(request):
    valori = {chiave: SiteConfig.get(chiave, default) for chiave, _, default in _LOGIN_CONFIG_KEYS}
    logo_url = SiteConfig.get("login_logo_url", "")
    branding = SiteConfig.get_many(_LOGIN_BRANDING_DEFAULTS)
    landing_url = branding.get("brand_landing_image", "")
    banners = list(LoginBanner.objects.all())
    return render(request, "admin_portale/pages/login_config.html", {
        "config_keys": _LOGIN_CONFIG_KEYS,
        "valori": valori,
        "logo_url": logo_url,
        "landing_url": landing_url,
        "branding": branding,
        "banners": banners,
        "banner_tipi": LoginBanner.TIPO_CHOICES,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_config_save(request):
    changed = {}
    for chiave, descrizione, _ in _LOGIN_CONFIG_KEYS:
        if chiave in request.POST:
            valore = request.POST[chiave].strip()
            SiteConfig.set(chiave, valore, descrizione)
            changed[chiave] = valore
    try:
        for key, descrizione in _LOGIN_BRANDING_TEXT_KEYS.items():
            if key not in request.POST:
                continue
            if key in {"brand_logo_full", "brand_logo_compact", "brand_landing_image"}:
                value = _helpers._clean_login_asset_url(request.POST.get(key, ""), label=descrizione)
            elif key == "brand_logo_remove_white_bg":
                value = _normalize_checkbox_flag(request.POST.get(key))
            else:
                value = request.POST.get(key, "").strip()
            SiteConfig.set(key, value, descrizione)
            changed[key] = value

        if "brand_landing_fit_mode" in request.POST:
            fit_mode = _clean_login_landing_fit_mode(request.POST.get("brand_landing_fit_mode", ""))
            SiteConfig.set("brand_landing_fit_mode", fit_mode, "Modalita sfondo pagina login.")
            changed["brand_landing_fit_mode"] = fit_mode

        for key in _LOGIN_BRANDING_DIMENSIONS:
            if key in request.POST:
                value = _clean_login_dimension(request.POST.get(key, ""), field_name=key)
                SiteConfig.set(key, value, f"Configurazione login: {key}.")
                changed[key] = value

        strip_white_bg = _normalize_checkbox_flag(request.POST.get("brand_logo_remove_white_bg")) == "1"
        for key, meta in _LOGIN_BRAND_ASSETS.items():
            file_field = str(meta["file_field"])
            clear_field = str(meta["clear_field"])
            uploaded_file = request.FILES.get(file_field)
            clear_requested = _normalize_checkbox_flag(request.POST.get(clear_field)) == "1"

            if clear_requested:
                _delete_login_brand_asset(str(meta["slot"]), set(meta["allowed_extensions"]))
                if key == "brand_landing_image":
                    _delete_login_landing_files()
                value = ""
            elif uploaded_file:
                value = _save_login_brand_asset(
                    uploaded_file,
                    meta=meta,
                    strip_white_background=(strip_white_bg and key in _LOGIN_WHITE_BG_STRIP_KEYS),
                )
            elif key in request.POST:
                value = _helpers._clean_login_asset_url(request.POST.get(key, ""), label=str(meta["label"]))
            else:
                continue

            SiteConfig.set(key, value, _LOGIN_BRANDING_TEXT_KEYS.get(key, f"Configurazione login: {key}."))
            changed[key] = value
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:login_config")
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:login_config")
    _helpers._audit_safe(request, "login_config_save", "admin_portale", {"changed_keys": list(changed.keys())})
    messages.success(request, "Configurazione login salvata.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_logo_upload(request):
    upload = request.FILES.get("logo")
    if not upload:
        messages.error(request, "Nessun file selezionato.")
        return redirect("admin_portale:login_config")
    try:
        validate_extension_and_mime(
            upload,
            allowed_extensions=_ALLOWED_LOGO_EXTENSIONS,
            allowed_mimes=_ALLOWED_LOGO_MIMES,
            max_bytes=1024 * 1024,
            label="Logo login",
        )
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:login_config")
    ext = os.path.splitext(upload.name)[1].lower()
    if ext not in _ALLOWED_LOGO_EXTENSIONS:
        ext = ".png"
    filename = f"login_logo{ext}"
    save_path = os.path.join(_LOGO_UPLOAD_DIR, filename)
    # Salva sovrascrivendo un eventuale logo precedente
    saved = default_storage.save(save_path, upload)
    # Normalizza path â†’ URL relativa (sempre forward slash)
    url = settings.MEDIA_URL + saved.replace("\\", "/")
    SiteConfig.set("login_logo_url", url, "URL logo pagina login (caricato da admin)")
    messages.success(request, "Logo aggiornato.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_logo_remove(request):
    current = SiteConfig.get("login_logo_url", "")
    if current:
        # Rimuovi file fisico se presente
        rel = current.replace(settings.MEDIA_URL, "", 1)
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass
        SiteConfig.set("login_logo_url", "", "URL logo pagina login")
    messages.success(request, "Logo rimosso.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_landing_upload(request):
    upload = request.FILES.get("landing")
    if not upload:
        messages.error(request, "Nessun file selezionato.")
        return redirect("admin_portale:login_config")
    try:
        _delete_login_landing_files()
        url = _save_login_brand_asset(upload, meta=_LOGIN_BRAND_ASSETS["brand_landing_image"])
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:login_config")
    SiteConfig.set("brand_landing_image", url, "Immagine di sfondo pagina login (caricata da admin).")
    _helpers._audit_safe(request, "login_landing_upload", "admin_portale", {"url": url})
    messages.success(request, "Immagine landing aggiornata.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_landing_remove(request):
    current = SiteConfig.get("brand_landing_image", "")
    if current:
        rel = current.replace(settings.MEDIA_URL, "", 1)
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass
    _delete_login_landing_files()
    SiteConfig.set("brand_landing_image", "", "Immagine di sfondo pagina login.")
    _helpers._audit_safe(request, "login_landing_remove", "admin_portale")
    messages.success(request, "Immagine landing rimossa.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_create(request):
    testo = (request.POST.get("testo") or "").strip()
    if not testo:
        messages.error(request, "Il testo del banner non puÃ² essere vuoto.")
        return redirect("admin_portale:login_config")
    tipo = request.POST.get("tipo") or "info"
    if tipo not in dict(LoginBanner.TIPO_CHOICES):
        tipo = "info"
    ordine = int(request.POST.get("ordine") or 100)
    banner = LoginBanner.objects.create(testo=testo, tipo=tipo, ordine=ordine, is_active=True)
    _helpers._audit_safe(request, "login_banner_create", "admin_portale", {"banner_id": int(banner.id), "tipo": tipo})
    messages.success(request, "Banner aggiunto.")
    return redirect("admin_portale:login_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_toggle(request):
    payload = _helpers._json_payload(request)
    b = get_object_or_404(LoginBanner, id=_helpers._int_or_none(payload.get("id")))
    b.is_active = not b.is_active
    b.save(update_fields=["is_active"])
    _helpers._audit_safe(request, "login_banner_toggle", "admin_portale", {"banner_id": int(b.id), "is_active": b.is_active})
    return JsonResponse({"ok": True, "is_active": b.is_active})


@legacy_admin_required
@csrf_protect
@require_POST
def api_login_banner_delete(request):
    payload = _helpers._json_payload(request)
    b = get_object_or_404(LoginBanner, id=_helpers._int_or_none(payload.get("id")))
    banner_id = int(b.id)
    b.delete()
    _helpers._audit_safe(request, "login_banner_delete", "admin_portale", {"banner_id": banner_id})
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# TEMPLATE PDF — grafica condivisa dei report
# ---------------------------------------------------------------------------


@legacy_admin_required
@require_GET
def pdf_template_config(request):
    values = SiteConfig.get_many(PDF_TEMPLATE_DEFAULTS)
    branding = get_portal_branding()
    theme = PdfTheme.from_branding()
    effective_logo_url = str(values.get("pdf_template_logo_url") or "").strip() or branding.brand_logo_full
    if not theme.logo_path:
        effective_logo_url = ""
    return render(
        request,
        "admin_portale/pages/pdf_template_config.html",
        {
            "values": values,
            "theme": theme,
            "pdf_logo_url": values.get("pdf_template_logo_url", ""),
            "pdf_effective_logo_url": effective_logo_url,
            "pdf_primary_color": theme.primary,
            "pdf_accent_color": theme.accent,
            "pdf_preview_generated_at": timezone.localtime().strftime("%d-%m-%Y %H:%M"),
        },
    )


@legacy_admin_required
@require_GET
def pdf_template_preview(request):
    theme = PdfTheme.from_branding()
    styles = build_styles(theme)
    buffer = BytesIO()
    doc = make_document(buffer, title="Anteprima template PDF")

    rows = [
        [
            Paragraph("Sezione", styles["table_header"]),
            Paragraph("Elemento", styles["table_header"]),
            Paragraph("Stato", styles["table_header"]),
        ],
        [Paragraph("Header", styles["cell"]), Paragraph("Logo o monogramma", styles["cell"]), Paragraph("Visibile", styles["cell"])],
        [Paragraph("Palette", styles["cell"]), Paragraph(theme.primary, styles["cell"]), Paragraph("Applicata", styles["cell"])],
        [Paragraph("Footer", styles["cell"]), Paragraph(theme.footer_text, styles["cell"]), Paragraph("Configurato", styles["cell"])],
    ]

    story = [
        Paragraph("Anteprima template PDF", styles["title"]),
        Paragraph(
            "Documento sintetico per verificare intestazione, palette, contenuti tabellari e pi&egrave; di pagina.",
            styles["body"],
        ),
        Spacer(1, 6 * mm),
        *section_heading("Componenti grafici", theme, styles),
        data_table(rows, theme, col_widths=[54 * mm, 78 * mm, 42 * mm], header=True),
        Spacer(1, 8 * mm),
        Paragraph(
            "Questa anteprima usa dati dimostrativi e legge le impostazioni PDF salvate in Admin Portale.",
            styles["body"],
        ),
    ]
    draw = header_footer_callback(
        theme,
        title="ANTEPRIMA TEMPLATE PDF",
        subtitle="Documento dimostrativo",
    )
    doc.build(story, onFirstPage=draw, onLaterPages=draw)

    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="anteprima-template-pdf.pdf"'
    return response


@legacy_admin_required
@csrf_protect
@require_POST
def api_pdf_template_config_save(request):
    changed = {}
    try:
        logo_url = request.POST.get("pdf_template_logo_url", "")
        uploaded_logo = request.FILES.get("pdf_template_logo_file")
        clear_logo = _normalize_checkbox_flag(request.POST.get("clear_pdf_template_logo")) == "1"
        if clear_logo:
            _delete_pdf_template_logo_files()
            logo_url = ""
        elif uploaded_logo:
            logo_url = _save_pdf_template_logo(uploaded_logo)
        else:
            logo_url = _clean_pdf_template_logo_url(logo_url)

        fields = {
            "pdf_template_logo_url": (logo_url, "Logo specifico per intestazione PDF."),
            "pdf_template_primary_color": (
                _clean_pdf_template_color(
                    request.POST.get("pdf_template_primary_color", ""),
                    label="Colore primario PDF",
                ),
                "Colore primario specifico del template PDF.",
            ),
            "pdf_template_accent_color": (
                _clean_pdf_template_color(
                    request.POST.get("pdf_template_accent_color", ""),
                    label="Colore accento PDF",
                ),
                "Colore accento specifico del template PDF.",
            ),
            "pdf_template_footer_text": (
                _clean_pdf_template_footer_text(request.POST.get("pdf_template_footer_text", "")),
                "Testo footer condiviso dei PDF.",
            ),
            "pdf_template_show_generated_at": (
                _normalize_checkbox_flag(request.POST.get("pdf_template_show_generated_at")),
                "Mostra data e ora di generazione nell'intestazione PDF.",
            ),
            "pdf_template_show_page_number": (
                _normalize_checkbox_flag(request.POST.get("pdf_template_show_page_number")),
                "Mostra numero pagina nel footer PDF.",
            ),
        }
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:pdf_template_config")
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:pdf_template_config")

    current = SiteConfig.get_many(PDF_TEMPLATE_DEFAULTS)
    for key, (value, description) in fields.items():
        SiteConfig.set(key, value, description)
        if current.get(key) != value:
            changed[key] = value

    _helpers._audit_safe(request, "pdf_template_config_save", "admin_portale", {"changed_keys": list(changed.keys())})
    messages.success(request, "Template PDF salvato.")
    return redirect("admin_portale:pdf_template_config")


# ---------------------------------------------------------------------------
# BRANDING PORTALE — favicon globale
# ---------------------------------------------------------------------------

_FAVICON_UPLOAD_DIR = "site"
_FAVICON_ALLOWED_EXTS = {".ico", ".png"}  # niente SVG (audit A9)
_FAVICON_ALLOWED_MIMES = {
    "image/x-icon",
    "image/vnd.microsoft.icon",
    "image/png",
}


@legacy_admin_required
@require_GET
def branding_config(request):
    favicon_url = SiteConfig.get("brand_favicon", "")
    return render(request, "admin_portale/pages/branding_config.html", {
        "favicon_url": favicon_url,
    })


@legacy_admin_required
@csrf_protect
@require_POST
def api_branding_favicon_upload(request):
    upload = request.FILES.get("favicon")
    if not upload:
        messages.error(request, "Nessun file selezionato.")
        return redirect("admin_portale:branding_config")
    if upload.size > 512 * 1024:
        messages.error(request, "File troppo grande (max 512 KB).")
        return redirect("admin_portale:branding_config")
    try:
        validate_extension_and_mime(
            upload,
            allowed_extensions=_FAVICON_ALLOWED_EXTS,
            allowed_mimes=_FAVICON_ALLOWED_MIMES,
            max_bytes=None,
            label="Favicon",
        )
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return redirect("admin_portale:branding_config")
    raw_ext = os.path.splitext(upload.name)[1].lower()
    ext = raw_ext if raw_ext in _FAVICON_ALLOWED_EXTS else ".ico"
    save_path = os.path.join(_FAVICON_UPLOAD_DIR, f"branding_favicon{ext}")
    if default_storage.exists(save_path):
        default_storage.delete(save_path)
    saved = default_storage.save(save_path, upload)
    url = settings.MEDIA_URL + saved.replace("\\", "/")
    SiteConfig.set("brand_favicon", url, "URL favicon globale del portale")
    _helpers._audit_safe(request, "branding_favicon_upload", "admin_portale", {"path": saved})
    messages.success(request, "Favicon aggiornato.")
    return redirect("admin_portale:branding_config")


@legacy_admin_required
@csrf_protect
@require_POST
def api_branding_favicon_remove(request):
    current = SiteConfig.get("brand_favicon", "")
    if current:
        rel = current.replace(settings.MEDIA_URL, "", 1)
        try:
            if default_storage.exists(rel):
                default_storage.delete(rel)
        except Exception:
            pass
        SiteConfig.set("brand_favicon", "", "URL favicon globale del portale")
    _helpers._audit_safe(request, "branding_favicon_remove", "admin_portale", {})
    messages.success(request, "Favicon rimosso. Verrà usato il favicon predefinito.")
    return redirect("admin_portale:branding_config")
