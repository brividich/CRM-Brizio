"""Collegamenti di rete visti dal lato switch e dal lato rack: scelta dello switch, mappa porte, rack.

``AssetEndpoint.switch_name`` e' testo libero. Un punto rete e' "collegato" a uno
switch censito quando quel testo coincide (senza distinzione di maiuscole) con la
matricola o con il nome dell'asset switch: dalla scheda si sceglie lo switch e si
salva la matricola, che e' univoca. Nessun dato viene dedotto da nome o IP.

La porta segue la convenzione dell'inventario ``<prefisso>.<membro stack>.<porta>``
(es. ``A0.1.37``) oppure ``<prefisso>.<porta>`` (es. ``A1.19``). Il prefisso e' del
rack (``RackRete.prefisso_porte``) oppure dello switch (``Asset.switch_prefisso_porte``,
che vince su quello del rack). Dentro un prefisso il membro sceglie lo switch:
``A0.2.x`` va allo switch con membro "2"; uno switch senza membro serve tutte le porte
del prefisso che nessun membro reclama. I punti rete SENZA switch indicato seguono il
prefisso, anche quelli aggiunti dopo. Uno ``switch_name`` esplicito vince sempre; se
pero' indica uno stack di cui e' censito anche il membro della porta, la porta va al
membro (l'inventario spesso scrive il nome dello stack per tutte le porte).

Il rack di un punto rete: quello dello switch; se lo switch non e' noto, quello col
prefisso porte della porta; altrimenti quello col prefisso patch panel del punto
(es. "Q0" per Q0.89).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import Q

from ..models import Asset, AssetEndpoint, RackRete

_PORTA = re.compile(r"^\s*([A-Za-z0-9]+?)\s*[./:]\s*(?:([0-9]+)\s*[./:]\s*)?([0-9]+)\s*$")
_PREFISSO = re.compile(r"^[A-Z0-9]{1,20}$")
_MEMBRO = re.compile(r"^[0-9]{1,3}$")


def scomponi_porta(valore: str) -> tuple[str, str, int] | None:
    """``(prefisso, membro, numero)`` della porta, oppure None se non segue la convenzione."""
    match = _PORTA.match(valore or "")
    if not match:
        return None
    return match.group(1).upper(), match.group(2) or "", int(match.group(3))


def prefisso_valido(valore: str) -> str:
    valore = (valore or "").strip().upper()
    return valore if _PREFISSO.match(valore) else ""


def membro_valido(valore: str) -> str | None:
    """Membro normalizzato ("" se vuoto), None se non e' un numero."""
    valore = (valore or "").strip()
    if not valore:
        return ""
    return valore if _MEMBRO.match(valore) else None


def _filtro_switch() -> Q:
    return (
        Q(asset_type=Asset.TYPE_FIREWALL)
        | Q(name__icontains="switch")
        | Q(asset_category__label__icontains="switch")
        | Q(asset_category__label__icontains="apparati rete")
        | Q(asset_category__label__icontains="apparati di rete")
        | Q(switch_prefisso_porte__gt="")
        | Q(rack__isnull=False)
    )


def prefisso_effettivo(asset: Asset) -> str:
    """Prefisso porte dello switch: il suo, altrimenti quello del rack."""
    if asset.switch_prefisso_porte:
        return asset.switch_prefisso_porte
    rack = asset.rack if asset.rack_id else None
    return rack.prefisso_porte if rack else ""


def titolo_switch(asset: Asset) -> str:
    """Es. "A0.2" per il membro 2 del rack A0, "A1" per uno switch singolo, "" se non collocato."""
    prefisso = prefisso_effettivo(asset)
    if not prefisso:
        return ""
    return f"{prefisso}.{asset.switch_membro}" if asset.switch_membro else prefisso


def switch_disponibili() -> list[dict]:
    """Apparati di rete censiti, per la tendina "Switch" della modifica rete."""
    rows = (
        Asset.objects.filter(_filtro_switch())
        .exclude(status=Asset.STATUS_RETIRED)
        .select_related("rack")
        .order_by("name", "asset_tag")
        .only("id", "asset_tag", "name", "switch_prefisso_porte", "switch_membro", "rack__codice", "rack__prefisso_porte")[:300]
    )
    risultato = []
    for s in rows:
        dove = []
        if s.rack_id:
            dove.append(f"rack {s.rack.codice}")
        if titolo := titolo_switch(s):
            dove.append(f"porte {titolo}")
        risultato.append({
            "id": s.id,
            "valore": s.asset_tag,
            "etichetta": f"{s.asset_tag} — {s.name}" + (f" ({', '.join(dove)})" if dove else ""),
        })
    return risultato


