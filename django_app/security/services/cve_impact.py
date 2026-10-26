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

import logging
import re
from collections import Counter, defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from security.models import (
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityCveRisoluzione,
    SoftwareCpeMapping,
    SoftwareInstallation,
)
from security.services import soc_settings
from security.services.versioning import in_range

logger = logging.getLogger(__name__)

RANK = {SecurityCveImpact.IMPACTS: 2, SecurityCveImpact.TO_VERIFY: 1, SecurityCveImpact.NOT_IMPACTED: 0}

# Un solo ricalcolo completo alla volta: più copie in parallelo si bloccavano a vicenda
# (deadlock 40001) e tenevano occupato SQL per ore. Le chiavi stanno nella cache condivisa.
LOCK_KEY = "security:cve_recompute:in_corso"
QUEUED_KEY = "security:cve_recompute:accodato"
RERUN_KEY = "security:cve_recompute:da_rifare"
LOCK_TTL = 900


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
    if install.source_kind == "snmp_firmware":
        return f"fonte: monitoraggio SNMP del {install.last_inventory_date:%d/%m/%Y}"
    fonti = install.fonti_etichette
    nome = fonti[0] if len(fonti) == 1 else " + ".join(fonti)
    return f"fonte: export {nome} del {install.last_inventory_date:%d/%m/%Y}"


def _confirmed_mappings():
    out = defaultdict(list)
    for m in SoftwareCpeMapping.objects.filter(confirmed=True, not_applicable=False):
        out[(m.cpe_vendor.lower(), m.cpe_product.lower())].append((m.vendor, m.product))
    return out


def _evaluate_install(record, criterion, install, stale_before, auto_pairs=frozenset()):
    name = f"{install.product_raw} {install.version_raw}".strip()
    where = install.host_display or install.host
    rng = _range_text(criterion)
    base = f"{name} installato su {where}; {rng}; {_source_text(install)}"
    if (install.vendor, install.product) in auto_pairs:
        base += f"; collegamento automatico a {criterion.get('vendor')}:{criterion.get('product')} (nome identico in NVD)"
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


def _ci(text):
    """Confronto senza maiuscole, come la collation CI di SQL Server."""
    return str(text or "").lower()


class Contesto:
    """Mappature e installazioni lette UNA volta per tutto il ricalcolo, non per ogni criterio.

    Prima ogni criterio di ogni CVE rifaceva una ricerca ``icontains`` su tutto l'inventario:
    decine di migliaia di scansioni per un ricalcolo completo.
    """

    def __init__(self):
        self.mappings = _confirmed_mappings()
        self.auto_pairs = frozenset(
            SoftwareCpeMapping.objects.filter(confirmed=True, origin=SoftwareCpeMapping.ORIGIN_AUTO).values_list("vendor", "product")
        )
        self.not_applicable = set(SoftwareCpeMapping.objects.filter(not_applicable=True).values_list("vendor", "product"))
        self.installs = list(SoftwareInstallation.objects.filter(still_detected=True))
        self.per_prodotto = defaultdict(list)
        self.per_host = defaultdict(list)
        self.per_pk = {install.pk: install for install in self.installs}
        for install in self.installs:
            self.per_prodotto[(_ci(install.vendor), _ci(install.product))].append(install)
            self.per_host[install.host].append(install)

    def installazioni_di(self, products):
        visti = {}
        for vendor, product in products:
            for install in self.per_prodotto.get((_ci(vendor), _ci(product)), []):
                visti.setdefault(install.pk, install)
        return list(visti.values())

    def nome_contiene(self, testo):
        return [install for install in self.installs if testo in _ci(install.product)]


