"""Tempi di installazione delle patch WatchGuard (ISO/IEC 27001:2022, controllo 8.8).

Ogni patch mancante su un PC (``WatchGuardPatch`` con ``presente=True``) ha un termine che parte da
«pubblicata il» (``rilasciata_il``, la data del produttore) e dipende dalla **classe** della patch:

- ``kev``: corregge almeno una CVE sfruttata attivamente (CISA KEV);
- ``critica`` / ``importante``: la criticità che dà WatchGuard (201 / 202);
- ``altre``: moderata, bassa, service pack, non specificata.

I giorni sono in Impostazioni › «Patch: tempi di installazione». Una patch senza data di pubblicazione
non ha termine. «Ferma» è una patch mancante oltre il termine o con l'ultima installazione fallita.

Il tempo di installazione di una patch chiusa è da «pubblicata il» a «chiusa il»; le patch sparite
perché il PC è uscito da WatchGuard (``patch_storico.motivo == "pc_uscito"``) non contano: non sono
installazioni. Ogni numero delle pagine (Tempi delle patch, report periodico, Conformità ISO, scheda
asset) si calcola qui.

Oltre il termine, se acceso, nasce un evento ``patch_sla_scaduta`` (una volta per patch e termine)
che il motore regole trasforma in alert; quando la patch non manca più su nessun PC oltre il termine,
l'alert si chiude da solo. Ogni passo è nell'audit sigillato (``traccia``).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from statistics import median

from django.db.models import Q
from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityCveRecord,
    SecurityEventRecord,
    Severity,
    WatchGuardDispositivo,
    WatchGuardPatch,
    WatchGuardPatchGiorno,
)
from security.services import patch_storico, soc_settings, traccia
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

EVENT_SLA = "patch_sla_scaduta"
RULE_RIENTRO = "patch_sla_rientrata"
SOURCE_NAME = "Patch WatchGuard (tempi di installazione)"

KEV, CRITICA, IMPORTANTE, ALTRE = "kev", "critica", "importante", "altre"
CLASSI = (KEV, CRITICA, IMPORTANTE, ALTRE)
ETICHETTE = {KEV: "Corregge una CVE sfruttata (KEV)", CRITICA: "Critica", IMPORTANTE: "Importante", ALTRE: "Moderata e altre"}
_CHIAVI = {KEV: "patch.sla.kev_giorni", CRITICA: "patch.sla.critica_giorni", IMPORTANTE: "patch.sla.importante_giorni",
           ALTRE: "patch.sla.altre_giorni"}
FILTRI_CLASSE = {"": "Tutte", **ETICHETTE}
FILTRI_STATO = {"": "Oltre il termine o installazione fallita", "scadute": "Solo oltre il termine",
                "errori": "Solo installazione fallita"}
SETTIMANE = 26
RIGHE_MAX = 300


def giorni_termini() -> dict:
    return {cls: soc_settings.value(_CHIAVI[cls]) for cls in CLASSI}


def kev_di(patch_rows) -> set:
    """CVE KEV fra quelle corrette dalle patch date (una query)."""
    tutte = {c for p in patch_rows for c in p.cve_lista}
    if not tutte:
        return set()
    return set(SecurityCveRecord.objects.filter(kev=True, cve_id__in=tutte).values_list("cve_id", flat=True))


def classe(p: WatchGuardPatch, kev: set) -> str:
    if kev and any(c in kev for c in p.cve_lista):
        return KEV
    if p.criticita == 201:
        return CRITICA
    if p.criticita == 202:
        return IMPORTANTE
    return ALTRE


def _giorno(valore) -> date:
    if isinstance(valore, datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore


def scadenza(p: WatchGuardPatch, cls: str, termini: dict) -> date | None:
    """Termine di installazione: «pubblicata il» + i giorni della classe; ``None`` senza data di pubblicazione."""
    if not p.rilasciata_il:
        return None
    return p.rilasciata_il + timedelta(days=termini[cls])


def giorni_installazione(p: WatchGuardPatch) -> int | None:
    """Giorni da «pubblicata il» a «chiusa il» (mai negativi); ``None`` se manca una delle due date."""
    if not (p.rilasciata_il and p.chiusa_il):
        return None
    return max((_giorno(p.chiusa_il) - p.rilasciata_il).days, 0)


def stato(p: WatchGuardPatch, kev: set, termini: dict, oggi: date) -> dict:
    cls = classe(p, kev)
    termine = scadenza(p, cls, termini)
    ritardo = (oggi - termine).days if termine else 0
    return {"p": p, "classe": cls, "etichetta": ETICHETTE[cls], "giorni": termini[cls], "scadenza": termine,
            "giorni_ritardo": max(ritardo, 0), "giorni_restanti": max(-ritardo, 0) if termine else None,
            "scaduta": ritardo > 0, "errore": p.esito_errore, "kev": sorted(c for c in p.cve_lista if c in kev)}


def mancanti(oggi=None, qs=None) -> list[dict]:
    """Le patch mancanti adesso (una riga per patch e PC) con classe, termine e ritardo."""
    oggi = oggi or timezone.localdate()
    righe = list((qs if qs is not None else WatchGuardPatch.objects.filter(presente=True)).select_related("hub_asset"))
    kev, termini = kev_di(righe), giorni_termini()
    return [stato(p, kev, termini, oggi) for p in righe]


def _chiave(p) -> tuple:
    return (p.nome, p.programma)


def ferme(oggi=None, classe_filtro="", stato_filtro="", q="") -> dict:
    """Patch ferme raggruppate per patch: PC oltre il termine e PC con l'installazione fallita."""
    oggi = oggi or timezone.localdate()
    classe_filtro = classe_filtro if classe_filtro in FILTRI_CLASSE else ""
    stato_filtro = stato_filtro if stato_filtro in FILTRI_STATO else ""
    qs = WatchGuardPatch.objects.filter(presente=True)
    testo = (q or "").strip()
    if testo:
        qs = qs.filter(Q(host__icontains=testo) | Q(host_display__icontains=testo) | Q(nome__icontains=testo)
                       | Q(programma__icontains=testo) | Q(cve__icontains=testo.upper()))
    voci = mancanti(oggi, qs)
    gruppi = {}
    for v in voci:
        if not (v["scaduta"] or v["errore"]):
            continue
        if stato_filtro == "scadute" and not v["scaduta"]:
            continue
        if stato_filtro == "errori" and not v["errore"]:
            continue
        if classe_filtro and v["classe"] != classe_filtro:
            continue
        p = v["p"]
        g = gruppi.setdefault(_chiave(p), {
            "nome": p.nome, "programma": p.programma, "criticita_label": p.criticita_label, "rilasciata_il": p.rilasciata_il,
            "classe": v["classe"], "etichetta": v["etichetta"], "giorni": v["giorni"], "scadenza": v["scadenza"],
            "giorni_ritardo": 0, "cve": set(), "kev": set(), "pc": [], "scadute": 0, "errori": 0,
        })
        g["pc"].append(v)
        g["cve"].update(p.cve_lista)
        g["kev"].update(v["kev"])
        g["scadute"] += int(v["scaduta"])
        g["errori"] += int(v["errore"])
        g["giorni_ritardo"] = max(g["giorni_ritardo"], v["giorni_ritardo"])
    righe = sorted(gruppi.values(), key=lambda g: (CLASSI.index(g["classe"]), -g["giorni_ritardo"], -len(g["pc"]), g["nome"]))
    for g in righe:
        g["cve"], g["kev"] = sorted(g["cve"]), sorted(g["kev"])
        g["pc"].sort(key=lambda v: (not v["errore"], v["p"].host))
    return {
        "classe": classe_filtro, "classi_scelte": list(FILTRI_CLASSE.items()),
        "stato": stato_filtro, "stati_scelte": list(FILTRI_STATO.items()), "q": testo,
        "righe": righe, "righe_mostrate": righe[:RIGHE_MAX], "righe_max": RIGHE_MAX,
        "kpi": {
            "patch": len(righe),
            "pc": len({v["p"].host for g in righe for v in g["pc"]}),
            "scadute": sum(g["scadute"] for g in righe),
            "errori": sum(g["errori"] for g in righe),
            "kev": sum(1 for g in righe if g["kev"]),
        },
    }


