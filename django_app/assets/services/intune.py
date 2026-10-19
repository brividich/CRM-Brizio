"""Dispositivi gestiti da Microsoft Intune (Graph, licenza Intune Plan 1 di Business Premium).

Ogni mattina (schedule ``intune_sync``, prima degli avvisi IT delle 07:15) legge
``deviceManagement/managedDevices`` e aggiorna ``DispositivoIntune``:

- identità del dispositivo (nome, seriale, produttore, modello), Windows/versione,
  conformità ai criteri, cifratura del disco, ultima sincronizzazione, utente
  principale;
- i problemi aperti: disco non cifrato, non conforme, nessuna sincronizzazione da
  oltre ``NON_SINCRONIZZA_GIORNI`` giorni. ``problemi_dal`` cambia solo quando cambia
  l'insieme, così gli avvisi IT notificano solo i problemi nuovi;
- sugli asset già collegati riempie i dati di inventario ancora vuoti (produttore,
  modello, seriale, sistema operativo): mai sovrascritti.

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
_SELECT = ("id,deviceName,serialNumber,manufacturer,model,operatingSystem,osVersion,complianceState,"
           "isEncrypted,lastSyncDateTime,enrolledDateTime,userPrincipalName,userDisplayName")
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


def normalizza(device: dict) -> dict:
    return {
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
    if sistema:
        details, _ = AssetITDetails.objects.get_or_create(asset=asset)
        if not details.os.strip():
            details.os = sistema
            details.save(update_fields=["os"])
            scritti.append("os")
    return scritti


def sincronizza(now=None, *, devices: list[dict] | None = None) -> dict:
    """Legge Intune e aggiorna i dispositivi. ``devices`` serve ai test."""
    from assets.models import DispositivoIntune
    from core import m365_graph

    now = now or timezone.now()
    if devices is None:
        devices = m365_graph.get_all(URL, permesso=PERMESSO, params={"$select": _SELECT, "$top": "1000"})
    visti = set()
    creati = aggiornati = completati = 0
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
        disp.save()
        if completa_asset(disp):
            completati += 1
    usciti = DispositivoIntune.objects.filter(presente=True).exclude(intune_id__in=visti).update(presente=False)
    return {"letti": len(devices), "creati": creati, "aggiornati": aggiornati,
            "usciti": usciti, "asset_completati": completati}


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


def per_asset(asset) -> list:
    from assets.models import DispositivoIntune

    return list(DispositivoIntune.objects.filter(asset=asset).order_by("-presente", "nome"))
