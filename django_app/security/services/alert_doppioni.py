"""Alert doppi: un problema sullo stesso soggetto è un alert solo, non uno per ogni mail.

* **Report via mail con un soggetto** (Endpoint Security «N devices blocked su PC», backup di un job):
  ogni mail è un evento a sé, ma l'alert si apre una volta per (sorgente, tipo, PC o job). Le mail
  successive aggiornano lo stesso alert (titolo con il conteggio nuovo, evento più recente) finché
  qualcuno lo chiude o il rientro lo chiude. La chiave è ``chiave_alert``.
* **CVE dalla mail di Defender e dall'inventario**: la mail apre «Vulnerabilità critica esposta CVE-X»,
  l'inventario apre gli alert PC per PC (versione vulnerabile, oltre il termine). Quando la CVE è già
  seguita PC per PC l'alert della mail è un doppione: non si apre, e quello già aperto si chiude come
  doppione (``chiudi_cve_doppie``), con il rimando agli alert dell'inventario.
* ``unisci_doppioni`` sistema gli alert già aperti prima di questa regola (comando
  ``security_unisci_doppioni``): tiene il più recente di ogni gruppo e chiude gli altri come «unito».

Nessuna chiusura qui dice «risolto»: un doppione chiuso rimanda sempre all'alert che resta aperto.
"""
from __future__ import annotations

import re
from collections import defaultdict

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, SecurityEventRecord, Status
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

AUTO_ACTOR = "system"
TIPI_PER_SOGGETTO = ("watchguard_alert_candidate", "backup_job", "cve_sla_scaduta", "veeam_malware")
TIPI_CVE_INVENTARIO = ("cve_impact_confirmed", "cve_sla_scaduta")
TIPI_CVE_IMPATTO = ("cve_impact_confirmed",)
EVENTO_MALWARE = "veeam_malware"
_NUMERI = re.compile(r"\d+(?:[.,]\d+)*")
_CVE = re.compile(r"CVE-\d{4}-\d{4,}", re.I)
_RETRY = re.compile(r"\s*\((?:retry|tentativo)\s*\d*\)\s*$", re.I)
_MALWARE = re.compile(r"malware\s+(?:activity|detection|event)", re.I)
DISPOSITIVI_BLOCCATI = "devices blocked"


def _norm(valore) -> str:
    return str(valore or "").strip().lower()


def job_base(nome) -> str:
    """Nome del job senza il tentativo: «Backup X (Retry 2)» è lo stesso job di «Backup X»."""
    return _RETRY.sub("", str(nome or "")).strip()


def e_report_malware(payload) -> bool:
    """Mail di Veeam sul malware trovato nei backup («Potential malware activity detected», «Daily malware detection
    report»): non è l'esito di un job, è un segnale di sicurezza a sé."""
    payload = payload or {}
    return bool(_MALWARE.search(f"{payload.get('job_name') or ''} {payload.get('subject') or ''}"))


def solo_dispositivi_bloccati(payload) -> bool:
    """Notifica di Endpoint Security che riporta solo dispositivi bloccati (chiavette USB fermate dalla policy)."""
    categorie = (payload or {}).get("categories") or []
    etichette = {_norm(c[1]) if isinstance(c, (list, tuple)) and len(c) > 1 else _norm(c) for c in categorie}
    return bool(etichette) and etichette == {DISPOSITIVI_BLOCCATI}


def blocchi_della_notifica(payload) -> int:
    """Quanti dispositivi bloccati dice la notifica (somma delle categorie «devices blocked»)."""
    totale = 0
    for c in (payload or {}).get("categories") or []:
        if isinstance(c, (list, tuple)) and len(c) > 1 and _norm(c[1]) == DISPOSITIVI_BLOCCATI:
            try:
                totale += int(c[0])
            except (TypeError, ValueError):
                continue
    return totale


def soggetto_watchguard(payload) -> str:
    """Il PC della notifica; senza PC il titolo senza numeri («... su computer non indicato»)."""
    payload = payload or {}
    return _norm(payload.get("computer")) or _NUMERI.sub("#", _norm(payload.get("title")))


def chiave_alert(event) -> str:
    """Chiave dell'alert per gli eventi che hanno un soggetto; vuota = vale l'impronta dell'evento."""
    payload = event.payload or {}
    if event.event_type == EVENTO_MALWARE or (event.event_type == "backup_job" and e_report_malware(payload)):
        # Tutte le mail sul malware nei backup: un alert solo, aggiornato dalla più recente.
        return make_hash(event.source_id, "alert", EVENTO_MALWARE)
    if event.event_type == "backup_job":
        job = _norm(job_base(payload.get("job_name")))
        if not job:
            return ""
        return make_hash(event.source_id, "alert", "backup_job", job, _norm(payload.get("device_name")))
    if event.event_type == "cve_sla_scaduta":
        cve = str(payload.get("cve") or "").upper()
        # Un alert per CVE, non uno per PC: i PC oltre il termine sono nella sua timeline.
        return make_hash(event.source_id, "alert", "cve_sla_scaduta", cve) if cve else ""
    if event.event_type == "watchguard_alert_candidate":
        tipo = _norm(payload.get("type"))
        # Senza PC: il titolo senza i numeri («Endpoint Security: # devices blocked su computer non indicato»).
        soggetto = soggetto_watchguard(payload)
        if not (tipo or soggetto):
            return ""
        return make_hash(event.source_id, "alert", "watchguard_alert_candidate", tipo, soggetto)
    return ""


