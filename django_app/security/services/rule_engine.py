import logging

from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertActionLog, SecurityAlertRuleConfig, SecurityAlertSuppressionRule, SecurityEventRecord, Severity
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.auto_resolution import resolve_backup_recovered, resolve_vulnerability_cleared
from security.services.evidence_builder import build_evidence_container
from security.services.notifications import notify_alert_created
from security.services.ticketing import create_backup_ticket, create_or_update_remediation_ticket_for_vulnerability_finding

logger = logging.getLogger(__name__)


EVALUATION_ERROR = "evaluation_error"


def evaluate_security_rules():
    """Valuta gli eventi non ancora decisi.

    Ogni evento è isolato in un savepoint: prima un solo evento malformato (un payload
    inatteso, un ticket che non si salvava) interrompeva il giro e, restando senza
    decisione, era il primo ripreso al ciclo successivo — dove falliva di nuovo. Nessun
    altro evento veniva più valutato e il SOC sembrava tranquillo. Ora l'evento difettoso
    riceve la decisione ``evaluation_error`` (con l'errore, visibile in «Stato
    elaborazione») e gli altri proseguono.
    """
    evaluated = 0
    for event in SecurityEventRecord.objects.filter(decision_trace={}).order_by("occurred_at"):
        evaluated += 1
        try:
            with transaction.atomic():
                _evaluate_event(event)
        except Exception as exc:  # noqa: BLE001 - un evento difettoso non ferma gli altri
            logger.exception("Valutazione regole fallita sull'evento %s (%s)", event.pk, event.event_type)
            _mark_evaluation_error(event, exc)
    return evaluated


def evaluate_event(event):
    """Valuta subito un solo evento appena creato (es. ``core.eventi_sicurezza.segnala``).

    Stesse regole e stesso isolamento del giro completo, senza scorrere gli altri
    eventi in attesa. Un evento già deciso non si rivaluta.
    """
    if event.decision_trace:
        return False
    try:
        with transaction.atomic():
            _evaluate_event(event)
    except Exception as exc:  # noqa: BLE001 - come nel giro completo
        logger.exception("Valutazione regole fallita sull'evento %s (%s)", event.pk, event.event_type)
        _mark_evaluation_error(event, exc)
    return True


def _mark_evaluation_error(event, exc):
    trace = {
        "decision": EVALUATION_ERROR,
        "reason": "La valutazione delle regole è andata in errore: l'evento va controllato a mano.",
        "error": f"{type(exc).__name__}: {exc}"[:300],
        "at": timezone.now().isoformat(),
    }
    try:
        SecurityEventRecord.objects.filter(pk=event.pk).update(decision_trace=trace)
    except Exception:  # noqa: BLE001 - se neanche questo riesce, il log sopra resta l'unica traccia
        logger.exception("Impossibile registrare l'errore di valutazione sull'evento %s", event.pk)


def _evaluate_event(event):
    suppression = _matching_suppression(event)
    if suppression:
        _mark_suppressed(event, suppression)
        return
    handler = _HANDLERS.get(event.event_type)
    if handler is None and (event.payload or {}).get("evento_portale"):
        handler = _evaluate_evento_portale
    if handler:
        handler(event)
    else:
        event.decision_trace = {"decision": "kpi_only", "reason": "No alert rule matched"}
        event.save(update_fields=["decision_trace"])
    if (event.decision_trace or {}).get("decision") != "alert":
        _apply_learned_escalation(event)


def _apply_learned_escalation(event):
    """Regole apprese (eventi che le persone hanno promosso ad alert): dopo le regole standard."""
    from security.services.event_triage import apply_learned_escalation

    try:
        # Savepoint proprio: un errore di database qui non deve invalidare la valutazione
        # standard già fatta sull'evento (che sta nel savepoint esterno).
        with transaction.atomic():
            apply_learned_escalation(event)
    except Exception:  # noqa: BLE001 - una regola appresa difettosa non ferma la valutazione degli altri eventi
        logger.exception("Regola appresa non applicata all'evento %s", event.pk)


def _matching_suppression(event):
    for rule in SecurityAlertSuppressionRule.objects.filter(is_active=True):
        if rule.matches(event):
            return rule
    return None


def _mark_suppressed(event, rule):
    event.suppressed = True
    event.decision_trace = {"decision": "suppressed_kpi_only", "rule": rule.name, "rule_id": rule.pk, "reason": rule.reason}
    if rule.fingerprint:
        event.decision_trace.update({"learned": True, "fingerprint": rule.fingerprint, "rule_expires_at": rule.expires_at.isoformat() if rule.expires_at else None})
    event.save(update_fields=["suppressed", "decision_trace"])
    rule.hit_count += 1
    rule.last_hit_at = timezone.now()
    rule.save(update_fields=["hit_count", "last_hit_at", "updated_at"])


