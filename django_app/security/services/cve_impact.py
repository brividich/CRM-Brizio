"""La CVE impatta i nostri asset? Esito per (CVE, host) con spiegazione leggibile.

- **IMPATTA**: prodotto mappato (CPE confermato) e versione installata nel range vulnerabile.
- **NON IMPATTA**: prodotto presente con versione fuori range, oppure prodotto assente da un
  inventario aggiornato di recente (si dichiara la data dell'inventario).
- **DA VERIFICARE**: versione non confrontabile, mappatura CPE mancante, inventario vecchio,
  configurazione CVE ambigua (es. vulnerabile solo su una certa piattaforma).

Nel dubbio il sistema dice «da verificare», mai «sicuro». Nessuna chiusura automatica qui:
``closure_proposal`` dice solo se una CVE *può essere proposta* per la chiusura (mai se è
in CISA KEV o critica).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from security.models import (
    SecurityCveImpact,
    SecurityCveRecord,
    SoftwareCpeMapping,
    SoftwareInstallation,
)
from security.services import soc_settings
from security.services.versioning import in_range

RANK = {SecurityCveImpact.IMPACTS: 2, SecurityCveImpact.TO_VERIFY: 1, SecurityCveImpact.NOT_IMPACTED: 0}


def freshness_days():
    return soc_settings.value("cve.inventario.freschezza_giorni")


def fresh_since(today=None):
    return (today or timezone.localdate()) - timedelta(days=freshness_days())


def _key(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _range_text(c):
    parts = []
    if c.get("start_including"):
        parts.append(f">= {c['start_including']}")
    if c.get("start_excluding"):
        parts.append(f"> {c['start_excluding']}")
    if c.get("end_including"):
        parts.append(f"<= {c['end_including']}")
    if c.get("end_excluding"):
        parts.append(f"< {c['end_excluding']}")
    if not parts and c.get("version") not in ("", "*", "-"):
        parts.append(f"= {c['version']}")
    return "vulnerabile " + (" e ".join(parts) if parts else "in tutte le versioni")


def _source_text(install):
    return f"fonte: export {install.get_source_kind_display()} del {install.last_inventory_date:%d/%m/%Y}"


def _confirmed_mappings():
    out = defaultdict(list)
    for m in SoftwareCpeMapping.objects.filter(confirmed=True, not_applicable=False):
        out[(m.cpe_vendor.lower(), m.cpe_product.lower())].append((m.vendor, m.product))
    return out


def _evaluate_install(record, criterion, install, stale_before):
    name = f"{install.product_raw} {install.version_raw}".strip()
    where = install.host_display or install.host
    rng = _range_text(criterion)
    base = f"{name} installato su {where}; {rng}; {_source_text(install)}"
    if criterion.get("version") == "-":
        return SecurityCveImpact.TO_VERIFY, f"{base}. La CVE non indica versioni confrontabili."
    exact = criterion.get("version") if criterion.get("version") not in ("", "*", "-") else None
    verdict = in_range(
        install.version_raw, exact=exact,
        start_including=criterion.get("start_including"), start_excluding=criterion.get("start_excluding"),
        end_including=criterion.get("end_including"), end_excluding=criterion.get("end_excluding"),
    )
    if install.last_inventory_date < stale_before:
        return SecurityCveImpact.TO_VERIFY, f"{base}. Inventario vecchio (oltre {freshness_days()} giorni): la versione può essere cambiata."
    if verdict is None:
        return SecurityCveImpact.TO_VERIFY, f"{base}. Versione «{install.version_raw}» non confrontabile in modo affidabile."
    if verdict and (criterion.get("requires_platform") or record.ambiguous_configuration):
        return SecurityCveImpact.TO_VERIFY, f"{base}. Versione nel range, ma la CVE vale solo con una piattaforma/configurazione specifica."
    if verdict:
        return SecurityCveImpact.IMPACTS, f"{base}."
    return SecurityCveImpact.NOT_IMPACTED, f"{base}: versione fuori dal range vulnerabile."


def evaluate(record, today=None):
    """Esiti per host (dict host → (esito, [spiegazioni], installazione, data inventario)) + criteri non mappati."""
    stale_before = fresh_since(today)
    mappings = _confirmed_mappings()
    not_applicable = set(SoftwareCpeMapping.objects.filter(not_applicable=True).values_list("vendor", "product"))
    per_host, unmapped = {}, []
    for criterion in record.configurations or []:
        pair = (criterion.get("vendor", "").lower(), criterion.get("product", "").lower())
        products = mappings.get(pair, [])
        if products:
            q = Q()
            for vendor, product in products:
                q |= Q(vendor=vendor, product=product)
            installs = SoftwareInstallation.objects.filter(q, still_detected=True)
            for install in installs:
                outcome, text = _evaluate_install(record, criterion, install, stale_before)
                _merge(per_host, install, outcome, text)
            continue
        # Nessuna mappatura confermata: cerco prodotti dal nome simile, da verificare.
        cpe_name = _key(criterion.get("product"))
        if not cpe_name:
            continue
        similar = [
            install for install in SoftwareInstallation.objects.filter(still_detected=True, product__icontains=cpe_name.split(" ")[0])
            if (install.vendor, install.product) not in not_applicable and (cpe_name in _key(install.product) or _key(install.product) in cpe_name)
        ]
        unmapped.append({"cpe": f"{pair[0]}:{pair[1]}", "similar": len(similar)})
        for install in similar:
            text = (f"{install.product_raw} {install.version_raw} installato su {install.host_display or install.host}; "
                    f"possibile corrispondenza con {pair[0]}:{pair[1]} ma la mappatura CPE non è confermata; {_source_text(install)}.")
            _merge(per_host, install, SecurityCveImpact.TO_VERIFY, text)
    return per_host, unmapped


def _merge(per_host, install, outcome, text):
    current = per_host.get(install.host)
    if current is None:
        per_host[install.host] = [outcome, [text], install, install.last_inventory_date]
        return
    if RANK[outcome] > RANK[current[0]]:
        current[0], current[2] = outcome, install
    if text not in current[1]:
        current[1].append(text)


def recompute(record, today=None):
    per_host, _unmapped = evaluate(record, today)
    now = timezone.now()
    rows = [
        SecurityCveImpact(cve=record, host=host[:255], installation=install, hub_asset_id=install.hub_asset_id, outcome=outcome,
                          explanation="\n".join(texts)[:4000], inventory_date=inventory_date, computed_at=now)
        for host, (outcome, texts, install, inventory_date) in per_host.items()
    ]
    with transaction.atomic():
        SecurityCveImpact.objects.filter(cve=record).delete()
        SecurityCveImpact.objects.bulk_create(rows, batch_size=100)
        record.impact_computed_at = now
        record.save(update_fields=["impact_computed_at"])
    return len(rows)


def recompute_all(today=None):
    total = 0
    for record in SecurityCveRecord.objects.all():
        total += recompute(record, today)
    return total


def latest_inventory_date():
    return SoftwareInstallation.objects.aggregate(last=Max("last_inventory_date"))["last"]


def summary(record, today=None):
    """Conteggi per esito, host senza il prodotto (non impatta) e proposta di chiusura."""
    counts = Counter(record.impacts.values_list("outcome", flat=True))
    stale_before = fresh_since(today)
    fresh_hosts = set(SoftwareInstallation.objects.filter(last_inventory_date__gte=stale_before).values_list("host", flat=True).distinct())
    with_rows = set(record.impacts.values_list("host", flat=True))
    _per_host, unmapped = evaluate(record, today) if record.configurations else ({}, [])
    absent = len(fresh_hosts - with_rows)
    latest = latest_inventory_date()
    info = {
        "impacts": counts.get(SecurityCveImpact.IMPACTS, 0),
        "to_verify": counts.get(SecurityCveImpact.TO_VERIFY, 0),
        "not_impacted": counts.get(SecurityCveImpact.NOT_IMPACTED, 0),
        "absent_hosts": absent,
        "inventory_date": latest,
        "inventory_fresh": bool(latest and latest >= stale_before),
        "no_configurations": not record.configurations,
        "nvd_missing": record.nvd_fetched_at is None,
        "unmapped": unmapped,
    }
    info["closure"] = closure_proposal(record, info)
    return info


def closure_proposal(record, info):
    """(proponibile, motivo). Mai chiusa da sola: al massimo proposta a una persona."""
    if info["nvd_missing"] or info["no_configurations"]:
        return False, "Configurazioni CVE non disponibili: da verificare."
    if info["impacts"] or info["to_verify"]:
        return False, "Ci sono host impattati o da verificare."
    if not info["inventory_fresh"]:
        return False, "Inventario software non aggiornato di recente."
    if any(item["similar"] for item in info["unmapped"]):
        return False, "Prodotti simili senza mappatura CPE confermata."
    if record.kev:
        return False, "CVE sfruttata attivamente (CISA KEV): la chiusura resta manuale dopo verifica."
    if (record.severity or "").lower() == "critical" or (record.cvss or 0) >= 9:
        return False, "CVE critica: la chiusura resta manuale dopo verifica."
    return True, f"Nessun host impattato secondo l'inventario del {info['inventory_date']:%d/%m/%Y}: si può proporre la chiusura."


# --- Dashboard ------------------------------------------------------------------------------

def impacting_cves(limit=50):
    rows = (
        SecurityCveRecord.objects.annotate(
            impacted=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.IMPACTS)),
            to_verify=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.TO_VERIFY)),
        )
        .filter(Q(impacted__gt=0) | Q(to_verify__gt=0))
        .order_by("-kev", "-cvss", "-epss", "-impacted", "cve_id")
    )
    return list(rows[:limit])


def most_exposed_hosts(limit=20):
    return list(
        SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS)
        .values("host").order_by()
        .annotate(cves=Count("cve", distinct=True), kev=Count("cve", filter=Q(cve__kev=True), distinct=True))
        .order_by("-kev", "-cves", "host")[:limit]
    )


def unmapped_software(limit=50):
    mapped = set(SoftwareCpeMapping.objects.filter(Q(confirmed=True) | Q(not_applicable=True)).values_list("vendor", "product"))
    rows = (
        SoftwareInstallation.objects.filter(still_detected=True)
        .values("vendor", "product").order_by()
        .annotate(hosts=Count("host", distinct=True))
        .order_by("-hosts", "vendor", "product")
    )
    out = []
    for row in rows:
        if (row["vendor"], row["product"]) in mapped:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def impacts_for_hub_asset(asset):
    return list(
        SecurityCveImpact.objects.filter(hub_asset=asset).exclude(outcome=SecurityCveImpact.NOT_IMPACTED)
        .select_related("cve").order_by("-cve__kev", "-cve__cvss", "cve__cve_id")[:50]
    )
