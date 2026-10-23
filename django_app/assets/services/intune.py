"""Dispositivi gestiti da Microsoft Intune (Graph, licenza Intune Plan 1 di Business Premium).

Ogni mattina (schedule ``intune_sync``, prima degli avvisi IT delle 07:15) legge
``deviceManagement/managedDevices`` e aggiorna ``DispositivoIntune``:

- identità del dispositivo (nome, seriale, produttore, modello), Windows/versione,
  conformità ai criteri, cifratura del disco, ultima sincronizzazione, utente
  principale;
- hardware: disco (totale/libero), MAC Wi-Fi ed Ethernet e RAM. La RAM Intune la dà
  solo leggendo il singolo dispositivo: si legge per chi non ce l'ha ancora, al massimo
  ``RAM_PER_GIRO`` dispositivi al giorno. Il processore Graph v1.0 non lo espone;
- i problemi aperti: disco non cifrato, non conforme, nessuna sincronizzazione da
  oltre ``NON_SINCRONIZZA_GIORNI`` giorni. ``problemi_dal`` cambia solo quando cambia
  l'insieme, così gli avvisi IT notificano solo i problemi nuovi;
- sugli asset già collegati riempie i dati di inventario ancora vuoti (produttore,
  modello, seriale, sistema operativo, RAM, disco): mai sovrascritti.

Il collegamento a un asset non è automatico: si conferma dalla riconciliazione
dispositivi IT, con l'abbinatore unico (seriale, poi nome). Permesso applicativo
Graph ``DeviceManagementManagedDevices.Read.All``. Sola lettura.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

PERMESSO = "DeviceManagementManagedDevices.Read.All"
URL = "https://graph.microsoft.com/v1.0/deviceManagement/managedDevices"
NON_SINCRONIZZA_GIORNI = 30
_SELECT_BASE = ("id,deviceName,serialNumber,manufacturer,model,operatingSystem,osVersion,complianceState,"
                "isEncrypted,lastSyncDateTime,enrolledDateTime,userPrincipalName,userDisplayName")
_SELECT = _SELECT_BASE + ",totalStorageSpaceInBytes,freeStorageSpaceInBytes,wiFiMacAddress,ethernetMacAddress"
RAM_PER_GIRO = 50
# Seriali di comodo dei produttori: non identificano nessuno.
_SERIALI_VUOTI = {"", "0", "none", "default string", "to be filled by o.e.m.", "system serial number", "0123456789"}


def _data(valore):
    d = parse_datetime(str(valore or "")) if valore else None
    # Intune restituisce 0001-01-01 per «mai».
    return d if d and d.year > 2000 else None


def seriale_valido(seriale: str) -> str:
    s = str(seriale or "").strip()
    return "" if s.lower() in _SERIALI_VUOTI else s


def problemi_di(dati: dict, now) -> list[str]:
    from assets.models import DispositivoIntune as D

    out = []
    if dati.get("cifrato") is False:
        out.append(D.PROBLEMA_NON_CIFRATO)
    if str(dati.get("conformita") or "").lower() == "noncompliant":
        out.append(D.PROBLEMA_NON_CONFORME)
    sync = dati.get("ultima_sync")
    if sync is None or now - sync > timedelta(days=NON_SINCRONIZZA_GIORNI):
        out.append(D.PROBLEMA_NON_SINCRONIZZA)
    return out


def _byte(valore):
    try:
        n = int(valore or 0)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _mac(valore):
    from assets.services.mac import normalizza_mac

    return normalizza_mac(str(valore or ""))[:32]


def normalizza(device: dict) -> dict:
    hardware = {
        "disco_totale_bytes": _byte(device.get("totalStorageSpaceInBytes")),
        "disco_libero_bytes": _byte(device.get("freeStorageSpaceInBytes")),
        "mac_wifi": _mac(device.get("wiFiMacAddress")),
        "mac_ethernet": _mac(device.get("ethernetMacAddress")),
    }
    # Nella lista Intune la RAM vale 0: si tiene solo un valore vero, mai lo zero sopra quello letto prima.
    if _byte(device.get("physicalMemoryInBytes")):
        hardware["ram_bytes"] = _byte(device.get("physicalMemoryInBytes"))
    return {
        **hardware,
        "nome": str(device.get("deviceName") or "")[:200],
        "seriale": seriale_valido(device.get("serialNumber"))[:120],
        "produttore": str(device.get("manufacturer") or "")[:120],
        "modello": str(device.get("model") or "")[:120],
        "sistema": str(device.get("operatingSystem") or "")[:60],
        "versione_sistema": str(device.get("osVersion") or "")[:60],
        "conformita": str(device.get("complianceState") or "")[:30],
        "cifrato": device.get("isEncrypted") if isinstance(device.get("isEncrypted"), bool) else None,
        "ultima_sync": _data(device.get("lastSyncDateTime")),
        "registrato_il": _data(device.get("enrolledDateTime")),
        "utente_upn": str(device.get("userPrincipalName") or "")[:200],
        "utente_nome": str(device.get("userDisplayName") or "")[:200],
    }


def completa_asset(disp) -> list[str]:
    """Riempie i campi di inventario vuoti dell'asset collegato. Ritorna i campi scritti."""
    from assets.models import AssetITDetails

    asset = disp.asset
    if asset is None:
        return []
    scritti = []
    for campo, valore in (("manufacturer", disp.produttore), ("model", disp.modello), ("serial_number", disp.seriale)):
        if valore and not (getattr(asset, campo) or "").strip():
            setattr(asset, campo, valore)
            scritti.append(campo)
    if scritti:
        asset.save(update_fields=[*scritti, "updated_at"])
    sistema = " ".join(x for x in (disp.sistema, disp.versione_sistema) if x)[:120]
    valori = {"os": sistema, "ram": disp.ram_label, "disco": disp.disco_label}
    if any(valori.values()):
        details, _ = AssetITDetails.objects.get_or_create(asset=asset)
        vuoti = [campo for campo, valore in valori.items() if valore and not getattr(details, campo).strip()]
        for campo in vuoti:
            setattr(details, campo, valori[campo][:120])
        if vuoti:
            details.save(update_fields=vuoti)
            scritti.extend(vuoti)
    return scritti


