"""Strumenti immagine delle planimetrie officina: ruota, ritaglia, PDF → PNG.

Le posizioni di reparti e marker sono in percentuale dell'immagine: ogni
trasformazione dell'immagine riscrive anche le coordinate, altrimenti le
macchine finirebbero nel punto sbagliato della pianta.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction

from ..models import PlantLayoutArea, PlantLayoutMarker

# Il marker creato in automatico (salvataggio asset con «includi in planimetria»)
# nasce al centro: finché nessuno lo sposta la posizione vera non è nota.
UNPLACED_PERCENT = Decimal("50")

# Lato lungo massimo del raster ottenuto da PDF: abbastanza per leggere i
# numeri macchina con lo zoom, sotto i 10 MB del campo.
PDF_RASTER_MAX_SIDE = 5000
PDF_MAX_BYTES = 30 * 1024 * 1024


def marker_is_unplaced(marker) -> bool:
    return Decimal(str(marker.x_percent)) == UNPLACED_PERCENT and Decimal(str(marker.y_percent)) == UNPLACED_PERCENT


def reset_marker_position(marker) -> None:
    marker.x_percent = UNPLACED_PERCENT
    marker.y_percent = UNPLACED_PERCENT


def area_at_point(areas, x_percent, y_percent):
    """Il reparto disegnato che contiene il punto (il più piccolo, se si sovrappongono)."""
    x = float(x_percent)
    y = float(y_percent)
    hits = [
        area for area in areas
        if float(area.x_percent) <= x <= float(area.x_percent) + float(area.width_percent)
        and float(area.y_percent) <= y <= float(area.y_percent) + float(area.height_percent)
    ]
    hits.sort(key=lambda a: float(a.width_percent) * float(a.height_percent))
    return hits[0] if hits else None


def pdf_to_png_upload(upload) -> SimpleUploadedFile:
    """Prima pagina del PDF come PNG: la planimetria CAD arriva quasi sempre così."""
    import fitz  # PyMuPDF

    data = upload.read()
    upload.seek(0)
    if not data.startswith(b"%PDF"):
        raise ValueError("Il file non è un PDF valido.")
    if len(data) > PDF_MAX_BYTES:
        raise ValueError("Il PDF non può superare 30 MB.")
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.page_count < 1:
            raise ValueError("Il PDF non contiene pagine.")
        page = doc[0]
        long_side_pt = max(page.rect.width, page.rect.height) or 1
        zoom = min(PDF_RASTER_MAX_SIDE / long_side_pt, 300 / 72)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png = pix.tobytes("png")
    stem = Path(getattr(upload, "name", "") or "planimetria").stem or "planimetria"
    return SimpleUploadedFile(f"{stem}.png", png, content_type="image/png")


# Sempre dal database, mai ``layout.areas``/``layout.markers``: l'editor carica
# la planimetria con prefetch, e la cache non vede i marker appena salvati.


@dataclass
class TransformResult:
    ok: bool
    message: str


def _open_layout_image(layout):
    from PIL import Image, ImageOps

    with layout.image.open("rb") as handle:
        image = Image.open(handle)
        image.load()
    fmt = (image.format or "PNG").upper()
    image = ImageOps.exif_transpose(image)
    return image, fmt


def _store_layout_image(layout, image, fmt: str, suffix: str) -> None:
    buffer = io.BytesIO()
    if fmt in {"JPEG", "JPG"}:
        image.convert("RGB").save(buffer, format="JPEG", quality=92, optimize=True)
        ext = ".jpg"
    else:
        image.save(buffer, format="PNG", optimize=True)
        ext = ".png"
    stem = Path(layout.image.name or "planimetria").stem.split("__")[0][-60:] or "planimetria"
    layout.image.save(f"{stem}__{suffix}{ext}", ContentFile(buffer.getvalue()), save=False)
    # PlantLayout.save cancella il file precedente quando il nome cambia.
    layout.save()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _d(value: float) -> Decimal:
    return Decimal(str(round(value, 2)))


@transaction.atomic
def rotate_layout(layout, *, clockwise: bool) -> TransformResult:
    """Ruota di 90° e riporta reparti e marker nella stessa posizione della pianta."""
    from PIL import Image

    image, fmt = _open_layout_image(layout)
    image = image.transpose(Image.Transpose.ROTATE_270 if clockwise else Image.Transpose.ROTATE_90)

    for area in PlantLayoutArea.objects.filter(layout=layout):
        x, y = float(area.x_percent), float(area.y_percent)
        w, h = float(area.width_percent), float(area.height_percent)
        if clockwise:
            nx, ny = 100 - (y + h), x
        else:
            nx, ny = y, 100 - (x + w)
        area.x_percent, area.y_percent = _d(_clamp(nx)), _d(_clamp(ny))
        area.width_percent, area.height_percent = _d(h), _d(w)
        area.save(update_fields=["x_percent", "y_percent", "width_percent", "height_percent", "updated_at"])
    for marker in PlantLayoutMarker.objects.filter(layout=layout):
        if marker_is_unplaced(marker):
            continue
        x, y = float(marker.x_percent), float(marker.y_percent)
        nx, ny = (100 - y, x) if clockwise else (y, 100 - x)
        marker.x_percent, marker.y_percent = _d(_clamp(nx)), _d(_clamp(ny))
        marker.save(update_fields=["x_percent", "y_percent", "updated_at"])

    _store_layout_image(layout, image, fmt, "ruotata")
    verso = "a destra" if clockwise else "a sinistra"
    return TransformResult(True, f"Planimetria ruotata {verso}: reparti e macchine seguono la pianta.")


@transaction.atomic
def crop_layout(layout, *, x_percent: float, y_percent: float, width_percent: float, height_percent: float) -> TransformResult:
    """Tiene solo il riquadro indicato (in % dell'immagine attuale)."""
    image, fmt = _open_layout_image(layout)
    cx, cy = _clamp(float(x_percent)), _clamp(float(y_percent))
    cw = _clamp(float(width_percent), 0, 100 - cx)
    ch = _clamp(float(height_percent), 0, 100 - cy)
    if cw < 5 or ch < 5:
        return TransformResult(False, "Riquadro troppo piccolo: disegna l'area da tenere sulla planimetria.")
    if cw >= 99.5 and ch >= 99.5:
        return TransformResult(False, "Il riquadro copre già tutta la planimetria: niente da ritagliare.")
    W, H = image.size
    box = (round(cx / 100 * W), round(cy / 100 * H), round((cx + cw) / 100 * W), round((cy + ch) / 100 * H))
    image = image.crop(box)
    # Percentuali effettive dopo l'arrotondamento ai pixel.
    cx, cy = box[0] / W * 100, box[1] / H * 100
    cw, ch = (box[2] - box[0]) / W * 100, (box[3] - box[1]) / H * 100

    def remap_x(x: float) -> float:
        return (x - cx) / cw * 100

    def remap_y(y: float) -> float:
        return (y - cy) / ch * 100

    dropped_areas = 0
    for area in PlantLayoutArea.objects.filter(layout=layout):
        x0 = _clamp(remap_x(float(area.x_percent)))
        y0 = _clamp(remap_y(float(area.y_percent)))
        x1 = _clamp(remap_x(float(area.x_percent) + float(area.width_percent)))
        y1 = _clamp(remap_y(float(area.y_percent) + float(area.height_percent)))
        if x1 - x0 < 0.5 or y1 - y0 < 0.5:
            area.delete()
            dropped_areas += 1
            continue
        area.x_percent, area.y_percent = _d(x0), _d(y0)
        area.width_percent, area.height_percent = _d(x1 - x0), _d(y1 - y0)
        area.save(update_fields=["x_percent", "y_percent", "width_percent", "height_percent", "updated_at"])

    outside = 0
    for marker in PlantLayoutMarker.objects.filter(layout=layout):
        if marker_is_unplaced(marker):
            continue
        nx, ny = remap_x(float(marker.x_percent)), remap_y(float(marker.y_percent))
        if not (0 <= nx <= 100 and 0 <= ny <= 100):
            reset_marker_position(marker)
            outside += 1
        else:
            marker.x_percent, marker.y_percent = _d(nx), _d(ny)
        marker.save(update_fields=["x_percent", "y_percent", "updated_at"])

    _store_layout_image(layout, image, fmt, "ritagliata")
    bits = ["Planimetria ritagliata."]
    if outside:
        bits.append(f"{outside} macchin{'a' if outside == 1 else 'e'} fuori dal riquadro: ora da posizionare.")
    if dropped_areas:
        bits.append(f"{dropped_areas} repart{'o' if dropped_areas == 1 else 'i'} fuori dal riquadro eliminat{'o' if dropped_areas == 1 else 'i'}.")
    return TransformResult(True, " ".join(bits))

