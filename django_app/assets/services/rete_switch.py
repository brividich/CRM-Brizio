"""Collegamenti di rete visti dal lato switch: scelta dello switch e mappa delle porte.

``AssetEndpoint.switch_name`` e' testo libero. Un punto rete e' "collegato" a uno
switch censito quando quel testo coincide (senza distinzione di maiuscole) con la
matricola o con il nome dell'asset switch: dalla scheda si sceglie lo switch e si
salva la matricola, che e' univoca. Nessun dato viene dedotto da nome o IP.

La porta segue la convenzione dell'inventario ``<switch>.<membro stack>.<porta>``
(es. ``A0.1.37``) oppure ``<switch>.<porta>`` (es. ``A1.19``); il prefisso serve a
collegare in blocco allo switch le porte gia' censite senza switch indicato.
"""
from __future__ import annotations

import re

from django.db.models import Q

from ..models import Asset, AssetEndpoint

_PORTA = re.compile(r"^\s*([A-Za-z0-9]+?)\s*[./:]\s*(?:([0-9]+)\s*[./:]\s*)?([0-9]+)\s*$")
_PREFISSO = re.compile(r"^[A-Za-z0-9_-]{1,20}$")


def scomponi_porta(valore: str) -> tuple[str, str, int] | None:
    """``(prefisso, membro, numero)`` della porta, oppure None se non segue la convenzione."""
    match = _PORTA.match(valore or "")
    if not match:
        return None
    return match.group(1).upper(), match.group(2) or "", int(match.group(3))


def prefisso_valido(valore: str) -> str:
    valore = (valore or "").strip().upper()
    return valore if _PREFISSO.match(valore) else ""


def _filtro_switch() -> Q:
    return (
        Q(asset_type=Asset.TYPE_FIREWALL)
        | Q(name__icontains="switch")
        | Q(asset_category__label__icontains="switch")
        | Q(asset_category__label__icontains="apparati rete")
        | Q(asset_category__label__icontains="apparati di rete")
    )


def switch_disponibili() -> list[dict]:
    """Apparati di rete censiti, per la tendina "Switch" della modifica rete."""
    rows = (
        Asset.objects.filter(_filtro_switch())
        .exclude(status=Asset.STATUS_RETIRED)
        .order_by("name", "asset_tag")
        .values("id", "asset_tag", "name")[:300]
    )
    return [{"id": r["id"], "valore": r["asset_tag"], "etichetta": f"{r['asset_tag']} — {r['name']}"} for r in rows]


def chiavi_switch(asset: Asset) -> list[str]:
    return [v for v in {(asset.asset_tag or "").strip(), (asset.name or "").strip()} if v]


def risolvi_switch(endpoints) -> dict[str, Asset]:
    """Mappa ``switch_name`` (casefold) -> asset switch, per linkare la scheda dello switch."""
    nomi = {(e.switch_name or "").strip() for e in endpoints if (e.switch_name or "").strip()}
    if not nomi:
        return {}
    filtro = Q()
    for nome in nomi:
        filtro |= Q(asset_tag__iexact=nome) | Q(name__iexact=nome)
    trovati: dict[str, Asset] = {}
    for asset in Asset.objects.filter(filtro).only("id", "asset_tag", "name").order_by("id"):
        trovati.setdefault(asset.asset_tag.casefold(), asset)
        trovati.setdefault((asset.name or "").casefold(), asset)
    return {nome.casefold(): trovati[nome.casefold()] for nome in nomi if nome.casefold() in trovati}


def _endpoint_collegati(asset: Asset):
    filtro = Q()
    for chiave in chiavi_switch(asset):
        filtro |= Q(switch_name__iexact=chiave)
    if not filtro:
        return AssetEndpoint.objects.none()
    return (
        AssetEndpoint.objects.filter(filtro)
        .exclude(asset_id=asset.id)
        .select_related("asset")
        .order_by("switch_port", "id")
    )


def _classi_vlan(endpoints) -> dict:
    """Colore per VLAN in base all'ordine delle VLAN presenti sullo switch (8 colori, poi si ripete)."""
    vlan = sorted({ep.vlan for ep in endpoints if ep.vlan is not None})
    return {v: f"af-vl{i % 8}" for i, v in enumerate(vlan)}


def mappa_switch(asset: Asset) -> dict | None:
    """Pannello frontale dello switch: porte occupate per membro dello stack."""
    collegati = list(_endpoint_collegati(asset))
    colori = _classi_vlan(collegati)
    membri: dict[tuple[str, str], dict[int, list]] = {}
    altre = []
    for ep in collegati:
        parti = scomponi_porta(ep.switch_port)
        if parti is None:
            altre.append(ep)
            continue
        prefisso, membro, numero = parti
        membri.setdefault((prefisso, membro), {}).setdefault(numero, []).append(ep)
    pannelli = []
    for (prefisso, membro), porte in sorted(membri.items()):
        massimo = max(porte)
        totale = 24 if massimo <= 24 else 48 if massimo <= 48 else massimo + (massimo % 2)
        slot = []
        for numero in range(1, totale + 1):
            occupanti = porte.get(numero, [])
            primo = occupanti[0] if occupanti else None
            slot.append({
                "numero": numero,
                "occupanti": occupanti,
                "conflitto": len(occupanti) > 1,
                "classe": colori.get(primo.vlan, "af-vlx") if primo else "",
            })
        pannelli.append({
            "titolo": f"{prefisso}.{membro}" if membro else prefisso,
            "membro": membro,
            "sopra": [s for s in slot if s["numero"] % 2 == 1],
            "sotto": [s for s in slot if s["numero"] % 2 == 0],
            "occupate": len(porte),
            "totale": totale,
        })

    return {
        "pannelli": pannelli,
        "altre": altre,
        "collegati": collegati,
        "totale": len(collegati),
        "vlan": [{"vlan": v, "classe": c} for v, c in colori.items()],
        "prefissi_liberi": prefissi_senza_switch(),
    }


def prefissi_senza_switch() -> list[dict]:
    """Prefissi di porta ancora senza switch indicato, con quante porte li usano."""
    conteggi: dict[str, int] = {}
    for porta in AssetEndpoint.objects.filter(switch_name="").exclude(switch_port="").values_list("switch_port", flat=True):
        parti = scomponi_porta(porta)
        if parti:
            conteggi[parti[0]] = conteggi.get(parti[0], 0) + 1
    return [{"prefisso": k, "porte": v} for k, v in sorted(conteggi.items())]


def endpoint_con_prefisso(prefisso: str) -> list[AssetEndpoint]:
    """Punti rete senza switch la cui porta inizia con ``prefisso``."""
    return [
        ep for ep in AssetEndpoint.objects.filter(switch_name="").exclude(switch_port="")
        if (parti := scomponi_porta(ep.switch_port)) and parti[0] == prefisso
    ]


def is_switch(asset: Asset) -> bool:
    return Asset.objects.filter(_filtro_switch(), pk=asset.pk).exists()
