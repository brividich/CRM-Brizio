"""Software non conforme: il catalogo dice cosa non deve esserci, l'inventario dice dove c'è.

Le decisioni stanno nel Catalogo software del modulo Asset (``assets.SoftwareCatalogEntry``):
- **Non autorizzato** / **Da rimuovere**: ogni PC che ha ancora il prodotto è un problema;
- **Versione minima**: ogni PC con una versione *sicuramente* più vecchia (una versione non
  confrontabile non viene mai contata come vecchia).

Come per l'impatto CVE nasce un evento solo quando **nuovi** PC entrano nel problema; il motore
regole ne fa un alert per (prodotto, tipo di problema), aggiornato se altri PC si aggiungono.
Nessuna chiusura automatica: quando il software sparisce dall'inventario l'alert lo chiude una persona.
"""
from __future__ import annotations

from django.utils import timezone

from security.models import SecurityEventRecord, SecuritySource, Severity, SourceType
from security.services import soc_settings
from security.services.dedup import make_hash

EVENT_TYPE = "software_policy"
SOURCE_NAME = "Inventario software (conformità)"
KIND_FORBIDDEN = "non_autorizzato"
KIND_REMOVE = "da_rimuovere"
KIND_OUTDATED = "versione_vecchia"
KIND_LABELS = {
    KIND_FORBIDDEN: "software non autorizzato",
    KIND_REMOVE: "software da rimuovere",
    KIND_OUTDATED: "versione sotto la minima",
}
KIND_SETTING = {
    KIND_FORBIDDEN: "software.non_autorizzato.alert",
    KIND_REMOVE: "software.da_rimuovere.alert",
    KIND_OUTDATED: "software.versione_minima.alert",
}
KIND_SEVERITY = {KIND_FORBIDDEN: Severity.HIGH, KIND_REMOVE: Severity.WARNING, KIND_OUTDATED: Severity.WARNING}


def policy_source():
    source, _ = SecuritySource.objects.get_or_create(name=SOURCE_NAME, defaults={"source_type": SourceType.MANUAL, "vendor": "inventario"})
    return source


def findings():
    """[(voce di catalogo, tipo, [installazioni])] per i prodotti che oggi violano una decisione."""
    from assets.models import SoftwareCatalogEntry
    from security.services import software_catalog as sc

    out = []
    for entry in SoftwareCatalogEntry.objects.exclude(classification=SoftwareCatalogEntry.CLASS_UNREVIEWED).order_by("inventory_key"):
        if entry.classification in (SoftwareCatalogEntry.CLASS_FORBIDDEN, SoftwareCatalogEntry.CLASS_REMOVE):
            installs = sc.product_hosts(entry.inventory_key)
            if installs:
                kind = KIND_FORBIDDEN if entry.classification == SoftwareCatalogEntry.CLASS_FORBIDDEN else KIND_REMOVE
                out.append((entry, kind, installs))
        if entry.min_version and entry.classification == SoftwareCatalogEntry.CLASS_ALLOWED:
            installs = sc.outdated_hosts(entry.inventory_key, entry.min_version)
            if installs:
                out.append((entry, KIND_OUTDATED, installs))
    return out


def summary():
    """Conteggi per la pagina Vulnerabilità del SOC: prodotti e PC per tipo di problema."""
    counts = {kind: {"products": 0, "hosts": set()} for kind in KIND_LABELS}
    for _entry, kind, installs in findings():
        counts[kind]["products"] += 1
        counts[kind]["hosts"].update(i.host for i in installs)
    return [{"kind": kind, "label": KIND_LABELS[kind], "products": c["products"], "hosts": len(c["hosts"])} for kind, c in counts.items()]


def _previous_hosts(source, dedup):
    last = (
        SecurityEventRecord.objects.filter(source=source, event_type=EVENT_TYPE, dedup_hash=dedup)
        .order_by("-occurred_at", "-id").values_list("payload", flat=True).first()
    )
    return set((last or {}).get("hosts") or [])


def record_events(now=None):
    """Un evento per (prodotto, tipo) quando nuovi PC entrano nel problema. Ritorna gli eventi creati."""
    now = now or timezone.now()
    source = None
    created = []
    for entry, kind, installs in findings():
        if not soc_settings.value(KIND_SETTING[kind]):
            continue
        source = source or policy_source()
        dedup = make_hash(source.pk, EVENT_TYPE, kind, entry.inventory_key)
        hosts = sorted({i.host for i in installs})
        new_hosts = sorted(set(hosts) - _previous_hosts(source, dedup))
        if not new_hosts:
            continue
        payload = {
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "inventory_key": entry.inventory_key,
            "product": entry.display_name or entry.inventory_key,
            "vendor": entry.vendor_name,
            "min_version": entry.min_version,
            "hosts": hosts[:300],
            "host_count": len(hosts),
            "new_hosts": new_hosts[:300],
            "versions": sorted({i.version_raw for i in installs})[:20],
            "notes": entry.notes[:500],
            "alert_candidate": True,
        }
        created.append(SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_TYPE, severity=KIND_SEVERITY[kind], occurred_at=now,
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        ))
    return created


def run():
    """Eventi + valutazione: da chiamare dopo un import dell'inventario o un cambio nel catalogo."""
    events = record_events()
    if events:
        from security.services.rule_engine import evaluate_security_rules

        evaluate_security_rules()
    return len(events)
