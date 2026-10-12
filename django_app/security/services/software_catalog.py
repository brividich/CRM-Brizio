"""Inventario software visto dalla gestione asset: catalogo dei prodotti, software di un PC, PC per licenza.

L'inventario è uno solo (``SoftwareInstallation``, importato nel SOC). Qui si legge soltanto:
la scheda asset mostra i software del PC, le licenze contano i PC che hanno il prodotto.
La chiave di collegamento è ``vendor|product`` normalizzati, la stessa della mappatura CPE.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.db.models import Count, Max
from django.utils import timezone

from security.models import SecurityCveImpact, SoftwareInstallation


def inventory_key(vendor, product):
    return f"{vendor or ''}|{product or ''}"[:300]


def split_key(key):
    vendor, _sep, product = (key or "").partition("|")
    return vendor, product


def catalog(limit=2000):
    """Prodotti presenti oggi, con il nome più usato nell'export e quanti PC li hanno."""
    rows = (
        SoftwareInstallation.objects.filter(still_detected=True)
        .values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True))
        .order_by("product", "vendor")[:limit]
    )
    labels = defaultdict(Counter)
    for vendor, product, raw, vendor_raw in SoftwareInstallation.objects.filter(still_detected=True).values_list(
        "vendor", "product", "product_raw", "vendor_raw"
    ):
        labels[(vendor, product)][(raw, vendor_raw)] += 1
    out = []
    for row in rows:
        (raw, vendor_raw), _n = labels[(row["vendor"], row["product"])].most_common(1)[0]
        out.append({
            "key": inventory_key(row["vendor"], row["product"]),
            "label": raw or row["product"],
            "vendor_label": vendor_raw or row["vendor"],
            "hosts": row["hosts"],
        })
    return out


def catalog_choices():
    return [(item["key"], f"{item['label']} · {item['vendor_label'] or 'produttore n/d'} ({item['hosts']} PC)") for item in catalog()]


def hosts_by_key(keys):
    """{chiave: numero di PC che hanno oggi quel prodotto} per le chiavi richieste, in una query."""
    wanted = {split_key(k) for k in keys if k}
    if not wanted:
        return {}
    vendors = {v for v, _p in wanted}
    products = {p for _v, p in wanted}
    counts = {}
    rows = (
        SoftwareInstallation.objects.filter(still_detected=True, vendor__in=vendors, product__in=products)
        .values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True))
    )
    for row in rows:
        if (row["vendor"], row["product"]) in wanted:
            counts[inventory_key(row["vendor"], row["product"])] = row["hosts"]
    return counts


def latest_inventory_date():
    return SoftwareInstallation.objects.aggregate(last=Max("last_inventory_date"))["last"]


def software_for_hub_asset(asset, *, with_cve=False, license_states=None):
    """Software del PC raggruppati per prodotto: versione attuale, versioni precedenti, CVE, licenza.

    ``license_states``: {chiave inventario: "coperta" | "scaduta"} dalle licenze del modulo Asset.
    """
    installs = list(SoftwareInstallation.objects.filter(hub_asset=asset).order_by("product", "vendor", "-last_seen_at"))
    if not installs:
        return {"rows": [], "present": 0, "removed": 0, "inventory_date": None}
    cve = defaultdict(lambda: {"impacts": [], "to_verify": 0})
    if with_cve:
        for inst_id, outcome, cve_id in SecurityCveImpact.objects.filter(
            installation__in=[i.pk for i in installs if i.still_detected],
            outcome__in=[SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY],
        ).values_list("installation_id", "outcome", "cve__cve_id"):
            if outcome == SecurityCveImpact.IMPACTS:
                cve[inst_id]["impacts"].append(cve_id)
            else:
                cve[inst_id]["to_verify"] += 1
    groups = defaultdict(list)
    for inst in installs:
        groups[(inst.vendor, inst.product)].append(inst)
    rows = []
    for (vendor, product), items in groups.items():
        current = [i for i in items if i.still_detected]
        previous = [i for i in items if not i.still_detected]
        head = current[0] if current else items[0]
        impacts = sorted({c for i in current for c in cve[i.pk]["impacts"]})
        key = inventory_key(vendor, product)
        rows.append({
            "key": key,
            "name": head.product_raw,
            "vendor": head.vendor_raw or vendor,
            "versions": [i.version_raw for i in current],
            "present": bool(current),
            "first_seen": min(i.seen_at for i in items),
            "last_seen": max(i.last_seen_at for i in items),
            "previous": [{"version": i.version_raw, "until": i.last_seen_at} for i in previous][:5],
            "cve_impacts": impacts,
            "cve_to_verify": sum(cve[i.pk]["to_verify"] for i in current),
            "license": (license_states or {}).get(key, ""),
        })
    rows.sort(key=lambda r: (not r["present"], -len(r["cve_impacts"]), r["name"].lower()))
    return {
        "rows": rows,
        "present": sum(1 for r in rows if r["present"]),
        "removed": sum(1 for r in rows if not r["present"]),
        "inventory_date": max(i.last_inventory_date for i in installs),
    }


def license_states_for_keys(licenses, today=None):
    """{chiave: "coperta" | "scaduta"} da licenze con ``inventory_key``; una licenza valida vince su una scaduta."""
    today = today or timezone.localdate()
    out = {}
    for lic in licenses:
        if not lic.inventory_key:
            continue
        valid = lic.is_active and (lic.expiry_date is None or lic.expiry_date >= today)
        if valid:
            out[lic.inventory_key] = "coperta"
        else:
            out.setdefault(lic.inventory_key, "scaduta")
    return out