def _evaluate_vulnerability(event):
    payload = event.payload
    cvss = _as_number(payload.get("cvss"), float)
    critical_rule = _get_rule("defender_critical_cve_cvss_gte_9")
    exposed_rule = _get_rule("defender_critical_cve_exposed_devices_gt_0")
    is_critical = _rule_matches(critical_rule, cvss, payload) if critical_rule else (payload.get("severity") == Severity.CRITICAL or cvss >= 9)
    exposed_count = _as_number(payload.get("exposed_devices"), int)
    exposed = _rule_matches(exposed_rule, exposed_count, payload) if exposed_rule else exposed_count > 0

    # Fail-closed: devices are exposed but neither the score nor the severity could be
    # read. `cvss` above is 0 only because nothing could be parsed - acting on that 0
    # would silently drop a possibly critical CVE. Raise it for manual review instead.
    if not is_critical and exposed and payload.get("cvss_unparsed") and payload.get("severity_unrecognized"):
        _alert_unreadable_vulnerability(event, payload)
        return
    # Stesso principio sul conteggio: CVE critica ma numero di dispositivi illeggibile.
    # Lo 0 della colonna non dice «nessuno esposto», dice «non lo so».
    if is_critical and payload.get("exposed_devices_unparsed"):
        _alert_unreadable_vulnerability(event, payload, exposed_unknown=True)
        return

    if is_critical and exposed:
        trace = {
            "decision": "alert",
            "rule": "CVE Critical/CVSS >= 9/exposed_devices > 0",
            "cvss": payload.get("cvss"),
            "exposed_devices": payload.get("exposed_devices"),
        }
        alert, alert_created = _get_or_create_active_alert(
            source=event.source,
            event=event,
            title=f"Critical exposed vulnerability {payload.get('cve')}",
            severity=(critical_rule.severity if critical_rule else Severity.CRITICAL),
            dedup_hash=event.dedup_hash,
            decision_trace=trace,
        )
        trace["alert_created"] = alert_created
        _store_alert_decision_trace(alert, trace, alert_created)
        event.decision_trace = trace
        event.save(update_fields=["decision_trace"])
        evidence = build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
        create_or_update_remediation_ticket_for_vulnerability_finding(
            event.source,
            alert,
            evidence,
            payload,
            dedup_hash=event.dedup_hash,
        )
        SecurityAlertActionLog.objects.create(
            alert=alert,
            action="alert_created" if alert_created else "alert_reused",
            details=trace,
        )
        if alert_created:
            notify_alert_created(alert)
        _mark_rule_triggered(critical_rule)
        _mark_rule_triggered(exposed_rule)
    else:
        event.decision_trace = {"decision": "kpi_only", "reason": "Vulnerability not both critical and exposed"}
        resolved = resolve_vulnerability_cleared(event)
        if resolved:
            event.decision_trace["auto_resolved_alerts"] = resolved
        event.save(update_fields=["decision_trace"])


def _evaluate_source_silent(event):
    """A source that stopped reporting is an alert. Nothing else in the system can see it:
    every other check reasons about data that arrived."""
    payload = event.payload
    rule = _get_rule("source_silent_beyond_expected")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "Source heartbeat rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return

    trace = {
        "decision": "alert",
        "rule": "Source silent beyond expected cadence => alert",
        "reason": payload.get("detail"),
        "source_code": payload.get("source_code"),
        "expected_every_hours": payload.get("expected_every_hours"),
        "hours_silent": payload.get("hours_silent"),
        "last_report_at": payload.get("last_report_at"),
        "last_run_at": payload.get("last_run_at"),
    }
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=f"Source silent: {payload.get('source_name') or payload.get('source_code')}",
        severity=(rule.severity if rule else Severity.WARNING),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(rule)
    if alert_created:
        notify_alert_created(alert)


def _evaluate_cve_impact(event):
    """PC che l'inventario dice vulnerabili a una CVE critica o sfruttata (CISA KEV): alert per CVE.

    Il ticket si apre solo se acceso in Impostazioni; se la CVE ha già un ticket aperto (per
    esempio da Defender) l'alert si collega a quello, senza un secondo ticket per lo stesso rimedio.
    """
    from security.services import cve_chiusura, soc_settings

    payload = event.payload
    rule = _get_rule("cve_impact_confirmed")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "CVE impact rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return
    cve = (payload.get("cve") or "").upper()
    # Versione vulnerabile ricomparsa dopo una chiusura automatica recente: si riapre lo stesso alert (recidiva).
    recidiva = cve_chiusura.riapri_recidiva(event)
    trace = {
        "decision": "alert",
        "rule": "Inventario: PC con versione vulnerabile di una CVE critica o in CISA KEV => alert",
        "cve": cve,
        "cvss": payload.get("cvss"),
        "kev": payload.get("kev"),
        "impacted_count": payload.get("impacted_count"),
        "new_hosts": payload.get("new_hosts"),
        "inventory_date": payload.get("inventory_date"),
        "recidiva": recidiva is not None,
    }
    impacted_count = payload.get("impacted_count") or 0
    title = cve_chiusura.titolo_alert(payload, impacted_count, impacted_count)
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=title,
        severity=(rule.severity if rule else Severity.CRITICAL),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    if not alert_created:
        # «N PC su M ancora»: conta anche i PC già usciti dopo la nascita dell'alert.
        alert.title = cve_chiusura.titolo_progresso(alert, payload)
        alert.save(update_fields=["title", "updated_at"])
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    evidence = build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    if soc_settings.value("cve.impatto.ticket"):
        _ticket_for_cve_impact(event, alert, evidence, payload, cve)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(rule)
    if alert_created:
        notify_alert_created(alert)