def leggi_dispositivi() -> list[dict]:
    """Tutti i dispositivi Intune. Se Graph rifiuta i campi hardware (400) si rilegge senza."""
    from core import m365_graph

    try:
        return m365_graph.get_all(URL, permesso=PERMESSO, params={"$select": _SELECT, "$top": "1000"})
    except m365_graph.GraphError as exc:
        if exc.status != 400:
            raise
        logger.warning("Intune: campi hardware rifiutati da Graph (%s), letti solo quelli di base", exc)
        return m365_graph.get_all(URL, permesso=PERMESSO, params={"$select": _SELECT_BASE, "$top": "1000"})


def ram_da_graph(intune_id: str):
    """RAM in byte del singolo dispositivo (Intune la dà solo così), oppure None."""
    from core import m365_graph

    try:
        dati = m365_graph.get(f"{URL}/{intune_id}", permesso=PERMESSO, params={"$select": "id,physicalMemoryInBytes"})
    except m365_graph.GraphError as exc:
        logger.info("Intune: RAM non letta per %s (%s)", intune_id, exc)
        return None
    return _byte(dati.get("physicalMemoryInBytes"))


def sincronizza(now=None, *, devices: list[dict] | None = None, dettaglio=None) -> dict:
    """Legge Intune e aggiorna i dispositivi. ``devices`` e ``dettaglio`` (RAM per id) servono ai test."""
    from assets.models import DispositivoIntune

    now = now or timezone.now()
    if devices is None:
        devices = leggi_dispositivi()
        dettaglio = dettaglio or ram_da_graph
    visti = set()
    creati = aggiornati = completati = 0
    ram_lette = 0
    for raw in devices:
        intune_id = str(raw.get("id") or "")
        if not intune_id:
            continue
        visti.add(intune_id)
        dati = normalizza(raw)
        problemi = problemi_di(dati, now)
        disp = DispositivoIntune.objects.filter(intune_id=intune_id).first()
        if disp is None:
            disp = DispositivoIntune(intune_id=intune_id)
            creati += 1
        else:
            aggiornati += 1
        if sorted(disp.problemi or []) != sorted(problemi):
            disp.problemi_dal = now if problemi else None
        for campo, valore in dati.items():
            setattr(disp, campo, valore)
        disp.problemi = problemi
        disp.presente = True
        if dettaglio is not None and not disp.ram_bytes and ram_lette < RAM_PER_GIRO:
            ram_lette += 1
            disp.ram_bytes = dettaglio(intune_id)
        disp.save()
        if completa_asset(disp):
            completati += 1
    usciti = DispositivoIntune.objects.filter(presente=True).exclude(intune_id__in=visti).update(presente=False)
    return {"letti": len(devices), "creati": creati, "aggiornati": aggiornati,
            "usciti": usciti, "asset_completati": completati, "ram_lette": ram_lette}