def chiavi_switch(asset: Asset) -> list[str]:
    return [v for v in {(asset.asset_tag or "").strip(), (asset.name or "").strip()} if v]


@dataclass
class Collegamento:
    switch: Asset | None
    da_prefisso: bool
    rack: RackRete | None


class Indice:
    """Switch collocati (con prefisso proprio o rack) e rack, letti una volta sola."""

    def __init__(self):
        self.rack = list(RackRete.objects.all())
        self.rack_per_id = {r.id: r for r in self.rack}
        self.rack_per_porte = {r.prefisso_porte: r for r in self.rack if r.prefisso_porte}
        self.rack_per_patch = {r.prefisso_patch: r for r in self.rack if r.prefisso_patch}
        self.per_prefisso: dict[str, list[Asset]] = {}
        qs = (
            Asset.objects.filter(Q(switch_prefisso_porte__gt="") | Q(rack__isnull=False))
            .only("id", "asset_tag", "name", "switch_prefisso_porte", "switch_membro", "rack_id")
            .order_by("id")
        )
        for asset in qs:
            asset.rack = self.rack_per_id.get(asset.rack_id)
            if prefisso := prefisso_effettivo(asset):
                self.per_prefisso.setdefault(prefisso, []).append(asset)

    def switch_da_porta(self, porta: str, prefisso_stack: str = "") -> Asset | None:
        """Switch della porta secondo prefisso e membro (``prefisso_stack`` forza il prefisso)."""
        parti = scomponi_porta(porta)
        if not parti:
            return None
        prefisso, membro, _ = parti
        candidati = self.per_prefisso.get(prefisso_stack or prefisso, [])
        if not candidati:
            return None
        esatti = [s for s in candidati if s.switch_membro == membro]
        if esatti:
            return esatti[0]
        generici = [s for s in candidati if not s.switch_membro]
        if generici:
            return generici[0]
        if not membro and len(candidati) == 1:
            return candidati[0]
        return None

    def rack_di(self, endpoint: AssetEndpoint, switch: Asset | None) -> RackRete | None:
        if switch is not None and switch.rack_id:
            return self.rack_per_id.get(switch.rack_id) or switch.rack
        if (parti := scomponi_porta(endpoint.switch_port)) and parti[0] in self.rack_per_porte:
            return self.rack_per_porte[parti[0]]
        if (parti := scomponi_porta(endpoint.punto)) and parti[0] in self.rack_per_patch:
            return self.rack_per_patch[parti[0]]
        return None


def _switch_per_nome(nomi: set[str]) -> dict[str, Asset]:
    if not nomi:
        return {}
    filtro = Q(pk__in=[])
    for nome in nomi:
        filtro |= Q(asset_tag__iexact=nome) | Q(name__iexact=nome)
    per_nome: dict[str, Asset] = {}
    for asset in (
        Asset.objects.filter(filtro).select_related("rack")
        .only("id", "asset_tag", "name", "switch_prefisso_porte", "switch_membro", "rack_id",
              "rack__codice", "rack__nome", "rack__prefisso_porte", "rack__prefisso_patch")
        .order_by("id")
    ):
        per_nome.setdefault(asset.asset_tag.casefold(), asset)
        per_nome.setdefault((asset.name or "").casefold(), asset)
    return per_nome


def collegamenti(endpoints, indice: Indice | None = None) -> dict[int, Collegamento]:
    """``endpoint.id -> Collegamento`` (switch, se trovato dal prefisso, rack)."""
    endpoints = list(endpoints)
    if not endpoints:
        return {}
    indice = indice or Indice()
    per_nome = _switch_per_nome({(e.switch_name or "").strip() for e in endpoints if (e.switch_name or "").strip()})
    risultato: dict[int, Collegamento] = {}
    for ep in endpoints:
        nome = (ep.switch_name or "").strip()
        switch, da_prefisso = None, False
        if nome:
            switch = per_nome.get(nome.casefold())
            parti = scomponi_porta(ep.switch_port)
            if switch is not None and parti and parti[1] and parti[0] == (stack := prefisso_effettivo(switch)):
                membro = indice.switch_da_porta(ep.switch_port, prefisso_stack=stack)
                if membro is not None and membro.switch_membro and membro.pk != switch.pk:
                    switch = membro
        else:
            switch = indice.switch_da_porta(ep.switch_port)
            da_prefisso = switch is not None
        risultato[ep.id] = Collegamento(switch, da_prefisso, indice.rack_di(ep, switch))
    return risultato


