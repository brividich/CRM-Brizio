"""Tabella MAC degli switch via SNMP (sola lettura): su quale porta sta ogni PC.

Per ogni apparato di categoria «Rete» attivo e raggiungibile legge:

* ``dot1qTpFdbPort`` (Q-BRIDGE-MIB, per VLAN) o, se l'apparato non lo espone, ``dot1dTpFdbPort`` (BRIDGE-MIB);
* ``dot1dBasePortIfIndex`` (porta del bridge → interfaccia) e ``ifName`` (nome della porta).

Le righe vanno in ``MacPortaSwitch`` (ogni lettura sostituisce quelle dello switch). Una porta con
più di 3 MAC è verso un altro switch o un access point: lì il PC «passa», non è collegato.
Il MAC dei PC arriva da Intune, da WatchGuard e dal punto rete dichiarato dell'asset.

Gli switch Cisco che separano la tabella MAC per VLAN (community@vlan) non sono coperti.
"""
from __future__ import annotations

import logging
from collections import Counter

from django.db import transaction
from django.utils import timezone

from .models import DispositivoSNMP, ImpostazioniSNMP, MacPortaSwitch, StatoSNMP

logger = logging.getLogger(__name__)

Q_FDB_PORT = "1.3.6.1.2.1.17.7.1.2.2.1.2"
FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"
BASE_PORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
MAX_RIGHE = 20_000
MAX_DURATA = 60.0
PORTA_ACCESSO_MAX = 3


def _indice(oid: str, radice: str) -> list[int]:
    return [int(p) for p in oid[len(radice) + 1:].split(".") if p]


def _intero(record):
    try:
        return int(record.value)
    except (TypeError, ValueError):
        return None


def _testo(record):
    from .snmp_capture import to_bytes

    if record.tag == "4":
        return record.value
    dati = to_bytes(record)
    return dati.decode("utf-8", "replace") if dati else str(record.value)


def _walk(host, credenziali, radice, *, port, timeout, versione):
    from .snmp_capture import capture

    return capture(host, credenziali, port=port, timeout=timeout, retries=1, root=radice, version=versione,
                   max_rows=MAX_RIGHE, max_duration=MAX_DURATA, drop=()).records


def righe_da_record(fdb_q, fdb, base_port, if_name) -> list[dict]:
    """Dalle colonne lette alle righe {mac, porta, if_index, vlan}: una per MAC e VLAN."""
    porta_if = {}
    for r in base_port:
        idx, val = _indice(r.oid, BASE_PORT_IFINDEX), _intero(r)
        if idx and val:
            porta_if[idx[0]] = val
    nomi = {}
    for r in if_name:
        idx = _indice(r.oid, IF_NAME)
        if idx:
            nomi[idx[0]] = _testo(r).strip()
    out = []
    for radice, records in ((Q_FDB_PORT, fdb_q), (FDB_PORT, fdb)):
        for r in records:
            idx, bridge_port = _indice(r.oid, radice), _intero(r)
            if not bridge_port or len(idx) < 6:
                continue
            ottetti = idx[-6:]
            if any(o > 255 for o in ottetti):
                continue
            mac = ":".join(f"{o:02x}" for o in ottetti)
            if mac == "00:00:00:00:00:00" or ottetti[0] & 1:  # niente multicast
                continue
            if_index = porta_if.get(bridge_port)
            out.append({"mac": mac, "if_index": if_index, "vlan": idx[0] if radice == Q_FDB_PORT and len(idx) == 7 else None,
                        "porta": nomi.get(if_index) or (f"porta {bridge_port}")})
        if out:
            break  # Q-BRIDGE letto: il BRIDGE-MIB classico ripeterebbe le stesse righe
    return out


def salva(dispositivo, righe, now=None) -> int:
    now = now or timezone.now()
    per_porta = Counter(r["porta"] for r in {(r["mac"], r["porta"]): r for r in righe}.values())
    unici = {(r["mac"], r["porta"], r["vlan"]): r for r in righe}
    with transaction.atomic():
        MacPortaSwitch.objects.filter(dispositivo=dispositivo).delete()
        MacPortaSwitch.objects.bulk_create([
            MacPortaSwitch(dispositivo=dispositivo, mac=r["mac"], porta=r["porta"][:120], if_index=r["if_index"],
                           vlan=r["vlan"], mac_sulla_porta=per_porta[r["porta"]], letto_il=now)
            for r in unici.values()
        ], batch_size=500)
    return len(unici)


