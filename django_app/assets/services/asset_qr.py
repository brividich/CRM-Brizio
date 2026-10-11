"""QR degli asset: destinazione, immagine PNG e link pubblico opt-in.

Regole (audit B3):
- il token pubblico NON nasce mai da solo: lo crea solo ``abilita_link_pubblico``,
  chiamato da un'azione esplicita di un utente con permesso;
- l'immagine e' un PNG generato qui con ``qrcode`` (mai SVG caricati da utenti);
- la cache dell'immagine ha come chiave asset + destinazione + URL (che contiene
  tag o token): se cambia il tag o si rigenera il token la chiave cambia da sola.
"""
from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

import qrcode
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse

QR_CACHE_VERSION = "v1"
QR_CACHE_SECONDS = 60 * 60 * 24 * 7
# Dimensioni ammesse (box_size qrcode): miniatura, anteprima, stampa/scarico.
QR_SIZES = {"s": 3, "m": 8, "l": 14}

DEST_PUBLIC = "public"
DEST_INTERNAL = "internal"


@dataclass(frozen=True)
class QrDestinazione:
    kind: str  # DEST_PUBLIC | DEST_INTERNAL
    url: str
    label: str


def link_pubblico_attivo(asset) -> bool:
    return bool((asset.public_qr_token or "").strip()) and bool(asset.public_qr_enabled)


def url_assoluto(request, path: str) -> str:
    site_url = str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")
    if site_url:
        return f"{site_url}{path if path.startswith('/') else '/' + path}"
    return request.build_absolute_uri(path)


def destinazione(request, asset) -> QrDestinazione:
    """Landing pubblica se il link e' stato abilitato, altrimenti landing interna (login)."""
    if link_pubblico_attivo(asset):
        path = reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": asset.public_qr_token})
        return QrDestinazione(DEST_PUBLIC, url_assoluto(request, path), "Landing QR pubblica")
    path = reverse("assets:asset_qr_landing", kwargs={"asset_tag": asset.asset_tag})
    return QrDestinazione(DEST_INTERNAL, url_assoluto(request, path), "Landing mobile QR")


def _cache_key(asset_id: int, dest: QrDestinazione, size: str) -> str:
    digest = hashlib.sha256(dest.url.encode("utf-8")).hexdigest()[:24]
    return f"assets:qr:{QR_CACHE_VERSION}:{asset_id}:{dest.kind}:{size}:{digest}"


def genera_png(url: str, size: str = "m") -> bytes:
    box = QR_SIZES.get(size, QR_SIZES["m"])
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box, border=2)
    code.add_data(url)
    code.make(fit=True)
    buf = io.BytesIO()
    code.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def png_asset(asset_id: int, dest: QrDestinazione, size: str = "m") -> bytes:
    size = size if size in QR_SIZES else "m"
    key = _cache_key(asset_id, dest, size)
    data = cache.get(key)
    if data is None:
        data = genera_png(dest.url, size)
        cache.set(key, data, QR_CACHE_SECONDS)
    return data


# ── Link pubblico: solo azioni esplicite ─────────────────────────────────────


def abilita_link_pubblico(asset) -> bool:
    """Abilita il link pubblico; crea il token solo se manca. Ritorna True se e' cambiato qualcosa."""
    with transaction.atomic():
        locked = type(asset).objects.select_for_update().get(pk=asset.pk)
        changed = False
        if not (locked.public_qr_token or "").strip():
            locked.public_qr_token = uuid.uuid4().hex
            changed = True
        if not locked.public_qr_enabled:
            locked.public_qr_enabled = True
            changed = True
        if changed:
            type(asset).objects.filter(pk=locked.pk).update(
                public_qr_token=locked.public_qr_token, public_qr_enabled=True
            )
    asset.public_qr_token, asset.public_qr_enabled = locked.public_qr_token, True
    return changed


def revoca_link_pubblico(asset) -> bool:
    """Disattiva il link pubblico (il token resta per poterlo riattivare con le etichette gia' stampate)."""
    updated = type(asset).objects.filter(pk=asset.pk, public_qr_enabled=True).update(public_qr_enabled=False)
    asset.public_qr_enabled = False
    return bool(updated)


def rigenera_link_pubblico(asset) -> str:
    """Nuovo token: le etichette gia' stampate smettono di funzionare. Il link resta abilitato."""
    token = uuid.uuid4().hex
    type(asset).objects.filter(pk=asset.pk).update(public_qr_token=token, public_qr_enabled=True)
    asset.public_qr_token, asset.public_qr_enabled = token, True
    return token
