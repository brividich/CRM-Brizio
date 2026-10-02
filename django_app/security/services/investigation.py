"""Analisi e risposta: cosa sappiamo di un alert e cosa si fa di solito.

- ``alert_kind``: il tipo di problema (accessi VPN negati, backup, minaccia su un computer, ...).
- ``related_facts``: incrocia l'alert con il resto dei dati IT del portale (storico VPN, backup,
  dispositivi e asset HUB, altri alert) e restituisce pochi fatti leggibili, ognuno con un link.
- ``precedents``: quante volte e' gia' successo e come e' stato chiuso.
- ``PLAYBOOKS``: i passi standard di risposta per tipo, scritti a mano (non dall'AI): sono la base
  da cui l'operatore parte e su cui l'AI si appoggia per proporre i passi del ticket.

Tutto in sola lettura: nessuna funzione qui cambia alert o ticket.
"""
import ipaddress
import re
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Count, Max, Min
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from security.models import (
    BackupJobRecord, SecurityAlert, SecurityAsset, SecurityEventRecord, SecurityRemediationTicket, SecurityVpnAccess, Status,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES as ACTIVE

_IP = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
_CVE = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)
_LAN = [ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]

# Tipo candidato del parser -> tipo di problema.
_KIND_BY_TYPE = {
    "watchguard_vpn_repeated_denied": "vpn_denied",
    "watchguard_vpn_many_short_reconnects": "vpn_access",
    "watchguard_vpn_long_session": "vpn_access",
    "watchguard_epdr_threat_detected": "endpoint_threat",
    "watchguard_epdr_malware_detected": "endpoint_threat",
    "watchguard_epdr_malware_critical_asset": "endpoint_threat",
    "watchguard_epdr_pending_severe": "endpoint_threat",
    "watchguard_epdr_unprotected_endpoints": "endpoint_protection",
    "watchguard_epdr_unmanaged_computers": "endpoint_protection",
    "watchguard_epdr_critical_risk": "endpoint_protection",
    "watchguard_epdr_license_expiring": "license",
    "watchguard_license_expiring": "license",
    "watchguard_malware_blocked": "firewall_threat",
    "watchguard_botnet_blocked_aggregate": "firewall_threat",
    "watchguard_zero_day_apt_hit": "firewall_threat",
    "watchguard_threatsync_open_severe": "firewall_threat",
    "watchguard_sdwan_packet_loss": "network",
    "watchguard_sdwan_latency": "network",
    "watchguard_sdwan_jitter": "network",
    "watchguard_dropped_packets": "network",
    "defender_critical_vulnerability": "vulnerability",
    "defender_unreadable_vulnerability": "vulnerability",
}
_KIND_BY_EVENT = {
    "vulnerability_finding": "vulnerability",
    "backup_job": "backup",
    "source_silent": "source_silent",
    "possible_sender_spoofing": "spoofing",
    "vpn_auth_denied": "vpn_denied",
    "vpn_auth_allowed": "vpn_access",
}