def switch_per_endpoint(endpoints) -> dict[int, tuple[Asset, bool]]:
    """``endpoint.id -> (switch, da_prefisso)`` per linkare la scheda dello switch."""
    return {k: (c.switch, c.da_prefisso) for k, c in collegamenti(endpoints).items() if c.switch is not None}


def _endpoint_candidati(asset: Asset) -> list[AssetEndpoint]:
    filtro = Q(pk__in=[])
    for chiave in chiavi_switch(asset):
        filtro |= Q(switch_name__iexact=chiave)
    if prefisso := prefisso_effettivo(asset):
        filtro |= Q(switch_port__istartswith=prefisso)
        # Porte del suo stack indicate col nome di un altro switch dello stesso prefisso.
        for altro in Asset.objects.filter(Q(switch_prefisso_porte=prefisso) | Q(switch_prefisso_porte="", rack__prefisso_porte=prefisso)).exclude(pk=asset.pk).only("asset_tag", "name"):
            for chiave in chiavi_switch(altro):
                filtro |= Q(switch_name__iexact=chiave)
    return list(AssetEndpoint.objects.filter(filtro).exclude(asset_id=asset.id).select_related("asset"))


def _endpoint_collegati(asset: Asset, indice: Indice | None = None) -> list[AssetEndpoint]:
    candidati = _endpoint_candidati(asset)
    risolti = collegamenti(candidati, indice)
    collegati = []
    for ep in candidati:
        c = risolti.get(ep.id)
        if c and c.switch is not None and c.switch.pk == asset.pk:
            ep.da_prefisso = c.da_prefisso
            collegati.append(ep)
    collegati.sort(key=lambda ep: (scomponi_porta(ep.switch_port) or ("~", "", 0), ep.switch_port, ep.id))
    return collegati


def _classi_vlan(endpoints) -> dict:
    """Colore per VLAN in base all'ordine delle VLAN presenti sullo switch (8 colori, poi si ripete)."""
    vlan = sorted({ep.vlan for ep in endpoints if ep.vlan is not None})
    return {v: f"af-vl{i % 8}" for i, v in enumerate(vlan)}


def _pannelli(collegati: list[AssetEndpoint], colori: dict) -> tuple[list[dict], list[AssetEndpoint]]:
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
    return pannelli, altre


def mappa_switch(asset: Asset, indice: Indice | None = None) -> dict:
    """Pannello frontale dello switch: porte occupate per membro dello stack."""
    collegati = _endpoint_collegati(asset, indice)
    colori = _classi_vlan(collegati)
    pannelli, altre = _pannelli(collegati, colori)
    return {
        "pannelli": pannelli,
        "altre": altre,
        "collegati": collegati,
        "totale": len(collegati),
        "vlan": [{"vlan": v, "classe": c} for v, c in colori.items()],
        "prefisso": asset.switch_prefisso_porte,
        "prefisso_effettivo": prefisso_effettivo(asset),
        "membro": asset.switch_membro,
        "rack": asset.rack if asset.rack_id else None,
        "rack_disponibili": list(RackRete.objects.order_by("codice").only("id", "codice", "nome", "prefisso_porte")),
        "prefissi_liberi": prefissi_senza_switch(),
    }


def porte_senza_switch(indice: Indice | None = None) -> list[dict]:
    """Gruppi di porte (es. "A0.2") senza switch indicato che nessuno switch censito serve."""
    indice = indice or Indice()
    conteggi: dict[str, int] = {}
    for porta in AssetEndpoint.objects.filter(switch_name="").exclude(switch_port="").values_list("switch_port", flat=True):
        parti = scomponi_porta(porta)
        if parti and indice.switch_da_porta(porta) is None:
            chiave = f"{parti[0]}.{parti[1]}" if parti[1] else parti[0]
            conteggi[chiave] = conteggi.get(chiave, 0) + 1
    return [{"prefisso": k, "porte": v} for k, v in sorted(conteggi.items())]


