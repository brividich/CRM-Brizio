"""Planimetrie per i ticket di manutenzione: riconoscere un asset dal punto in cui si trova.

Il caporeparto che segnala un guasto non sempre riconosce l'asset dal nome
(«Chiller 2206006809170001»): sulla pianta lo vede dov'è. Qui si prepara, per
le planimetrie attive, la posizione degli asset non IT già collocati e quali
sono «del tuo reparto».

Il «tuo reparto» si decide in due modi (Impostazioni ticket):

- ``testo``: il reparto scritto sulla scheda asset, riconosciuto per nome di
  reparto o area oppure tramite i collegamenti di Impostazioni asset › Reparti e capi;
- ``aree``: le aree dei reparti disegnate sulla planimetria (se una pianta non
  ne ha, per quella pianta si torna al testo).

Non scrive niente e non filtra per permessi: nel form del ticket si può
segnalare qualunque asset, la pianta evidenzia solo quelli di competenza.
"""
from __future__ import annotations

import logging

from ..models import IT_DEVICE_TYPES, Asset, PlantLayout
from .responsabile_asset import chiave_reparto

logger = logging.getLogger(__name__)

MODALITA_TESTO = "testo"
MODALITA_AREE = "aree"


def indice_unita() -> dict[str, frozenset[str]]:
    """Testo di reparto normalizzato → unità («r:<id>», «a:<id>»; un'area porta con sé il suo reparto)."""
    from anagrafica.models import AreaAziendale, Reparto

    from ..models import RepartoAssetCollegato

    indice: dict[str, frozenset[str]] = {}
    for rid, nome in Reparto.objects.filter(is_active=True).values_list("pk", "nome"):
        indice[chiave_reparto(nome)] = frozenset({f"r:{rid}"})
    reparto_di_area: dict[int, int | None] = {}
    for aid, nome, rid in AreaAziendale.objects.filter(is_active=True).values_list("pk", "nome", "reparto_id"):
        reparto_di_area[aid] = rid
        indice[chiave_reparto(nome)] = frozenset({f"a:{aid}"} | ({f"r:{rid}"} if rid else set()))
    for chiave, rid, aid in RepartoAssetCollegato.objects.values_list("chiave", "reparto_id", "area_id"):
        if aid:
            rid_area = reparto_di_area.get(aid)
            indice[chiave] = frozenset({f"a:{aid}"} | ({f"r:{rid_area}"} if rid_area else set()))
        elif rid:
            indice[chiave] = frozenset({f"r:{rid}"})
    return indice


def unita_di(testo, indice: dict[str, frozenset[str]]) -> frozenset[str]:
    """Le unità di un testo di reparto; un testo non riconosciuto vale solo per sé stesso."""
    chiave = chiave_reparto(testo)
    if not chiave:
        return frozenset()
    return indice.get(chiave) or frozenset({f"t:{chiave}"})


def unita_utente(reparto_testo: str, anagrafica_id: int | None, indice: dict[str, frozenset[str]]) -> frozenset[str]:
    """Il reparto della persona più i reparti e le aree di cui è capo o co-capo.

    Chi lavora in un'area ha solo quell'area, non tutto il reparto: le altre aree
    dello stesso reparto non sono sue.
    """
    unita = set(unita_di(reparto_testo, indice))
    if any(u.startswith("a:") for u in unita):
        unita = {u for u in unita if u.startswith("a:")}
    if anagrafica_id:
        try:
            from anagrafica.models import AreaAziendale, Reparto

            for rid in Reparto.objects.filter(is_active=True, caporeparto_legacy_id=anagrafica_id).values_list("pk", flat=True):
                unita.add(f"r:{rid}")
            for rid in Reparto.objects.filter(is_active=True, responsabili=anagrafica_id).values_list("pk", flat=True):
                unita.add(f"r:{rid}")
            for aid in AreaAziendale.objects.filter(is_active=True, responsabile_legacy_id=anagrafica_id).values_list("pk", flat=True):
                unita.add(f"a:{aid}")
            for aid in AreaAziendale.objects.filter(is_active=True, responsabili=anagrafica_id).values_list("pk", flat=True):
                unita.add(f"a:{aid}")
        except Exception:  # anagrafica non allineata: resta il reparto scritto
            logger.debug("Reparti di cui la persona è capo non risolti", exc_info=True)
    return frozenset(unita)