# Passi standard di risposta. Brevi, concreti, nell'ordine in cui si fanno.
PLAYBOOKS = {
    "vpn_denied": ("Tentativi di accesso VPN negati", [
        "Verificare se l'IP di origine è noto (sede, dipendente in trasferta) o estraneo",
        "Controllare nel registro VPN che dallo stesso IP non ci siano accessi riusciti dopo i tentativi",
        "Se l'IP è estraneo, bloccarlo sul Firebox (Blocked Sites)",
        "Se l'utente provato esiste, fargli cambiare la password e verificare che abbia l'MFA attiva",
        "Se gli utenti provati sono generici (admin, test), verificare che quegli account siano disabilitati",
    ]),
    "vpn_access": ("Sessione VPN anomala", [
        "Chiedere all'utente se riconosce l'accesso (orario, durata, provenienza)",
        "Controllare nel registro VPN gli IP di origine usati dall'utente nello stesso periodo",
        "Se l'accesso non è riconosciuto: disconnettere la sessione, cambiare la password e verificare l'MFA",
    ]),
    "backup": ("Backup fallito", [
        "Aprire il dettaglio del job sulla console di backup e leggere l'errore",
        "Rilanciare il backup a mano e verificare che termini",
        "Controllare lo spazio libero sulla destinazione e che il dispositivo sia raggiungibile",
        "Se fallisce da più giorni, verificare di avere un ripristino recente utilizzabile",
        "Annotare la causa nel ticket",
    ]),
    "endpoint_threat": ("Minaccia rilevata su un computer", [
        "In Endpoint Security verificare cosa è stato rilevato e se è stato bloccato o messo in quarantena",
        "Se la minaccia non è neutralizzata, isolare il computer dalla rete dalla console",
        "Chiedere all'utente cosa stava facendo (mail, chiavetta USB, sito web)",
        "Eseguire un'analisi completa del computer",
        "Se è ransomware o un computer critico: avvisare la direzione e valutare la notifica di incidente (NIS2/ACN)",
    ]),
    "endpoint_protection": ("Computer senza protezione", [
        "Aprire in Endpoint Security l'elenco dei computer non protetti o non gestiti",
        "Installare o reinstallare l'agente sui computer aziendali e assegnare la licenza",
        "Per i dispositivi sconosciuti in rete, individuare proprietario e posizione",
        "Aggiornare l'inventario asset",
    ]),
    "license": ("Licenza in scadenza", [
        "Verificare la data di scadenza nel portale del produttore",
        "Chiedere il preventivo di rinnovo al fornitore",
        "Fissare un promemoria 15 giorni prima della scadenza",
    ]),
    "firewall_threat": ("Minaccia bloccata dal firewall", [
        "Nel report individuare il computer interno coinvolto (sorgente del traffico)",
        "Se un computer interno contatta botnet o server malevoli: analisi completa con Endpoint Security",
        "Verificare che Gateway AV, IPS e Botnet Detection del Firebox siano attivi e aggiornati",
    ]),
    "network": ("Problema di linea o di rete", [
        "Verificare lo stato della linea con il provider",
        "Controllare sul Firebox l'interfaccia indicata (errori, failover SD-WAN)",
        "Se si ripete, aprire una segnalazione al provider con orari e valori",
    ]),
    "vulnerability": ("Vulnerabilità critica", [
        "Individuare i dispositivi esposti in Microsoft Defender (Vulnerabilità)",
        "Applicare l'aggiornamento del produttore o, se non c'è, la mitigazione indicata",
        "Dopo 24-48 ore verificare che i dispositivi esposti siano scesi a zero",
    ]),
    "source_silent": ("Report non più ricevuti", [
        "Verificare che la casella riceva ancora i report (regole di posta, mittente cambiato)",
        "Controllare che il servizio che invia il report sia attivo e programmato",
        "Rileggere la casella con «Leggi adesso» dalla pagina Caselle mail",
    ]),
    "spoofing": ("Mail che imita un fornitore", [
        "Non aprire allegati o link della mail",
        "Verificare il mittente reale dalle intestazioni e segnalare la mail come phishing",
        "Bloccare il mittente sul filtro della posta",
        "Se il dominio imita quello del fornitore, avvisare il fornitore",
    ]),
    "other": ("Verifica generica", [
        "Leggere i dettagli dell'evento e il report d'origine",
        "Decidere se è un problema reale: se sì lavorarlo nel ticket, se no chiuderlo come falso positivo con il motivo",
    ]),
}


def _payload(alert):
    return ((alert.event.payload if alert.event_id else None) or {}) if alert else {}


def alert_kind(alert):
    """Tipo di problema dell'alert: dal tipo del parser, poi dall'evento, poi dalle parole del titolo."""
    payload = _payload(alert)
    kind = _KIND_BY_TYPE.get(str(payload.get("type") or ""))
    if not kind and alert.event_id:
        kind = _KIND_BY_EVENT.get(alert.event.event_type)
    if kind:
        return kind
    title = (alert.title or "").lower()
    if "vpn" in title:
        return "vpn_denied" if any(word in title for word in ("negat", "denied", "rifiut")) else "vpn_access"
    if "backup" in title:
        return "backup"
    if "cve-" in title or "vulnerab" in title:
        return "vulnerability"
    if "licen" in title:
        return "license"
    return "other"


def playbook(alert):
    title, steps = PLAYBOOKS[alert_kind(alert)]
    return {"kind": alert_kind(alert), "title": title, "steps": steps}