def prefissi_senza_switch() -> list[dict]:
    """Prefissi usati da porte senza switch e non ancora assegnati a nessuno switch o rack."""
    assegnati = set(Asset.objects.exclude(switch_prefisso_porte="").values_list("switch_prefisso_porte", flat=True))
    assegnati |= set(
        Asset.objects.filter(switch_prefisso_porte="", rack__isnull=False)
        .exclude(rack__prefisso_porte="").values_list("rack__prefisso_porte", flat=True)
    )
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


def conflitto_collocazione(asset: Asset, prefisso: str, membro: str) -> Asset | None:
    """Altro switch che serve gia' le stesse porte (stesso prefisso effettivo e stesso membro)."""
    if not prefisso:
        return None
    qs = (
        Asset.objects.filter(Q(switch_prefisso_porte=prefisso) | Q(switch_prefisso_porte="", rack__prefisso_porte=prefisso))
        .filter(switch_membro=membro)
        .exclude(pk=asset.pk)
    )
    return qs.only("id", "asset_tag", "name").first()


def is_switch(asset: Asset) -> bool:
    return Asset.objects.filter(_filtro_switch(), pk=asset.pk).exists()


def panoramica_rack() -> dict:
    """Pagina «Rack e switch»: per ogni rack i suoi switch con porte occupate e dispositivi."""
    indice = Indice()
    endpoints = list(AssetEndpoint.objects.exclude(switch_port="", switch_name="", punto="").select_related("asset"))
    risolti = collegamenti(endpoints, indice)
    per_switch: dict[int, list] = {}
    per_rack: dict[int, set] = {}
    for ep in endpoints:
        c = risolti.get(ep.id)
        if not c:
            continue
        if c.switch is not None:
            per_switch.setdefault(c.switch.pk, []).append(ep)
        if c.rack is not None:
            per_rack.setdefault(c.rack.pk, set()).add(ep.asset_id)
    switch_in_rack = list(
        Asset.objects.filter(rack__isnull=False).select_related("rack")
        .only("id", "asset_tag", "name", "model", "status", "switch_prefisso_porte", "switch_membro", "rack")
    )

    def riga(s: Asset) -> dict:
        porte = per_switch.get(s.pk, [])
        return {
            "asset": s,
            "titolo": titolo_switch(s),
            "porte": len(porte),
            "vlan": sorted({ep.vlan for ep in porte if ep.vlan is not None}),
        }
    racks = []
    for rack in indice.rack:
        sw = sorted((s for s in switch_in_rack if s.rack_id == rack.pk),
                    key=lambda s: (int(s.switch_membro) if s.switch_membro.isdigit() else 0, s.asset_tag))
        racks.append({
            "rack": rack,
            "switch": [riga(s) for s in sw],
            "dispositivi": len(per_rack.get(rack.pk, ())),
        })
    senza_rack = [
        riga(s) for s in Asset.objects.filter(_filtro_switch(), rack__isnull=True)
        .exclude(status=Asset.STATUS_RETIRED).order_by("asset_tag")
        .only("id", "asset_tag", "name", "model", "status", "switch_prefisso_porte", "switch_membro")
    ]
    return {"racks": racks, "senza_rack": senza_rack, "porte_libere": porte_senza_switch(indice)}


def dettaglio_rack(rack: RackRete) -> dict:
    """Un rack: mappa porte di ogni switch e dispositivi del rack senza switch riconosciuto."""
    indice = Indice()
    switch = sorted(
        Asset.objects.filter(rack=rack).select_related("rack"),
        key=lambda s: (int(s.switch_membro) if s.switch_membro.isdigit() else 0, s.asset_tag),
    )
    blocchi = [{"asset": s, "titolo": titolo_switch(s), "mappa": mappa_switch(s, indice)} for s in switch]
    filtro = Q(pk__in=[])
    if rack.prefisso_porte:
        filtro |= Q(switch_port__istartswith=rack.prefisso_porte)
    if rack.prefisso_patch:
        filtro |= Q(punto__istartswith=rack.prefisso_patch)
    candidati = list(AssetEndpoint.objects.filter(filtro).select_related("asset"))
    risolti = collegamenti(candidati, indice)
    orfani = [
        ep for ep in candidati
        if (c := risolti.get(ep.id)) and c.switch is None and c.rack is not None and c.rack.pk == rack.pk
    ]
    orfani.sort(key=lambda ep: (ep.switch_port or "~", ep.punto or "", ep.id))
    return {"switch": blocchi, "orfani": orfani}