def _aware(valore, fine=False):
    if isinstance(valore, datetime):
        return valore if timezone.is_aware(valore) else timezone.make_aware(valore)
    return timezone.make_aware(datetime.combine(valore, time.max if fine else time.min))


def installazioni(dal, al) -> list[WatchGuardPatch]:
    """Patch chiuse nel periodo che contano come installazioni (non quelle sparite col PC)."""
    presenti = set(WatchGuardDispositivo.objects.filter(presente=True).values_list("device_id", flat=True))
    qs = WatchGuardPatch.objects.filter(presente=False, chiusa_il__range=(_aware(dal), _aware(al, fine=True)))
    return [p for p in qs if patch_storico.motivo(p, presenti) != "pc_uscito"]


def tempi(dal, al, oggi=None) -> dict:
    """Per classe: installate nel periodo, giorni medi e mediani, in tempo / in ritardo; mancanti e oltre il termine adesso."""
    oggi = oggi or timezone.localdate()
    termini = giorni_termini()
    chiuse = installazioni(dal, al)
    aperte = mancanti(oggi)
    kev = kev_di(chiuse)
    righe = {cls: {"classe": cls, "etichetta": ETICHETTE[cls], "termine_giorni": termini[cls], "installate": 0,
                   "giorni": [], "in_tempo": 0, "in_ritardo": 0, "mancanti": 0, "oltre_termine": 0} for cls in CLASSI}
    senza_data = 0
    for p in chiuse:
        g = giorni_installazione(p)
        if g is None:
            senza_data += 1
            continue
        r = righe[classe(p, kev)]
        r["installate"] += 1
        r["giorni"].append(g)
        if g <= termini[r["classe"]]:
            r["in_tempo"] += 1
        else:
            r["in_ritardo"] += 1
    for v in aperte:
        righe[v["classe"]]["mancanti"] += 1
        righe[v["classe"]]["oltre_termine"] += int(v["scaduta"])
    classi = []
    for cls in CLASSI:
        r = righe[cls]
        valori = r.pop("giorni")
        r["giorni_medi"] = round(sum(valori) / len(valori)) if valori else None
        r["giorni_mediana"] = round(median(valori)) if valori else None
        r["in_tempo_pct"] = round(100 * r["in_tempo"] / r["installate"]) if r["installate"] else None
        classi.append(r)
    tutti = [g for p in chiuse if (g := giorni_installazione(p)) is not None]
    installate = sum(r["installate"] for r in classi)
    in_tempo = sum(r["in_tempo"] for r in classi)
    return {
        "dal": _giorno(dal), "al": _giorno(al), "classi": classi,
        "installate": installate, "in_tempo": in_tempo, "in_ritardo": installate - in_tempo,
        "in_tempo_pct": round(100 * in_tempo / installate) if installate else None,
        "giorni_medi": round(sum(tutti) / len(tutti)) if tutti else None,
        "senza_data": senza_data,
        "mancanti": len(aperte), "oltre_termine": sum(1 for v in aperte if v["scaduta"]),
        "oltre_termine_gravi": sum(1 for v in aperte if v["scaduta"] and v["classe"] in (KEV, CRITICA)),
        "errori": sum(1 for v in aperte if v["errore"]),
    }