def _evaluate_software_policy(event):
    """Software non autorizzato, da rimuovere o sotto la versione minima secondo il Catalogo software."""
    payload = event.payload
    rule = _get_rule("software_policy")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "Software policy rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Catalogo software: prodotto non conforme presente su PC => alert",
        "kind": payload.get("kind"),
        "product": payload.get("product"),
        "host_count": payload.get("host_count"),
        "new_hosts": payload.get("new_hosts"),
        "min_version": payload.get("min_version"),
    }
    title = f"{payload.get('product')}: {payload.get('kind_label')} su {payload.get('host_count')} PC"[:255]
    alert, alert_created = _get_or_create_active_alert(
        source=event.source, event=event, title=title,
        severity=(rule.severity if rule else event.severity), dedup_hash=event.dedup_hash, decision_trace=trace,
    )
    if not alert_created and alert.title != title:
        alert.title = title
        alert.save(update_fields=["title", "updated_at"])
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(alert=alert, action="alert_created" if alert_created else "alert_reused", details=trace)
    _mark_rule_triggered(rule)
    if alert_created:
        notify_alert_created(alert)


def _evaluate_defender_alert(event):
    """Alert di Microsoft Defender (``defender_alerts``): uno per id di Defender.

    Risolto in Defender → chiude l'alert attivo del SOC (se c'è). Sotto la severità
    minima scelta in /soc/impostazioni/ → resta un evento (KPI). Altrimenti apre o
    aggiorna l'alert del SOC con lo stesso dedup.
    """
    from security.services import defender_alerts
    from security.services.auto_resolution import resolve_alert

    payload = event.payload or {}
    if payload.get("status_defender") in defender_alerts.RESOLVED_STATUSES:
        alert = _active_alert(event.source, event.dedup_hash)
        trace = {"decision": "resolved_upstream", "reason": "Alert risolto in Microsoft Defender",
                 "classification": payload.get("classification")}
        if alert:
            resolve_alert(alert, "Risolto in Microsoft Defender", evidence_event=event, rule_code=defender_alerts.EVENT_TYPE)
            trace["alert_id"] = alert.pk
        event.decision_trace = trace
        event.save(update_fields=["decision_trace"])
        return
    if not defender_alerts.meets_threshold(event.severity):
        event.decision_trace = {"decision": "kpi_only", "reason": "Sotto la severità minima scelta per Defender",
                                "severity": event.severity}
        event.save(update_fields=["decision_trace"])
        return
    if payload.get("incident_id") and soc_settings_value("defender.incidenti.attivo"):
        # Raggruppamento per incidente: l'alert del SOC è quello dell'incidente (defender_incident).
        event.decision_trace = {"decision": "kpi_only", "reason": "Raggruppato nell'incidente di Defender",
                                "incident_id": payload.get("incident_id")}
        event.save(update_fields=["decision_trace"])
        return
    devices = payload.get("devices") or []
    trace = {
        "decision": "alert",
        "rule": "Microsoft Defender: alert sopra la severità minima => alert",
        "defender_id": payload.get("defender_id"),
        "status_defender": payload.get("status_defender"),
        "category": payload.get("category"),
        "devices": devices,
        "web_url": payload.get("web_url"),
    }
    where = f" su {devices[0]}" if len(devices) == 1 else (f" su {len(devices)} dispositivi" if devices else "")
    title = f"Defender: {payload.get('title')}{where}"[:255]
    alert, alert_created = _get_or_create_active_alert(
        source=event.source, event=event, title=title, severity=event.severity,
        dedup_hash=event.dedup_hash, decision_trace=trace,
    )
    if not alert_created and (alert.severity != event.severity or alert.title != title):
        alert.severity = event.severity
        alert.title = title
        alert.save(update_fields=["severity", "title", "updated_at"])
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(alert=alert, action="alert_created" if alert_created else "alert_reused", details=trace)
    if alert_created:
        notify_alert_created(alert)