def entities(alert):
    """IP, utente, computer, job di backup e CVE citati dall'alert."""
    payload = _payload(alert)
    title = alert.title or ""
    ip = str(payload.get("source_ip") or payload.get("ip") or "").strip()
    if not ip:
        match = _IP.search(title)
        ip = match.group(1) if match else ""
    cve = str(payload.get("cve") or "").strip()
    if not cve:
        match = _CVE.search(title)
        cve = match.group(0).upper() if match else ""
    return {
        "ip": ip,
        "user": str(payload.get("user") or payload.get("username") or "").strip(),
        "computer": str(payload.get("computer") or payload.get("device_name") or payload.get("hostname") or "").strip(),
        "job": str(payload.get("job_name") or "").strip(),
        "cve": cve,
    }


def _url(name, *args, query=None):
    try:
        url = reverse(name, args=args)
    except NoReverseMatch:
        return ""
    return f"{url}?{urlencode(query)}" if query else url


def _when(value):
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def _ip_fact(ip, since):
    try:
        address = ipaddress.ip_address(ip)
        # Solo le reti aziendali vere (RFC 1918): `is_private` vale anche per gli indirizzi di documentazione.
        internal = any(address in network for network in _LAN)
    except ValueError:
        return None
    rows = SecurityVpnAccess.objects.filter(source_ip=ip, login_at__gte=since)
    allowed = rows.filter(action=SecurityVpnAccess.ACTION_ALLOWED).count()
    denied = rows.filter(action=SecurityVpnAccess.ACTION_DENIED).count()
    lines = ["Indirizzo della rete aziendale" if internal else "Indirizzo esterno (Internet)"]
    tone = ""
    if allowed or denied:
        span = rows.aggregate(first=Min("login_at"), last=Max("login_at"))
        users = rows.order_by().values("username").annotate(n=Count("id")).order_by("-n")[:5]
        lines.append(f"Ultimi 90 giorni: {allowed} accessi VPN riusciti, {denied} negati")
        lines.append("Utenti usati: " + ", ".join(f"{u['username'] or '(vuoto)'} ({u['n']})" for u in users))
        lines.append(f"Visto la prima volta il {_when(span['first'])}, l'ultima il {_when(span['last'])}")
        if denied and not allowed:
            lines.append("Da questo indirizzo non è mai entrato nessuno: non è un utente noto.")
            tone = "warn"
        elif denied and allowed:
            lines.append("Da questo indirizzo ci sono anche accessi riusciti: controllare che siano legittimi.")
            tone = "warn"
    else:
        lines.append("Nessun accesso VPN da questo indirizzo negli ultimi 90 giorni")
    return {"label": f"Indirizzo {ip}", "lines": lines, "tone": tone,
            "url": _url("security:vpn_history", query={"ip": ip, "giorni": 90, "kind": "all"}), "link": "Apri gli accessi"}


def _user_fact(user, since):
    rows = SecurityVpnAccess.objects.filter(username__iexact=user, login_at__gte=since)
    allowed = rows.filter(action=SecurityVpnAccess.ACTION_ALLOWED)
    denied = rows.filter(action=SecurityVpnAccess.ACTION_DENIED).count()
    ips = allowed.order_by().values("source_ip").distinct().count()
    last = allowed.aggregate(last=Max("login_at"))["last"]
    lines = [f"Ultimi 90 giorni: {allowed.count()} accessi riusciti da {ips} indirizzi diversi, {denied} negati",
             f"Ultimo accesso riuscito: {_when(last)}"]
    tone = "warn" if ips >= 10 else ""
    if tone:
        lines.append("Molti indirizzi diversi: credenziali forse condivise o usate da altri.")
    if not allowed.exists() and denied:
        lines.append("Questo utente non è mai entrato in VPN: l'account potrebbe non esistere o essere un bersaglio a caso.")
    return {"label": f"Utente {user}", "lines": lines, "tone": tone,
            "url": _url("security:vpn_history", query={"user": user, "giorni": 90, "kind": "all"}), "link": "Apri i suoi accessi"}


