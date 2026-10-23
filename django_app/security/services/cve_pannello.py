"""Pannello laterale delle CVE: per un programma dell'inventario, per un PC (asset) e per una CVE.

Legge solo i calcoli d'impatto già fatti (``SecurityCveImpact``), mai l'NVD in diretta.
Esiti mostrati: «Colpisce» (versione nel range, CPE confermato) e «Da verificare»;
«Non impatta» non entra nel pannello. Le CVE sono in ordine di priorità (``priorita``: sfruttate
attivamente secondo CISA KEV o probabili secondo EPSS prima, poi CVSS).

Accanto al calcolo del SOC: le patch WatchGuard che correggono la CVE (``WatchGuardPatch``, API
WatchGuard) e il confronto con le CVE che vede Defender (``DefenderVulnerabilita``).

Le CVE chiuse su un PC (programma aggiornato o disinstallato) arrivano da ``SecurityCveRisoluzione``,
scritta dal ricalcolo: si mostrano gli ultimi ``GIORNI_RISOLTE`` giorni.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.utils import timezone

from security.models import SecurityCveImpact, SecurityCveRecord, SecurityCveRisoluzione
from security.services import software_catalog as sc
from security.services.cve_impact import _range_text

ESITI = (SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY)
NVD_URL = "https://nvd.nist.gov/vuln/detail/{}"
GIORNI_RISOLTE = 90
# EPSS = probabilità che la CVE venga sfruttata nei prossimi 30 giorni (FIRST.org).
EPSS_SUBITO = 0.10
EPSS_PRESTO = 0.01
_RANGO = {"subito": 0, "presto": 1, "normale": 2}


def _risolte(qs, giorni=GIORNI_RISOLTE):
    """L'ultima risoluzione per (CVE, PC) negli ultimi ``giorni``: un PC che va e viene conta una volta."""
    dal = timezone.now() - timedelta(days=giorni)
    visti, out = set(), []
    for r in qs.filter(risolta_il__gte=dal).select_related("cve", "hub_asset").order_by("-risolta_il"):
        if (r.cve_id, r.host) in visti:
            continue
        visti.add((r.cve_id, r.host))
        out.append(r)
    return out


def _conta_risolte(righe):
    corrette = [r for r in righe if r.correzione]
    return {"risolte": righe, "corrette": len(corrette), "uscite": len(righe) - len(corrette)}


def gravita(record):
    """(tono, etichetta) del pericolo: KEV o CVSS ≥ 9 critica, ≥ 7 alta, ≥ 4 media, poi bassa/n.d."""
    cvss = record.cvss
    if record.kev or (cvss is not None and cvss >= 9):
        return "critical", "Critica"
    if cvss is None:
        return "muted", "n.d."
    if cvss >= 7:
        return "high", "Alta"
    if cvss >= 4:
        return "medium", "Media"
    return "low", "Bassa"


def priorita(record):
    """(codice, etichetta, motivo): «subito» = sfruttata (KEV) o EPSS ≥ 10%; «presto» = CVSS ≥ 9, o CVSS ≥ 7 con EPSS ≥ 1%."""
    epss, cvss = record.epss or 0, record.cvss
    if record.kev:
        return "subito", "Subito", "sfruttata attivamente (CISA KEV)"
    if epss >= EPSS_SUBITO:
        return "subito", "Subito", f"probabilità di attacco alta (EPSS {epss:.0%} nei prossimi 30 giorni)"
    if cvss is not None and cvss >= 9:
        return "presto", "Presto", "CVSS 9 o più"
    if cvss is not None and cvss >= 7 and epss >= EPSS_PRESTO:
        return "presto", "Presto", f"CVSS {cvss:.1f} e probabilità di attacco {epss:.0%}"
    return "normale", "Normale", ""


def _ordine(riga):
    rec = riga["record"]
    return (riga["esito"] != SecurityCveImpact.IMPACTS, _RANGO[riga["priorita"]], -(rec.cvss if rec.cvss is not None else -1),
            rec.cve_id)


def _patch(cve_ids, hosts):
    """{(cve, host): patch WatchGuard aperta}; vuoto se l'API WatchGuard non è usata."""
    try:
        from security.services.watchguard_api import patch_aperte_per_cve

        return patch_aperte_per_cve(cve_ids, hosts)
    except Exception:  # noqa: BLE001 - il pannello non deve rompersi per le patch
        return {}


