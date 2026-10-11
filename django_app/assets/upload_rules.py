"""Regole di upload del modulo assets (audit A9): estensione + MIME reale dal contenuto.

Immagini: solo raster (PNG/JPG/WEBP) verificate con Pillow; SVG e HTML non passano
mai, nemmeno rinominati, perche' finirebbero serviti da MEDIA.
"""
from __future__ import annotations

from django import forms

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}


def clean_image_upload(upload, *, extensions=IMAGE_EXTENSIONS, max_bytes: int, label: str):
    """Valida un'immagine raster in un ``clean_<campo>``; solleva ``forms.ValidationError``."""
    if not upload or not hasattr(upload, "read"):
        return upload
    mimes = {mime for mime in IMAGE_MIMES if not (mime == "image/webp" and ".webp" not in extensions)}
    try:
        validate_extension_and_mime(
            upload, allowed_extensions=set(extensions), allowed_mimes=mimes, max_bytes=max_bytes, label=label, allow_empty=False
        )
    except UploadMimeValidationError as exc:
        raise forms.ValidationError(str(exc))
    finally:
        upload.seek(0)
    try:
        from PIL import Image

        with Image.open(upload) as image:
            image.verify()
    except Exception:
        raise forms.ValidationError(f"{label}: il file non e' un'immagine valida.")
    finally:
        upload.seek(0)
    return upload


def clean_document_upload(upload, *, label: str):
    """Allegati (rapporti, documenti): stesse regole dei documenti asset."""
    if not upload or not hasattr(upload, "read"):
        return upload
    from .views import ASSET_DOCUMENT_ALLOWED_EXTENSIONS, ASSET_DOCUMENT_ALLOWED_MIMES, ASSET_DOCUMENT_MAX_BYTES

    try:
        validate_extension_and_mime(
            upload,
            allowed_extensions=ASSET_DOCUMENT_ALLOWED_EXTENSIONS,
            allowed_mimes=ASSET_DOCUMENT_ALLOWED_MIMES,
            max_bytes=ASSET_DOCUMENT_MAX_BYTES,
            label=label,
        )
    except UploadMimeValidationError as exc:
        raise forms.ValidationError(str(exc))
    finally:
        upload.seek(0)
    return upload
