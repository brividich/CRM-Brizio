"""Indice di postura di un PC (0-100): una sola regola per la scheda del dispositivo e per la mappa dei PC.

Si parte da 100 e si toglie per backup, alert, CVE, protezione WatchGuard, problemi Intune, sistema operativo
e patch mancanti. È una sintesi dei fatti già nel SOC: non apre alert né cambia altri numeri.

I fatti si raccolgono con le stesse funzioni sia per un PC solo (``key``) sia per tutti: backup dalla
finestra della pagina Backup (``metriche.backup_dispositivi``, 90 giorni come ``device_detail``), CVE uniche
(``pc_overview.cve_uniche``), alert aperti per nome host, dispositivo WatchGuard e patch presenti.
"""
from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

CACHE_MAPPA = "security:postura:mappa:v1"
CACHE_SECONDI = 600
GIORNI_WG_VECCHIO = 7


def norm(host):
    from security.services.pc_copertura import norm as _norm

    return _norm(host)


# --- Fatti ------------------------------------------------------------------------------

def stato_backup(dev):
    """«fallito», «vecchio», «assente» o «ok» da una riga di dispositivo della pagina Backup (o ``device_detail``)."""
    from security.services.backup_center import FAIL

    if not dev:
        return "assente"
    if dev["last_status"] == FAIL:
        return "fallito"
    return "vecchio" if dev["stale"] else "ok"


def stato_wg(dev, now=None):
    """(stato, etichetta protezione): «senza_agente», «non_protetto», «vecchio» o «ok»."""
    if dev is None or not dev.gestito:
        return "senza_agente", ""
    if not dev.protetto:
        return "non_protetto", dev.protezione_label
    now = now or timezone.now()
    if dev.ultima_connessione and dev.ultima_connessione < now - timedelta(days=GIORNI_WG_VECCHIO):
        return "vecchio", dev.protezione_label
    return "ok", dev.protezione_label


def alert_per_pc(key=None):
    """{nome normalizzato: (critici, totale)} degli alert aperti, dal nome host del dispositivo dell'evento."""
    from security.models import SecurityAlert
    from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

    qs = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__asset__isnull=False)
    if key:
        qs = qs.filter(event__asset__hostname__istartswith=key)
    out = {}
    for host, sev in qs.values_list("event__asset__hostname", "severity").iterator():
        k = norm(host)
        if not k or (key and k != key):
            continue
        crit, tot = out.get(k, (0, 0))
        out[k] = (crit + (sev == "critical"), tot + 1)
    return out


def wg_per_pc(key=None):
    """{nome normalizzato: WatchGuardDispositivo}: tra più righe vince il gestito con la connessione più recente."""
    from security.models import WatchGuardDispositivo

    qs = WatchGuardDispositivo.objects.filter(presente=True)
    if key:
        qs = qs.filter(host=key)
    out = {}
    for d in qs.order_by("gestito", "ultima_connessione"):  # l'ultimo scritto è il migliore
        out[d.host] = d
    return out


def patch_per_pc(key=None):
    """{nome normalizzato: (critiche, totale)} delle patch WatchGuard ancora da installare."""
    from security.models import WatchGuardPatch

    qs = WatchGuardPatch.objects.filter(presente=True)
    if key:
        qs = qs.filter(host=key)
    out = {}
    for host, crit in qs.values_list("host", "criticita").iterator():
        c, t = out.get(host, (0, 0))
        out[host] = (c + (crit == 201), t + 1)
    return out


# --- Regola -------------------------------------------------------------------------------