def correzione(record):
    """Da quale versione la CVE è corretta, se l'NVD lo dice (limite «<» dei range); altrimenti ''."""
    fixed = sorted({c["end_excluding"] for c in record.configurations or [] if c.get("end_excluding")})
    if not fixed:
        return ""
    if len(fixed) == 1:
        return f"corretta dalla versione {fixed[0]}"
    return "corretta dalle versioni " + ", ".join(fixed[:4]) + ("…" if len(fixed) > 4 else "")


def _righe(impatti):
    """Una riga per CVE: esito peggiore, PC colpiti, versioni colpite."""
    per_cve = defaultdict(lambda: {"colpiti": set(), "da_verificare": set(), "versioni": set()})
    records = {}
    for imp in impatti:
        g = per_cve[imp.cve_id]
        records[imp.cve_id] = imp.cve
        if imp.outcome == SecurityCveImpact.IMPACTS:
            g["colpiti"].add(imp.host)
            if imp.installation_id and imp.installation.version_raw:
                g["versioni"].add(imp.installation.version_raw)
        else:
            g["da_verificare"].add(imp.host)
    patch = _patch({r.cve_id for r in records.values()}, {h for g in per_cve.values() for h in g["colpiti"] | g["da_verificare"]})
    out = []
    for cve_pk, g in per_cve.items():
        rec = records[cve_pk]
        tono, etichetta = gravita(rec)
        prio, prio_label, prio_motivo = priorita(rec)
        con_patch = [h for h in g["colpiti"] | g["da_verificare"] if (rec.cve_id, h) in patch]
        out.append({
            "record": rec,
            "esito": SecurityCveImpact.IMPACTS if g["colpiti"] else SecurityCveImpact.TO_VERIFY,
            "pc": len(g["colpiti"]),
            "pc_da_verificare": len(g["da_verificare"] - g["colpiti"]),
            "versioni": sorted(g["versioni"]),
            "tono": tono,
            "gravita": etichetta,
            "correzione": correzione(rec),
            "priorita": prio,
            "priorita_label": prio_label,
            "priorita_motivo": prio_motivo,
            "pc_con_patch": len(con_patch),
            "patch": patch.get((rec.cve_id, con_patch[0])) if con_patch else None,
        })
    out.sort(key=_ordine)
    return out


def _riepilogo(righe):
    colpiscono = [r for r in righe if r["esito"] == SecurityCveImpact.IMPACTS]
    return {
        "colpiscono": colpiscono,
        "da_verificare": [r for r in righe if r["esito"] != SecurityCveImpact.IMPACTS],
        "gravi": sum(1 for r in colpiscono if r["tono"] == "critical"),
        "kev": sum(1 for r in colpiscono if r["record"].kev),
        "subito": sum(1 for r in colpiscono if r["priorita"] == "subito"),
    }


def _impatti_programma(key):
    pairs = {sc.split_key(k) for k in sc.member_keys(key)}
    qs = SecurityCveImpact.objects.filter(
        outcome__in=ESITI, installation__still_detected=True,
        installation__vendor__in={v for v, _p in pairs}, installation__product__in={p for _v, p in pairs},
    ).select_related("cve", "installation")
    return [i for i in qs if (i.installation.vendor, i.installation.product) in pairs]


def per_programma(key):
    """CVE del programma (tutti i nomi che lo formano) sui PC che lo hanno oggi, più quelle chiuse di recente."""
    risolte = _risolte(SecurityCveRisoluzione.objects.filter(chiave__in=sc.member_keys(key)))
    return {**_riepilogo(_righe(_impatti_programma(key))), **_conta_risolte(risolte)}


def cve_per_versione(key):
    """{versione: numero di CVE che la colpiscono} per la tabella «Versioni presenti»."""
    out = defaultdict(set)
    for imp in _impatti_programma(key):
        if imp.outcome == SecurityCveImpact.IMPACTS:
            out[imp.installation.version_raw].add(imp.cve_id)
    return {v: len(ids) for v, ids in out.items()}


