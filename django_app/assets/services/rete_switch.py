"""Collegamenti di rete visti dal lato switch: scelta dello switch e mappa delle porte.

``AssetEndpoint.switch_name`` e' testo libero. Un punto rete e' "collegato" a uno
switch censito quando quel testo coincide (senza distinzione di maiuscole) con la
matricola o con il nome dell'asset switch: dalla scheda si sceglie lo switch e si
salva la matricola, che e' univoca. Nessun dato viene dedotto da nome o IP.

La porta segue la convenzione dell'inventario ``<switch>.<membro stack>.<porta>``
(es. ``A0.1.37``) oppure ``<switch>.<porta>`` (es. ``A1.19``). Lo switch puo' dichiarare
il suo prefisso (``Asset.switch_prefisso_porte``, es. "A0"): i punti rete SENZA switch
indicato e con quel prefisso gli appartengono, anche quelli aggiunti dopo. Uno
``switch_name`` esplicito vince sempre sul prefisso.
"""
from __future__ import annotations

import re

from django.db.models import Q

from ..models import Asset, AssetEndpoint

_PORTA = re.compile(r"^\s*([A-Za-z0-9]+?)\s*[./:]\s*(?:([0-9]+)\s*[./:]\s*)?([0-9]+)\s*$")
_PREFISSO = re.compile(r"^[A-Z0-9]{1,20}$")


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
        | Q(switch_prefisso_porte__gt="")
    )


def switch_disponibili() -> list[dict]:
    """Apparati di rete censiti, per la tendina "Switch" della modifica rete."""
    rows = (
        Asset.objects.filter(_filtro_switch())
        .exclude(status=Asset.STATUS_RETIRED)
        .order_by("name", "asset_tag")
        .values("id", "asset_tag", "name", "switch_prefisso_porte")[:300]
    )
    return [
        {
            "id": r["id"],
            "valore": r["asset_tag"],
            "etichetta": f"{r['asset_tag']} — {r['name']}"
            + (f" (porte {r['switch_prefisso_porte']})" if r["switch_prefisso_porte"] else ""),
        }
        for r in rows
    ]


def chiavi_switch(asset: Asset) -> list[str]:
    return [v for v in {(asset.asset_tag or "").strip(), (asset.name or "").strip()} if v]


def switch_per_endpoint(endpoints) -> dict[int, tuple[Asset, bool]]:
    """``endpoint.id -> (switch, da_prefisso)`` per linkare la scheda dello switch."""
    endpoints = list(endpoints)
    nomi = {(e.switch_name or "").strip() for e in endpoints if (e.switch_name or "").strip()}
    prefissi = {
        parti[0] for e in endpoints
        if not (e.switch_name or "").strip() and (parti := scomponi_porta(e.switch_port))
    }
    if not nomi and not prefissi:
        return {}
    filtro = Q(pk__in=[])
    for nome in nomi:
        filtro |= Q(asset_tag__iexact=nome) | Q(name__iexact=nome)
    if prefissi:
        filtro |= Q(switch_prefisso_porte__in=prefissi)
    per_nome: dict[str, Asset] = {}
    per_prefisso: dict[str, Asset] = {}
    for asset in Asset.objects.filter(filtro).only("id", "asset_tag", "name", "switch_prefisso_porte").order_by("id"):
        per_nome.setdefault(asset.asset_tag.casefold(), asset)
        per_nome.setdefault((asset.name or "").casefold(), asset)
        if asset.switch_prefisso_porte:
            per_prefisso.setdefault(asset.switch_prefisso_porte, asset)
    risultato: dict[int, tuple[Asset, bool]] = {}
    for ep in endpoints:
        nome = (ep.switch_name or "").strip()
        if nome:
            if nome.casefold() in per_nome:
                risultato[ep.id] = (per_nome[nome.casefold()], False)
        elif (parti := scomponi_porta(ep.switch_port)) and parti[0] in per_prefisso:
            risultato[ep.id] = (per_prefisso[parti[0]], True)
    return risultato


def _endpoint_collegati(asset: Asset) -> list[AssetEndpoint]:
    filtro = Q(pk__in=[])
    for chiave in chiavi_switch(asset):
        filtro |= Q(switch_name__iexact=chiave)
    collegati = list(AssetEndpoint.objects.filter(filtro).exclude(asset_id=asset.id).select_related("asset"))
    prefisso = asset.switch_prefisso_porte
    if prefisso:
        for ep in (
            AssetEndpoint.objects.filter(switch_name="", switch_port__istartswith=prefisso)
            .exclude(asset_id=asset.id)
            .select_related("asset")
        ):
            parti = scomponi_porta(ep.switch_port)
            if parti and parti[0] == prefisso:
                ep.da_prefisso = True
                collegati.append(ep)
    collegati.sort(key=lambda ep: (scomponi_porta(ep.switch_port) or ("~", "", 0), ep.switch_port, ep.id))
    return collegati


def _classi_vlan(endpoints) -> dict:
    """Colore per VLAN in base all'ordine delle VLAN presenti sullo switch (8 colori, poi si ripete)."""
    vlan = sorted({ep.vlan for ep in endpoints if ep.vlan is not None})
    return {v: f"af-vl{i % 8}" for i, v in enumerate(vlan)}


def mappa_switch(asset: Asset) -> dict:
    """Pannello frontale dello switch: porte occupate per membro dello stack."""
    collegati = _endpoint_collegati(asset)
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
        "prefisso": asset.switch_prefisso_porte,
        "prefissi_liberi": prefissi_senza_switch(),
    }


def prefissi_senza_switch() -> list[dict]:
    """Prefissi usati da porte senza switch e non ancora assegnati a nessuno switch."""
    assegnati = set(Asset.objects.exclude(switch_prefisso_porte="").values_list("switch_prefisso_porte", flat=True))
    conteggi: dict[str, int] = {}
    for porta in AssetEndpoint.objects.filter(switch_name="").exclude(switch_port="").values_list("switch_port", flat=True):
        parti = scomponi_porta(porta)
        if parti and parti[0] not in assegnati:
            conteggi[parti[0]] = conteggi.get(parti[0], 0) + 1
    return [{"prefisso": k, "porte": v} for k, v in sorted(conteggi.items())]


def switch_con_prefisso(prefisso: str, *, escludi_id: int | None = None) -> Asset | None:
    qs = Asset.objects.filter(switch_prefisso_porte=prefisso)
    if escludi_id:
        qs = qs.exclude(pk=escludi_id)
    return qs.only("id", "asset_tag", "name").first()


def is_switch(asset: Asset) -> bool:
    return Asset.objects.filter(_filtro_switch(), pk=asset.pk).exists()
