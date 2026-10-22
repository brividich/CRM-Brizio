"""Pannello laterale delle CVE: per un programma dell'inventario, per un PC (asset) e per una CVE.

Legge solo i calcoli d'impatto già fatti (``SecurityCveImpact``), mai l'NVD in diretta.
Esiti mostrati: «Colpisce» (versione nel range, CPE confermato) e «Da verificare»;
«Non impatta» non entra nel pannello. Le CVE sono in ordine di pericolo:
sfruttate attivamente (CISA KEV), poi CVSS, poi le più recenti.
"""
from __future__ import annotations

from collections import defaultdict

from security.models import SecurityCveImpact, SecurityCveRecord
from security.services import software_catalog as sc
from security.services.cve_impact import _range_text

ESITI = (SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY)
NVD_URL = "https://nvd.nist.gov/vuln/detail/{}"


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


def _ordine(riga):
    rec = riga["record"]
    return (riga["esito"] != SecurityCveImpact.IMPACTS, not rec.kev, -(rec.cvss if rec.cvss is not None else -1), rec.cve_id)


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
    out = []
    for cve_pk, g in per_cve.items():
        rec = records[cve_pk]
        tono, etichetta = gravita(rec)
        out.append({
            "record": rec,
            "esito": SecurityCveImpact.IMPACTS if g["colpiti"] else SecurityCveImpact.TO_VERIFY,
            "pc": len(g["colpiti"]),
            "pc_da_verificare": len(g["da_verificare"] - g["colpiti"]),
            "versioni": sorted(g["versioni"]),
            "tono": tono,
            "gravita": etichetta,
            "correzione": correzione(rec),
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
    }


def _impatti_programma(key):
    pairs = {sc.split_key(k) for k in sc.member_keys(key)}
    qs = SecurityCveImpact.objects.filter(
        outcome__in=ESITI, installation__still_detected=True,
        installation__vendor__in={v for v, _p in pairs}, installation__product__in={p for _v, p in pairs},
    ).select_related("cve", "installation")
    return [i for i in qs if (i.installation.vendor, i.installation.product) in pairs]


def per_programma(key):
    """CVE del programma (tutti i nomi che lo formano) sui PC che lo hanno oggi."""
    return _riepilogo(_righe(_impatti_programma(key)))


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
    return {"software": software, "colpiscono": len(tutte["colpiscono"]), "da_verificare": len(tutte["da_verificare"]),
            "gravi": tutte["gravi"], "kev": tutte["kev"]}


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
    pc = [{
        "host": i.host,
        "asset": i.hub_asset,
        "versione": i.installation.version_raw if i.installation_id else "",
        "esito": i.outcome,
        "spiegazione": _perche(i.explanation),
        "questo": bool(asset is not None and i.hub_asset_id == asset.pk),
    } for i in impatti]
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
    }
