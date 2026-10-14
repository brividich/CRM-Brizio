"""Firmware dei dispositivi SNMP nell'inventario software del SOC.

Ogni dispositivo monitorato con produttore/modello e una versione firmware letta
diventa una riga ``SoftwareInstallation`` di fonte «Firmware da monitoraggio SNMP»
(prodotto «<modello> firmware», come i CPE NVD «…_firmware»). Da li' passa per lo
stesso percorso del software dei PC: mappatura CPE, confronto con le CVE, impatti
sull'asset collegato. Una versione nuova sostituisce la precedente, che resta
storicizzata come «non più rilevata».
"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from security.models import SoftwareInstallation, SoftwareSourceKind
from security.services.software_inventory import installation_key, normalize_product, normalize_vendor
from security.services.versioning import normalize as normalize_version

KIND = SoftwareSourceKind.SNMP_FIRMWARE


def _host(dispositivo) -> str:
    return str(dispositivo.host or "").strip().lower()


def sincronizza_dispositivo(dispositivo) -> SoftwareInstallation | None:
    """Upsert del firmware corrente; ``None`` se mancano modello o versione."""
    host = _host(dispositivo)
    versione = (dispositivo.firmware or "").strip()
    modello = (dispositivo.modello or "").strip()
    with transaction.atomic():
        if not (host and versione and modello):
            SoftwareInstallation.objects.filter(source_kind=KIND, host=host, still_detected=True).update(still_detected=False)
            return None
        product_raw = f"{modello} firmware"
        vendor = normalize_vendor(dispositivo.produttore or "")
        product = normalize_product(product_raw, version=versione)
        key = installation_key(KIND, host, vendor, product, versione)
        now = timezone.now()
        oggi = timezone.localdate()
        riga, creata = SoftwareInstallation.objects.get_or_create(dedup_key=key, defaults={
            "source_kind": KIND, "host": host, "host_display": (dispositivo.nome or host)[:255],
            "vendor_raw": (dispositivo.produttore or "")[:255], "product_raw": product_raw[:255],
            "vendor": vendor, "product": product, "version_raw": versione[:120],
            "version_norm": normalize_version(versione), "hub_asset_id": dispositivo.asset_id,
            "detected_at": now, "seen_at": now, "last_seen_at": now, "last_inventory_date": oggi,
            "still_detected": True,
        })
        if not creata:
            SoftwareInstallation.objects.filter(pk=riga.pk).update(
                last_seen_at=now, last_inventory_date=oggi, still_detected=True, hub_asset_id=dispositivo.asset_id,
                host_display=(dispositivo.nome or host)[:255],
            )
        SoftwareInstallation.objects.filter(source_kind=KIND, host=host, still_detected=True).exclude(
            pk=riga.pk).update(still_detected=False)
    return riga