# --- Andamento ---------------------------------------------------------------------------------

def registra_giorno(now=None) -> WatchGuardPatchGiorno:
    """Fotografia delle patch mancanti di oggi (chiamata dopo ogni lettura delle patch: l'ultima del giorno vince)."""
    now = now or timezone.now()
    voci = mancanti(_giorno(now))
    obj, _ = WatchGuardPatchGiorno.objects.update_or_create(giorno=_giorno(now), defaults={
        "mancanti": len(voci), "pc": len({v["p"].host for v in voci}),
        "critiche": sum(1 for v in voci if v["p"].criticita == 201), "kev": sum(1 for v in voci if v["kev"]),
        "oltre_termine": sum(1 for v in voci if v["scaduta"]), "letto_il": now,
    })
    return obj


def _barre(valori: list, larghezza=720, altezza=150, sinistra=34, alto=14, destra=18) -> dict:
    """Geometria di un grafico a barre SVG (stesso disegno del grafico VPN): una barra per valore, ``None`` = senza dato."""
    picco = max([v for v in valori if v is not None] or [0]) or 1
    slot = (larghezza - sinistra - destra) / max(len(valori), 1)
    base = alto + altezza
    barre = []
    for i, v in enumerate(valori):
        h = round(altezza * (v or 0) / picco, 1)
        barre.append({"x": round(sinistra + i * slot + slot * 0.15, 1), "w": round(slot * 0.7, 1), "y": round(base - h, 1),
                      "h": h, "valore": v, "label_x": round(sinistra + i * slot + slot / 2, 1)})
    return {"barre": barre, "picco": picco, "width": larghezza, "height": base + 22, "baseline": base, "top": alto, "left": sinistra}


