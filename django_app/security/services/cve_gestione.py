"""Gestione delle CVE: l'elenco delle CVE aperte con tutto quello che serve per decidere,
e il registro delle correzioni (PC usciti da una CVE perché il programma è stato aggiornato
o disinstallato).

Solo letture: i dati li scrive il ricalcolo degli impatti (``cve_impact.recompute``) in
``SecurityCveImpact`` e ``SecurityCveRisoluzione``. Il termine di correzione è quello di
``cve_sla`` (ISO 27001 8.8).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from security.models import SecurityCveImpact, SecurityCveRecord, SecurityCveRisoluzione
from security.services import cve_sla

logger = logging.getLogger(__name__)

PERIODI = {"30": 30, "90": 90, "365": 365, "tutto": None}
PERIODO_DEFAULT = "90"

COME_FILTRI = {
    "correzioni": ("Corrette (aggiornate o disinstallate)", SecurityCveRisoluzione.CORREZIONI),
    SecurityCveRisoluzione.AGGIORNATO: ("Programma aggiornato", (SecurityCveRisoluzione.AGGIORNATO,)),
    SecurityCveRisoluzione.RIMOSSO: ("Programma disinstallato", (SecurityCveRisoluzione.RIMOSSO,)),
    "altro": ("PC uscito per altro motivo", (SecurityCveRisoluzione.PC_ASSENTE, SecurityCveRisoluzione.RIVALUTATA)),
    "tutte": ("Tutte le uscite", None),
}
COME_DEFAULT = "correzioni"

STATI_TERMINE = {
    "": "Tutti",
    "scaduta": "Oltre il termine",
    "in_scadenza": "In scadenza (7 giorni)",
    "accettata": "Con rischio accettato",
}
GIORNI_IN_SCADENZA = 7
ESITI = {"": "Impatta o da verificare", "impatta": "Impatta", "da_verificare": "Solo da verificare"}
MAX_RIGHE = 500


def _accettazioni():
    try:
        from security.services import accettazione_rischio

        return accettazione_rischio, accettazione_rischio.attive(timezone.localdate())
    except Exception:  # noqa: BLE001 - senza accettazioni l'elenco resta valido
        logger.exception("CVE: accettazioni del rischio non leggibili")
        return None, []


def _programma(inst):
    if inst is None:
        return ""
    nome = (inst.product_raw or inst.product or "").strip()
    return f"{nome} {inst.version_raw}".strip() if inst.version_raw else nome


# ── Elenco delle CVE aperte ────────────────────────────────────────────────────

def elenco_cve(q="", classe="", solo_kev=False, termine="", esito="", oggi=None) -> dict:
    """CVE che impattano o da verificare, una riga per CVE con programmi, termine e correzioni."""
    oggi = oggi or timezone.localdate()
    records = (
        SecurityCveRecord.objects.annotate(
            impacted=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.IMPACTS)),
            to_verify=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.TO_VERIFY)),
        )
        .filter(Q(impacted__gt=0) | Q(to_verify__gt=0))
        .order_by("-kev", "-cvss", "-epss", "-impacted", "cve_id")
    )
    if solo_kev:
        records = records.filter(kev=True)
    if esito == "impatta":
        records = records.filter(impacted__gt=0)
    elif esito == "da_verificare":
        records = records.filter(impacted=0)
    records = list(records)
    per_id = {r.pk: r for r in records}

    impatti = defaultdict(list)
    for imp in (SecurityCveImpact.objects.filter(cve_id__in=list(per_id))
                .exclude(outcome=SecurityCveImpact.NOT_IMPACTED).select_related("installation")):
        impatti[imp.cve_id].append(imp)

    dal = timezone.now() - timedelta(days=90)
    corrette = dict(
        SecurityCveRisoluzione.objects.filter(cve_id__in=list(per_id), come__in=SecurityCveRisoluzione.CORREZIONI,
                                              risolta_il__gte=dal)
        .values("cve_id").order_by().annotate(n=Count("host", distinct=True)).values_list("cve_id", "n")
    )
    modulo_acc, coperture = _accettazioni()

    testo = (q or "").strip().lower()
    righe = []
    for rec in records:
        voci = impatti.get(rec.pk, [])
        programmi = sorted({p for p in (_programma(i.installation) for i in voci) if p})
        if testo and testo not in rec.cve_id.lower() and testo not in (rec.description or "").lower() \
                and not any(testo in p.lower() for p in programmi) and not any(testo in i.host.lower() for i in voci):
            continue
        info_classe = cve_sla.classe(rec)
        if classe and info_classe != classe:
            continue
        esposti = [i for i in voci if i.outcome == SecurityCveImpact.IMPACTS]
        oltre = accettati = in_scadenza = 0
        prima = None
        for imp in esposti:
            aperta = imp.aperta_dal or imp.computed_at
            acc = modulo_acc.copre(coperture, rec.cve_id, imp.host) if modulo_acc else None
            st = cve_sla.stato(rec, aperta, oggi, acc)
            if acc:
                accettati += 1
            elif st["scaduta"]:
                oltre += 1
            elif st["giorni_restanti"] <= GIORNI_IN_SCADENZA:
                in_scadenza += 1
            if aperta and (prima is None or aperta < prima):
                prima = aperta
        termine_cve = cve_sla.stato(rec, prima, oggi) if prima else None
        if termine == "scaduta" and not oltre:
            continue
        if termine == "in_scadenza" and not in_scadenza:
            continue
        if termine == "accettata" and not accettati:
            continue
        righe.append({
            "record": rec,
            "cve_id": rec.cve_id,
            "classe": info_classe,
            "classe_label": cve_sla.ETICHETTE[info_classe],
            "programmi": programmi,
            "impatta": rec.impacted,
            "da_verificare": rec.to_verify,
            "esposta_dal": prima,
            "termine": termine_cve,
            "pc_oltre": oltre,
            "pc_in_scadenza": in_scadenza,
            "pc_accettati": accettati,
            "corretti_90": corrette.get(rec.pk, 0),
        })
        if len(righe) >= MAX_RIGHE:
            break

    return {
        "righe": righe,
        "troncato": len(righe) >= MAX_RIGHE,
        "totali": {
            "cve": len(righe),
            "kev": sum(1 for r in righe if r["record"].kev),
            "pc_esposti": len({i.host for r in righe for i in impatti.get(r["record"].pk, [])
                               if i.outcome == SecurityCveImpact.IMPACTS}),
            "oltre": sum(1 for r in righe if r["pc_oltre"]),
            "corretti_90": sum(r["corretti_90"] for r in righe),
        },
        "classi": [(c, cve_sla.ETICHETTE[c]) for c in cve_sla.CLASSI],
        "termini": STATI_TERMINE,
        "esiti": ESITI,
    }


# ── Registro delle correzioni ──────────────────────────────────────────────────

def correzioni(periodo=PERIODO_DEFAULT, come=COME_DEFAULT, q="", oggi=None) -> dict:
    """PC usciti da una CVE nel periodo, con versione prima/dopo, giorni e termine, e riepilogo per CVE."""
    oggi = oggi or timezone.localdate()
    periodo = periodo if periodo in PERIODI else PERIODO_DEFAULT
    come = come if come in COME_FILTRI else COME_DEFAULT
    qs = SecurityCveRisoluzione.objects.select_related("cve", "hub_asset")
    giorni = PERIODI[periodo]
    if giorni:
        qs = qs.filter(risolta_il__gte=timezone.now() - timedelta(days=giorni))
    valori = COME_FILTRI[come][1]
    if valori:
        qs = qs.filter(come__in=valori)
    testo = (q or "").strip()
    if testo:
        qs = qs.filter(Q(cve__cve_id__icontains=testo) | Q(host__icontains=testo) | Q(host_display__icontains=testo)
                       | Q(software__icontains=testo))

    # Una riga per CVE + PC: l'ultima uscita (un PC può uscire, rientrare e riuscire).
    visti = set()
    righe = []
    for r in qs.order_by("-risolta_il", "cve__cve_id", "host"):
        chiave = (r.cve_id, r.host.lower())
        if chiave in visti:
            continue
        visti.add(chiave)
        giorni_aperta = None
        nel_termine = None
        if r.aperta_dal:
            giorni_aperta = max((r.risolta_il - r.aperta_dal).days, 0)
            if r.come in SecurityCveRisoluzione.CORREZIONI:
                nel_termine = timezone.localtime(r.risolta_il).date() <= cve_sla.scadenza(r.cve, r.aperta_dal)
        righe.append({
            "r": r,
            "cve_id": r.cve.cve_id,
            "classe_label": cve_sla.ETICHETTE[cve_sla.classe(r.cve)],
            "correzione": r.come in SecurityCveRisoluzione.CORREZIONI,
            "giorni": giorni_aperta,
            "nel_termine": nel_termine,
        })
        if len(righe) >= 2000:
            break

    # Stato attuale delle CVE toccate: chiusa del tutto o ancora aperta su altri PC.
    cve_ids = {x["r"].cve_id for x in righe}
    ancora = dict(
        SecurityCveImpact.objects.filter(cve_id__in=cve_ids, outcome=SecurityCveImpact.IMPACTS)
        .values("cve_id").order_by().annotate(n=Count("id")).values_list("cve_id", "n")
    )
    da_verif = dict(
        SecurityCveImpact.objects.filter(cve_id__in=cve_ids, outcome=SecurityCveImpact.TO_VERIFY)
        .values("cve_id").order_by().annotate(n=Count("id")).values_list("cve_id", "n")
    )
    per_cve = {}
    for x in righe:
        r = x["r"]
        g = per_cve.setdefault(r.cve_id, {
            "record": r.cve, "cve_id": x["cve_id"], "classe_label": x["classe_label"], "corretti": 0, "aggiornati": 0,
            "rimossi": 0, "altro": 0, "programmi": set(), "ultima": r.risolta_il,
            "ancora": ancora.get(r.cve_id, 0), "da_verificare": da_verif.get(r.cve_id, 0), "giorni": [],
        })
        if r.come == SecurityCveRisoluzione.AGGIORNATO:
            g["aggiornati"] += 1
        elif r.come == SecurityCveRisoluzione.RIMOSSO:
            g["rimossi"] += 1
        else:
            g["altro"] += 1
        if x["correzione"]:
            g["corretti"] += 1
            if x["giorni"] is not None:
                g["giorni"].append(x["giorni"])
        if r.software:
            g["programmi"].add(f"{r.software} {r.versione_prima} → {r.versione_dopo}".strip(" →")
                               if r.versione_dopo else f"{r.software} {r.versione_prima}".strip())
        g["ultima"] = max(g["ultima"], r.risolta_il)
    gruppi = []
    for g in per_cve.values():
        g["programmi"] = sorted(g["programmi"])[:4]
        g["giorni_medi"] = round(sum(g["giorni"]) / len(g["giorni"])) if g["giorni"] else None
        g["chiusa"] = not g["ancora"] and not g["da_verificare"]
        gruppi.append(g)
    gruppi.sort(key=lambda g: (g["chiusa"], -g["record"].kev, -(g["record"].cvss or 0), g["cve_id"]))

    corr = [x for x in righe if x["correzione"]]
    con_giorni = [x["giorni"] for x in corr if x["giorni"] is not None]
    valutate = [x for x in corr if x["nel_termine"] is not None]
    nel = sum(1 for x in valutate if x["nel_termine"])
    return {
        "righe": righe,
        "gruppi": gruppi,
        "periodo": periodo,
        "come": come,
        "q": testo,
        "periodi": [("30", "30 giorni"), ("90", "90 giorni"), ("365", "12 mesi"), ("tutto", "Tutto")],
        "come_scelte": [(k, v[0]) for k, v in COME_FILTRI.items()],
        "kpi": {
            "corretti": len(corr),
            "aggiornati": sum(1 for x in corr if x["r"].come == SecurityCveRisoluzione.AGGIORNATO),
            "rimossi": sum(1 for x in corr if x["r"].come == SecurityCveRisoluzione.RIMOSSO),
            "altro": sum(1 for x in righe if not x["correzione"]),
            "cve_chiuse": sum(1 for g in gruppi if g["chiusa"] and g["corretti"]),
            "cve_parziali": sum(1 for g in gruppi if not g["chiusa"]),
            "giorni_medi": round(sum(con_giorni) / len(con_giorni)) if con_giorni else None,
            "pct_termine": round(nel * 100 / len(valutate)) if valutate else None,
            "nel_termine": nel,
            "valutate": len(valutate),
        },
    }