def evaluate(record, today=None, ctx=None):
    """Esiti per host (dict host → (esito, [spiegazioni], installazione, data inventario)) + criteri non mappati."""
    stale_before = fresh_since(today)
    ctx = ctx or Contesto()
    per_host, unmapped = {}, []
    for criterion in record.configurations or []:
        pair = (criterion.get("vendor", "").lower(), criterion.get("product", "").lower())
        products = ctx.mappings.get(pair, [])
        if products:
            for install in ctx.installazioni_di(products):
                outcome, text = _evaluate_install(record, criterion, install, stale_before, ctx.auto_pairs)
                _merge(per_host, install, outcome, text)
            continue
        # Nessuna mappatura confermata: cerco prodotti dal nome simile, da verificare.
        cpe_name = _key(criterion.get("product"))
        if not cpe_name:
            continue
        similar = [
            install for install in ctx.nome_contiene(cpe_name.split(" ")[0])
            if (install.vendor, install.product) not in ctx.not_applicable and (cpe_name in _key(install.product) or _key(install.product) in cpe_name)
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


APERTI = (SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY)


def _risoluzione(record, prima, inst, ctx, now):
    """Perché il PC di ``prima`` (riga del giro precedente, installazione ``inst``) non è più esposto."""
    from security.services.software_catalog import _famiglia

    attuali = ctx.per_host.get(prima.host, [])
    come, dopo = SecurityCveRisoluzione.PC_ASSENTE, ""
    if inst is not None and inst.still_detected:
        come, dopo = SecurityCveRisoluzione.RIVALUTATA, inst.version_raw
    elif inst is not None and attuali:
        famiglia = _famiglia(inst.vendor, inst.product)
        stesso = [i for i in attuali if (i.vendor, i.product) == (inst.vendor, inst.product) or _famiglia(i.vendor, i.product) == famiglia]
        if stesso:
            come = SecurityCveRisoluzione.AGGIORNATO
            dopo = ", ".join(sorted({i.version_raw for i in stesso if i.version_raw}))
        else:
            come = SecurityCveRisoluzione.RIMOSSO
    elif inst is None and attuali:
        come = SecurityCveRisoluzione.RIVALUTATA
    return SecurityCveRisoluzione(
        cve=record, host=prima.host, host_display=((inst.host_display if inst else "") or prima.host)[:255],
        hub_asset_id=prima.hub_asset_id, software=(inst.product_raw if inst else "")[:255],
        chiave=f"{inst.vendor}|{inst.product}"[:300] if inst else "", versione_prima=(inst.version_raw if inst else "")[:120],
        versione_dopo=dopo[:120], come=come, esito_prima=prima.outcome, aperta_dal=prima.aperta_dal or prima.computed_at, risolta_il=now,
    )


def recompute(record, today=None, ctx=None):
    ctx = ctx or Contesto()
    per_host, _unmapped = evaluate(record, today, ctx)
    now = timezone.now()
    prima = {r.host: r for r in record.impacts.filter(outcome__in=APERTI)}
    before = {host for host, r in prima.items() if r.outcome == SecurityCveImpact.IMPACTS}
    rows = []
    for host, (outcome, texts, install, inventory_date) in per_host.items():
        aperta_dal = None
        if outcome in APERTI:
            aperta_dal = (prima[host].aperta_dal or prima[host].computed_at) if host in prima else now
        rows.append(SecurityCveImpact(
            cve=record, host=host[:255], installation=install, hub_asset_id=install.hub_asset_id, outcome=outcome,
            explanation="\n".join(texts)[:4000], inventory_date=inventory_date, computed_at=now, aperta_dal=aperta_dal,
        ))
    # Il PC esposto al giro prima e non più adesso lascia la traccia della risoluzione.
    uscite = [r for host, r in prima.items() if per_host.get(host, (None,))[0] not in APERTI]
    # Le installazioni ancora rilevate sono già nel contesto; si legge solo quella che non c'è più.
    mancanti = {r.installation_id for r in uscite if r.installation_id and r.installation_id not in ctx.per_pk}
    altre = SoftwareInstallation.objects.in_bulk(mancanti) if mancanti else {}
    risolte = [_risoluzione(record, r, ctx.per_pk.get(r.installation_id) or altre.get(r.installation_id), ctx, now) for r in uscite]
    with transaction.atomic():
        SecurityCveImpact.objects.filter(cve=record).delete()
        SecurityCveImpact.objects.bulk_create(rows, batch_size=100)
        if risolte:
            SecurityCveRisoluzione.objects.bulk_create(risolte, batch_size=100)
        record.impact_computed_at = now
        record.save(update_fields=["impact_computed_at"])
    impacted = {host: per_host[host] for host in per_host if per_host[host][0] == SecurityCveImpact.IMPACTS}
    record._new_impact_event = record_new_impacts(record, impacted, set(impacted) - before, now)
    if risolte or set(impacted) != before:
        # L'alert aperto della CVE segue il progresso: PC usciti in timeline, «N PC su M» nel titolo.
        try:
            from security.services import cve_chiusura

            cve_chiusura.aggiorna_alert(record, risolte)
        except Exception:  # noqa: BLE001 - l'alert è un di più: il ricalcolo non deve fallire per lui
            logger.exception("Aggiornamento dell'alert della CVE %s non riuscito", record.cve_id)
    return len(rows)


def recompute_all(today=None):
    if not cache.add(LOCK_KEY, timezone.now().isoformat(), LOCK_TTL):
        # Un ricalcolo è già in corso: lo si rifà alla sua fine, per non perdere le modifiche arrivate nel frattempo.
        cache.set(RERUN_KEY, 1, LOCK_TTL)
        logger.info("Ricalcolo impatti CVE già in corso: rimandato alla sua fine")
        return 0
    cache.delete(QUEUED_KEY)
    try:
        total, events = 0, 0
        ctx = Contesto()
        for record in SecurityCveRecord.objects.all():
            total += recompute(record, today, ctx)
            events += 1 if getattr(record, "_new_impact_event", None) else 0
        if events:
            # Gli eventi passano dal motore regole come tutti gli altri: soppressioni, alert, ticket, notifiche.
            from security.services.rule_engine import evaluate_security_rules

            evaluate_security_rules()
        try:
            # Chiusura con prove degli alert «PC con versione vulnerabile» (regola cve_impatto_risolto).
            from security.services.auto_resolution import run_cve_impatto_risolto

            run_cve_impatto_risolto()
        except Exception:  # noqa: BLE001 - una chiusura mancata si ritenta al ciclo SOC successivo
            logger.exception("Chiusura automatica degli alert CVE non riuscita")
        return total
    finally:
        cache.delete(LOCK_KEY)
        if cache.get(RERUN_KEY):
            cache.delete(RERUN_KEY)
            from security.services.cve_feeds import queue_recompute

            queue_recompute()


# --- Alert sui PC impattati ---------------------------------------------------------------

IMPACT_EVENT_TYPE = "cve_impact_confirmed"
IMPACT_SOURCE_NAME = "Inventario software (impatto CVE)"


def alert_worthy(record):
    """Solo CVE sfruttate (CISA KEV) o critiche: il resto si guarda nella pagina Vulnerabilità."""
    return bool(record.kev) or (record.severity or "").lower() == "critical" or (record.cvss or 0) >= 9


def impact_source():
    from security.models import SecuritySource, SourceType

    source, _ = SecuritySource.objects.get_or_create(
        name=IMPACT_SOURCE_NAME, defaults={"source_type": SourceType.MANUAL, "vendor": "inventario"},
    )
    return source


def alert_dedup_hash(source, record):
    from security.services.dedup import make_hash

    return make_hash(source.pk, IMPACT_EVENT_TYPE, record.cve_id.upper())


def record_new_impacts(record, impacted, new_hosts, now=None):
    """Un evento quando almeno un PC *diventa* impattato da una CVE critica o sfruttata.

    Un PC già impattato al giro precedente non rigenera nulla: l'evento nasce solo per i PC nuovi.
    L'alert è uno per CVE (dedup sulla CVE) e si aggiorna se altri PC si aggiungono dopo.
    """
    if not new_hosts or not alert_worthy(record) or not soc_settings.value("cve.impatto.alert"):
        return None
    from security.models import SecurityEventRecord, Severity

    now = now or timezone.now()
    source = impact_source()
    dedup = alert_dedup_hash(source, record)
    products = Counter(entry[2].product_raw for entry in impacted.values() if entry[2] is not None)
    severity = Severity.CRITICAL
    payload = {
        "cve": record.cve_id,
        "cvss": record.cvss,
        "severity": severity,
        "nvd_severity": record.severity,
        "kev": record.kev,
        "kev_due": record.kev_due.isoformat() if record.kev_due else None,
        "epss": record.epss,
        "affected_product": products.most_common(1)[0][0] if products else "",
        "impacted_hosts": sorted(impacted)[:200],
        "impacted_count": len(impacted),
        "new_hosts": sorted(new_hosts)[:200],
        "explanations": [impacted[h][1][0] for h in sorted(new_hosts)[:20]],
        "inventory_date": max((entry[3] for entry in impacted.values() if entry[3]), default=None),
        "alert_candidate": True,
    }
    if payload["inventory_date"]:
        payload["inventory_date"] = payload["inventory_date"].isoformat()
    return SecurityEventRecord.objects.create(
        source=source, event_type=IMPACT_EVENT_TYPE, severity=severity, occurred_at=now,
        fingerprint=dedup, dedup_hash=dedup, payload=payload,
    )


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
        return False, ("CVE sfruttata attivamente (CISA KEV): l'alert si chiude da solo solo con due prove concordi per ogni PC "
                       "(regola «CVE critica corretta con prove»), altrimenti a mano dopo verifica.")
    if (record.severity or "").lower() == "critical" or (record.cvss or 0) >= 9:
        return False, ("CVE critica: l'alert si chiude da solo solo con due prove concordi per ogni PC "
                       "(regola «CVE critica corretta con prove»), altrimenti a mano dopo verifica.")
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