def _alert_da_evento(event, title, severity, trace):
    """Apre o riusa l'alert del SOC per un evento (stesso dedup), con traccia e notifica."""
    alert, alert_created = _get_or_create_active_alert(
        source=event.source, event=event, title=title[:255], severity=severity,
        dedup_hash=event.dedup_hash, decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(alert=alert, action="alert_created" if alert_created else "alert_reused", details=trace)
    if alert_created:
        notify_alert_created(alert)


def _evaluate_apparato_irraggiungibile(event):
    """Apparato di rete di Contatori IT senza risposta (``contatori.soc``): un alert per apparato."""
    payload = event.payload or {}
    if not soc_settings_value("apparati.irraggiungibile.alert"):
        event.decision_trace = {"decision": "kpi_only", "reason": "Alert sugli apparati di rete spenti in /soc/impostazioni/"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Apparato di rete senza risposta SNMP per più controlli consecutivi => alert",
        "apparato": payload.get("apparato"),
        "host": payload.get("host"),
        "errore": payload.get("errore"),
        "controlli": payload.get("controlli_senza_risposta"),
    }
    _alert_da_evento(event, f"Apparato non raggiungibile: {payload.get('apparato')} ({payload.get('categoria')}, "
                            f"{payload.get('host')})", event.severity, trace)


def _evaluate_apparato_raggiungibile(event):
    """L'apparato risponde di nuovo: chiude l'alert di caduta (stesso dedup)."""
    from security.services.auto_resolution import resolve_alert

    alert = _active_alert(event.source, event.dedup_hash)
    trace = {"decision": "resolved_upstream", "reason": "L'apparato risponde di nuovo al monitoraggio SNMP"}
    if alert is not None:
        resolve_alert(alert, "L'apparato risponde di nuovo al monitoraggio SNMP di Contatori IT.",
                      evidence_event=event, rule_code="apparato_raggiungibile")
        trace["alert_id"] = alert.pk
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])


def _evaluate_backup_repository_space(event):
    """Repository di Veeam sotto la soglia di spazio libero (``veeam_api``): un alert per repository.

    Lo stesso evento con ``sotto_soglia`` falso (spazio tornato sopra) chiude l'alert.
    """
    from security.services.auto_resolution import resolve_alert

    payload = event.payload or {}
    if not payload.get("sotto_soglia"):
        alert = _active_alert(event.source, event.dedup_hash)
        trace = {"decision": "resolved_upstream", "reason": "Spazio libero del repository tornato sopra la soglia",
                 "free_pct": payload.get("free_pct")}
        if alert is not None:
            resolve_alert(alert, f"Spazio libero tornato al {payload.get('free_pct')}% (soglia {payload.get('soglia_pct')}%).",
                          evidence_event=event, rule_code="backup_repository_space")
            trace["alert_id"] = alert.pk
        event.decision_trace = trace
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Repository di backup Veeam sotto la soglia di spazio libero => alert",
        "repository": payload.get("repository"),
        "host": payload.get("host"),
        "free_gb": payload.get("free_gb"),
        "free_pct": payload.get("free_pct"),
        "soglia_pct": payload.get("soglia_pct"),
    }
    _alert_da_evento(event, f"Repository di backup quasi pieno: {payload.get('repository')} "
                            f"({payload.get('free_pct')}% libero, {payload.get('free_gb')} GB)", event.severity, trace)


def _evaluate_cve_sla_scaduta(event):
    """PC esposto a una CVE oltre il termine di correzione (ISO 27001 8.8, ``cve_sla``): un alert per CVE, PC e termine.

    Severità alta per CVE sfruttate (KEV) o critiche, media per le altre (dall'evento, o dalla
    regola facoltativa ``cve_sla_scaduta`` se definita). Si chiude da solo quando l'esposizione
    rientra o viene accettata (``cve_sla.chiudi_rientrate``).
    """
    from security.services import cve_sla

    payload = event.payload or {}
    rule = _get_rule(cve_sla.EVENT_SLA)
    if not soc_settings_value("cve.sla.attivo") or (rule and not rule.enabled):
        event.decision_trace = {"decision": "kpi_only", "reason": "Segnalazione dei termini di correzione spenta in /soc/impostazioni/"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Esposizione a una CVE oltre il termine di correzione della sua classe => alert",
        "cve": payload.get("cve"), "host": payload.get("host"), "classe": payload.get("classe"),
        "scadenza": payload.get("scadenza"), "giorni_ritardo": payload.get("giorni_ritardo"), "aperta_dal": payload.get("aperta_dal"),
    }
    _alert_da_evento(event, cve_sla.titolo_evento(payload), rule.severity if rule else event.severity, trace)
    _mark_rule_triggered(rule)


def _evaluate_accettazione_rischio(event):
    """Accettazione del rischio in scadenza o scaduta (``accettazione_rischio``): un alert di attenzione per fase."""
    from security.services import accettazione_rischio

    payload = event.payload or {}
    if not soc_settings_value("cve.sla.accettazione_alert"):
        event.decision_trace = {"decision": "kpi_only", "reason": "Alert sulle accettazioni del rischio spenti in /soc/impostazioni/"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Accettazione del rischio in scadenza o scaduta => alert",
        "accettazione_id": payload.get("accettazione_id"), "fase": payload.get("fase"), "cve": payload.get("cve"),
        "host": payload.get("host"), "scadenza": payload.get("scadenza"),
    }
    _alert_da_evento(event, accettazione_rischio.titolo_evento(payload), event.severity, trace)