def eventi_collegati_ids(alert) -> list[int]:
    """Gli eventi passati da questo alert (l'impronta dell'evento non basta più quando la chiave è il soggetto)."""
    ids = set()
    for details in SecurityAlertActionLog.objects.filter(
            alert=alert, action__in=("alert_created", "alert_reused", "alert_merged", "cve_termine_scaduto")
    ).values_list("details", flat=True):
        if isinstance(details, dict):
            for chiave in ("event_id",):
                if isinstance(details.get(chiave), int):
                    ids.add(details[chiave])
            for valore in details.get("event_ids") or []:
                if isinstance(valore, int):
                    ids.add(valore)
    if alert.event_id:
        ids.add(alert.event_id)
    return sorted(ids)


def occorrenze(alert):
    """Eventi dello stesso alert: stessa impronta oppure passati dall'alert (chiave per soggetto)."""
    filtro = Q(pk__in=eventi_collegati_ids(alert))
    if alert.dedup_hash:
        filtro |= Q(dedup_hash=alert.dedup_hash)
    return SecurityEventRecord.objects.filter(filtro)


# --- CVE: mail di Defender e inventario -----------------------------------------------------

def alert_inventario_per_cve(cve: str, tipi=TIPI_CVE_INVENTARIO):
    """Alert aperti dell'inventario (PC per PC) su questa CVE."""
    cve = (cve or "").upper()
    if not cve:
        return []
    candidati = (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type__in=tipi,
                                              title__icontains=cve)
                 .select_related("event"))
    return [a for a in candidati if str((a.event.payload or {}).get("cve") or "").upper() == cve]


def alert_impatto_per_cve(cve: str):
    """Alert aperti «PC con versione vulnerabile» su questa CVE: è lì che si segue la correzione PC per PC."""
    return alert_inventario_per_cve(cve, TIPI_CVE_IMPATTO)


def _chiudi_come_doppione(alert, motivo: str, verso=None, azione="alert_merged", event_ids=None):
    vecchio = alert.status
    alert.status = Status.CLOSED
    alert.status_reason = motivo[:2000]
    alert.closed_at = timezone.now()
    alert.snoozed_until = None
    alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
    dettagli = {"old_status": vecchio, "new_status": Status.CLOSED, "reason": motivo, "actor": AUTO_ACTOR}
    if verso is not None:
        dettagli["unito_a"] = verso.pk
    SecurityAlertActionLog.objects.create(alert=alert, action="closed_as_duplicate", actor=AUTO_ACTOR, details=dettagli)
    if verso is not None:
        SecurityAlertActionLog.objects.create(alert=verso, action=azione, actor=AUTO_ACTOR,
                                              details={"da_alert": alert.pk, "event_ids": list(event_ids or []),
                                                       "reason": motivo})
    from security.services import traccia

    traccia.registra(traccia.ALERT_AUTO_RISOLTO, {"alert_id": alert.pk, "titolo": alert.title, "rule": "doppione", **dettagli},
                     oggetto=alert, attore=AUTO_ACTOR)


def chiudi_cve_doppie(apply: bool = True) -> list[dict]:
    """Alert «Vulnerabilità critica esposta» (mail di Defender) la cui CVE è seguita PC per PC dall'inventario."""
    out = []
    for alert in (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type="vulnerability_finding")
                  .select_related("event")):
        cve = str((alert.event.payload or {}).get("cve") or "").upper() or next(iter(_CVE.findall(alert.title or "")), "").upper()
        inventario = alert_inventario_per_cve(cve)
        if not inventario:
            continue
        motivo = (f"Doppione: {cve} è seguita PC per PC dall'inventario ({len(inventario)} alert aperti, "
                  f"es. #{inventario[0].pk} «{inventario[0].title[:80]}»). Si chiude lì, PC per PC.")
        out.append({"alert": alert.pk, "titolo": alert.title, "cve": cve, "inventario": len(inventario)})
        if apply:
            with transaction.atomic():
                _chiudi_come_doppione(alert, motivo, verso=inventario[0], azione="cve_doppione_unito",
                                      event_ids=[alert.event_id] if alert.event_id else [])
    return out


