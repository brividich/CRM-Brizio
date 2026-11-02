"""Immagini di copertina della stanza «Sapere» (risorse, cataloghi, voci).

Ogni immagine caricata viene aperta con Pillow, raddrizzata, ridotta a
``COPERTINA_LATO_MAX`` pixel sul lato lungo e ricodificata in JPEG: il file
salvato non porta con sé i metadati dell'originale (EXIF, posizione GPS,
modello del telefono) e non può essere un file diverso travestito da
immagine. Lo storage è quello privato e cifrato della bacheca.
"""
from __future__ import annotations

import io
import os
import uuid

from django.core.files.base import ContentFile

COPERTINA_EST = (".jpg", ".jpeg", ".png", ".webp")
COPERTINA_MAX_MB = 10
COPERTINA_MAX_BYTES = COPERTINA_MAX_MB * 1024 * 1024
COPERTINA_LATO_MAX = 1200
COPERTINA_PIXEL_MAX = 40_000_000  # oltre: rifiutata (difesa da immagini «bomba»)
COPERTINA_ACCEPT = ",".join(COPERTINA_EST)


class CopertinaNonValida(ValueError):
    """Messaggio leggibile per l'utente: va mostrato così com'è."""


def prepara_copertina(upload) -> ContentFile:
    """File caricato → ``ContentFile`` JPEG pronto per un ``FileField``."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    nome = getattr(upload, "name", "") or ""
    est = os.path.splitext(nome)[1].lower()
    if est not in COPERTINA_EST:
        raise CopertinaNonValida("Copertina: usa un'immagine JPG, PNG o WEBP.")
    if (getattr(upload, "size", 0) or 0) > COPERTINA_MAX_BYTES:
        raise CopertinaNonValida(f"Copertina troppo grande (massimo {COPERTINA_MAX_MB} MB).")
    try:
        img = Image.open(upload)
        larghezza, altezza = img.size
        if larghezza * altezza > COPERTINA_PIXEL_MAX:
            raise CopertinaNonValida("Copertina: immagine troppo grande in pixel.")
        img.load()
    except CopertinaNonValida:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise CopertinaNonValida("Copertina: il file non è un'immagine leggibile.") from exc

    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fondo = Image.new("RGB", img.size, (255, 255, 255))
        fondo.paste(img, mask=img.split()[-1])
        img = fondo
    elif img.mode != "RGB":
        img = img.convert("RGB")
    img.thumbnail((COPERTINA_LATO_MAX, COPERTINA_LATO_MAX))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=84, optimize=True)
    return ContentFile(buf.getvalue(), name=f"{uuid.uuid4().hex}.jpg")


def sostituisci_copertina(obj, upload) -> None:
    """Imposta la nuova copertina su ``obj`` e cancella il file precedente (senza salvare l'oggetto)."""
    nuovo = prepara_copertina(upload)
    rimuovi_copertina(obj)
    obj.copertina.save(nuovo.name, nuovo, save=False)


def rimuovi_copertina(obj) -> None:
    vecchia = getattr(obj, "copertina", None)
    if vecchia:
        try:
            vecchia.delete(save=False)
        except OSError:
            pass
        obj.copertina = None
