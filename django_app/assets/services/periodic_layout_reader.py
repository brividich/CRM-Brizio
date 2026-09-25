"""Lettura della scansione di un foglio di verifica a planimetria.

Il riferimento e' il foglio stesso, rigenerato senza QR (``periodic_layout.build_sheet``):
la scansione viene allineata al foglio (rotazione a 90 gradi, scala, traslazione,
poi affinamento sui simboli dei punti) e tutto l'inchiostro che sul foglio non c'era
diventa un «segno». Ogni segno vicino a un punto propone quel punto.

Solo la planimetria conta: intestazione, QR e vecchio cartiglio sono fuori dalla
zona di ricerca. Nessuna AI: allineamento per correlazione e soglie di colore.
Le soglie sono espresse in punti della planimetria originale e scalate con il
foglio (``unit``), cosi' valgono per qualsiasi planimetria.

Il risultato e' una proposta: la conferma resta a una persona.
"""
from __future__ import annotations

import colorsys
import math
from collections import deque
from dataclasses import dataclass, field
from io import BytesIO

import fitz  # PyMuPDF
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from PIL import Image, ImageDraw, ImageFilter

FINE_DPI = 150
SEARCH_ZOOM = 0.25
COARSE_ZOOM = 0.5
SCALE_RANGE = (0.60, 1.40)  # pt scansione per pt foglio (A4 al 100% ~ 0.97-1.0)

# Soglie in punti della planimetria ORIGINALE (tarate sulle luci di emergenza, A3).
MATCH_RADIUS = 14.0
MIN_MARK_AREA = 6.0
MIN_PEN_AREA = 30.0
MIN_MARK_SIZE = 4.0
IGNORE_BEYOND = 40.0
MIN_LOOSE_COLOR_AREA = 40.0
MIN_HIGHLIGHT_THICK = 2.0
MAX_CIRCLE = 60.0
DARK_LUM = 175
CIRCLE_RING = (6.0, 32.0)  # corona in cui cercare un cerchio attorno a un punto
CIRCLE_SECTORS = 16
CIRCLE_MIN_KNOWN = 8  # settori in cui la carta era libera, per poter giudicare
CIRCLE_MIN_INKED = 6
CIRCLE_COVERAGE = 0.7  # quota dei settori liberi che il tratto deve toccare

KIND_HIGHLIGHT = "evidenziatore"
KIND_PEN = "penna"


@dataclass
class Mark:
    code: str | None
    kind: str
    shape: str
    color: str
    area: float
    distance: float
    candidates: list[tuple[str, float]]
    bbox_px: tuple[int, int, int, int]


@dataclass
class ReadResult:
    ok: bool
    registration: dict
    marks: list[Mark] = field(default_factory=list)
    overlay_png: bytes = b""

    @property
    def proposed(self) -> dict[str, str]:
        """Codice punto -> tipo del segno piu' evidente (evidenziatore vince sulla penna)."""
        out: dict[str, str] = {}
        for mark in self.marks:
            if mark.code and (mark.code not in out or mark.kind == KIND_HIGHLIGHT):
                out[mark.code] = mark.kind
        return out

    @property
    def unmatched(self) -> list[Mark]:
        return [m for m in self.marks if m.code is None]


# ---------------------------------------------------------------------------
# Immagini
# ---------------------------------------------------------------------------

def _scan_page_rgb(data: bytes, name: str = "") -> np.ndarray:
    """Prima pagina della scansione a FINE_DPI (PDF o immagine), carta normalizzata."""
    if data[:4] == b"%PDF" or name.lower().endswith(".pdf"):
        doc = fitz.open(stream=data, filetype="pdf")
    else:
        img = Image.open(BytesIO(data)).convert("RGB")
        w, h = img.size
        pw, ph = (595.0, 842.0) if h >= w else (842.0, 595.0)
        doc = fitz.open()
        page = doc.new_page(width=pw, height=ph)
        buf = BytesIO()
        img.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
    pix = doc[0].get_pixmap(dpi=FINE_DPI, colorspace=fitz.csRGB, alpha=False)
    rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).astype(np.float32)
    doc.close()
    paper = np.percentile(rgb.reshape(-1, 3), 90, axis=0)
    return np.clip(rgb / np.maximum(paper, 1) * 255.0, 0, 255).astype(np.uint8)


def _darkness(page: fitz.Page, zoom: float) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    return 1.0 - arr.astype(np.float32) / 255.0


def _to_img(arr):
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))