def stesso_reparto(testo_asset, mie: frozenset[str], indice: dict[str, frozenset[str]]) -> bool:
    """L'asset sta in un reparto (o area) della persona? Un reparto copre anche le sue aree."""
    if not mie:
        return False
    return bool(unita_di(testo_asset, indice) & mie)


def testo_reparto(asset: Asset) -> str:
    return asset.reparto or asset.assignment_reparto or ""


def _dentro(area: dict, x: float, y: float) -> bool:
    return area["_area"].contiene(x, y)


def mappe(
    reparto_testo: str = "",
    anagrafica_id: int | None = None,
    modalita: str = MODALITA_TESTO,
    solo_asset: int | None = None,
    solo_layout: int | None = None,
) -> list[dict]:
    """Le planimetrie attive con gli asset non IT collocati, pronte per ``json_script``.

    ``solo_asset`` / ``solo_layout`` restringono alle piante che contengono quell'asset
    o a quella pianta (pagine di dettaglio del ticket).
    """
    from .plant_layout_image import marker_is_unplaced

    try:
        indice = indice_unita()
    except Exception:
        logger.debug("Indice reparti non disponibile", exc_info=True)
        indice = {}
    mie = unita_utente(reparto_testo, anagrafica_id, indice)
    layouts = PlantLayout.objects.filter(is_active=True).prefetch_related("areas").order_by("category", "name", "id")
    if solo_layout:
        layouts = layouts.filter(pk=solo_layout)
    elif solo_asset:
        layouts = layouts.filter(markers__asset_id=solo_asset).distinct()

    risultato = []
    for layout in layouts:
        if not layout.image:
            continue
        aree = []
        for area in layout.areas.all():
            aree.append({
                "nome": area.name,
                "colore": area.color,
                "x": float(area.x_percent),
                "y": float(area.y_percent),
                "w": float(area.width_percent),
                "h": float(area.height_percent),
                "punti": area.punti if area.e_poligono else [],
                "mia": stesso_reparto(area.reparto_code, mie, indice),
                "_area": area,
            })
        da_aree = modalita == MODALITA_AREE and bool(aree)
        markers = []
        for m in (
            layout.markers.filter(is_visible=True)
            .exclude(asset__asset_type__in=IT_DEVICE_TYPES)
            .exclude(asset__status=Asset.STATUS_RETIRED)
            .select_related("asset", "asset__asset_category")
            .order_by("sort_order", "id")
        ):
            if marker_is_unplaced(m):
                continue
            a = m.asset
            x, y = float(m.x_percent), float(m.y_percent)
            reparto = testo_reparto(a)
            if da_aree:
                mio = any(area["mia"] and _dentro(area, x, y) for area in aree)
            else:
                mio = stesso_reparto(reparto, mie, indice)
            markers.append({
                "asset_id": a.pk,
                "x": x,
                "y": y,
                "nome": a.name,
                "tag": a.asset_tag or "",
                "categoria": a.asset_category.label if a.asset_category_id else a.get_asset_type_display(),
                "reparto": reparto,
                "mio": mio,
            })
        if not markers and not solo_layout:
            continue
        risultato.append({
            "id": layout.pk,
            "categoria": layout.category,
            "nome": layout.name,
            "immagine": layout.image.url,
            "aree": [{k: v for k, v in a.items() if k != "_area"} for a in aree] if da_aree else [],
            "da_aree": da_aree,
            "markers": markers,
            "mie": sum(1 for m in markers if m["mio"]),
        })
    return risultato


def asset_del_reparto(reparto_testo: str, anagrafica_id: int | None, qs) -> list[Asset]:
    """Gli asset di ``qs`` nei reparti della persona, col testo riconosciuto come nella mappa."""
    try:
        indice = indice_unita()
    except Exception:
        logger.debug("Indice reparti non disponibile", exc_info=True)
        indice = {}
    mie = unita_utente(reparto_testo, anagrafica_id, indice)
    if not mie:
        return []
    return [a for a in qs if stesso_reparto(testo_reparto(a), mie, indice)]