def _evaluate_backup_restore_test_failed(event):
    """Prova di ripristino fallita (``services.ripristini``, ISO 27001 8.13): un alert alto per prova."""
    payload = event.payload or {}
    trace = {
        "decision": "alert",
        "rule": "Prova di ripristino del backup fallita => alert",
        "sistema": payload.get("sistema"),
        "job": payload.get("job"),
        "data": payload.get("data"),
        "prova_id": payload.get("prova_id"),
    }
    _alert_da_evento(event, f"Prova di ripristino fallita: {payload.get('sistema') or 'sistema non indicato'}"
                            f"{' (' + payload['job'] + ')' if payload.get('job') else ''}", Severity.HIGH, trace)


def soc_settings_value(key):
    from security.services import soc_settings

    return soc_settings.value(key)


def _evaluate_defender_incident(event):
    """Incidente di Microsoft Defender (alert correlati): un alert del SOC per incidente."""
    from security.services import defender_alerts
    from security.services.auto_resolution import resolve_alert

    payload = event.payload or {}
    if payload.get("status_defender") in defender_alerts.RESOLVED_STATUSES:
        alert = _active_alert(event.source, event.dedup_hash)
        trace = {"decision": "resolved_upstream", "reason": "Incidente risolto in Microsoft Defender"}
        if alert:
            resolve_alert(alert, "Incidente risolto in Microsoft Defender", evidence_event=event,
                          rule_code=defender_alerts.EVENT_INCIDENT)
            trace["alert_id"] = alert.pk
        event.decision_trace = trace
        event.save(update_fields=["decision_trace"])
        return
    if not defender_alerts.meets_threshold(event.severity):
        event.decision_trace = {"decision": "kpi_only", "reason": "Sotto la severità minima scelta per Defender",
                                "severity": event.severity}
        event.save(update_fields=["decision_trace"])
        return
    trace = {"decision": "alert", "rule": "Microsoft Defender: incidente sopra la severità minima => alert",
             "incident_id": payload.get("incident_id"), "status_defender": payload.get("status_defender"),
             "web_url": payload.get("web_url")}
    _alert_da_evento(event, f"Defender: incidente «{payload.get('title')}»", event.severity, trace)


def _evaluate_accesso_nuovo_dispositivo(event):
    """Accesso al portale da un dispositivo nuovo (core.dispositivi): solo KPI, la persona è già avvisata."""
    event.decision_trace = {"decision": "kpi_only", "reason": "Accesso da un dispositivo nuovo: avvisata la persona"}
    event.save(update_fields=["decision_trace"])


def _evaluate_accesso_non_riconosciuto(event):
    """La persona ha premuto «Non ero io» su un accesso: alert alto."""
    payload = event.payload or {}
    trace = {"decision": "alert", "rule": "Accesso al portale non riconosciuto dalla persona => alert",
             "utente": payload.get("utente"), "dispositivo": payload.get("dispositivo"), "ip": payload.get("ip")}
    _alert_da_evento(event, f"Accesso al portale non riconosciuto: {payload.get('utente')} da {payload.get('dispositivo')} "
                            f"({payload.get('ip')})", Severity.HIGH, trace)