def andamento(settimane=SETTIMANE, oggi=None) -> dict:
    """Per settimana (lunedì-domenica, l'ultima è quella in corso): patch installate e patch mancanti a fine settimana.

    Le installate vengono da ``chiusa_il`` (stesso criterio di ``installazioni``); le mancanti dalla
    fotografia giornaliera più recente della settimana, che esiste solo da quando il servizio gira.
    """
    oggi = oggi or timezone.localdate()
    lunedi = oggi - timedelta(days=oggi.weekday())
    inizi = [lunedi - timedelta(weeks=i) for i in range(settimane - 1, -1, -1)]
    chiuse = installazioni(inizi[0], oggi)
    foto = {f.giorno: f for f in WatchGuardPatchGiorno.objects.filter(giorno__gte=inizi[0], giorno__lte=oggi)}
    righe = []
    for inizio in inizi:
        fine = inizio + timedelta(days=6)
        n = sum(1 for p in chiuse if inizio <= _giorno(p.chiusa_il) <= fine)
        giorni = [g for g in foto if inizio <= g <= fine]
        f = foto[max(giorni)] if giorni else None
        righe.append({"inizio": inizio, "fine": fine, "installate": n, "mancanti": f.mancanti if f else None,
                      "oltre_termine": f.oltre_termine if f else None, "foto_del": f.giorno if f else None})
    prima_foto = WatchGuardPatchGiorno.objects.order_by("giorno").values_list("giorno", flat=True).first()
    g_inst, g_manc = _barre([r["installate"] for r in righe]), _barre([r["mancanti"] for r in righe])
    for i, (r, bi, bm) in enumerate(zip(righe, g_inst["barre"], g_manc["barre"], strict=True)):
        r["bar_installate"], r["bar_mancanti"] = bi, bm
        r["etichetta"] = (len(righe) - i - 1) % 4 == 0  # una data ogni 4 settimane, l'ultima sempre
    return {"settimane": righe, "grafico_installate": g_inst, "grafico_mancanti": g_manc, "prima_foto": prima_foto,
            "installate_totale": sum(r["installate"] for r in righe)}


# --- Scheda asset ------------------------------------------------------------------------------

def per_asset(asset, oggi=None, giorni_storico=365) -> dict:
    """Patch di un PC: mancanti con il termine, installate nell'ultimo anno con le CVE corrette."""
    oggi = oggi or timezone.localdate()
    from security.services.patch_kb import comprese

    aperte = mancanti(oggi, WatchGuardPatch.objects.filter(hub_asset=asset, presente=True))
    incluse = comprese([v["p"] for v in aperte])
    for v in aperte:
        v["compresa"] = incluse.get(v["p"].pk)
    aperte.sort(key=lambda v: (bool(v["compresa"]), not v["errore"], not v["scaduta"], CLASSI.index(v["classe"]), v["p"].nome))
    presenti = set(WatchGuardDispositivo.objects.filter(presente=True).values_list("device_id", flat=True))
    chiuse = list(WatchGuardPatch.objects.filter(hub_asset=asset, presente=False, chiusa_il__gte=timezone.now() - timedelta(days=giorni_storico))
                  .order_by("-chiusa_il", "nome"))
    kev = kev_di(chiuse)
    storico = []
    for p in chiuse:
        m = patch_storico.motivo(p, presenti)
        storico.append({"p": p, "motivo": m, "motivo_label": patch_storico.MOTIVI[m], "cve": p.cve_lista,
                        "kev": [c for c in p.cve_lista if c in kev], "giorni": giorni_installazione(p)})
    host = (aperte[0]["p"].host if aperte else chiuse[0].host if chiuse else "")
    return {
        "aperte": aperte, "storico": storico, "host": host, "giorni_storico": giorni_storico,
        "oltre_termine": sum(1 for v in aperte if v["scaduta"]), "errori": sum(1 for v in aperte if v["errore"]),
        "cve_corrette": len({c for r in storico for c in r["cve"]}),
    }