def _computer_fact(name, alert, since):
    asset = SecurityAsset.objects.filter(hostname__iexact=name).select_related("hub_asset").first()
    others = SecurityAlert.objects.filter(title__icontains=name, created_at__gte=since).exclude(pk=alert.pk).count()
    lines = []
    url, link = "", ""
    if asset and asset.hub_asset_id:
        lines.append(f"Collegato all'asset HUB «{asset.hub_asset}»")
        url, link = _url("assets:asset_view", asset.hub_asset_id), "Apri l'asset"
    elif asset:
        lines.append("Conosciuto dai report ma non ancora collegato a un asset HUB")
        url, link = _url("security:assets"), "Collega l'asset"
    else:
        lines.append("Non presente nei dispositivi dei report")
    if asset:
        signals = asset.signals.filter(occurred_at__gte=since).order_by().values("kind").annotate(n=Count("id"))
        for row in signals:
            label = {"backup": "backup registrati", "endpoint_detections": "rilevamenti Endpoint", "endpoint_threat": "minacce"}.get(row["kind"], row["kind"])
            lines.append(f"Ultimi 90 giorni: {row['n']} {label}")
    lines.append(f"Altri alert su questo computer negli ultimi 90 giorni: {others}")
    return {"label": f"Computer {name}", "lines": lines, "tone": "warn" if others else "", "url": url, "link": link}


def _job_fact(job):
    runs = list(BackupJobRecord.objects.filter(job_name=job).order_by("-started_at", "-created_at")[:14])
    if not runs:
        return None
    ok = [run for run in runs if run.status == "completed"]
    last_ok = ok[0].started_at or ok[0].created_at if ok else None
    lines = [f"Ultime {len(runs)} esecuzioni: {len(ok)} riuscite, {len(runs) - len(ok)} non riuscite"]
    tone = ""
    if last_ok:
        days = (timezone.now() - last_ok).days
        lines.append(f"Ultimo backup riuscito: {_when(last_ok)}" + (f" ({days} giorni fa)" if days else " (oggi)"))
        tone = "warn" if days >= 2 else ""
    else:
        lines.append("Nessun backup riuscito tra le ultime esecuzioni registrate.")
        tone = "warn"
    return {"label": f"Job {job}", "lines": lines, "tone": tone,
            "url": _url("security:kpi_detail", "backup_failed_count"), "link": "Andamento backup"}


def _cve_fact(cve):
    tickets = SecurityRemediationTicket.objects.filter(cve__iexact=cve).order_by("-updated_at")
    total = tickets.count()
    if not total:
        return None
    last = tickets.first()
    return {"label": cve, "lines": [f"{total} ticket di rimedio per questa CVE; l'ultimo è «{last.get_status_display()}»",
                                    f"Dispositivi esposti (massimo visto): {last.max_exposed_devices}"],
            "tone": "", "url": _url("security:case_detail", last.pk), "link": "Apri il ticket"}


def related_facts(alert, days=90):
    """Fatti collegati all'alert, presi dagli altri dati del portale. Vuoto se non c'e' nulla da dire."""
    since = timezone.now() - timedelta(days=days)
    found = entities(alert)
    facts = []
    if found["ip"]:
        facts.append(_ip_fact(found["ip"], since))
    if found["user"]:
        facts.append(_user_fact(found["user"], since))
    if found["computer"]:
        facts.append(_computer_fact(found["computer"], alert, since))
    if found["job"]:
        facts.append(_job_fact(found["job"]))
    if found["cve"]:
        facts.append(_cve_fact(found["cve"]))
    return [fact for fact in facts if fact]


STATUS_LABELS = {  # (una, piu')
    Status.FALSE_POSITIVE: ("falso positivo", "falsi positivi"), Status.CLOSED: ("chiuso", "chiusi"), Status.RESOLVED: ("risolto", "risolti"),
    Status.SUPPRESSED: ("soppresso", "soppressi"), Status.MUTED: ("silenziato", "silenziati"), Status.SNOOZED: ("posticipato", "posticipati"),
    Status.NEW: ("nuovo", "nuovi"), Status.OPEN: ("aperto", "aperti"), Status.ACKNOWLEDGED: ("preso in carico", "presi in carico"),
    Status.IN_PROGRESS: ("in lavorazione", "in lavorazione"),
}


def status_label(status, count=1):
    one, many = STATUS_LABELS.get(status, (status, status))
    return one if count == 1 else many