def leggi_switch(dispositivo, cfg=None) -> int:
    from .services import _community_snmp, _parametri_snmp
    from .snmp import costruisci_credenziali

    cfg = cfg or ImpostazioniSNMP.get_solo()
    porta, timeout, versione = _parametri_snmp(dispositivo, cfg)
    cred = costruisci_credenziali(_community_snmp(dispositivo, cfg), versione)
    kw = {"port": porta, "timeout": timeout, "versione": versione}
    fdb_q = _walk(dispositivo.host, cred, Q_FDB_PORT, **kw)
    fdb = [] if fdb_q else _walk(dispositivo.host, cred, FDB_PORT, **kw)
    if not fdb_q and not fdb:
        return 0
    righe = righe_da_record(fdb_q, fdb, _walk(dispositivo.host, cred, BASE_PORT_IFINDEX, **kw),
                            _walk(dispositivo.host, cred, IF_NAME, **kw))
    return salva(dispositivo, righe)


def run() -> dict:
    """Task notturno: tutti gli switch («Rete») attivi e raggiungibili. Mai un'eccezione verso la coda."""
    try:
        from security.services import soc_settings

        if not soc_settings.value("apparati.tabella_mac.attivo"):
            return {"attivo": False}
    except Exception:  # noqa: BLE001 - SOC non installato: si legge comunque
        pass
    cfg = ImpostazioniSNMP.get_solo()
    out = {"switch": 0, "mac": 0, "errori": []}
    for disp in DispositivoSNMP.objects.filter(attivo=True, categoria=DispositivoSNMP.Categoria.RETE).exclude(
            snmp_stato=StatoSNMP.ERROR):
        try:
            n = leggi_switch(disp, cfg)
        except Exception as exc:  # noqa: BLE001 - uno switch che non risponde non ferma gli altri
            logger.warning("Tabella MAC %s: %s", disp.host, type(exc).__name__)
            out["errori"].append(f"{disp.nome}: {type(exc).__name__}")
            continue
        out["switch"] += 1
        out["mac"] += n
    return out


# --- Lettura per le schede ---------------------------------------------------------------------

def mac_di_asset(asset) -> set[str]:
    """MAC noti di un asset: punto rete dichiarato, Intune, WatchGuard."""
    from assets.models import AssetEndpoint, DispositivoIntune

    macs = set(AssetEndpoint.objects.filter(asset=asset).exclude(mac="").values_list("mac", flat=True))
    for wifi, eth in DispositivoIntune.objects.filter(asset=asset).values_list("mac_wifi", "mac_ethernet"):
        macs.update(m for m in (wifi, eth) if m)
    try:
        from security.models import WatchGuardDispositivo

        for testo in WatchGuardDispositivo.objects.filter(hub_asset=asset, presente=True).values_list("mac", flat=True):
            macs.update(testo.split())
    except Exception:  # noqa: BLE001 - SOC non installato
        pass
    return {m.strip().lower() for m in macs if m}


def porte_di_asset(asset) -> list[MacPortaSwitch]:
    """Dove l'asset è collegato: prima le porte d'accesso (pochi MAC), poi le altre."""
    macs = mac_di_asset(asset)
    if not macs:
        return []
    righe = list(MacPortaSwitch.objects.filter(mac__in=list(macs)[:50]).select_related("dispositivo", "dispositivo__asset"))
    righe.sort(key=lambda r: (not r.porta_accesso, r.mac_sulla_porta, r.dispositivo.nome))
    visti, out = set(), []
    for r in righe:
        chiave = (r.dispositivo_id, r.porta)
        if chiave not in visti:
            visti.add(chiave)
            out.append(r)
    return out


def collegati_allo_switch(dispositivo) -> list[dict]:
    """Per lo switch: porta → PC riconosciuti (solo porte d'accesso)."""
    from assets.models import AssetEndpoint, DispositivoIntune

    righe = list(MacPortaSwitch.objects.filter(dispositivo=dispositivo, mac_sulla_porta__lte=PORTA_ACCESSO_MAX))
    macs = {r.mac for r in righe}
    asset_per_mac = {}
    for mac, asset_id in AssetEndpoint.objects.filter(mac__in=list(macs)[:2000]).values_list("mac", "asset_id"):
        asset_per_mac[mac.lower()] = asset_id
    for wifi, eth, asset_id in DispositivoIntune.objects.filter(asset__isnull=False).values_list(
            "mac_wifi", "mac_ethernet", "asset_id"):
        for m in (wifi, eth):
            if m and m.lower() in macs:
                asset_per_mac.setdefault(m.lower(), asset_id)
    try:
        from security.models import WatchGuardDispositivo

        for testo, asset_id in WatchGuardDispositivo.objects.filter(hub_asset__isnull=False, presente=True).values_list(
                "mac", "hub_asset_id"):
            for m in testo.lower().split():
                if m in macs:
                    asset_per_mac.setdefault(m, asset_id)
    except Exception:  # noqa: BLE001 - SOC non installato
        pass
    from assets.models import Asset

    assets = Asset.objects.in_bulk({a for a in asset_per_mac.values() if a})
    out = []
    for r in sorted(righe, key=lambda r: (r.if_index or 0, r.porta)):
        out.append({"porta": r.porta, "mac": r.mac, "vlan": r.vlan, "asset": assets.get(asset_per_mac.get(r.mac))})
    return out
