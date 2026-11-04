"""Pianta base + livelli di servizio.

Le piante dei servizi (condizionatori, differenziali, telecamere...) sono lo
stesso edificio stampato con scala, ritaglio o rotazione diversi. Un livello si
appoggia a una **pianta base** con due punti uguali indicati su entrambe le
immagini: da lì una similitudine (scala, rotazione, spostamento) porta ogni
punto del livello sulla base. I marker restano sul livello con le loro
coordinate: la base li mostra trasformati, accesi o spenti come strati.
"""
from __future__ import annotations

import cmath

from ..models import Asset, AssetCategory, PlantLayout

COLORI_LIVELLI = ["#0EA5E9", "#F97316", "#A855F7", "#22C55E", "#EF4444", "#EAB308", "#14B8A6", "#EC4899"]


class ErroreAllineamento(ValueError):
    pass


def dimensioni_immagine(layout: PlantLayout) -> tuple[int, int]:
    try:
        return int(layout.image.width or 0), int(layout.image.height or 0)
    except (OSError, ValueError, AttributeError):
        return 0, 0


def calcola_matrice(punti: list[list[float]], dim_livello: tuple[int, int], dim_base: tuple[int, int]) -> list[float]:
    """Matrice affine in % (livello → base) da due coppie di punti ``[x, y, xb, yb]`` in %.

    Il calcolo è in pixel, così anche immagini di proporzioni diverse e ruotate di 90° tornano allineate.
    """
    if len(punti) != 2:
        raise ErroreAllineamento("Servono due coppie di punti.")
    wl, hl = dim_livello
    wb, hb = dim_base
    if not (wl and hl and wb and hb):
        raise ErroreAllineamento("Le immagini delle due piante non si possono leggere.")
    (x1, y1, bx1, by1), (x2, y2, bx2, by2) = [[float(v) for v in p] for p in punti]
    l1, l2 = complex(x1 * wl / 100, y1 * hl / 100), complex(x2 * wl / 100, y2 * hl / 100)
    b1, b2 = complex(bx1 * wb / 100, by1 * hb / 100), complex(bx2 * wb / 100, by2 * hb / 100)
    if abs(l2 - l1) < 1 or abs(b2 - b1) < 1:
        raise ErroreAllineamento("I due punti sono troppo vicini: scegline due lontani (es. due angoli opposti).")
    s = (b2 - b1) / (l2 - l1)
    t = b1 - s * l1

    def porta(u: float, v: float) -> tuple[float, float]:
        z = s * complex(u * wl / 100, v * hl / 100) + t
        return z.real / wb * 100, z.imag / hb * 100

    ox, oy = porta(0, 0)
    ax, ay = porta(100, 0)
    bx, by = porta(0, 100)
    return [round(v, 6) for v in ((ax - ox) / 100, (bx - ox) / 100, ox, (ay - oy) / 100, (by - oy) / 100, oy)]


def descrivi_matrice(matrice: list[float], dim_livello: tuple[int, int], dim_base: tuple[int, int]) -> dict:
    """Scala e rotazione leggibili (per la pagina): «ruotata di 90°, scala 1,25»."""
    wl, hl = dim_livello
    wb, hb = dim_base
    if not (wl and wb):
        return {}
    a, _b, _c, d, _e, _f = matrice
    z = complex(a * wb / wl, d * hb / wl)  # immagine di un passo di un pixel lungo x
    return {"scala": round(abs(z), 3), "rotazione": round((cmath.phase(z) * 180 / cmath.pi) % 360, 1)}