def per_asset(asset):
    """CVE del PC raggruppate per software installato (nome del programma come nel catalogo)."""
    impatti = list(
        SecurityCveImpact.objects.filter(hub_asset=asset, outcome__in=ESITI, installation__still_detected=True)
        .select_related("cve", "installation")
    )
    fam = sc.families()
    gruppi = defaultdict(list)
    nomi = {}
    for imp in impatti:
        inst = imp.installation
        chiave = sc.inventory_key(*fam.get((inst.vendor, inst.product), (inst.vendor, inst.product)))
        nome, versione = inst.product_raw or inst.product, inst.version_raw
        gruppi[chiave].append(imp)
        nomi.setdefault(chiave, (nome, versione))
    software = []
    for chiave, imps in gruppi.items():
        righe = _righe(imps)
        nome, versione = nomi[chiave]
        software.append({"key": chiave, "nome": nome, "versione": versione, **_riepilogo(righe), "totale": len(righe)})
    software.sort(key=lambda s: (-s["gravi"], -len(s["colpiscono"]), s["nome"].lower()))
    tutte = _riepilogo(_righe(impatti))
    risolte = _risolte(SecurityCveRisoluzione.objects.filter(hub_asset=asset))
    return {"software": software, "colpiscono": len(tutte["colpiscono"]), "da_verificare": len(tutte["da_verificare"]),
            "gravi": tutte["gravi"], "kev": tutte["kev"], "subito": tutte["subito"], **_conta_risolte(risolte),
            "defender": _defender_asset(asset, {i.cve.cve_id for i in impatti})}


def _defender_asset(asset, nostre):
    from security.models import SoftwareInstallation
    from security.services import defender_vuln

    host = SoftwareInstallation.objects.filter(hub_asset=asset, still_detected=True).values_list("host", flat=True).first()
    try:
        return defender_vuln.confronto_asset(host or "", nostre)
    except Exception:  # noqa: BLE001
        return None


def _perche(testo):
    """Prima riga della spiegazione senza «<prodotto> installato su <PC>; » (già mostrati nella riga)."""
    riga = (testo or "").splitlines()[0] if testo else ""
    return riga.split("; ", 1)[1] if " installato su " in riga.split("; ", 1)[0] and "; " in riga else riga


def dettaglio(cve_id, *, key="", asset=None):
    """Scheda breve di una CVE: pericolo, correzione, range vulnerabili e PC colpiti (prima quelli del contesto)."""
    record = SecurityCveRecord.objects.filter(cve_id=cve_id).first()
    if record is None:
        return None
    impatti = list(record.impacts.filter(outcome__in=ESITI).select_related("installation", "hub_asset").order_by("outcome", "host"))
    tono, etichetta = gravita(record)
    patch = _patch({record.cve_id}, {i.host for i in impatti})
    pc = [{
        "host": i.host,
        "asset": i.hub_asset,
        "versione": i.installation.version_raw if i.installation_id else "",
        "esito": i.outcome,
        "aperta_dal": i.aperta_dal,
        "spiegazione": _perche(i.explanation),
        "questo": bool(asset is not None and i.hub_asset_id == asset.pk),
        "patch": patch.get((record.cve_id, i.host)),
        "defender": None,
    } for i in impatti]
    from security.services import defender_vuln

    try:
        defender = defender_vuln.confronto_cve(record.cve_id, {i.host for i in impatti if i.outcome == SecurityCveImpact.IMPACTS})
    except Exception:  # noqa: BLE001
        defender = None
    if defender:
        for r in pc:
            r["defender"] = r["host"] in defender["defender"]
    prio, prio_label, prio_motivo = priorita(record)
    pc.sort(key=lambda r: (not r["questo"], r["esito"] != SecurityCveImpact.IMPACTS, r["host"].lower()))
    ranges = []
    for c in record.configurations or []:
        testo = f"{c.get('vendor', '')}:{c.get('product', '')} {_range_text(c)}".strip()
        if c.get("requires_platform"):
            testo += " (solo su piattaforma specifica)"
        if testo not in ranges:
            ranges.append(testo)
    return {
        "record": record,
        "tono": tono,
        "gravita": etichetta,
        "correzione": correzione(record),
        "ranges": ranges[:8],
        "ranges_altri": max(len(ranges) - 8, 0),
        "pc": pc[:30],
        "pc_altri": max(len(pc) - 30, 0),
        "colpiti": sum(1 for r in pc if r["esito"] == SecurityCveImpact.IMPACTS),
        "da_verificare": sum(1 for r in pc if r["esito"] != SecurityCveImpact.IMPACTS),
        "nvd_url": NVD_URL.format(record.cve_id),
        "priorita": prio,
        "priorita_label": prio_label,
        "priorita_motivo": prio_motivo,
        "pc_con_patch": sum(1 for r in pc if r["patch"]),
        "defender": defender,
        **_conta_risolte(_risolte(record.risoluzioni.all())),
    }