def problemi_aperti(now=None) -> list[dict]:
    """Per gli avvisi IT del mattino: ``[{"kind","title","detail","url","new"}]``."""
    from django.urls import reverse

    from assets.models import DispositivoIntune

    now = now or timezone.now()
    out = []
    for d in DispositivoIntune.objects.filter(presente=True).exclude(problemi=[]).select_related("asset"):
        if not d.problemi:
            continue
        nome = d.asset.name if d.asset_id else (d.nome or d.seriale)
        url = reverse("assets:asset_view", args=[d.asset_id]) if d.asset_id else reverse("assets:it_reconciliation")
        out.append({
            "kind": "intune",
            "title": f"{nome}: " + ", ".join(d.problemi_label),
            "detail": " · ".join(x for x in (d.utente_nome or d.utente_upn, d.sistema + " " + d.versione_sistema) if x.strip()),
            "url": url,
            "new": bool(d.problemi_dal and now - d.problemi_dal <= timedelta(hours=24)),
        })
    return out


# Build di Windows → nome della versione (solo per l'etichetta).
RAMI_WINDOWS = {19044: "Windows 10 21H2", 19045: "Windows 10 22H2", 22621: "Windows 11 22H2", 22631: "Windows 11 23H2",
                26100: "Windows 11 24H2", 26200: "Windows 11 25H2"}


def build_windows(versione: str):
    """(build, revisione) da «10.0.26100.2033», o None se non è una versione Windows confrontabile."""
    parti = str(versione or "").strip().split(".")
    if len(parti) != 4 or parti[0] != "10" or not all(p.isdigit() for p in parti):
        return None
    return int(parti[2]), int(parti[3])


def revisioni_massime() -> dict:
    """{build: revisione più alta vista sui PC presenti in Intune}: il riferimento «al passo»."""
    from assets.models import DispositivoIntune

    out: dict = {}
    for versione in DispositivoIntune.objects.filter(presente=True, sistema__iexact="Windows").values_list(
            "versione_sistema", flat=True):
        b = build_windows(versione)
        if b:
            out[b[0]] = max(out.get(b[0], 0), b[1])
    return out


def aggiornamento_windows(disp, massime=None) -> dict | None:
    """Aggiornamenti cumulativi del PC rispetto agli altri PC con la stessa versione di Windows.

    Il riferimento è il PC più aggiornato in azienda (Intune non dice qual è l'ultima cumulativa
    pubblicata): «indietro» = altri PC dello stesso ramo hanno già una revisione più alta.
    """
    b = build_windows(getattr(disp, "versione_sistema", ""))
    if b is None or str(getattr(disp, "sistema", "")).lower() != "windows":
        return None
    massime = revisioni_massime() if massime is None else massime
    massima = massime.get(b[0], b[1])
    return {"ramo": RAMI_WINDOWS.get(b[0], f"build {b[0]}"), "build": f"{b[0]}.{b[1]}", "riferimento": f"{b[0]}.{massima}",
            "indietro": b[1] < massima}


def per_asset(asset) -> list:
    from assets.models import DispositivoIntune

    dispositivi = list(DispositivoIntune.objects.filter(asset=asset).order_by("-presente", "nome"))
    if dispositivi:
        massime = revisioni_massime()
        for d in dispositivi:
            d.windows = aggiornamento_windows(d, massime)
    return dispositivi