def salva_allineamento(livello: PlantLayout, base: PlantLayout, punti: list[list[float]]) -> None:
    if base.pk == livello.pk:
        raise ErroreAllineamento("Una pianta non può essere il livello di se stessa.")
    if base.base_id:
        raise ErroreAllineamento("La pianta base scelta è a sua volta un livello: scegli la sua pianta base.")
    matrice = calcola_matrice(punti, dimensioni_immagine(livello), dimensioni_immagine(base))
    livello.base = base
    livello.allineamento = {
        "matrice": matrice,
        "punti": [[round(float(v), 2) for v in p] for p in punti],
        "base_immagine": base.image.name if base.image else "",
        "da_verificare": False,
    }
    if not livello.colore:
        usati = set(PlantLayout.objects.filter(base=base).exclude(pk=livello.pk).values_list("colore", flat=True))
        livello.colore = next((c for c in COLORI_LIVELLI if c not in usati), COLORI_LIVELLI[0])
    livello.save(update_fields=["base", "allineamento", "colore", "updated_at"])


def rimappa_riferimenti(layout: PlantLayout, porta) -> None:
    """Dopo una rotazione o un ritaglio: punti di allineamento (come livello e come base) e scala seguono la pianta."""
    def nuovo(x, y):
        nx, ny = porta(float(x), float(y))
        return round(min(100.0, max(0.0, nx)), 2), round(min(100.0, max(0.0, ny)), 2)

    layout.refresh_from_db()
    campi = []
    punti = (layout.allineamento or {}).get("punti") or []
    if layout.base_id and len(punti) == 2:
        nuovi = [[*nuovo(p[0], p[1]), p[2], p[3]] for p in punti]
        try:
            matrice = calcola_matrice(nuovi, dimensioni_immagine(layout), dimensioni_immagine(layout.base))
            layout.allineamento = {**layout.allineamento, "punti": nuovi, "matrice": matrice}
        except ErroreAllineamento:
            layout.allineamento = {**layout.allineamento, "da_verificare": True}
        campi.append("allineamento")
    scala = layout.scala or {}
    if scala.get("punti"):
        w, h = dimensioni_immagine(layout)
        layout.scala = {**scala, "punti": [list(nuovo(*p)) for p in scala["punti"][:2]],
                        "rapporto": round(h / w, 6) if w else scala.get("rapporto")}
        campi.append("scala")
    if campi:
        layout.save(update_fields=[*campi, "updated_at"])
    for livello in PlantLayout.objects.filter(base=layout):
        punti = (livello.allineamento or {}).get("punti") or []
        if len(punti) != 2:
            continue
        nuovi = [[p[0], p[1], *nuovo(p[2], p[3])] for p in punti]
        try:
            matrice = calcola_matrice(nuovi, dimensioni_immagine(livello), dimensioni_immagine(layout))
            livello.allineamento = {**livello.allineamento, "punti": nuovi, "matrice": matrice,
                                    "base_immagine": layout.image.name if layout.image else ""}
        except ErroreAllineamento:
            livello.allineamento = {**livello.allineamento, "da_verificare": True}
        livello.save(update_fields=["allineamento", "updated_at"])


def livelli_della_base(base: PlantLayout | None) -> list[PlantLayout]:
    """Livelli attivi e allineati di una pianta base."""
    if base is None or not base.pk:
        return []
    return [
        livello for livello in PlantLayout.objects.filter(base=base, is_active=True).order_by("category", "name", "id")
        if livello.matrice
    ]


