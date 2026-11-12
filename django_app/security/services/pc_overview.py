"""Scheda unica di un PC o server: tutto quello che il SOC sa di quel nome host.

Fonti: backup (``backup_center``), dispositivi SOC con lo stesso nome host
(``SecurityAsset``: segnali endpoint, vulnerabilità, eventi, alert) e l'asset HUB
collegato. Il nome è l'unica chiave comune ai fornitori: il confronto ignora maiuscole.
Sola lettura, a numero di query limitato.
"""
from __future__ import annotations

from security.models import (
    SecurityAlert,
    SecurityAsset,
    SecurityAssetSignal,
    SecurityEventRecord,
    SecurityVulnerabilityFinding,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

SIGNAL_LABELS = {
    SecurityAssetSignal.KIND_BACKUP: "Backup",
    SecurityAssetSignal.KIND_DETECTIONS: "Rilevamenti endpoint",
    SecurityAssetSignal.KIND_THREAT: "Minaccia endpoint",
}


def pc_overview(name, days=90):
    from security.services.backup_center import device_detail

    backup = device_detail(name, days)
    assets = list(SecurityAsset.objects.filter(hostname__iexact=name).select_related("source", "hub_asset"))
    intune = _intune(name)
    cve_impacts = _cve_impacts(name)
    if backup is None and not assets and intune is None and not cve_impacts and not _in_inventario(name):
        return None
    hub_asset = (next((a.hub_asset for a in assets if a.hub_asset_id), None) or (backup or {}).get("asset")
                 or (intune.asset if intune else None))
    alerts = SecurityAlert.objects.filter(event__asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    vulns = SecurityVulnerabilityFinding.objects.filter(asset__in=assets, status__in=ACTIVE_ALERT_STATUSES).select_related("source")
    signals = SecurityAssetSignal.objects.filter(asset__in=assets).exclude(kind=SecurityAssetSignal.KIND_BACKUP).select_related("source")
    events = SecurityEventRecord.objects.filter(asset__in=assets, suppressed=False).select_related("source")
    open_alerts = list(alerts.order_by("-created_at")[:10])
    # Le CVE già elencate dall'inventario non si ripetono tra quelle di Defender.
    gia_viste = {i.cve.cve_id.upper() for i in cve_impacts}
    open_vulns = [v for v in vulns.order_by("-cvss", "-last_seen_at")[:10 + len(gia_viste)] if (v.cve or "").upper() not in gia_viste][:10]
    uniche = cve_uniche(name).get(_norm(name), {"cves": 0, "kev": 0, "gravi": 0})
    endpoint = list(signals.order_by("-occurred_at")[:8])
    status = _overall(backup, open_alerts, open_vulns + [i for i in cve_impacts if i.grave])
    return {
        "name": (backup or {}).get("name") or (assets[0].hostname if assets else (intune.nome if intune else name)),
        "status": status,
        "hub_asset": hub_asset,
        "sources": sorted({a.source.name for a in assets if a.source_id} | ({"Intune"} if intune else set())),
        "ip": next((a.ip_address for a in assets if a.ip_address), ""),
        "asset_type": next((a.asset_type for a in assets if a.asset_type), ""),
        "backup": backup,
        "alerts": open_alerts,
        "alert_count": alerts.count(),
        "vulns": open_vulns,
        "vuln_count": vulns.count(),
        "cve_impacts": cve_impacts[:10],
        "cve_count": len(cve_impacts),
        # Il numero delle vulnerabilità del PC, uguale in scheda, pannello ed elenco Dispositivi.
        "cve_uniche": uniche["cves"],
        "cve_gravi": uniche["gravi"],
        "endpoint": [{"signal": s, "label": SIGNAL_LABELS.get(s.kind, s.kind)} for s in endpoint],
        "events": list(events.order_by("-occurred_at")[:8]),
        "days": days,
        "rete": _rete(name, hub_asset),
        "intune": intune,
        "assets": assets,
        "cve_all": cve_impacts,
        "open_vulns_all": open_vulns,
    }


PATCH_IN_SCHEDA = 25


def pc_scheda(name, days=90):
    """La scheda completa del PC: ``pc_overview`` più caratteristiche, protezione WatchGuard, patch e software.

    Solo per la pagina ``/soc/pc/``: pannello laterale e controllo AI restano su ``pc_overview``, più leggero.
    Niente manutenzione né altro del registro asset: solo quello che dicono le fonti del SOC.
    """
    from datetime import timedelta

    from django.utils import timezone

    from security.models import SoftwareInstallation, WatchGuardDispositivo, WatchGuardPatch
    from security.services.rischio_asset import stato_sistema

    data = pc_overview(name, days)
    if data is None:
        return None
    key = _norm(name)
    now = timezone.now()
    intune = data["intune"]

    wg = (WatchGuardDispositivo.objects.filter(host=key, presente=True).order_by("-gestito", "-ultima_connessione").first()
          if key else None)
    patch_qs = WatchGuardPatch.objects.filter(host=key, presente=True) if key else WatchGuardPatch.objects.none()
    patch = sorted(patch_qs, key=lambda p: (p.criticita or 999, -(p.rilasciata_il.toordinal() if p.rilasciata_il else 0), p.nome))
    patch_errori = list(WatchGuardPatch.objects.filter(host=key, esito__in=WatchGuardPatch.ESITI_ERRORE,
                                                       esito_il__gte=now - timedelta(days=14)).order_by("-esito_il")[:10]) if key else []

    software = [s for s in SoftwareInstallation.objects.filter(still_detected=True, host__istartswith=key)
                .exclude(source_kind="snmp_firmware").order_by("product_raw") if _norm(s.host) == key] if key else []
    sistema = stato_sistema([s for s in software if (s.product or "").lower().startswith("windows ")])
    defender_visto = max((s.last_seen_at for s in software if "defender" in (s.fonti or [])), default=None)

    disco = None
    if intune and intune.disco_totale_bytes:
        libero = intune.disco_libero_bytes or 0
        usato_pct = round(100 * (intune.disco_totale_bytes - libero) / intune.disco_totale_bytes)
        disco = {"totale": intune.disco_label, "libero": intune._gb(libero) or "0 GB", "usato_pct": usato_pct,
                 "tono": "critical" if usato_pct >= 90 else ("warning" if usato_pct >= 80 else "success")}

    b = data["backup"]
    fonti = [
        {"nome": "Intune", "visto": bool(intune), "quando": intune.ultima_sync if intune else None,
         "nota": (", ".join(intune.problemi_label) or "nessun problema") if intune else "non registrato in Intune",
         "tono": ("warning" if intune.problemi else "success") if intune else "muted"},
        {"nome": "WatchGuard", "visto": bool(wg and wg.gestito), "quando": wg.ultima_connessione if wg else None,
         "nota": (f"protezione {wg.protezione_label.lower()}" if wg.gestito else "visto in rete senza agente") if wg else "nessun agente",
         "tono": ("success" if wg.protetto else "critical") if wg and wg.gestito else ("warning" if wg else "muted")},
        {"nome": "Microsoft Defender", "visto": bool(defender_visto), "quando": defender_visto,
         "nota": "inventario software e vulnerabilità" if defender_visto else "non visto da Defender",
         "tono": "success" if defender_visto else "muted"},
        {"nome": "Backup", "visto": bool(b), "quando": b["last_at"] if b else None,
         "nota": b["last_label"] if b else f"nessun report negli ultimi {days} giorni",
         "tono": b["last_tone"] if b else "muted"},
        {"nome": "DHCP / DNS", "visto": bool(data["rete"]), "quando": None,
         "nota": ", ".join(r.ip for r in data["rete"]) if data["rete"] else "nessun indirizzo attivo",
         "tono": "success" if data["rete"] else "muted"},
    ]

    mac = [m for m in ((intune.mac_ethernet, "Ethernet") if intune else ("", ""), (intune.mac_wifi, "Wi-Fi") if intune else ("", "")) if m[0]]
    wg_vecchio = bool(wg and wg.ultima_connessione and wg.ultima_connessione < now - timedelta(days=7))
    patch_critiche = sum(1 for p in patch if p.criticita == 201)
    rischio = _rischio(data, wg, wg_vecchio, intune, sistema, patch_critiche, len(patch))
    asset = data["hub_asset"]
    produttore = (intune.produttore if intune else "") or (getattr(asset, "manufacturer", "") or "")
    modello = (intune.modello if intune else "") or (getattr(asset, "model", "") or "")
    return {
        **data,
        "rischio": rischio,
        "cve_gravita": _cve_gravita(data["cve_all"], data["open_vulns_all"]),
        "patch_per_criticita": _patch_per_criticita(patch),
        "produttori_sw": _produttori(software),
        "timeline": _timeline(data, patch_errori, wg),
        "wg": wg,
        "wg_vecchio": wg_vecchio,
        "patch": patch[:PATCH_IN_SCHEDA],
        "patch_count": len(patch),
        "patch_critiche": patch_critiche,
        "patch_errori": patch_errori,
        "software": software,
        "sistema": sistema,
        "disco": disco,
        "fonti": fonti,
        "fonti_viste": sum(1 for f in fonti[:4] if f["visto"]),
        "mac": mac,
        "produttore": produttore,
        "modello": modello,
        "produttore_modello": " ".join(x for x in (produttore, modello) if x),
        "seriale": (intune.seriale if intune else "") or (getattr(asset, "serial_number", "") or ""),
        "sistema_nome": (intune.sistema if intune else "") or (wg.sistema if wg else ""),
    }


def _rischio(data, wg, wg_vecchio, intune, sistema, patch_critiche, patch_tot):
    """Indice di postura 0-100 (100 = nessun problema noto) con i motivi che lo abbassano, ciascuno con la sua scheda.

    Solo una lettura sintetica dei fatti già in pagina: non apre alert né cambia altri numeri del SOC.
    """
    motivi = []

    def togli(punti, testo, scheda):
        if punti > 0:
            motivi.append({"punti": punti, "testo": testo, "scheda": scheda})

    b = data["backup"]
    if b and b["last_status"] == "failed":
        togli(25, "Ultimo backup fallito", "backup")
    elif b and b["stale"]:
        togli(10, "Backup non recente", "backup")
    elif not b:
        togli(10, "Nessun backup registrato", "backup")
    critici = sum(1 for a in data["alerts"] if a.severity == "critical")
    togli(min(30, 20 * critici + 5 * (data["alert_count"] - critici)), f"{data['alert_count']} alert apert{'o' if data['alert_count'] == 1 else 'i'}", "eventi")
    togli(min(25, 5 * data["cve_gravi"]), f"{data['cve_gravi']} CVE gravi (KEV o CVSS ≥ 9)", "vulnerabilita")
    togli(min(10, data["cve_uniche"] - data["cve_gravi"]), f"{data['cve_uniche'] - data['cve_gravi']} altre CVE", "vulnerabilita")
    if wg is None or not wg.gestito:
        togli(15, "Senza agente WatchGuard", "protezione")
    elif not wg.protetto:
        togli(20, f"Protezione WatchGuard: {wg.protezione_label.lower()}", "protezione")
    elif wg_vecchio:
        togli(5, "WatchGuard non si collega da più di 7 giorni", "protezione")
    if intune:
        for p in intune.problemi_label:
            togli(10, f"Intune: {p}", "protezione")
    if sistema and sistema["fuori"]:
        togli(20, f"{sistema['nome']} fuori supporto", "caratteristiche")
    elif sistema and sistema["in_scadenza"]:
        togli(5, f"{sistema['nome']}: supporto in scadenza", "caratteristiche")
    togli(min(15, 3 * patch_critiche + (patch_tot - patch_critiche) // 5), f"{patch_tot} patch mancanti ({patch_critiche} critiche)", "vulnerabilita")
    punteggio = max(0, 100 - sum(m["punti"] for m in motivi))
    tono = "success" if punteggio >= 80 else ("warning" if punteggio >= 50 else "critical")
    return {"punteggio": punteggio, "tono": tono, "motivi": sorted(motivi, key=lambda m: -m["punti"]),
            "etichetta": {"success": "Postura buona", "warning": "Da migliorare", "critical": "A rischio"}[tono]}


def _cve_gravita(impacts, vulns):
    """Conteggi per gravità (KEV, critica, alta, media/bassa) di tutte le CVE note del PC, una volta ciascuna."""
    viste, out = set(), {"kev": 0, "critica": 0, "alta": 0, "altra": 0}
    righe = [((i.cve.cve_id or "").upper(), i.cve.kev, i.cve.cvss or 0) for i in impacts]
    righe += [((v.cve or "").upper(), False, v.cvss or 0) for v in vulns]
    for cve, kev, cvss in righe:
        if not cve or cve in viste:
            continue
        viste.add(cve)
        out["kev" if kev else "critica" if cvss >= 9 else "alta" if cvss >= 7 else "altra"] += 1
    tot = sum(out.values())
    # Angoli del grafico ad anello (conic-gradient), in percentuale cumulata.
    acc, fette = 0, []
    for chiave, colore in (("kev", "var(--danger)"), ("critica", "#f97316"), ("alta", "var(--warning)"), ("altra", "#64748b")):
        pct = round(100 * out[chiave] / tot, 1) if tot else 0
        fette.append(f"{colore} {acc}% {acc + pct}%")
        acc += pct
    return {**out, "totale": tot, "anello": ", ".join(fette) if tot else "var(--border) 0% 100%"}


def _patch_per_criticita(patch):
    from collections import Counter

    conta = Counter(p.criticita_label for p in patch)
    tot = len(patch) or 1
    ordine = ["Critica", "Importante", "Moderata", "Bassa", "Service pack", "Non specificata", "Altro"]
    return [{"label": k, "n": conta[k], "pct": round(100 * conta[k] / tot)} for k in ordine if conta.get(k)]


def _produttori(software, quanti=8):
    from collections import Counter

    conta = Counter((s.vendor or s.vendor_raw or "Altro").strip() or "Altro" for s in software)
    top = conta.most_common(quanti)
    massimo = top[0][1] if top else 1
    return [{"nome": n, "n": c, "pct": round(100 * c / massimo)} for n, c in top]


def _timeline(data, patch_errori, wg):
    """Ultimi fatti del PC da tutte le fonti, in ordine di tempo: backup, alert, protezione, eventi, patch fallite."""
    from django.urls import reverse

    voci = []
    for r in ((data["backup"] or {}).get("history") or [])[:12]:
        voci.append({"quando": r["at"], "tipo": "backup", "fonte": "Backup", "titolo": f"{r['label']} · {r['job']}", "tono": r["tone"], "url": ""})
    for a in data["alerts"]:
        voci.append({"quando": a.created_at, "tipo": "alert", "fonte": a.source.name if a.source_id else "Alert", "titolo": a.title,
                     "tono": "critical" if a.severity == "critical" else "warning", "url": reverse("security:alert_detail", args=[a.pk])})
    for e in data["endpoint"]:
        s = e["signal"]
        voci.append({"quando": s.occurred_at, "tipo": "protezione", "fonte": e["label"], "titolo": s.title, "tono": "warning", "url": ""})
    for ev in data["events"]:
        voci.append({"quando": ev.occurred_at, "tipo": "evento", "fonte": ev.source.name, "titolo": ev.event_type, "tono": "muted",
                     "url": reverse("security:event_detail", args=[ev.pk])})
    for p in patch_errori:
        voci.append({"quando": p.esito_il, "tipo": "patch", "fonte": "WatchGuard", "titolo": f"{p.esito_label}: {p.nome}", "tono": "critical", "url": ""})
    if wg and wg.ultima_connessione:
        voci.append({"quando": wg.ultima_connessione, "tipo": "protezione", "fonte": "WatchGuard", "titolo": "Ultima connessione dell'agente",
                     "tono": "success" if wg.protetto else "warning", "url": ""})
    voci = [v for v in voci if v["quando"]]
    return sorted(voci, key=lambda v: v["quando"], reverse=True)[:30]


def _norm(name):
    from security.services.pc_copertura import norm

    return norm(name)


def cve_uniche(name=None):
    """CVE uniche per PC: {nome normalizzato: {"cves", "kev", "gravi"}}. Unica definizione del numero.

    Una CVE conta una volta per PC anche se la segnalano sia l'inventario software
    (``SecurityCveImpact`` che colpisce) sia Microsoft Defender (vulnerabilità aperta sul
    dispositivo SOC con lo stesso nome). Grave = in CISA KEV o CVSS ≥ 9. Con ``name`` si
    calcola solo quel PC.
    """
    from security.models import SecurityCveImpact

    key = _norm(name) if name is not None else None
    if name is not None and not key:
        return {}
    impacts = SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS)
    findings = SecurityVulnerabilityFinding.objects.filter(status__in=ACTIVE_ALERT_STATUSES, asset__isnull=False).exclude(cve="")
    if key:
        impacts = impacts.filter(host__istartswith=key)
        findings = findings.filter(asset__hostname__istartswith=key)
    per_pc = {}  # host -> {cve: grave}
    kev_ids = set()
    for host, cve_id, kev, cvss in impacts.values_list("host", "cve__cve_id", "cve__kev", "cve__cvss").iterator():
        k = _norm(host)
        if k and (key is None or k == key):
            cve_id = (cve_id or "").upper()
            per_pc.setdefault(k, {})[cve_id] = per_pc.get(k, {}).get(cve_id, False) or bool(kev or (cvss or 0) >= 9)
            if kev:
                kev_ids.add(cve_id)
    da_defender = []
    for host, cve_id, cvss in findings.values_list("asset__hostname", "cve", "cvss").iterator():
        k = _norm(host)
        if k and (key is None or k == key):
            da_defender.append((k, (cve_id or "").upper(), cvss))
    # KEV delle CVE viste solo da Defender: dal catalogo CVE, una query.
    solo_defender = {c for _k, c, _s in da_defender} - kev_ids
    if solo_defender:
        from security.services.kev import kev_tra

        kev_ids |= {c.upper() for c in kev_tra(solo_defender)}
    for k, cve_id, cvss in da_defender:
        cves = per_pc.setdefault(k, {})
        cves[cve_id] = cves.get(cve_id, False) or cve_id in kev_ids or (cvss or 0) >= 9
    return {k: {"cves": len(cves), "kev": sum(1 for c in cves if c in kev_ids), "gravi": sum(1 for g in cves.values() if g)}
            for k, cves in per_pc.items()}


def _rete(name, hub_asset):
    """Indirizzi attivi dal DHCP/DNS di Windows (collegati all'asset o con lo stesso nome host) e porta dello switch."""
    try:
        from django.db.models import Q

        from assets.models import IndirizzoRete
        from assets.services.rete_windows import porta_switch
    except ImportError:  # pragma: no cover
        return []
    corto = (name or "").split(".")[0]
    filtro = Q(nome_dhcp__iexact=corto) | Q(nome_dhcp__istartswith=corto + ".") if corto else Q(pk__in=[])
    if hub_asset is not None:
        filtro |= Q(asset=hub_asset)
    righe = list(IndirizzoRete.objects.filter(filtro).filter(Q(nel_dhcp=True) | Q(nel_dns=True)).order_by("-nel_dhcp", "ip")[:3])
    for r in righe:
        r.switch = porta_switch(r.mac) if r.mac else None
    return righe


def _intune(name):
    from assets.models import DispositivoIntune
    from security.services.pc_copertura import norm

    key = norm(name)
    return next((d for d in DispositivoIntune.objects.filter(presente=True, nome__istartswith=key).select_related("asset") if norm(d.nome) == key), None) if key else None


def _in_inventario(name):
    from security.models import SoftwareInstallation
    from security.services.pc_copertura import norm

    key = norm(name)
    return bool(key) and any(norm(h) == key for h in SoftwareInstallation.objects.filter(still_detected=True, host__istartswith=key).values_list("host", flat=True)[:50])


def _cve_impacts(name):
    """CVE che colpiscono il PC secondo l'inventario software (stesso esito della pagina Vulnerabilità)."""
    from security.models import SecurityCveImpact
    from security.services.pc_copertura import norm

    key = norm(name)
    if not key:
        return []
    impacts = [
        i for i in SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS, host__istartswith=key).select_related("cve", "installation")
        if norm(i.host) == key
    ]
    seen, out = set(), []
    for i in sorted(impacts, key=lambda i: (not i.cve.kev, -(i.cve.cvss or 0), i.cve.cve_id)):
        if i.cve_id in seen:
            continue
        seen.add(i.cve_id)
        i.grave = bool(i.cve.kev or (i.cve.cvss or 0) >= 9)
        i.severity = "critical" if i.grave else "high"
        out.append(i)
    return out


def _overall(backup, alerts, vulns):
    """Verdetto in testa alla scheda: il problema più serio vince."""
    if any(a.severity == "critical" for a in alerts) or (backup and backup["last_status"] == "failed"):
        return ("critical", "Da gestire subito")
    if alerts or any(v.severity in ("critical", "high") for v in vulns) or (backup and backup["stale"]):
        return ("warning", "Da controllare")
    if backup is None:
        return ("muted", "Nessun backup registrato")
    return ("success", "In regola")