def _evaluate_evento_portale(event):
    """Evento del catalogo ``core.eventi_sicurezza``: alert se il tipo lo prevede e l'interruttore è acceso."""
    from core.eventi_sicurezza import TIPI, chiave_interruttore

    payload = event.payload or {}
    tipo = TIPI.get(event.event_type)
    if tipo is None or not tipo.alert:
        event.decision_trace = {"decision": "kpi_only", "reason": "Evento del portale senza alert previsto"}
        event.save(update_fields=["decision_trace"])
        return
    if tipo.interruttore and not soc_settings_value(chiave_interruttore(tipo.codice)):
        event.decision_trace = {"decision": "kpi_only",
                                "reason": "Alert spento in /soc/impostazioni/ (Eventi di sicurezza del portale)"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {"decision": "alert", "rule": f"Portale: {tipo.etichetta} => alert",
             "utente": payload.get("utente"), "ip": payload.get("ip"), "dettaglio": payload.get("dettaglio")}
    _alert_da_evento(event, payload.get("titolo") or tipo.etichetta, event.severity, trace)


def _evaluate_m365_account_cessato(event):
    """Account Microsoft 365 abilitato di un ex dipendente (``entra_signals``): un alert per account."""
    payload = event.payload or {}
    trace = {
        "decision": "alert",
        "rule": "Account Microsoft 365 abilitato di una persona con data di cessazione passata => alert",
        "upn": payload.get("upn"),
        "cessato_il": payload.get("cessato_il"),
    }
    chi = payload.get("persona") or payload.get("account") or payload.get("upn")
    _alert_da_evento(event, f"Account Microsoft 365 attivo di un ex dipendente: {chi}", Severity.HIGH, trace)


def _evaluate_entra_audit(event):
    """Modifica amministrativa sorvegliata in Entra ID (``entra_signals``): un alert per riga di audit."""
    payload = event.payload or {}
    trace = {
        "decision": "alert",
        "rule": "Entra ID: attività amministrativa sorvegliata => alert",
        "attivita": payload.get("attivita"),
        "autore": payload.get("autore"),
        "target": payload.get("target"),
        "esito": payload.get("esito"),
    }
    target = (payload.get("target") or [""])[0]
    title = f"Entra: {payload.get('etichetta')}" + (f" ({target})" if target else "") + f" da {payload.get('autore')}"
    _alert_da_evento(event, title, event.severity, trace)


def _evaluate_entra_accesso(event):
    """Accesso sospetto a Microsoft 365 (``entra_signals``): un alert per anomalia (dedup giornaliero)."""
    payload = event.payload or {}
    trace = {
        "decision": "alert",
        "rule": "Entra ID: accesso sospetto (falliti a raffica, Paese non ammesso, protocollo vecchio) => alert",
        "motivo": payload.get("motivo"),
        "upn": payload.get("upn"),
        "dettaglio": payload.get("dettaglio"),
        "ip": payload.get("ip"),
    }
    title = f"{payload.get('etichetta')}: {payload.get('upn')} ({payload.get('dettaglio')})"
    _alert_da_evento(event, title, event.severity, trace)


def _evaluate_registro_log(event):
    """Evento del Registro accessi (``registro_log.ciclo``): un alert per evento, già filtrato dagli interruttori."""
    payload = event.payload or {}
    trace = {
        "decision": "alert",
        "rule": "Registro accessi: evento importante o interruzione della raccolta => alert",
        "motivo": payload.get("motivo"),
        "host": payload.get("host"),
        "account": payload.get("account"),
        "ip": payload.get("ip"),
    }
    _alert_da_evento(event, payload.get("titolo") or "Registro accessi", event.severity, trace)


def _ticket_for_cve_impact(event, alert, evidence, payload, cve):
    from security.models import SecurityRemediationTicket
    from security.services.ticketing import ACTIVE_TICKET_STATUSES

    active = SecurityRemediationTicket.objects.filter(status__in=ACTIVE_TICKET_STATUSES).order_by("-updated_at")
    existing = active.filter(cve=cve).first() or next((t for t in active[:300] if cve in (t.cve_ids or [])), None)
    if existing:
        existing.linked_alerts.add(alert)
        if evidence:
            existing.evidence.add(evidence)
        SecurityAlertActionLog.objects.create(alert=alert, ticket=existing, action="ticket_linked_existing_cve",
                                              details={"cve": cve, "impacted_count": payload.get("impacted_count")})
        return existing
    ticket, _created = create_or_update_remediation_ticket_for_vulnerability_finding(
        event.source, alert, evidence,
        {"cve": cve, "affected_product": payload.get("affected_product") or "", "source": "inventario",
         "cvss": payload.get("cvss") or 0, "exposed_devices": payload.get("impacted_count") or 0,
         "severity": Severity.CRITICAL},
        dedup_hash=event.dedup_hash,
    )
    return ticket


def _evaluate_sender_spoofing(event):
    """A mail that looks like a trusted vendor's report from an untrusted sender.

    The provenance gate already refused to parse it (fail-closed). Refusing silently,
    though, hid a phishing/spoofing attempt aimed at the SOC mailbox: raise it instead.
    """
    payload = event.payload
    rule = _get_rule("possible_sender_spoofing")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "Sender spoofing rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "Vendor-looking report from untrusted sender => alert (not parsed)",
        "reason": payload.get("detail"),
        "claimed_vendor": payload.get("claimed_vendor"),
        "sender": payload.get("sender"),
        "sender_domain": payload.get("sender_domain"),
    }
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=f"Possible sender spoofing: {payload.get('claimed_vendor') or 'vendor'} report from {payload.get('sender_domain') or 'unknown domain'}",
        severity=(rule.severity if rule else Severity.WARNING),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(rule)
    if alert_created:
        notify_alert_created(alert)


def _alert_unreadable_vulnerability(event, payload, exposed_unknown=False):
    """Alert on a vulnerability we could not read, rather than scoring it 0 and moving on."""
    if exposed_unknown:
        trace = {
            "decision": "alert",
            "rule": "Critical vulnerability with unreadable exposed devices count => fail-closed manual review",
            "reason": "La CVE è critica ma il numero di dispositivi esposti non è leggibile: NON viene considerato 0",
            "cve": payload.get("cve"),
            "cvss": payload.get("cvss"),
            "exposed_devices_unparsed": True,
        }
    else:
        trace = {
            "decision": "alert",
            "rule": "Vulnerability data unreadable while devices are exposed => fail-closed manual review",
            "reason": "Neither CVSS nor severity could be parsed; the score is NOT assumed to be 0",
            "cve": payload.get("cve"),
            "exposed_devices": payload.get("exposed_devices"),
            "cvss_unparsed": True,
            "severity_unrecognized": True,
        }
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=f"Unreadable vulnerability data for {payload.get('cve') or 'unknown CVE'} (manual review)",
        severity=Severity.HIGH,
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    # Evidence, so the operator can see the raw excerpt that defeated the parser. No
    # remediation ticket: the data is not trustworthy enough to drive remediation.
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    if alert_created:
        notify_alert_created(alert)


