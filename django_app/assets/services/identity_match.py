"""Abbinamento di un dispositivo (SNMP, SOC, ...) a un Asset del registro HUB.

Un solo algoritmo per tutti i moduli che "vedono" dispositivi IT, cosi' un
collegamento fatto in un modulo aiuta gli altri: se la stampante e' gia'
collegata nella centrale SNMP, il SOC che la trova per IP la propone sullo
stesso asset.

Ordine, dal segnale piu' forte al piu' debole:

1. **seriale** (``Asset.serial_number``, senza maiuscole);
1b. **MAC** (normalizzato): punto rete dell'asset (``AssetEndpoint.mac``), poi i
   MAC Wi-Fi/Ethernet dei PC Intune già collegati;
2. **indirizzo IP**: endpoint dell'asset, poi collegamenti gia' confermati
   negli altri moduli (dispositivi/MFC SNMP, dispositivi SOC);
3. **nome**: identico al nome dell'asset, poi il nome host corto
   (``pc-01.dominio.local`` -> ``pc-01``) su nome o nome endpoint.

Mai una scelta arbitraria: con piu' candidati il risultato e' ``None`` e il
motivo dice perche'. Gli asset dismessi non vengono proposti.
"""
from __future__ import annotations

import ipaddress

REASON_SERIAL = "seriale"
REASON_SERIAL_AMBIGUOUS = "seriale ambiguo"
REASON_MAC = "indirizzo MAC"
REASON_MAC_AMBIGUOUS = "indirizzo MAC ambiguo"
REASON_IP = "indirizzo IP"
REASON_IP_LINKED = "IP già collegato in un altro modulo"
REASON_IP_AMBIGUOUS = "indirizzo IP ambiguo"
REASON_NAME = "nome identico"
REASON_HOSTNAME = "nome host"
REASON_NAME_AMBIGUOUS = "più asset con lo stesso nome"
REASON_NONE = "nessuna corrispondenza"

AMBIGUOUS_REASONS = {REASON_SERIAL_AMBIGUOUS, REASON_MAC_AMBIGUOUS, REASON_IP_AMBIGUOUS, REASON_NAME_AMBIGUOUS}


def _valid_ip(value) -> str:
    try:
        return str(ipaddress.ip_address(str(value or "").strip()))
    except ValueError:
        return ""


def _active_assets():
    from assets.models import Asset

    return Asset.objects.exclude(status=Asset.STATUS_RETIRED)


def _unique(ids) -> tuple[int | None, bool]:
    """``(id, ambiguo)`` da un insieme di id candidati."""
    ids = {pk for pk in ids if pk}
    if len(ids) == 1:
        return next(iter(ids)), False
    return None, len(ids) > 1


def _linked_ids_for_ip(ip: str) -> set[int]:
    """Asset gia' collegati a questo IP negli altri moduli (solo collegamenti confermati)."""
    ids: set[int] = set()
    try:
        from contatori.models import DispositivoSNMP, Macchina

        ids.update(DispositivoSNMP.objects.filter(host=ip, asset__isnull=False).values_list("asset_id", flat=True))
        ids.update(Macchina.objects.filter(host=ip, asset__isnull=False).values_list("asset_id", flat=True))
    except ImportError:  # pragma: no cover - modulo non installato
        pass
    try:
        from security.models import SecurityAsset

        ids.update(SecurityAsset.objects.filter(ip_address=ip, hub_asset__isnull=False).values_list("hub_asset_id", flat=True))
    except ImportError:  # pragma: no cover
        pass
    return ids


def _ids_for_mac(mac: str) -> set[int]:
    """Asset con questo MAC: punto rete dichiarato, poi PC di Intune già collegati."""
    from django.db.models import Q

    ids = set(_active_assets().filter(endpoints__mac=mac).values_list("pk", flat=True)[:5])
    if not ids:
        from assets.models import DispositivoIntune

        bare = mac.replace(":", "")  # Intune dà il MAC senza separatori
        ids.update(DispositivoIntune.objects.filter(asset__isnull=False).filter(
            Q(mac_wifi__iexact=bare) | Q(mac_ethernet__iexact=bare) | Q(mac_wifi__iexact=mac) | Q(mac_ethernet__iexact=mac)
        ).values_list("asset_id", flat=True)[:5])
    return ids


def match_hub_asset(*, serial: str = "", ip: str = "", hostname: str = "", mac: str = ""):
    """``(asset | None, motivo)`` per un dispositivo descritto da seriale, MAC, IP e/o nome."""
    assets = _active_assets()

    serial = (serial or "").strip()
    if serial:
        ids = list(assets.filter(serial_number__iexact=serial).values_list("pk", flat=True)[:2])
        if len(ids) == 1:
            return assets.get(pk=ids[0]), REASON_SERIAL
        if len(ids) > 1:
            return None, REASON_SERIAL_AMBIGUOUS

    from .mac import normalizza_mac

    mac = normalizza_mac(mac)
    if mac:
        pk, ambiguous = _unique(_ids_for_mac(mac))
        if pk and assets.filter(pk=pk).exists():
            return assets.get(pk=pk), REASON_MAC
        if ambiguous:
            return None, REASON_MAC_AMBIGUOUS

    ip = _valid_ip(ip)
    if ip:
        pk, ambiguous = _unique(assets.filter(endpoints__ip=ip).values_list("pk", flat=True)[:5])
        if pk:
            return assets.get(pk=pk), REASON_IP
        if ambiguous:
            return None, REASON_IP_AMBIGUOUS
        active_ids = set(assets.filter(pk__in=_linked_ids_for_ip(ip)).values_list("pk", flat=True))
        pk, ambiguous = _unique(active_ids)
        if pk:
            return assets.get(pk=pk), REASON_IP_LINKED
        if ambiguous:
            return None, REASON_IP_AMBIGUOUS

    hostname = (hostname or "").strip()
    if hostname:
        pk, ambiguous = _unique(assets.filter(name__iexact=hostname).values_list("pk", flat=True)[:5])
        if pk:
            return assets.get(pk=pk), REASON_NAME
        if ambiguous:
            return None, REASON_NAME_AMBIGUOUS
        short = hostname.split(".", 1)[0].strip()
        if short and short.lower() != hostname.lower():
            from django.db.models import Q

            pk, ambiguous = _unique(
                assets.filter(Q(name__iexact=short) | Q(endpoints__endpoint_name__iexact=short))
                .values_list("pk", flat=True).distinct()[:5]
            )
            if pk:
                return assets.get(pk=pk), REASON_HOSTNAME
            if ambiguous:
                return None, REASON_NAME_AMBIGUOUS

    return None, REASON_NONE