# --- Automatismo: evento oltre il termine, chiusura al rientro -------------------------------

def patch_source():
    from security.models import SecuritySource, SourceType

    source, _ = SecuritySource.objects.get_or_create(
        name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "watchguard"},
    )
    return source


def _dedup(source, g):
    return make_hash(source.pk, EVENT_SLA, g["nome"], g["programma"], g["scadenza"].isoformat())


def _gruppi_scaduti(oggi):
    return [g for g in ferme(oggi, stato_filtro="scadute")["righe"] if g["scadenza"]]


def segnala_scadute(oggi=None):
    """Un evento ``patch_sla_scaduta`` per ogni patch mancante oltre il termine (una volta per patch e termine).

    Torna ``(eventi creati, alert chiusi perché rientrati)``. Spento di default (``patch.sla.attivo``):
    la pagina Tempi delle patch mostra comunque tutto.
    """
    if not soc_settings.value("patch.sla.attivo"):
        return 0, 0
    oggi = oggi or timezone.localdate()
    source = patch_source()
    gruppi = _gruppi_scaduti(oggi)
    creati = 0
    for g in gruppi:
        dedup = _dedup(source, g)
        if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_SLA, dedup_hash=dedup).exists():
            continue
        hosts = sorted({v["p"].host_display or v["p"].host for v in g["pc"] if v["scaduta"]})
        payload = {
            "patch": g["nome"], "programma": g["programma"], "classe": g["classe"], "etichetta": g["etichetta"],
            "pubblicata_il": g["rilasciata_il"].isoformat(), "scadenza": g["scadenza"].isoformat(),
            "giorni_termine": g["giorni"], "giorni_ritardo": g["giorni_ritardo"], "pc": len(hosts), "host": hosts[:30],
            "cve": g["cve"][:30], "kev": g["kev"][:30], "alert_candidate": True,
        }
        severity = Severity.HIGH if g["classe"] in (KEV, CRITICA) else Severity.MEDIUM
        event = SecurityEventRecord.objects.create(
            source=source, event_type=EVENT_SLA, severity=severity, occurred_at=timezone.now(),
            fingerprint=dedup, dedup_hash=dedup, payload=payload,
        )
        traccia.registra(traccia.PATCH_TERMINE_SCADUTO, {
            "patch": g["nome"], "programma": g["programma"], "classe": g["classe"], "scadenza": g["scadenza"],
            "giorni_ritardo": g["giorni_ritardo"], "pc": len(hosts), "evento_id": event.pk, "regola": EVENT_SLA,
        })
        creati += 1
    return creati, chiudi_rientrate(gruppi, source)


def chiudi_rientrate(gruppi_scaduti=None, source=None, oggi=None):
    """Chiude gli alert «patch oltre il termine» la cui patch non manca più oltre il termine su nessun PC."""
    from security.services.auto_resolution import resolve_alert

    source = source or patch_source()
    gruppi = _gruppi_scaduti(oggi or timezone.localdate()) if gruppi_scaduti is None else gruppi_scaduti
    ancora = {_dedup(source, g) for g in gruppi}
    chiusi = 0
    alerts = SecurityAlert.objects.filter(source=source, status__in=ACTIVE_ALERT_STATUSES, event__event_type=EVENT_SLA).select_related("event")
    for alert in alerts:
        if alert.dedup_hash in ancora:
            continue
        payload = (alert.event.payload or {}) if alert.event_id else {}
        reason = f"{payload.get('patch')}: non manca più oltre il termine su nessun PC (installata o non più segnalata da WatchGuard)."
        resolve_alert(alert, reason[:500], rule_code=RULE_RIENTRO)
        traccia.registra(traccia.PATCH_TERMINE_RIENTRATO, {
            "patch": payload.get("patch"), "alert_id": alert.pk, "motivo": reason, "regola": RULE_RIENTRO,
        }, oggetto=alert)
        chiusi += 1
    return chiusi


def titolo_evento(payload):
    pc = payload.get("pc") or 0
    return (f"Patch oltre il termine: {payload.get('patch')} manca su {pc} PC, classe "
            f"{str(payload.get('etichetta') or '').lower()}, {payload.get('giorni_ritardo')} giorni di ritardo")[:255]