def _evaluate_backup(event):
    status = event.payload.get("status", "").lower()
    if status == "completed":
        event.decision_trace = {"decision": "kpi_only", "rule": "Backup completed => KPI only"}
        resolved = resolve_backup_recovered(event)
        if resolved:
            event.decision_trace["auto_resolved_alerts"] = resolved
        event.save(update_fields=["decision_trace"])
        return
    if status == "unknown":
        event.decision_trace = {"decision": "diagnostic_event", "rule": "Backup status unknown => diagnostic only"}
        event.save(update_fields=["decision_trace"])
        return
    failed_rule = _get_rule("backup_failed_gt_0")
    if failed_rule and not failed_rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "Backup failure rule disabled"}
        event.save(update_fields=["decision_trace"])
        return
    trace = {"decision": "alert", "rule": "Backup missing/failed => alert + evidence", "backup_status": status}
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=f"Backup job requires attention: {event.payload.get('job_name')}",
        severity=(failed_rule.severity if failed_rule else Severity.WARNING),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    evidence = build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    create_backup_ticket(event.source, alert, evidence, event.payload.get("job_name"), event.dedup_hash)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(failed_rule)


def _evaluate_vpn(event):
    window_start = timezone.now() - timezone.timedelta(hours=1)
    count = SecurityEventRecord.objects.filter(
        source=event.source,
        event_type=event.event_type,
        occurred_at__gte=window_start,
    ).aggregate(total=Count("id"))["total"]
    threshold = int(event.payload.get("threshold", 10))
    if count > threshold:
        trace = {"decision": "alert", "rule": "VPN reconnect spike above threshold", "count": count, "threshold": threshold}
        alert, alert_created = _get_or_create_active_alert(
            source=event.source,
            event=event,
            title="VPN authentication spike detected",
            severity=Severity.WARNING,
            dedup_hash=event.dedup_hash,
            decision_trace=trace,
        )
        trace["alert_created"] = alert_created
        _store_alert_decision_trace(alert, trace, alert_created)
        SecurityAlertActionLog.objects.create(
            alert=alert,
            action="alert_created" if alert_created else "alert_reused",
            details=trace,
        )
        if alert_created:
            notify_alert_created(alert)
        event.decision_trace = trace
    else:
        event.decision_trace = {"decision": "kpi_only", "reason": "VPN volume below threshold", "count": count, "threshold": threshold}
    event.save(update_fields=["decision_trace"])


