"""Copertura licenze ↔ software installato (inventario SOC) e licenze di un asset.

Sola lettura: confronta le licenze del modulo Asset con ``security.SoftwareInstallation`` tramite
``inventory_key`` e con le decisioni del catalogo (``SoftwareCatalogEntry``). Usato dall'elenco licenze
e dal modulo contatori (licenze del dispositivo collegato).
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from assets.models import SoftwareCatalogEntry, SoftwareLicense

EXPIRING_DAYS = 30


def license_status(lic, today=None):
    """«inactive» | «expired» | «expiring» | «active» (stessa soglia dei 30 giorni dell'elenco licenze)."""
    today = today or timezone.localdate()
    if not lic.is_active:
        return "inactive"
    if lic.expiry_date is None:
        return "active"
    if lic.expiry_date < today:
        return "expired"
    if lic.expiry_date <= today + timedelta(days=EXPIRING_DAYS):
        return "expiring"
    return "active"


def licenses_for_asset(asset, today=None):
    """Licenze assegnate all'asset, con stato e giorni dalla/alla scadenza; le più urgenti per prime."""
    today = today or timezone.localdate()
    order = {"expired": 0, "expiring": 1, "inactive": 2, "active": 3}
    rows = [
        {"license": lic, "status": license_status(lic, today),
         "giorni": abs((lic.expiry_date - today).days) if lic.expiry_date else None}
        for lic in SoftwareLicense.objects.filter(asset=asset)
    ]
    rows.sort(key=lambda r: (order[r["status"]], r["license"].product_name.lower()))
    return rows


def expiring_for_assets(asset_ids, today=None):
    """{asset_id: (scadute, in scadenza)} delle licenze attive degli asset indicati, in una query."""
    today = today or timezone.localdate()
    out = {}
    ids = {a for a in asset_ids if a}
    if not ids:
        return out
    for asset_id, expiry in SoftwareLicense.objects.filter(
        asset_id__in=ids, is_active=True, expiry_date__isnull=False,
        expiry_date__lte=today + timedelta(days=EXPIRING_DAYS),
    ).values_list("asset_id", "expiry_date"):
        expired, expiring = out.get(asset_id, (0, 0))
        out[asset_id] = (expired + 1, expiring) if expiry < today else (expired, expiring + 1)
    return out


def _device_asset_ids():
    """Asset collegati a un apparato del modulo contatori (vuoto se il modulo non c'è)."""
    try:
        from contatori.models import DispositivoSNMP, Macchina
    except ImportError:
        return set()
    ids = set(Macchina.objects.filter(asset__isnull=False).values_list("asset_id", flat=True))
    ids |= set(DispositivoSNMP.objects.filter(asset__isnull=False).values_list("asset_id", flat=True))
    return ids


def _norm(text):
    return "".join(ch for ch in (text or "").lower() if ch.isalnum() or ch == " ").strip()


def suggest_inventory_key(lic, catalog_items):
    """Chiave di inventario più plausibile per una licenza non collegata, o None se ambigua/assente."""
    name = _norm(lic.product_name)
    if len(name) < 3:
        return None
    hits = [
        item for item in catalog_items
        if name == _norm(item["label"]) or name in _norm(item["label"]) or _norm(item["label"]) in name
    ]
    if lic.vendor:
        vendor = _norm(lic.vendor)
        narrowed = [i for i in hits if vendor in _norm(i["vendor_label"]) or _norm(i["vendor_label"]) in vendor]
        hits = narrowed or hits
    return hits[0] if len(hits) == 1 else None


def coverage_report(today=None):
    """Cosa non quadra tra licenze e software installato.

    - ``unlicensed``: prodotti «a pagamento» a catalogo installati su PC senza alcuna licenza valida collegata;
    - ``over_seats``: più PC con il software che posti acquistati;
    - ``expired_installed``: licenza scaduta/disattiva ma software ancora installato;
    - ``unused``: licenza valida collegata a un prodotto che non risulta più installato (possibile risparmio);
    - ``unlinked``: licenze attive senza chiave d'inventario, con proposta quando univoca.
    """
    from security.services.software_catalog import catalog, hosts_by_key

    today = today or timezone.localdate()
    licenses = list(SoftwareLicense.objects.select_related("asset"))
    keys = {lic.inventory_key for lic in licenses if lic.inventory_key}
    paid = {
        e.inventory_key: e
        for e in SoftwareCatalogEntry.objects.filter(licensing=SoftwareCatalogEntry.LICENSING_PAID)
    }
    installed = hosts_by_key(keys | set(paid))

    valid_keys, by_key = set(), {}
    for lic in licenses:
        if not lic.inventory_key:
            continue
        by_key.setdefault(lic.inventory_key, []).append(lic)
        if license_status(lic, today) in {"active", "expiring"}:
            valid_keys.add(lic.inventory_key)

    report = {"unlicensed": [], "over_seats": [], "expired_installed": [], "unused": [], "unlinked": []}
    for key, entry in paid.items():
        hosts = installed.get(key, 0)
        if hosts and key not in valid_keys:
            report["unlicensed"].append({"key": key, "name": entry.display_name or key, "hosts": hosts})
    for key, group in by_key.items():
        hosts = installed.get(key, 0)
        if key in valid_keys:
            seats = [lic.seats_total for lic in group if lic.seats_total and license_status(lic, today) in {"active", "expiring"}]
            if seats and hosts > sum(seats):
                report["over_seats"].append({"key": key, "license": group[0], "hosts": hosts, "seats": sum(seats)})
            if not hosts:
                report["unused"].append({"key": key, "license": group[0]})
        elif hosts:
            report["expired_installed"].append({"key": key, "license": group[0], "hosts": hosts})
    # Le licenze di apparati (MFC, switch, UPS... del modulo contatori) non stanno nell'inventario dei PC.
    device_assets = _device_asset_ids()
    unlinked = [
        lic for lic in licenses
        if not lic.inventory_key and license_status(lic, today) != "inactive" and lic.asset_id not in device_assets
    ]
    if unlinked:
        items = catalog()
        for lic in unlinked:
            report["unlinked"].append({"license": lic, "suggestion": suggest_inventory_key(lic, items)})
    for rows in report.values():
        rows.sort(key=lambda r: str(r.get("name") or r["license"]).lower())
    report["total"] = sum(len(v) for k, v in report.items())
    return report