def _from_img(img):
    return np.asarray(img, dtype=np.float32) / 255.0


def _blur(arr, radius):
    return _from_img(_to_img(arr).filter(ImageFilter.GaussianBlur(radius)))


def _resize(arr, factor):
    img = _to_img(arr)
    return _from_img(img.resize((max(1, round(img.width * factor)), max(1, round(img.height * factor))), Image.BILINEAR))


def _phase_correlation(a, b):
    h = 1 << int(math.ceil(math.log2(max(a.shape[0], b.shape[0]) * 1.25)))
    w = 1 << int(math.ceil(math.log2(max(a.shape[1], b.shape[1]) * 1.25)))
    cross = np.fft.rfft2(b - b.mean(), s=(h, w)) * np.conj(np.fft.rfft2(a - a.mean(), s=(h, w)))
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.irfft2(cross, s=(h, w))
    acc = corr.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                acc += np.roll(np.roll(corr, dy, 0), dx, 1)
    dy, dx = np.unravel_index(np.argmax(acc), acc.shape)
    peak = float(acc[dy, dx])
    return peak, int(dy - h if dy > h // 2 else dy), int(dx - w if dx > w // 2 else dx)


def _match_template(window, tmpl):
    th, tw = tmpl.shape
    if window.shape[0] < th or window.shape[1] < tw:
        return -1.0, 0, 0
    views = sliding_window_view(window, (th, tw))
    t = tmpl - tmpl.mean()
    tn = np.sqrt((t * t).sum()) + 1e-6
    v = views - views.mean(axis=(2, 3), keepdims=True)
    ncc = (v * t).sum(axis=(2, 3)) / (np.sqrt((v * v).sum(axis=(2, 3))) * tn + 1e-6)
    y, x = np.unravel_index(np.argmax(ncc), ncc.shape)
    return float(ncc[y, x]), int(y), int(x)


def _fit_affine(src, dst):
    X = np.hstack([src, np.ones((len(src), 1))])
    M, *_ = np.linalg.lstsq(X, dst, rcond=None)
    return M


def _apply(M, pts):
    return np.hstack([pts, np.ones((len(pts), 1))]) @ M


def _to_ref(M, pts):
    return (pts - M[2]) @ np.linalg.inv(M[:2])


def _warp(ref_img, ref_zoom, M, size, resample=Image.BILINEAR, fill=0):
    Minv = np.linalg.inv(M[:2])
    a, d = Minv[0] * ref_zoom
    b, e = Minv[1] * ref_zoom
    c, f = (-M[2] @ Minv) * ref_zoom
    return ref_img.transform(size, Image.AFFINE, (a, b, c, d, e, f), resample=resample, fillcolor=fill)


# ---------------------------------------------------------------------------
# Allineamento
# ---------------------------------------------------------------------------

def _scan_dark(rgb):
    return np.clip(((1.0 - rgb.mean(axis=2).astype(np.float32) / 255.0) - 0.10) / 0.90, 0, 1)


class _Template:
    def __init__(self, page: fitz.Page):
        self.page = page
        self._cache: dict[float, np.ndarray] = {}

    def darkness(self, zoom: float) -> np.ndarray:
        key = round(zoom, 4)
        if key not in self._cache:
            self._cache[key] = _darkness(self.page, zoom)
        return self._cache[key]


def _coarse(tpl: _Template, dark, zoom, scales):
    fine_zoom = FINE_DPI / 72.0
    ref_c = _blur(tpl.darkness(zoom), 1.0)
    base = min(scales)
    small = _resize(dark, zoom / (base * fine_zoom))
    best = None
    for s in scales:
        peak, dy, dx = _phase_correlation(ref_c, _blur(_resize(small, base / s), 1.0))
        if best is None or peak > best[0]:
            best = (peak, float(s), dy, dx)
    return best


def register(tpl: _Template, points: np.ndarray, scan_rgb: np.ndarray, symbol_half_pt: float):
    fine_zoom = FINE_DPI / 72.0
    candidates = []
    for k in range(4):
        peak, s, _, _ = _coarse(tpl, _scan_dark(np.rot90(scan_rgb, k)), SEARCH_ZOOM, np.arange(*SCALE_RANGE, 0.02))
        candidates.append((peak, k, s))
    candidates.sort(reverse=True)
    _, k, s0 = candidates[0]
    rgb = np.ascontiguousarray(np.rot90(scan_rgb, k))
    dark = _scan_dark(rgb)
    _, s, dy, dx = _coarse(tpl, dark, COARSE_ZOOM, np.arange(s0 - 0.02, s0 + 0.0201, 0.004))
    factor = COARSE_ZOOM / (s * fine_zoom)
    M = np.array([[COARSE_ZOOM / factor, 0.0], [0.0, COARSE_ZOOM / factor], [dx / factor, dy / factor]])

    scan_blur = _blur(dark, 0.8)
    info = {"rotazione_gradi": 90 * k, "scala": round(float(s), 4), "simboli_totali": int(len(points))}
    for half_win in (30, 12, 6):
        scale = math.sqrt(abs(np.linalg.det(M[:2])))
        ref_fine = _blur(tpl.darkness(scale), 0.8)
        half = max(4, int(round(symbol_half_pt * scale)))
        src_ok, dst_ok = [], []
        for (rx, ry), (px, py) in zip(points, _apply(M, points)):
            cx, cy = int(round(rx * scale)), int(round(ry * scale))
            tmpl = ref_fine[cy - half:cy + half + 1, cx - half:cx + half + 1]
            ix, iy = int(round(px)), int(round(py))
            y0, x0 = iy - half - half_win, ix - half - half_win
            win = scan_blur[max(0, y0):iy + half + half_win + 1, max(0, x0):ix + half + half_win + 1]
            if tmpl.shape != (2 * half + 1,) * 2 or win.size == 0:
                continue
            score, wy, wx = _match_template(win, tmpl)
            if score < 0.45:
                continue
            src_ok.append((rx, ry))
            dst_ok.append((max(0, x0) + wx + half, max(0, y0) + wy + half))
        if len(src_ok) < 6:
            break
        src, dst = np.array(src_ok), np.array(dst_ok)
        keep = np.ones(len(src), bool)
        for _ in range(3):
            res = np.linalg.norm(_apply(_fit_affine(src[keep], dst[keep]), src) - dst, axis=1)
            new_keep = res < max(2.0, 3.0 * float(np.median(res[keep])))
            if new_keep.sum() < 6 or (new_keep == keep).all():
                break
            keep = new_keep
        M = _fit_affine(src[keep], dst[keep])
        res = np.linalg.norm(_apply(M, src) - dst, axis=1)[keep]
        info.update({"simboli_agganciati": int(keep.sum()), "residuo_rms_px": round(float(np.sqrt((res ** 2).mean())), 2)})
    info["affidabile"] = bool(
        info.get("simboli_agganciati", 0) >= max(6, 0.6 * len(points)) and info.get("residuo_rms_px", 99) < 4
    )
    return rgb, M, info


# ---------------------------------------------------------------------------
# Segni
# ---------------------------------------------------------------------------

def _components(mask):
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    comps = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        q = deque([(y, x)])
        seen[y, x] = True
        pts = []
        while q:
            cy, cx = q.popleft()
            pts.append((cy, cx))
            for ny in (cy - 1, cy, cy + 1):
                for nx in (cx - 1, cx, cx + 1):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        q.append((ny, nx))
        comps.append(np.array(pts))
    return comps


def _color_name(rgb_mean) -> str:
    h, s, _v = colorsys.rgb_to_hsv(*(float(c) / 255.0 for c in rgb_mean))
    if s < 0.25:
        return "nero/grigio"
    deg = h * 360
    for limit, name in ((15, "rosso"), (45, "arancione"), (70, "giallo"), (165, "verde"),
                        (200, "azzurro"), (255, "blu"), (290, "viola"), (345, "rosa/fucsia"), (361, "rosso")):
        if deg < limit:
            return name
    return "?"


def _region(page_w, page_h, M, size, rects, inside):
    zoom = 0.5
    img = Image.new("L", (int(page_w * zoom) + 1, int(page_h * zoom) + 1), 0)
    dr = ImageDraw.Draw(img)
    for x0, y0, x1, y1 in rects:
        dr.rectangle([x0 * zoom, y0 * zoom, x1 * zoom, y1 * zoom], fill=255)
    m = np.asarray(_warp(img, zoom, M, size, resample=Image.NEAREST)) > 127
    return m if inside else ~m


def find_marks(tpl, rgb, M, codes, pts, labels, search_rect, exclude, unit) -> list[Mark]:
    h, w = rgb.shape[:2]
    scale = math.sqrt(abs(np.linalg.det(M[:2])))
    px2 = scale * scale
    u2 = unit * unit

    ref_ink = _warp(_to_img((tpl.darkness(scale) > 0.12).astype(np.float32)), scale, M, (w, h), resample=Image.NEAREST)
    dil = max(5, int(round(2.2 * unit * scale)) | 1)
    ref_ink = np.asarray(ref_ink.filter(ImageFilter.MaxFilter(dil))) > 127

    f = rgb.astype(np.int16)
    mx, mn = f.max(axis=2), f.min(axis=2)
    colored = (mx - mn > 45) & (mx > 60)
    ink = (colored | (f.mean(axis=2) < DARK_LUM)) & ~ref_ink
    rect = tpl.page.rect
    ink &= _region(rect.width, rect.height, M, (w, h), [search_rect], inside=True)
    if exclude:
        ink &= _region(rect.width, rect.height, M, (w, h), exclude, inside=False)

    k = max(3, int(round(1.6 * unit * scale)) | 1)
    closed = np.asarray(
        Image.fromarray(ink.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(max(3, k - 2)))
    ) > 127

    out = []
    for comp in _components(closed):
        ys, xs = comp[:, 0], comp[:, 1]
        real = ink[ys, xs]
        n = int(real.sum())
        area = n / px2
        if area < MIN_MARK_AREA * u2:
            continue
        bw, bh = (xs.max() - xs.min() + 1) / scale, (ys.max() - ys.min() + 1) / scale
        if max(bw, bh) < MIN_MARK_SIZE * unit:
            continue
        ry, rx = ys[real], xs[real]
        color = _color_name(rgb[ry, rx].mean(axis=0))
        if color == "rosso":
            continue  # inchiostro della planimetria (residui della stampa a colori)
        is_col = colored[ry, rx].mean() > 0.5 and color != "nero/grigio"
        if is_col and area / max(bw, bh) < MIN_HIGHLIGHT_THICK * unit:
            continue
        fill = area / (bw * bh)
        aspect = max(bw, bh) / max(1e-6, min(bw, bh))
        shape = "linea" if aspect > 3.5 else ("cerchio" if fill < 0.35 else "campitura")
        if not is_col and shape == "linea":
            continue
        if not is_col and shape == "cerchio" and not (8 * unit <= max(bw, bh) <= MAX_CIRCLE * unit):
            continue
        if not is_col and shape == "campitura" and area < MIN_PEN_AREA * u2:
            continue
        cy, cx = ((ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2) if shape == "cerchio" else (ry.mean(), rx.mean())
        refp = _to_ref(M, np.array([[cx, cy]]))[0]
        d = np.minimum(np.linalg.norm(pts - refp, axis=1), np.linalg.norm(labels - refp, axis=1))
        order = np.argsort(d)
        i0 = order[0]
        code = codes[i0] if d[i0] <= MATCH_RADIUS * unit else None
        if shape == "cerchio" and code is None:
            corners = _to_ref(M, np.array([[xs.min(), ys.min()], [xs.max(), ys.max()]], float))
            x0, x1 = sorted(corners[:, 0])
            y0, y1 = sorted(corners[:, 1])
            inside = [i for i in order if x0 <= pts[i, 0] <= x1 and y0 <= pts[i, 1] <= y1]
            if inside:
                code = codes[inside[0]]
        if code is None and d[i0] > IGNORE_BEYOND * unit * (2 if is_col else 1):
            continue
        if code is None and is_col and area < MIN_LOOSE_COLOR_AREA * u2:
            continue
        out.append(Mark(
            code=code,
            kind=KIND_HIGHLIGHT if is_col else KIND_PEN,
            shape=shape,
            color=color,
            area=round(area / u2, 1),
            distance=round(float(d[i0]) / unit, 1),
            candidates=[(codes[i], round(float(d[i]) / unit, 1)) for i in order[:3]],
            bbox_px=(int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
        ))

    # Cerchi a penna spezzati dove passano sopra simboli e scritte stampate: per ogni
    # punto non ancora segnato si guarda la corona attorno. Un cerchio a mano ne copre
    # quasi tutti i settori; sporco, scritte e tratti isolati solo qualcuno.
    dark_new = ink & ~colored
    marked = {m.code for m in out if m.code}
    r_in, r_out = CIRCLE_RING[0] * unit * scale, CIRCLE_RING[1] * unit * scale
    for code, (cx, cy) in zip(codes, _apply(M, pts)):
        if code in marked:
            continue
        x0, x1 = max(0, int(cx - r_out)), min(w, int(cx + r_out) + 1)
        y0, y1 = max(0, int(cy - r_out)), min(h, int(cy + r_out) + 1)
        ys, xs = np.nonzero(dark_new[y0:y1, x0:x1])
        if len(ys) == 0:
            continue
        dx, dy = xs + x0 - cx, ys + y0 - cy
        dist = np.hypot(dx, dy)
        ring = (dist >= r_in) & (dist <= r_out)
        if ring.sum() < 8:
            continue
        # Raggio del presunto cerchio e fascia attorno: li' si misura la copertura.
        radius = float(np.median(dist[ring]))
        band_lo, band_hi = radius * 0.75, radius * 1.25
        in_band = ring & (dist >= band_lo) & (dist <= band_hi)
        sectors = ((np.arctan2(dy[in_band], dx[in_band]) + math.pi) / (2 * math.pi) * CIRCLE_SECTORS).astype(int) % CIRCLE_SECTORS
        inked = np.bincount(sectors, minlength=CIRCLE_SECTORS) >= 2
        # Settori in cui la fascia era gia' occupata dalla stampa: li' non si puo' sapere.
        gy, gx = np.mgrid[y0:y1, x0:x1]
        gdist = np.hypot(gx - cx, gy - cy)
        band = (gdist >= band_lo) & (gdist <= band_hi)
        gsec = ((np.arctan2(gy - cy, gx - cx) + math.pi) / (2 * math.pi) * CIRCLE_SECTORS).astype(int) % CIRCLE_SECTORS
        free = ~ref_ink[y0:y1, x0:x1] & band
        free_share = np.bincount(gsec[free], minlength=CIRCLE_SECTORS) / np.maximum(
            np.bincount(gsec[band], minlength=CIRCLE_SECTORS), 1)
        known = free_share >= 0.3
        if known.sum() < CIRCLE_MIN_KNOWN:
            continue
        if (inked & known).sum() >= max(CIRCLE_MIN_INKED, CIRCLE_COVERAGE * known.sum()):
            rx, ry = xs[in_band] + x0, ys[in_band] + y0
            out.append(Mark(
                code=code, kind=KIND_PEN, shape="cerchio", color="nero/grigio",
                area=round(float(ring.sum()) / px2 / u2, 1), distance=0.0, candidates=[(code, 0.0)],
                bbox_px=(int(rx.min()), int(ry.min()), int(rx.max()), int(ry.max())),
            ))
    return out


def _overlay(rgb, M, codes, pts, marks) -> bytes:
    img = Image.fromarray(rgb).convert("RGB")
    dr = ImageDraw.Draw(img)
    for code, (x, y) in zip(codes, _apply(M, pts)):
        dr.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(0, 90, 255), width=1)
    for mark in marks:
        x0, y0, x1, y1 = mark.bbox_px
        color = (0, 160, 0) if mark.code else (230, 120, 0)
        dr.rectangle([x0 - 4, y0 - 4, x1 + 4, y1 + 4], outline=color, width=3)
        dr.text((x1 + 6, y0 - 2), mark.code or "?", fill=color)
    if img.width > 1400:
        img = img.resize((1400, round(img.height * 1400 / img.width)), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def read_scan(
    scan: bytes,
    *,
    template_pdf: bytes,
    points: list[dict],
    search_rect: tuple[float, float, float, float],
    exclude: list | None = None,
    unit: float = 1.0,
    scan_name: str = "",
) -> ReadResult:
    """Legge una scansione. ``points``, ``search_rect`` ed ``exclude`` sono in punti del
    foglio; ``unit`` = punti del foglio per punto della planimetria originale."""
    doc = fitz.open(stream=template_pdf, filetype="pdf")
    tpl = _Template(doc[0])
    codes = [p["code"] for p in points]
    pts = np.array([[p["x"], p["y"]] for p in points], float)
    labels = np.array([[p.get("label_x") or p["x"], p.get("label_y") or p["y"]] for p in points], float)
    rgb = _scan_page_rgb(scan, scan_name)
    rgb, M, info = register(tpl, pts, rgb, symbol_half_pt=9 * unit)
    if not info["affidabile"]:
        return ReadResult(False, info, [], _overlay(rgb, M, codes, pts, []))
    marks = find_marks(tpl, rgb, M, codes, pts, labels, search_rect, exclude or [], unit)
    marks.sort(key=lambda m: (m.code is None, m.code or ""))
    return ReadResult(True, info, marks, _overlay(rgb, M, codes, pts, marks))