def _evaluate_watchguard_alert_candidate(event):
    payload = event.payload
    candidate_type = payload.get("type") or ""
    rule = _get_rule(candidate_type) or _get_rule("watchguard_botnet_detected_gt_baseline")
    if rule and not rule.enabled:
        event.decision_trace = {"decision": "kpi_only", "reason": "WatchGuard alert rule disabled", "rule": rule.code}
        event.save(update_fields=["decision_trace"])
        return
    trace = {
        "decision": "alert",
        "rule": "WatchGuard parser-generated anti-noise alert candidate",
        "candidate_type": payload.get("type"),
        "reason": payload.get("reason"),
    }
    alert, alert_created = _get_or_create_active_alert(
        source=event.source,
        event=event,
        title=payload.get("title") or "WatchGuard alert candidate",
        severity=(rule.severity if rule else payload.get("severity", Severity.WARNING)),
        dedup_hash=event.dedup_hash,
        decision_trace=trace,
    )
    trace["alert_created"] = alert_created
    _store_alert_decision_trace(alert, trace, alert_created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    SecurityAlertActionLog.objects.create(
        alert=alert,
        action="alert_created" if alert_created else "alert_reused",
        details=trace,
    )
    _mark_rule_triggered(rule)


def test_alert_rule(rule, metrics):
    value = metrics.get(rule.metric_name) if rule.metric_name else metrics.get("value")
    return _rule_matches(rule, value, metrics)


def _get_rule(code):
    try:
        return SecurityAlertRuleConfig.objects.get(code=code)
    except SecurityAlertRuleConfig.DoesNotExist:
        return None


def _rule_matches(rule, value, payload):
    if not rule or not rule.enabled:
        return False
    if rule.code == "defender_critical_cve_cvss_gte_9" and payload.get("severity") == Severity.CRITICAL:
        return True
    threshold = rule.threshold_value
    operator = rule.condition_operator
    if threshold == "" and rule.threshold_json:
        threshold = rule.threshold_json.get("value", "")
    try:
        numeric_value = float(value or 0)
        numeric_threshold = float(threshold or 0)
    except (TypeError, ValueError):
        numeric_value = None
        numeric_threshold = None
    if operator == "gt":
        return numeric_value is not None and numeric_value > numeric_threshold
    if operator == "gte":
        return numeric_value is not None and numeric_value >= numeric_threshold
    if operator == "lt":
        return numeric_value is not None and numeric_value < numeric_threshold
    if operator == "lte":
        return numeric_value is not None and numeric_value <= numeric_threshold
    if operator == "eq":
        return str(value) == str(threshold)
    if operator == "neq":
        return str(value) != str(threshold)
    if operator == "contains":
        return str(threshold).lower() in str(value).lower()
    if operator == "regex":
        import re

        return bool(re.search(str(threshold), str(value), re.I))
    if operator == "baseline_deviation":
        baseline = float(rule.threshold_json.get("baseline", 0) or 0)
        deviation = float(rule.threshold_json.get("deviation", numeric_threshold or 0) or 0)
        return numeric_value is not None and baseline and abs(numeric_value - baseline) >= deviation
    return False


def _mark_rule_triggered(rule):
    if not rule:
        return
    rule.last_triggered_at = timezone.now()
    rule.trigger_count += 1
    rule.save(update_fields=["last_triggered_at", "trigger_count", "updated_at"])


def _active_alert(source, dedup_hash):
    return (
        SecurityAlert.objects.filter(source=source, dedup_hash=dedup_hash, status__in=ACTIVE_ALERT_STATUSES)
        .order_by("-updated_at")
        .first()
    )


def _get_or_create_active_alert(source, event, title, severity, dedup_hash, decision_trace):
    """Check-then-create is a race. Let the database settle it.

    Two workers evaluating the same finding concurrently both used to read "no alert yet"
    and both created one. The partial unique index on (source, dedup_hash) over active
    statuses now makes the second INSERT fail; losing that race is not an error, it means
    somebody else just created the alert we were about to create, so we adopt theirs.
    """
    alert = _active_alert(source, dedup_hash)
    if alert:
        alert.event = event
        alert.save(update_fields=["event", "updated_at"])
        return alert, False

    try:
        with transaction.atomic():
            alert = SecurityAlert.objects.create(
                source=source,
                event=event,
                title=title,
                severity=severity,
                dedup_hash=dedup_hash,
                decision_trace=decision_trace,
            )
        return alert, True
    except IntegrityError:
        alert = _active_alert(source, dedup_hash)
        if alert is None:
            raise  # the constraint fired for some other reason: do not swallow it
        logger.info("Lost the alert creation race for dedup %s; adopting the existing alert", dedup_hash[:12])
        alert.event = event
        alert.save(update_fields=["event", "updated_at"])
        return alert, False


def _store_alert_decision_trace(alert, trace, alert_created):
    if alert_created:
        alert.decision_trace = trace
    else:
        alert.decision_trace = {**alert.decision_trace, "latest_decision": trace}
    alert.save(update_fields=["decision_trace", "updated_at"])

def _as_number(value, kind):
    """Numero dal payload, 0 se assente o illeggibile («n/d», None, testo).

    Prima ``int(payload["exposed_devices"])`` su un valore None o testuale sollevava e
    interrompeva la valutazione. I flag ``*_unparsed`` del parser dicono quando lo 0 non è
    un dato vero: le regole leggono quelli.
    """
    try:
        return kind(float(value or 0))
    except (TypeError, ValueError):
        return kind(0)


_HANDLERS = {
    "vulnerability_finding": _evaluate_vulnerability,
    "backup_job": _evaluate_backup,
    "vpn_auth_denied": _evaluate_vpn,
    "vpn_auth_allowed": _evaluate_vpn,
    "watchguard_alert_candidate": _evaluate_watchguard_alert_candidate,
    "source_silent": _evaluate_source_silent,
    "possible_sender_spoofing": _evaluate_sender_spoofing,
    "cve_impact_confirmed": _evaluate_cve_impact,
    "software_policy": _evaluate_software_policy,
    "defender_alert": _evaluate_defender_alert,
    "defender_incident": _evaluate_defender_incident,
    "accesso_nuovo_dispositivo": _evaluate_accesso_nuovo_dispositivo,
    "accesso_non_riconosciuto": _evaluate_accesso_non_riconosciuto,
    "m365_account_cessato": _evaluate_m365_account_cessato,
    "entra_audit": _evaluate_entra_audit,
    "entra_accesso": _evaluate_entra_accesso,
    "registro_log": _evaluate_registro_log,
    "apparato_irraggiungibile": _evaluate_apparato_irraggiungibile,
    "apparato_raggiungibile": _evaluate_apparato_raggiungibile,
    "backup_repository_space": _evaluate_backup_repository_space,
    "cve_sla_scaduta": _evaluate_cve_sla_scaduta,
    "accettazione_rischio": _evaluate_accettazione_rischio,
    "backup_restore_test_failed": _evaluate_backup_restore_test_failed,
}