# --- Alert già aperti, uno per mail ---------------------------------------------------------

def unisci_doppioni(apply: bool = False, escludi=()) -> list[dict]:
    """Per ogni (sorgente, PC o job) tiene l'alert aperto più recente e chiude gli altri come uniti a quello.

    L'alert tenuto prende la chiave per soggetto, così le mail successive lo aggiornano invece di aprirne uno nuovo.
    """
    gruppi = defaultdict(list)
    for alert in (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, event__event_type__in=TIPI_PER_SOGGETTO)
                  .exclude(pk__in=list(escludi)).select_related("event").order_by("created_at")):
        chiave = chiave_alert(alert.event)
        if chiave:
            gruppi[(alert.source_id, chiave)].append(alert)
    out = []
    for (_source, chiave), alerts in gruppi.items():
        if len(alerts) == 1 and alerts[0].dedup_hash == chiave:
            continue
        def _quando(a):
            return (a.event.occurred_at or a.created_at, a.created_at, a.pk)
        alerts.sort(key=_quando)
        tenuto, altri = alerts[-1], alerts[:-1]
        out.append({"tenuto": tenuto.pk, "titolo": tenuto.title, "uniti": [a.pk for a in altri]})
        if not apply:
            continue
        with transaction.atomic():
            for alert in altri:
                motivo = f"Unito all'alert #{tenuto.pk} «{tenuto.title[:80]}»: {_stesso_soggetto(alert)}."
                _chiudi_come_doppione(alert, motivo, verso=tenuto, event_ids=[alert.event_id] if alert.event_id else [])
            campi = []
            if tenuto.dedup_hash != chiave:
                tenuto.dedup_hash = chiave
                campi.append("dedup_hash")
            if tenuto.event.event_type == "cve_sla_scaduta":
                from security.services import cve_sla

                tenuto.title = cve_sla.titolo_cve(tenuto.event.payload or {})
                campi.append("title")
            if campi:
                tenuto.save(update_fields=[*campi, "updated_at"])
    return out


def _stesso_soggetto(alert) -> str:
    tipo = alert.event.event_type
    if tipo == "cve_sla_scaduta":
        return "stessa CVE oltre il termine su un altro PC; i PC sono nella timeline dell'alert che resta"
    if tipo == EVENTO_MALWARE or (tipo == "backup_job" and e_report_malware(alert.event.payload)):
        return "altra mail di Veeam sul malware nei backup"
    if tipo == "backup_job":
        return "stesso job (anche come nuovo tentativo), segnalato da un'altra mail"
    return "stesso problema sullo stesso PC, segnalato da un'altra mail"


# --- Rumore: alert che con le regole di adesso non si aprirebbero ----------------------------

def rumore_attivo() -> bool:
    from security.services import soc_settings

    return bool(soc_settings.value("rumore.attivo"))


def autore_fidato(autore: str) -> bool:
    """Chi ha fatto la modifica in Entra è un amministratore fidato: elenco in Impostazioni o amministratore del portale."""
    from security.services import soc_settings

    chi = _norm(autore)
    if not chi or chi == "sconosciuto":
        return False
    if chi in soc_settings.text_list("rumore.entra.autori_fidati"):
        return True
    if not soc_settings.value("rumore.entra.amministratori_portale"):
        return False
    from django.contrib.auth import get_user_model

    locale = chi.split("@", 1)[0]
    utenti = get_user_model().objects.filter(is_active=True, is_superuser=True)
    return utenti.filter(Q(email__iexact=chi) | Q(username__iexact=chi) | Q(username__iexact=locale)).exists()


def _chiudi_rumore(alert, motivo, regola):
    vecchio = alert.status
    alert.status = Status.CLOSED
    alert.status_reason = motivo[:2000]
    alert.closed_at = timezone.now()
    alert.snoozed_until = None
    alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
    dettagli = {"old_status": vecchio, "new_status": Status.CLOSED, "reason": motivo, "actor": AUTO_ACTOR, "regola": regola}
    SecurityAlertActionLog.objects.create(alert=alert, action="closed_as_noise", actor=AUTO_ACTOR, details=dettagli)
    from security.services import traccia

    traccia.registra(traccia.ALERT_AUTO_RISOLTO, {"alert_id": alert.pk, "titolo": alert.title, "rule": regola, **dettagli},
                     oggetto=alert, attore=AUTO_ACTOR)


