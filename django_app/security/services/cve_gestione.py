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

# Campi della CVE che servono a classe, termine e pagine. Le configurazioni NVD (JSON grande) e la
# descrizione non si caricano dove non si mostrano: in produzione erano la parte lenta delle pagine.
CAMPI_CVE = ("cve__cve_id", "cve__kev", "cve__kev_due", "cve__cvss", "cve__severity")

PERIODI = {"30": 30, "90": 90, "365": 365, "tutto": None}
PERIODO_DEFAULT = "90"

COME_FILTRI = {
    "correzioni": "Corrette (aggiornate o disinstallate)",
    SecurityCveRisoluzione.AGGIORNATO: "Programma aggiornato",
    SecurityCveRisoluzione.RIMOSSO: "Programma disinstallato",
    "altro": "Uscite senza correzione verificata",
    "tutte": "Tutte le uscite",
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
MAX_RIGHE_CORREZIONI = 2000


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


# ── Regola unica delle correzioni ─────────────────────────────────────────────
# Usata da questa pagina, dall'elenco CVE, dal riquadro «Dalla segnalazione alla correzione»
# (cve_chiusura.metriche), dai tempi di correzione (cve_sla.riepilogo) e quindi dalla conformità
# ISO 27001: lo stesso numero non può uscire diverso in due posti.

def ultime_uscite(qs) -> list:
    """L'ultima ``SecurityCveRisoluzione`` per CVE + PC del queryset (il PC può uscire, rientrare e riuscire)."""
    visti, out = set(), []
    for r in qs.order_by("-risolta_il", "cve_id", "host"):
        chiave = (r.cve_id, r.host.lower())
        if chiave not in visti:
            visti.add(chiave)
            out.append(r)
    return out


def esposti_oggi(cve_ids) -> set:
    """(cve_id, host in minuscolo) oggi impattati o da verificare."""
    if not cve_ids:
        return set()
    return {
        (cve_id, host.lower())
        for cve_id, host in SecurityCveImpact.objects.filter(cve_id__in=set(cve_ids))
        .exclude(outcome=SecurityCveImpact.NOT_IMPACTED).values_list("cve_id", "host")
    }


def correzioni_valide(dal, al=None) -> list:
    """PC corretti fra ``dal`` e ``al`` (datetime aware): ultima uscita del periodo per CVE + PC, programma
    aggiornato o disinstallato, PC oggi non di nuovo esposto alla stessa CVE."""
    qs = (SecurityCveRisoluzione.objects.filter(risolta_il__gte=dal).select_related("cve")
          .only("cve_id", "host", "come", "aperta_dal", "risolta_il", *CAMPI_CVE))
    if al is not None:
        qs = qs.filter(risolta_il__lte=al)
    ultime = ultime_uscite(qs)
    esposti = esposti_oggi({r.cve_id for r in ultime})
    return [r for r in ultime if r.come in SecurityCveRisoluzione.CORREZIONI and (r.cve_id, r.host.lower()) not in esposti]


# ── Elenco delle CVE aperte ────────────────────────────────────────────────────

@cve_sla.termini_fissati()
def elenco_cve(q="", classe="", solo_kev=False, termine="", esito="", oggi=None) -> dict:
    """CVE che impattano o da verificare, una riga per CVE con programmi, termine e correzioni."""
    oggi = oggi or timezone.localdate()
    records = (
        SecurityCveRecord.objects.annotate(
            impacted=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.IMPACTS)),
            to_verify=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.TO_VERIFY)),
        )
        .filter(Q(impacted__gt=0) | Q(to_verify__gt=0))
        .defer("configurations")
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
                .exclude(outcome=SecurityCveImpact.NOT_IMPACTED).select_related("installation")
                .only("cve_id", "host", "outcome", "aperta_dal", "computed_at",
                      "installation__product_raw", "installation__product", "installation__version_raw")):
        impatti[imp.cve_id].append(imp)

    corrette = defaultdict(int)
    for r in correzioni_valide(timezone.now() - timedelta(days=90)):
        if r.cve_id in per_id:
            corrette[r.cve_id] += 1
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

    # I totali contano tutte le righe che passano i filtri; la tabella ne mostra al massimo MAX_RIGHE.
    return {
        "righe": righe[:MAX_RIGHE],
        "troncato": len(righe) > MAX_RIGHE,
        "max_righe": MAX_RIGHE,
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

def _nel_filtro(come, come_riga, correzione) -> bool:
    """Filtro «Come» sull'ultima uscita: le correzioni valgono solo se il PC non è di nuovo esposto."""
    if come == "tutte":
        return True
    if come == "correzioni":
        return correzione
    if come == "altro":
        return not correzione
    return correzione and come_riga == come


@cve_sla.termini_fissati()
def correzioni(periodo=PERIODO_DEFAULT, come=COME_DEFAULT, q="", oggi=None) -> dict:
    """PC usciti da una CVE nel periodo, con versione prima/dopo, giorni e termine, e riepilogo per CVE.

    Regole, perché i numeri reggano a un audit:
    - per ogni CVE + PC conta solo l'**ultima** uscita del periodo (un PC può uscire, rientrare e
      riuscire); il filtro «Come» si applica dopo, sull'ultima uscita;
    - un PC che oggi è di nuovo impattato o da verificare per quella CVE è «di nuovo esposto» e
      non conta come corretto;
    - una CVE è «chiusa con gli aggiornamenti» solo se oggi non ha PC impattati né da verificare,
      almeno un PC è stato corretto e nessun PC è uscito perché sparito dall'inventario o è di nuovo
      esposto; le uscite «rivalutata» (il PC non era vulnerabile) non la impediscono. Altrimenti, senza
      PC esposti, è «nessun PC esposto».
    """
    oggi = oggi or timezone.localdate()
    periodo = periodo if periodo in PERIODI else PERIODO_DEFAULT
    come = come if come in COME_FILTRI else COME_DEFAULT
    qs = SecurityCveRisoluzione.objects.select_related("cve").defer("cve__configurations", "cve__description")
    giorni = PERIODI[periodo]
    if giorni:
        qs = qs.filter(risolta_il__gte=timezone.now() - timedelta(days=giorni))
    testo = (q or "").strip()
    if testo:
        qs = qs.filter(Q(cve__cve_id__icontains=testo) | Q(host__icontains=testo) | Q(host_display__icontains=testo)
                       | Q(software__icontains=testo))

    ultime = ultime_uscite(qs)
    cve_ids = {r.cve_id for r in ultime}
    riesposti = esposti_oggi(cve_ids)
    esposti_per_cve = defaultdict(lambda: {SecurityCveImpact.IMPACTS: 0, SecurityCveImpact.TO_VERIFY: 0})
    for cve_id, esito in (SecurityCveImpact.objects.filter(cve_id__in=cve_ids)
                          .exclude(outcome=SecurityCveImpact.NOT_IMPACTED).values_list("cve_id", "outcome")):
        esposti_per_cve[cve_id][esito] += 1

    righe = []
    per_cve = {}
    for r in ultime:
        di_nuovo = (r.cve_id, r.host.lower()) in riesposti
        correzione = r.come in SecurityCveRisoluzione.CORREZIONI and not di_nuovo
        giorni_aperta = nel_termine = None
        if r.aperta_dal:
            giorni_aperta = max((r.risolta_il - r.aperta_dal).days, 0)
            if correzione:
                nel_termine = timezone.localtime(r.risolta_il).date() <= cve_sla.scadenza(r.cve, r.aperta_dal)
        x = {
            "r": r, "cve_id": r.cve.cve_id, "classe_label": cve_sla.ETICHETTE[cve_sla.classe(r.cve)],
            "correzione": correzione, "di_nuovo": di_nuovo, "giorni": giorni_aperta, "nel_termine": nel_termine,
        }
        # Il riepilogo per CVE guarda tutte le ultime uscite, a prescindere dal filtro «Come»:
        # serve a dire se la CVE si è chiusa davvero con gli aggiornamenti.
        g = per_cve.setdefault(r.cve_id, {
            "record": r.cve, "cve_id": x["cve_id"], "classe_label": x["classe_label"], "corretti": 0,
            "aggiornati": 0, "rimossi": 0, "rivalutate": 0, "assenti": 0, "di_nuovo": 0, "programmi": set(), "ultima": r.risolta_il,
            "ancora": esposti_per_cve[r.cve_id][SecurityCveImpact.IMPACTS],
            "da_verificare": esposti_per_cve[r.cve_id][SecurityCveImpact.TO_VERIFY], "giorni": [], "nel_filtro": False,
        })
        if di_nuovo:
            g["di_nuovo"] += 1
        elif r.come == SecurityCveRisoluzione.AGGIORNATO:
            g["aggiornati"] += 1
        elif r.come == SecurityCveRisoluzione.RIMOSSO:
            g["rimossi"] += 1
        elif r.come == SecurityCveRisoluzione.RIVALUTATA:
            g["rivalutate"] += 1
        else:
            g["assenti"] += 1
        if correzione:
            g["corretti"] += 1
            if giorni_aperta is not None:
                g["giorni"].append(giorni_aperta)
            if r.software:
                g["programmi"].add(f"{r.software} {r.versione_prima} → {r.versione_dopo}" if r.versione_dopo
                                   else f"{r.software} {r.versione_prima} (disinstallato)")
        g["ultima"] = max(g["ultima"], r.risolta_il)
        if _nel_filtro(come, r.come, correzione):
            righe.append(x)
            g["nel_filtro"] = True

    gruppi = []
    for g in per_cve.values():
        if not g["nel_filtro"]:
            continue
        g["programmi"] = sorted(g["programmi"])
        g["giorni_medi"] = round(sum(g["giorni"]) / len(g["giorni"])) if g["giorni"] else None
        nessuno_esposto = not g["ancora"] and not g["da_verificare"]
        # «Rivalutata» è un dato (il PC non era vulnerabile, es. release di Windows non colpita): non toglie
        # la chiusura. Un PC sparito dall'inventario invece non dice niente: la CVE non è «corretta».
        g["stato"] = ("corretta" if nessuno_esposto and g["corretti"] and not g["assenti"] and not g["di_nuovo"]
                      else "nessuno_esposto" if nessuno_esposto else "aperta")
        gruppi.append(g)
    ordine = {"aperta": 0, "nessuno_esposto": 1, "corretta": 2}
    gruppi.sort(key=lambda g: (ordine[g["stato"]], -int(g["record"].kev), -(g["record"].cvss or 0), g["cve_id"]))

    corr = [x for x in righe if x["correzione"]]
    con_giorni = [x["giorni"] for x in corr if x["giorni"] is not None]
    valutate = [x for x in corr if x["nel_termine"] is not None]
    nel = sum(1 for x in valutate if x["nel_termine"])
    return {
        "righe": righe,
        "righe_mostrate": righe[:MAX_RIGHE_CORREZIONI],
        "troncato": len(righe) > MAX_RIGHE_CORREZIONI,
        "max_righe": MAX_RIGHE_CORREZIONI,
        "gruppi": gruppi,
        "periodo": periodo,
        "come": come,
        "q": testo,
        "periodi": [("30", "30 giorni"), ("90", "90 giorni"), ("365", "12 mesi"), ("tutto", "Tutto")],
        "come_scelte": list(COME_FILTRI.items()),
        "kpi": {
            "corretti": len(corr),
            "aggiornati": sum(1 for x in corr if x["r"].come == SecurityCveRisoluzione.AGGIORNATO),
            "rimossi": sum(1 for x in corr if x["r"].come == SecurityCveRisoluzione.RIMOSSO),
            "di_nuovo": sum(g["di_nuovo"] for g in per_cve.values()),
            "cve_corrette": sum(1 for g in gruppi if g["stato"] == "corretta"),
            "cve_nessuno_esposto": sum(1 for g in gruppi if g["stato"] == "nessuno_esposto"),
            "cve_aperte": sum(1 for g in gruppi if g["stato"] == "aperta"),
            "giorni_medi": round(sum(con_giorni) / len(con_giorni)) if con_giorni else None,
            "pct_termine": round(nel * 100 / len(valutate)) if valutate else None,
            "nel_termine": nel,
            "valutate": len(valutate),
        },
    }