def payload_livelli(base: PlantLayout | None, machines_by_id: dict | None = None, ticket_map: dict | None = None) -> list[dict]:
    """I marker dei livelli portati sulla pianta base, con quel che serve alla mappa per mostrarli e cercarli."""
    from django.urls import reverse

    from .plant_layout_image import marker_is_unplaced

    machines_by_id = machines_by_id or {}
    ticket_map = ticket_map or {}
    out = []
    for indice, livello in enumerate(livelli_della_base(base)):
        markers = []
        for marker in livello.markers.select_related("asset", "asset__asset_category").order_by("sort_order", "id"):
            asset = marker.asset
            if marker_is_unplaced(marker) or asset.status == Asset.STATUS_RETIRED:
                continue
            punto = livello.su_base(marker.x_percent, marker.y_percent)
            if punto is None or not (-2 <= punto[0] <= 102 and -2 <= punto[1] <= 102):
                continue
            macchina = dict(machines_by_id.get(asset.id) or {})
            tickets = ticket_map.get(asset.id, macchina.get("tickets") or [])
            if not macchina:
                macchina = {
                    "id": asset.id,
                    "asset_tag": asset.asset_tag,
                    "internal_number": (asset.internal_number or "").strip(),
                    "name": asset.name,
                    "reparto": (asset.reparto or "").strip(),
                    "status": asset.get_status_display(),
                    "manufacturer": (asset.manufacturer or "").strip(),
                    "model": (asset.model or "").strip(),
                    "detail_url": reverse("assets:asset_view", kwargs={"id": asset.id}),
                    "tickets": tickets,
                }
            macchina["category"] = asset.asset_category.label if asset.asset_category_id else ""
            macchina["serial_number"] = (asset.serial_number or "").strip()
            allerta = macchina.get("alert") or ("ticket" if tickets else "ok")
            markers.append({
                "id": f"L{livello.id}-{marker.id}",
                "asset_id": asset.id,
                "label": marker.label or asset.asset_tag or asset.name,
                "x_percent": max(0.0, min(100.0, punto[0])),
                "y_percent": max(0.0, min(100.0, punto[1])),
                "machine": macchina,
                "alert": allerta,
                "open_tickets": len(tickets),
                "tickets": tickets,
                "area_ids": [],
                "livello": livello.id,
            })
        out.append({
            "id": livello.id,
            "nome": livello.category,
            "pianta": livello.name,
            "colore": livello.colore or COLORI_LIVELLI[indice % len(COLORI_LIVELLI)],
            "da_verificare": bool((livello.allineamento or {}).get("da_verificare")),
            "markers": markers,
        })
    return out


def copertura(layout: PlantLayout) -> dict | None:
    """Asset delle categorie della planimetria: quanti sono collocati e quali mancano."""
    from .plant_layout_image import marker_is_unplaced

    categorie = set(layout.asset_categories.values_list("id", flat=True))
    if not categorie:
        return None
    from .planimetria_lettura import _con_figlie

    tutte = _con_figlie(categorie)
    assets = list(
        Asset.objects.filter(asset_category_id__in=tutte).exclude(status=Asset.STATUS_RETIRED)
        .only("id", "name", "asset_tag", "internal_number").order_by("name")
    )
    collocati = {
        m.asset_id for m in layout.markers.all() if not marker_is_unplaced(m)
    }
    mancanti = [a for a in assets if a.id not in collocati]
    totale = len(assets)
    return {
        "totale": totale,
        "collocati": totale - len(mancanti),
        "percentuale": round((totale - len(mancanti)) / totale * 100) if totale else 100,
        "mancanti": mancanti[:200],
        "categorie": list(AssetCategory.objects.filter(id__in=categorie).values_list("label", flat=True)),
    }


def url_mappa_marker(marker) -> str:
    """Mappa centrata sull'asset del marker: per un livello allineato, la pianta base con il livello acceso."""
    from urllib.parse import urlencode

    from django.urls import reverse

    layout = marker.layout
    parametri = {"asset": marker.asset_id}
    if layout.allineato and layout.base is not None and layout.base.is_active:
        parametri.update({"category": layout.base.category, "livelli": layout.id})
    else:
        parametri["category"] = layout.category
    return f"{reverse('assets:plant_layout_map')}?{urlencode(parametri)}"


def url_mappa_asset(asset) -> str:
    """«Dov'è?»: link alla mappa se l'asset è collocato su una pianta attiva, altrimenti stringa vuota."""
    from ..models import PlantLayoutMarker
    from .plant_layout_image import marker_is_unplaced

    if asset is None or not getattr(asset, "pk", None):
        return ""
    for marker in (
        PlantLayoutMarker.objects.filter(asset=asset, layout__is_active=True)
        .select_related("layout", "layout__base").order_by("layout__base_id", "layout__category", "id")
    ):
        if not marker_is_unplaced(marker):
            return url_mappa_marker(marker)
    return ""

