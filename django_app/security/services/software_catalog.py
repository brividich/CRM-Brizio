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


def _famiglia(vendor, product):
    """Il «programma»: produttore + nome senza le parole del produttore («chrome» = «google chrome»).

    Solo per mostrare: le decisioni, le licenze e la mappatura CPE restano legate a ``vendor|product``.
    """
    from security.services.software_inventory import _token, base_name

    return (_token(vendor)[:1] and _token(vendor)[0] or "", base_name(vendor, product))


def families():
    """{(vendor, product): chiave canonica} per i prodotti presenti: i nomi dello stesso programma
    puntano a quello più diffuso (a parità, il nome più corto). Un prodotto da solo punta a sé stesso."""
    rows = (
        SoftwareInstallation.objects.filter(still_detected=True)
        .values("vendor", "product").order_by().annotate(hosts=Count("host", distinct=True))
    )
    gruppi = defaultdict(list)
    for row in rows:
        gruppi[_famiglia(row["vendor"], row["product"])].append(row)
    out = {}
    for membri in gruppi.values():
        canonico = min(membri, key=lambda r: (-r["hosts"], len(r["product"]), r["product"], r["vendor"]))
        for r in membri:
            out[(r["vendor"], r["product"])] = (canonico["vendor"], canonico["product"])
    return out


def _canon(fam, vendor, product):
    return fam.get((vendor, product), (vendor, product))


def member_keys(key):
    """Tutte le chiavi dei nomi che formano lo stesso programma di ``key`` (compresa ``key``)."""
    target = _canon(families(), *split_key(key))
    keys = {inventory_key(*m) for m, c in families().items() if c == target}
    keys.add(key)
    return keys


def catalog(limit=2000):
    """Programmi presenti oggi (i nomi dello stesso programma sono una riga sola), con il nome più
    usato nell'export e quanti PC li hanno."""
    fam = families()
    labels = defaultdict(Counter)
    hosts = defaultdict(set)
    members = defaultdict(set)
    for vendor, product, raw, vendor_raw, host in SoftwareInstallation.objects.filter(still_detected=True).values_list(
        "vendor", "product", "product_raw", "vendor_raw", "host"
    ):
        canon = _canon(fam, vendor, product)
        labels[canon][(raw, vendor_raw)] += 1
        hosts[canon].add(host)
        members[canon].add(inventory_key(vendor, product))
    out = []
    for canon in sorted(hosts, key=lambda c: (c[1], c[0]))[:limit]:
        vendor, product = canon
        # il nome mostrato è quello del prodotto canonico (il più diffuso), non quello di un membro minore
        etichette = Counter({k: v for k, v in labels[canon].items()})
        (raw, vendor_raw), _n = etichette.most_common(1)[0]
        out.append({
            "key": inventory_key(vendor, product),
            "label": raw or product,
            "vendor_label": vendor_raw or vendor,
            "hosts": len(hosts[canon]),
            "member_keys": sorted(members[canon]),
        })
    return out


def catalog_choices():
    return [(item["key"], f"{item['label']} · {item['vendor_label'] or 'produttore n/d'} ({item['hosts']} PC)") for item in catalog()]


def hosts_by_key(keys):
    """{chiave: numero di PC che hanno oggi il programma} per le chiavi richieste (nomi dello stesso programma uniti)."""
    wanted = {k for k in keys if k}
    if not wanted:
        return {}
    fam = families()
    targets = {k: _canon(fam, *split_key(k)) for k in wanted}
    hosts = defaultdict(set)
    for vendor, product, host in SoftwareInstallation.objects.filter(still_detected=True).values_list("vendor", "product", "host").distinct():
        hosts[_canon(fam, vendor, product)].add(host)
    return {k: len(hosts[t]) for k, t in targets.items() if t in hosts}


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
    fam = families()
    groups = defaultdict(list)
    for inst in installs:
        groups[_canon(fam, inst.vendor, inst.product)].append(inst)
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


def product_hosts(key):
    """PC che hanno oggi il programma (tutti i nomi che lo formano), con versione, asset collegato e ultima rilevazione."""
    pairs = {split_key(k) for k in member_keys(key)}
    vendors, products = {v for v, _p in pairs}, {p for _v, p in pairs}
    rows = SoftwareInstallation.objects.filter(still_detected=True, vendor__in=vendors, product__in=products).select_related("hub_asset")
    return sorted((i for i in rows if (i.vendor, i.product) in pairs), key=lambda i: (i.host, i.version_raw))


def versions_by_key():
    """{chiave: Counter(versione → PC)} dei prodotti presenti."""
    fam = families()
    out = defaultdict(Counter)
    for vendor, product, version, host in SoftwareInstallation.objects.filter(still_detected=True).values_list(
        "vendor", "product", "version_raw", "host"
    ).distinct():
        out[inventory_key(*_canon(fam, vendor, product))][version] += 1
    return out


def cve_by_key():
    """{chiave: numero di CVE che impattano almeno un PC} dai calcoli d'impatto del SOC."""
    fam = families()
    out = defaultdict(set)
    for vendor, product, cve_id in SecurityCveImpact.objects.filter(
        outcome=SecurityCveImpact.IMPACTS, installation__isnull=False,
    ).values_list("installation__vendor", "installation__product", "cve__cve_id"):
        out[inventory_key(*_canon(fam, vendor, product))].add(cve_id)
    return {key: len(ids) for key, ids in out.items()}


def below_min_version(versions, min_version):
    """PC con versione sotto la minima e PC con versione non confrontabile (contati a parte, mai «vecchi»)."""
    from security.services.versioning import compare

    old, unknown = 0, 0
    if not min_version:
        return 0, 0
    for version, hosts in versions.items():
        result = compare(version, min_version)
        if result is None:
            unknown += hosts
        elif result < 0:
            old += hosts
    return old, unknown


def outdated_hosts(key, min_version):
    """PC con il prodotto in una versione sicuramente inferiore alla minima."""
    from security.services.versioning import compare

    if not min_version:
        return []
    return [i for i in product_hosts(key) if (compare(i.version_raw, min_version) or 0) < 0]


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