def punteggio(f):
    """Indice e motivi da un dizionario di fatti. Ogni motivo dice quale sezione della scheda lo spiega.

    Chiavi: ``backup`` (stato_backup), ``alert`` (critici, totale), ``cve`` (uniche, gravi), ``wg`` (stato_wg),
    ``intune`` (etichette dei problemi), ``sistema`` (stato_sistema o None), ``patch`` (critiche, totale).
    """
    motivi = []

    def togli(punti, testo, scheda):
        if punti > 0:
            motivi.append({"punti": punti, "testo": testo, "scheda": scheda})

    b = f.get("backup", "assente")
    if b == "fallito":
        togli(25, "Ultimo backup fallito", "backup")
    elif b == "vecchio":
        togli(10, "Backup non recente", "backup")
    elif b == "assente":
        togli(10, "Nessun backup registrato", "backup")
    crit, tot = f.get("alert", (0, 0))
    togli(min(30, 20 * crit + 5 * (tot - crit)), f"{tot} alert apert{'o' if tot == 1 else 'i'}", "timeline")
    uniche, gravi = f.get("cve", (0, 0))
    togli(min(25, 5 * gravi), f"{gravi} CVE gravi (KEV o CVSS ≥ 9)", "vulnerabilita")
    togli(min(10, uniche - gravi), f"{uniche - gravi} altre CVE", "vulnerabilita")
    wg, wg_label = f.get("wg", ("senza_agente", ""))
    if wg == "senza_agente":
        togli(15, "Senza agente WatchGuard", "protezione")
    elif wg == "non_protetto":
        togli(20, f"Protezione WatchGuard: {wg_label.lower()}", "protezione")
    elif wg == "vecchio":
        togli(5, f"WatchGuard non si collega da più di {GIORNI_WG_VECCHIO} giorni", "protezione")
    for p in f.get("intune") or []:
        togli(10, f"Intune: {p}", "protezione")
    s = f.get("sistema")
    if s and s["fuori"]:
        togli(20, f"{s['nome']} fuori supporto", "caratteristiche")
    elif s and s["in_scadenza"]:
        togli(5, f"{s['nome']}: supporto in scadenza", "caratteristiche")
    pc, pt = f.get("patch", (0, 0))
    togli(min(15, 3 * pc + (pt - pc) // 5), f"{pt} patch mancanti ({pc} critiche)", "vulnerabilita")
    valore = max(0, 100 - sum(m["punti"] for m in motivi))
    tono = tono_di(valore)
    return {"punteggio": valore, "tono": tono, "motivi": sorted(motivi, key=lambda m: -m["punti"]), "etichetta": ETICHETTE[tono]}


ETICHETTE = {"success": "Postura buona", "warning": "Da migliorare", "critical": "A rischio"}


def tono_di(valore):
    return "success" if valore >= 80 else ("warning" if valore >= 50 else "critical")


# --- Mappa di tutti i PC ------------------------------------------------------------------

def mappa(refresh=False):
    """Indice di ogni PC dell'elenco Dispositivi, dal peggiore. In cache 10 minuti (l'elenco è pesante)."""
    if not refresh:
        dati = cache.get(CACHE_MAPPA)
        if dati is not None:
            return dati
    from security.services import pc_copertura

    righe = pc_copertura.righe(proposte=False)
    alert, wg, patch = alert_per_pc(), wg_per_pc(), patch_per_pc()
    now = timezone.now()
    pcs = []
    for r in righe:
        k = r["key"]
        cve = r["cve"] or {}
        risultato = punteggio({
            "backup": stato_backup(r["backup"]),
            "alert": alert.get(k, (0, 0)),
            "cve": (cve.get("cves", 0), cve.get("gravi", 0)),
            "wg": stato_wg(wg.get(k), now),
            "intune": r["problemi"],
            "sistema": r.get("sistema"),
            "patch": patch.get(k, (0, 0)),
        })
        pcs.append({"nome": r["nome"], "key": k, "url": reverse("security:pc_detail") + "?nome=" + r["nome"],
                    "punteggio": risultato["punteggio"], "tono": risultato["tono"],
                    "motivo": risultato["motivi"][0]["testo"] if risultato["motivi"] else "Nessun problema noto"})
    pcs.sort(key=lambda p: (p["punteggio"], p["nome"].casefold()))
    conta = {t: sum(1 for p in pcs if p["tono"] == t) for t in ETICHETTE}
    media = round(sum(p["punteggio"] for p in pcs) / len(pcs)) if pcs else None
    dati = {"pcs": pcs, "conta": conta, "media": media, "tono_media": tono_di(media) if media is not None else "muted",
            "calcolata": timezone.now()}
    cache.set(CACHE_MAPPA, dati, CACHE_SECONDI)
    return dati
