"""Foto allegata dal form pubblico (telefono in reparto).

L'immagine viene aperta con Pillow, raddrizzata, ridotta a ``FOTO_LATO_MAX``
pixel sul lato lungo e ricodificata in JPEG: il file salvato non porta con sé
i metadati del telefono (posizione GPS, modello, data), che su una
segnalazione anonima potrebbero far risalire all'autore, e non può essere un
file diverso travestito da immagine. Stesso trattamento delle copertine di
«Sapere» (core/copertine.py), con soglie da foto di reparto.
"""
from __future__ import annotations

import io
import os
import uuid

from django.core.files.base import ContentFile

FOTO_EST = (".jpg", ".jpeg", ".png", ".webp")
FOTO_MAX_MB = 15
FOTO_MAX_BYTES = FOTO_MAX_MB * 1024 * 1024
FOTO_LATO_MAX = 2000
FOTO_PIXEL_MAX = 60_000_000  # oltre: rifiutata (difesa da immagini «bomba»)


class FotoNonValida(ValueError):
    """Messaggio leggibile per l'utente: va mostrato così com'è."""


def prepara_foto(upload) -> ContentFile:
    """File caricato → ``ContentFile`` JPEG senza metadati, pronto per un ``FileField``."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    est = os.path.splitext(getattr(upload, "name", "") or "")[1].lower()
    if est not in FOTO_EST:
        raise FotoNonValida("Foto: usa un'immagine JPG, PNG o WEBP.")
    if (getattr(upload, "size", 0) or 0) > FOTO_MAX_BYTES:
        raise FotoNonValida(f"Foto troppo grande (massimo {FOTO_MAX_MB} MB).")
    try:
        img = Image.open(upload)
        larghezza, altezza = img.size
        if larghezza * altezza > FOTO_PIXEL_MAX:
            raise FotoNonValida("Foto: immagine troppo grande in pixel.")
        img.load()
    except FotoNonValida:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise FotoNonValida("Foto: il file non è un'immagine leggibile.") from exc

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((FOTO_LATO_MAX, FOTO_LATO_MAX))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