def chiudi_rumore(apply: bool = False) -> list[dict]:
    """Alert aperti che le regole di adesso non aprirebbero più. Chiusi (non «risolti»), col motivo e nell'audit.

    * dispositivi bloccati dalla policy (chiavette USB) sotto la soglia: restano il conteggio per PC;
    * «oltre il termine» di una CVE che ha già l'alert «PC con versione vulnerabile»: il termine scaduto è
      scritto nella timeline di quello;
    * modifiche di Entra fatte da un amministratore fidato: restano nell'audit di Entra e negli eventi.
    """
    from security.services import soc_settings

    soglia = soc_settings.value("rumore.dispositivi_bloccati.soglia")
    out = []
    for alert in (SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES,
                                               event__event_type__in=("watchguard_alert_candidate", "cve_sla_scaduta", "entra_audit"))
                  .select_related("event").order_by("created_at")):
        payload = alert.event.payload or {}
        tipo = alert.event.event_type
        motivo = regola = ""
        if tipo == "watchguard_alert_candidate" and solo_dispositivi_bloccati(payload):
            if soglia and blocchi_ultime_24h(alert.event) >= soglia:
                continue
            regola = "dispositivi_bloccati"
            motivo = ("Dispositivi bloccati dalla policy di Endpoint Security (es. chiavette USB): la protezione ha funzionato. "
                      "Non è più un alert: il conteggio per PC è in Dispositivi › «Dispositivi bloccati dalla policy».")
        elif tipo == "cve_sla_scaduta":
            impatto = alert_impatto_per_cve(payload.get("cve"))
            if not impatto:
                continue
            regola = "cve_termine_nell_alert_impatto"
            motivo = (f"{payload.get('cve')} oltre il termine su {payload.get('host')}: si segue nell'alert #{impatto[0].pk} "
                      f"«{impatto[0].title[:80]}», che si chiude da solo PC per PC quando la correzione è provata.")
            if apply:
                registra_termine_su_impatto(impatto[0], payload, alert.event_id)
        elif tipo == "entra_audit" and autore_fidato(payload.get("autore")):
            regola = "entra_autore_fidato"
            motivo = (f"Modifica fatta da {payload.get('autore')}, amministratore fidato: resta negli eventi e nell'audit di Entra, "
                      f"senza alert.")
        if not regola:
            continue
        out.append({"alert": alert.pk, "titolo": alert.title, "regola": regola})
        if apply:
            with transaction.atomic():
                _chiudi_rumore(alert, motivo, regola)
    return out


def registra_termine_su_impatto(alert, payload, event_id=None):
    """Il termine di correzione scaduto su un PC, scritto nella timeline dell'alert della CVE (non un alert nuovo)."""
    dettagli = {"cve": payload.get("cve"), "host": payload.get("host"), "scadenza": payload.get("scadenza"),
                "giorni_ritardo": payload.get("giorni_ritardo"), "classe": payload.get("classe")}
    if event_id:
        dettagli["event_id"] = event_id
    SecurityAlertActionLog.objects.create(alert=alert, action="cve_termine_scaduto", actor=AUTO_ACTOR, details=dettagli)


def blocchi_ultime_24h(event) -> int:
    """Dispositivi bloccati sullo stesso PC nelle 24 ore fino a questo evento (tutte le notifiche)."""
    from datetime import timedelta

    quando = event.occurred_at or event.created_at or timezone.now()
    soggetto = soggetto_watchguard(event.payload)
    totale = 0
    for payload in (SecurityEventRecord.objects.filter(source_id=event.source_id, event_type="watchguard_alert_candidate",
                                                       occurred_at__gt=quando - timedelta(hours=24), occurred_at__lte=quando)
                    .values_list("payload", flat=True)):
        if solo_dispositivi_bloccati(payload) and soggetto_watchguard(payload) == soggetto:
            totale += blocchi_della_notifica(payload)
    return totale


def dispositivi_bloccati_per_pc(giorni: int = 30) -> list[dict]:
    """Conteggio dei dispositivi bloccati per PC negli ultimi ``giorni`` (da tutte le notifiche, anche senza alert)."""
    from datetime import timedelta

    da = timezone.now() - timedelta(days=giorni)
    per_pc = {}
    for occorso, payload in (SecurityEventRecord.objects.filter(event_type="watchguard_alert_candidate", occurred_at__gte=da)
                             .values_list("occurred_at", "payload")):
        if not solo_dispositivi_bloccati(payload):
            continue
        pc = str((payload or {}).get("computer") or "").strip() or "Computer non indicato nella mail"
        riga = per_pc.setdefault(pc.lower(), {"pc": pc, "blocchi": 0, "notifiche": 0, "ultima": occorso, "giorni": set()})
        riga["blocchi"] += blocchi_della_notifica(payload)
        riga["notifiche"] += 1
        if occorso and (riga["ultima"] is None or occorso > riga["ultima"]):
            riga["ultima"] = occorso
        if occorso:
            riga["giorni"].add(timezone.localtime(occorso).date())
    righe = []
    for riga in per_pc.values():
        riga["giorni"] = len(riga["giorni"])
        righe.append(riga)
    righe.sort(key=lambda r: (-r["blocchi"], r["pc"].lower()))
    return righe