def same_family(alert, candidates):
    """Alert «dello stesso tipo»: stesso tipo del parser se c'e', altrimenti stesso titolo o stesso dedup.

    Il confronto sul tipo si fa in Python e non con un lookup JSON: su SQL Server i lookup su
    chiavi JSON sono fragili, e qui le righe sono poche."""
    kind_type = _payload(alert).get("type")
    family = []
    for other in candidates:
        if other.pk == alert.pk:
            continue
        other_type = ((other.event.payload if other.event_id else None) or {}).get("type")
        if (kind_type and other_type == kind_type) or other.title == alert.title or (alert.dedup_hash and other.dedup_hash == alert.dedup_hash):
            family.append(other)
    return family


def _discarded_events(alert, since):
    """Eventi dello stesso tipo scartati dal motore (soppressi o tenuti solo per i KPI)."""
    if not alert.event_id:
        return 0, 0
    kind_type = _payload(alert).get("type")
    rows = SecurityEventRecord.objects.filter(event_type=alert.event.event_type, occurred_at__gte=since).only("payload", "suppressed", "decision_trace")[:3000]
    suppressed = kpi_only = 0
    for event in rows:
        if kind_type and (event.payload or {}).get("type") != kind_type:
            continue
        decision = (event.decision_trace or {}).get("decision", "")
        if event.suppressed or decision == "suppressed_kpi_only":
            suppressed += 1
        elif decision == "kpi_only":
            kpi_only += 1
    return suppressed, kpi_only


def precedents(alert, days=180):
    """Cosa e' gia' successo per questo tipo di alert: quante volte, come e' finito, perche'."""
    since = timezone.now() - timedelta(days=days)
    candidates = SecurityAlert.objects.filter(created_at__gte=since).select_related("event").order_by("-created_at")[:1000]
    family = same_family(alert, candidates)
    suppressed, kpi_only = _discarded_events(alert, since)
    discarded = []
    if suppressed:
        discarded.append(f"{suppressed} eventi simili scartati da una regola di soppressione")
    if kpi_only:
        discarded.append(f"{kpi_only} eventi simili sotto soglia (solo KPI, nessun alert)")
    if not family:
        return {"total": 0, "text": "È la prima volta negli ultimi 6 mesi.", "by_status": [], "reasons": [], "discarded": discarded, "hint": ""}
    counts = {}
    for other in family:
        counts[other.status] = counts.get(other.status, 0) + 1
    by_status = [f"{n} {status_label(status, n)}" for status, n in sorted(counts.items(), key=lambda item: -item[1])]
    reasons = []
    for other in family:
        reason = (other.status_reason or "").strip()
        if reason and other.status not in ACTIVE and reason not in [r["text"] for r in reasons]:
            reasons.append({"pk": other.pk, "at": other.updated_at, "status": status_label(other.status), "text": reason[:200]})
        if len(reasons) == 3:
            break
    total = len(family)
    hint = ""
    if total >= 3 and counts.get(Status.FALSE_POSITIVE, 0) * 2 >= total:
        hint = "Quasi sempre è stato un falso positivo: valuta una regola di soppressione in Config."
    elif total >= 3 and sum(counts.get(s, 0) for s in ACTIVE) == 0 and counts.get(Status.RESOLVED, 0) + counts.get(Status.CLOSED, 0) == total:
        hint = "Si ripete e ogni volta viene chiuso: conviene cercare la causa alla radice."
    return {
        "total": total,
        "text": f"Successo altre {total} volte negli ultimi 6 mesi: " + ", ".join(by_status) + ".",
        "by_status": by_status,
        "reasons": reasons,
        "discarded": discarded,
        "hint": hint,
    }


def facts_as_text(alert):
    """Fatti e precedenti in poche righe, per il contesto dell'AI (nessun dato oltre a quelli in pagina)."""
    lines = []
    for fact in related_facts(alert):
        lines.append(f"{fact['label']}: " + "; ".join(fact["lines"]))
    history = precedents(alert)
    lines.append("Precedenti: " + history["text"])
    for reason in history["reasons"]:
        lines.append(f"In passato finito come «{reason['status']}», motivo scritto dall'operatore: {reason['text']}")
    if history["discarded"]:
        lines.append("Scartati dal motore: " + "; ".join(history["discarded"]))
    book = playbook(alert)
    lines.append(f"Procedura standard «{book['title']}»: " + " | ".join(book["steps"]))
    return "\n".join(lines)
