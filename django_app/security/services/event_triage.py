"""Eventi ingeriti: elenco, decisione del motore e promozione ad alert («era un allarme vero»).

Ogni riga letta dai report diventa un `SecurityEventRecord`; il motore regole decide se farne un
alert o tenerla solo come statistica. Qui chi gestisce il SOC vede TUTTI gli eventi e, se il motore
ha giudicato «tutto ok» qualcosa che era un allarme, lo promuove ad alert.

La promozione insegna, in due modi:
- deterministico: una `SecurityEscalationRule` (regola appresa) fa creare l'alert da solo, d'ora in
  poi, agli eventi con lo stesso tipo e gli stessi valori scelti (stesso computer, stesso job...);
- AI locale: la decisione finisce nel registro `ai_assistant.apprendimento` (le proposte dell'AI
  confrontate con cio' che le persone decidono) e gli allarmi mancati entrano nel contesto con cui
  l'AI giudica i prossimi eventi, come sezione esplicita «DA TRATTARE COME ALLARME».
"""
import json
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q, TextField
from django.db.models.functions import Cast, TruncDate
from django.utils import timezone

from security.models import (
    SecurityAlert, SecurityAlertActionLog, SecurityEscalationRule, SecurityEventRecord, Severity,
)
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

logger = logging.getLogger(__name__)

AI_MODULE = "soc"
AI_ACTION_TRIAGE = "triage_evento"     # proposte dell'AI («e' un allarme?») vs decisione della persona
AI_ACTION_ENGINE = "motore_evento"     # decisioni del motore regole corrette dalle persone

DECISIONS = [
    ("alert", "Alert creato"),
    ("ok", "Giudicato a posto"),
    ("suppressed", "Silenziato da regola"),
    ("diagnostic", "Diagnostica"),
    ("pending", "Da valutare"),
]
DECISION_LABELS = dict(DECISIONS)
DECISION_HELP = {
    "alert": "Il motore (o una persona) ne ha fatto un alert",
    "ok": "Il motore l'ha tenuto solo come statistica: nessuna regola l'ha giudicato un problema",
    "suppressed": "Scartato da una regola di soppressione scritta da una persona",
    "diagnostic": "Dato tecnico incompleto (es. esito backup non leggibile)",
    "pending": "Arrivato ma non ancora passato dal motore regole",
}

# Campi del payload utili per riconoscere «lo stesso fatto» (proposti come firma della regola appresa).
SIGNATURE_KEYS = (
    ("type", "Tipo di segnalazione"), ("computer", "Computer"), ("device_name", "Dispositivo"), ("job_name", "Job di backup"),
    ("user", "Utente"), ("username", "Utente"), ("source_ip", "IP di origine"), ("ip", "IP"), ("cve", "CVE"),
    ("affected_product", "Prodotto"), ("status", "Esito"), ("nas_name", "NAS"), ("firebox_name", "Firewall"),
    ("interface", "Interfaccia"), ("group", "Gruppo"), ("claimed_vendor", "Si presenta come"), ("sender_domain", "Dominio mittente"),
)
# Campi che di solito identificano il fatto (pre-selezionati); gli altri si possono aggiungere.
_DEFAULT_SIGNATURE = {"type", "computer", "device_name", "job_name", "cve", "user", "username"}
_SUMMARY_KEYS = ("title", "reason", "job_name", "computer", "device_name", "user", "username", "cve", "affected_product", "detail")


def decision_of(event):
    trace = event.decision_trace or {}
    decision = trace.get("decision", "")
    if decision == "alert":
        return "alert"
    if event.suppressed or decision == "suppressed_kpi_only":
        return "suppressed"
    if decision == "diagnostic_event":
        return "diagnostic"
    if not trace:
        return "pending"
    return "ok"


def event_summary(event):
    payload = event.payload or {}
    parts = []
    for key in _SUMMARY_KEYS:
        value = payload.get(key)
        if value not in (None, "", [], {}) and not isinstance(value, (dict, list)):
            text = str(value).strip()
            if text and not any(text.casefold() in part.casefold() for part in parts):
                parts.append(text)
        if len(parts) >= 3:
            break
    return " · ".join(parts)[:220]


def decorate(events):
    events = list(events)
    active = set(
        SecurityAlert.objects.filter(event_id__in=[e.pk for e in events]).values_list("event_id", flat=True)
    )
    for event in events:
        event.decision_code = decision_of(event)
        event.decision_label = DECISION_LABELS[event.decision_code]
        event.summary = event_summary(event)
        event.has_alert = event.pk in active
    return events


def filter_events(params, today=None):
    """Queryset filtrato + valori dei filtri effettivi (periodo di default: 7 giorni)."""
    today = today or timezone.localdate()
    qs = SecurityEventRecord.objects.select_related("source", "report", "asset")
    f = {key: (params.get(key) or "").strip() for key in ("q", "source", "severity", "decision", "type", "from", "to", "giorno")}
    try:
        days = int(params.get("giorni") or 7)
    except ValueError:
        days = 7
    days = days if days in (1, 7, 30, 90) else 7
    day_from, day_to = _day(f["from"]), _day(f["to"])
    custom = bool(day_from or day_to)
    if not custom:
        day_to, day_from = today, today - timedelta(days=days - 1)
    day_from, day_to = day_from or day_to - timedelta(days=89), day_to or today
    selected_day = _day(f["giorno"])
    if selected_day and not (day_from <= selected_day <= day_to):
        # Giorno arrivato da un altro grafico (es. KPI a una data passata): il periodo lo segue.
        span = (day_to - day_from).days
        day_to, day_from = selected_day, selected_day - timedelta(days=span)
        custom = True
    qs = qs.filter(occurred_at__date__gte=day_from, occurred_at__date__lte=day_to)
    if f["source"].isdigit():
        qs = qs.filter(source_id=int(f["source"]))
    if f["severity"] in {value for value, _ in Severity.choices}:
        qs = qs.filter(severity=f["severity"])
    if f["type"]:
        qs = qs.filter(event_type=f["type"])
    if f["q"]:
        qs = qs.annotate(_payload_text=Cast("payload", TextField())).filter(
            Q(event_type__icontains=f["q"]) | Q(_payload_text__icontains=f["q"]) | Q(asset__hostname__icontains=f["q"])
        )
    period_qs = qs
    if selected_day:
        qs = qs.filter(occurred_at__date=selected_day)
    qs = _filter_decision(qs, f["decision"])
    return {
        "qs": qs.order_by("-occurred_at", "-id"), "period_qs": _filter_decision(period_qs, f["decision"]), "all_period_qs": period_qs,
        "filters": f, "days": days, "custom": custom, "day_from": day_from, "day_to": day_to, "selected_day": selected_day,
    }


def _filter_decision(qs, decision):
    if decision == "alert":
        return qs.filter(decision_trace__decision="alert")
    if decision == "suppressed":
        return qs.filter(Q(suppressed=True) | Q(decision_trace__decision="suppressed_kpi_only"))
    if decision == "diagnostic":
        return qs.filter(decision_trace__decision="diagnostic_event")
    if decision == "pending":
        return qs.filter(decision_trace={})
    if decision == "ok":
        return qs.filter(suppressed=False).exclude(decision_trace={}).exclude(
            decision_trace__decision__in=["alert", "suppressed_kpi_only", "diagnostic_event"])
    return qs


def _day(value):
    try:
        return timezone.datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except ValueError:
        return None


_ALERT_Q = Q(decision_trace__decision="alert")


def decision_counts(qs):
    """Quanti eventi per decisione, sul periodo e con gli altri filtri applicati."""
    agg = qs.order_by().aggregate(
        total=Count("id"),
        alert=Count("id", filter=_ALERT_Q),
        suppressed=Count("id", filter=Q(suppressed=True) | Q(decision_trace__decision="suppressed_kpi_only")),
        diagnostic=Count("id", filter=Q(decision_trace__decision="diagnostic_event")),
        pending=Count("id", filter=Q(decision_trace={})),
    )
    counts = {code: agg.get(code) or 0 for code, _ in DECISIONS if code != "ok"}
    counts["ok"] = max((agg["total"] or 0) - sum(counts.values()), 0)
    return {code: counts[code] for code, _ in DECISIONS}


def daily_chart(qs, day_from, day_to, selected=None, max_days=90):
    """Barre impilate (alert / tutto il resto) per giorno, con i dati per il tooltip e il link del giorno."""
    day_from = max(day_from, day_to - timedelta(days=max_days - 1))
    by_day = {}
    dated = qs.annotate(day=TruncDate("occurred_at")).order_by()
    for row in dated.values("day").annotate(total=Count("id"), alert=Count("id", filter=_ALERT_Q)):
        by_day[row["day"]] = {"alert": row["alert"], "other": row["total"] - row["alert"], "types": {}}
    for row in dated.values("day", "event_type").annotate(n=Count("id")):
        if row["day"] in by_day:
            by_day[row["day"]]["types"][row["event_type"]] = row["n"]
    span = (day_to - day_from).days + 1
    width, height, top, left = 760, 150, 12, 34
    peak = max([r["alert"] + r["other"] for r in by_day.values()] or [1]) or 1
    slot = (width - left) / span
    bar = max(min(slot * 0.7, 46), 3)
    baseline = top + height
    days = []
    for i in range(span):
        day = day_from + timedelta(days=i)
        row = by_day.get(day, {"alert": 0, "other": 0, "types": {}})
        h_other, h_alert = height * row["other"] / peak, height * row["alert"] / peak
        top_types = sorted(row["types"].items(), key=lambda item: -item[1])[:3]
        days.append({
            "date": day, "x": round(left + i * slot + (slot - bar) / 2, 1), "w": round(bar, 1), "label_x": round(left + i * slot + slot / 2, 1),
            "y_other": round(baseline - h_other, 1), "h_other": round(h_other, 1),
            "y_alert": round(baseline - h_other - h_alert, 1), "h_alert": round(h_alert, 1),
            "alert": row["alert"], "other": row["other"], "total": row["alert"] + row["other"], "top_types": top_types,
            "show_label": i % max(span // 10, 1) == 0, "selected": day == selected,
        })
    return {"days": days, "peak": peak, "width": width, "height": height + top + 24, "baseline": baseline, "top": top, "left": left,
            "empty": not by_day}


def signature_candidates(event):
    """Campi del payload proponibili come firma della regola appresa (valori semplici e corti)."""
    payload = event.payload or {}
    rows, seen = [], set()
    for key, label in SIGNATURE_KEYS:
        value = payload.get(key)
        if key in seen or value in (None, "", [], {}) or isinstance(value, (dict, list, bool)):
            continue
        text = str(value).strip()
        if not text or len(text) > 120:
            continue
        seen.add(key)
        rows.append({"key": key, "label": label, "value": text, "checked": key in _DEFAULT_SIGNATURE})
    return rows


def active_alert_for(event):
    return (
        SecurityAlert.objects.filter(Q(event=event) | Q(source_id=event.source_id, dedup_hash=event.dedup_hash),
                                     status__in=ACTIVE_ALERT_STATUSES)
        .order_by("-updated_at").first()
    )


def _alert_title(event):
    payload = event.payload or {}
    title = payload.get("title") or payload.get("reason") or ""
    if not title:
        from security.templatetags.security_i18n import metric_label

        title = f"{metric_label(event.event_type)}: {event_summary(event) or event.source.name}"
    return str(title)[:255]


def promote_event(event, *, user, severity, title="", reason="", learn=True, match_keys=None):
    """Crea l'alert da un evento che il motore aveva giudicato a posto. Ritorna (alert, regola_appresa|None, creato)."""
    from security.services.evidence_builder import build_evidence_container
    from security.services.notifications import notify_alert_created
    from security.services.rule_engine import _get_or_create_active_alert, _store_alert_decision_trace

    if severity not in {value for value, _ in Severity.choices}:
        severity = Severity.WARNING
    actor = getattr(user, "username", "") or "ui"
    previous = event.decision_trace or {}
    previous_code = decision_of(event)
    trace = {
        "decision": "alert",
        "rule": "Promosso ad alert da una persona: il motore lo aveva giudicato a posto",
        "manual_escalation": True,
        "previous_decision": previous.get("decision", ""),
        "previous_reason": previous.get("reason") or previous.get("rule") or "",
        "reason": reason[:500],
        "escalated_by": actor,
    }
    with transaction.atomic():
        alert, created = _get_or_create_active_alert(
            source=event.source, event=event, title=(title or _alert_title(event))[:255], severity=severity,
            dedup_hash=event.dedup_hash, decision_trace=trace,
        )
        trace["alert_created"] = created
        _store_alert_decision_trace(alert, trace, created)
        event.decision_trace = {**previous, **trace, "previous_trace": previous}
        event.suppressed = False
        event.save(update_fields=["decision_trace", "suppressed"])
        SecurityAlertActionLog.objects.create(alert=alert, action="manual_escalation", actor=actor[:120], details={
            "event_id": event.pk, "previous_decision": previous_code, "reason": reason[:500], "severity": severity})
        rule = None
        if learn:
            payload = event.payload or {}
            keys = [key for key in (match_keys or []) if key in dict(SIGNATURE_KEYS) and payload.get(key) not in (None, "")]
            rule = SecurityEscalationRule.objects.create(
                name=_rule_name(event, keys), source=event.source, event_type=event.event_type,
                match_payload={key: str(payload[key])[:255] for key in keys}, severity=severity, reason=reason[:1000],
                origin_event=event, origin_alert=alert, created_by=user if getattr(user, "pk", None) else None,
            )
    try:
        build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    except Exception:  # noqa: BLE001 - l'evidenza e' un di piu': l'alert c'e' comunque
        logger.exception("Evidenza non creata per l'evento %s", event.pk)
    if created:
        notify_alert_created(alert)
    _learn(event, severity=severity, user=user, previous_code=previous_code)
    if rule:
        _audit_rule(rule, user, "create")
    return alert, rule, created


def _rule_name(event, keys):
    from security.templatetags.security_i18n import metric_label

    payload = event.payload or {}
    detail = ", ".join(f"{payload[key]}" for key in keys)
    return (f"{metric_label(event.event_type)}" + (f" — {detail}" if detail else ""))[:200]


def _learn(event, *, severity, user, previous_code):
    """Registro dell'apprendimento: il motore aveva detto «no», la persona ha detto «allarme»."""
    try:
        from ai_assistant.apprendimento import registra_decisione, registra_proposta

        ref = f"event:{event.pk}"
        decision = {"crea_alert": True, "gravita": severity}
        # Proposta dell'AI chiesta in pagina (se c'e'): confronto con la decisione della persona.
        registra_decisione(modulo=AI_MODULE, azione=AI_ACTION_TRIAGE, oggetto_ref=ref, decisione=decision, user=user)
        # Il giudizio del motore regole, corretto dalla persona.
        registra_proposta(modulo=AI_MODULE, azione=AI_ACTION_ENGINE, oggetto_ref=ref,
                          proposta={"crea_alert": False, "tipo": event.event_type, "motore": previous_code})
        registra_decisione(modulo=AI_MODULE, azione=AI_ACTION_ENGINE, oggetto_ref=ref,
                           decisione={"crea_alert": True, "tipo": event.event_type, "motore": previous_code},
                           user=user, campi=["crea_alert"])
    except Exception:  # noqa: BLE001 - l'apprendimento non blocca mai la promozione
        logger.exception("Apprendimento non registrato per l'evento %s", event.pk)


def confirm_ok(event, *, user):
    """La persona conferma che l'evento e' a posto: se l'AI aveva proposto un allarme, lo impara."""
    try:
        from ai_assistant.apprendimento import registra_decisione

        registra_decisione(modulo=AI_MODULE, azione=AI_ACTION_TRIAGE, oggetto_ref=f"event:{event.pk}",
                           decisione={"crea_alert": False}, user=user, campi=["crea_alert"])
    except Exception:  # noqa: BLE001
        logger.exception("Conferma non registrata per l'evento %s", event.pk)
    trace = {**(event.decision_trace or {}), "confirmed_ok_by": getattr(user, "username", "") or "ui",
             "confirmed_ok_at": timezone.now().isoformat(timespec="seconds")}
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])


def _audit_rule(rule, user, action, field_name="", old="", new=""):
    try:
        from security.services.configuration import audit_config_change

        audit_config_change(user if getattr(user, "pk", None) else None, action, rule, field_name=field_name, old_value=old, new_value=new)
    except Exception:  # noqa: BLE001
        logger.exception("Audit regola appresa non scritto")


def set_rule_active(rule, active, user):
    if rule.is_active == active:
        return
    rule.is_active = active
    rule.save(update_fields=["is_active", "updated_at"])
    _audit_rule(rule, user, "update", "is_active", str(not active), str(active))


def apply_learned_escalation(event):
    """Chiamata dal motore per gli eventi giudicati a posto: se una regola appresa li riconosce, alert."""
    from security.services.evidence_builder import build_evidence_container
    from security.services.notifications import notify_alert_created
    from security.services.rule_engine import _get_or_create_active_alert, _store_alert_decision_trace

    rule = next((r for r in SecurityEscalationRule.objects.filter(is_active=True, event_type=event.event_type) if r.matches(event)), None)
    if rule is None:
        return None
    previous = event.decision_trace or {}
    trace = {
        "decision": "alert",
        "rule": f"Regola appresa: {rule.name}",
        "learned_rule_id": rule.pk,
        "reason": rule.reason[:300],
        "previous_decision": previous.get("decision", ""),
        "previous_reason": previous.get("reason") or previous.get("rule") or "",
    }
    alert, created = _get_or_create_active_alert(
        source=event.source, event=event, title=_alert_title(event), severity=rule.severity, dedup_hash=event.dedup_hash, decision_trace=trace,
    )
    trace["alert_created"] = created
    _store_alert_decision_trace(alert, trace, created)
    event.decision_trace = trace
    event.save(update_fields=["decision_trace"])
    SecurityAlertActionLog.objects.create(alert=alert, action="learned_escalation", details={"rule_id": rule.pk, "event_id": event.pk})
    rule.hit_count += 1
    rule.last_hit_at = timezone.now()
    rule.save(update_fields=["hit_count", "last_hit_at", "updated_at"])
    try:
        build_evidence_container(event.source, alert.title, alert=alert, event=event, decision_trace=trace)
    except Exception:  # noqa: BLE001
        logger.exception("Evidenza non creata per l'evento %s", event.pk)
    if created:
        notify_alert_created(alert)
    return alert


# --- AI locale: «e' un allarme?» ----------------------------------------------------------------

TRIAGE_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Il motore regole ha giudicato "
    "l'evento qui sotto senza creare un alert. Decidi se in realtà è un allarme da gestire. Rispondi in italiano, così:\n"
    "Prima riga ESATTAMENTE «VERDETTO: ALLARME» oppure «VERDETTO: OK».\nSeconda riga «GRAVITÀ: bassa|media|alta|critica».\n"
    "Poi 2-4 frasi: perché, citando i valori dell'evento. Se nel contesto c'è la sezione «DA TRATTARE COME ALLARME» e "
    "l'evento è dello stesso tipo con valori simili, il verdetto è ALLARME. Usa solo i dati forniti."
)
_SEVERITY_FROM_TEXT = {"bassa": Severity.LOW, "media": Severity.WARNING, "alta": Severity.HIGH, "critica": Severity.CRITICAL}


def missed_alarms_text(event_type=None, limit=8):
    """Sezione deterministica per il prompt: cosa le persone hanno gia' promosso ad alert."""
    rules = SecurityEscalationRule.objects.filter(is_active=True)
    if event_type:
        rules = rules.filter(event_type=event_type)
    lines = []
    for rule in rules.order_by("-created_at")[:limit]:
        values = ", ".join(f"{k}={v}" for k, v in (rule.match_payload or {}).items()) or "qualsiasi valore"
        lines.append(f"- {rule.event_type} ({values}) → allarme {rule.severity}" + (f": {rule.reason[:160]}" if rule.reason else ""))
    if not lines:
        return ""
    return "DA TRATTARE COME ALLARME (eventi che le persone hanno già promosso ad alert):\n" + "\n".join(lines)


def triage_context(event):
    from security.services.ai_explain import _PAYLOAD_KEYS

    payload = event.payload or {}
    details = {key: payload[key] for key in _PAYLOAD_KEYS if key in payload and payload[key] not in (None, "", [], {})}
    trace = event.decision_trace or {}
    since = timezone.now() - timedelta(days=90)
    similar = SecurityEventRecord.objects.filter(event_type=event.event_type, occurred_at__gte=since)
    lines = [
        f"Evento: {event.event_type} · severità del parser: {event.severity} · {event.occurred_at:%d/%m/%Y %H:%M}",
        f"Sorgente: {event.source.name}" + (f" · report {event.report.report_type} del {event.report.report_date:%d/%m/%Y}" if event.report_id else ""),
        "Dettagli: " + json.dumps(details, ensure_ascii=False, default=str)[:1500] if details else "",
        f"Decisione del motore: {trace.get('decision') or 'non ancora valutato'}" + (f" ({trace.get('reason') or trace.get('rule')})" if trace.get("reason") or trace.get("rule") else ""),
        f"Eventi dello stesso tipo negli ultimi 90 giorni: {similar.count()}, di cui con alert: {similar.filter(decision_trace__decision='alert').count()}",
        missed_alarms_text(event.event_type),
    ]
    try:
        from ai_assistant.apprendimento import lezioni_testo

        lines.append(lezioni_testo(AI_MODULE, AI_ACTION_TRIAGE))
    except Exception:  # noqa: BLE001
        pass
    return "\n".join(line for line in lines if line)


def ai_triage(event, *, user=None, refresh=False):
    """Proposta dell'AI (allarme si/no + gravita'), registrata per imparare dalla decisione della persona."""
    from security.services.ai_explain import _cached_ask

    result = _cached_ask("triage", TRIAGE_INSTRUCTIONS, triage_context(event), action="event_triage", user=user,
                         object_type="SecurityEventRecord", object_id=event.pk, refresh=refresh)
    text = result.get("text", "")
    verdict = re.search(r"VERDETTO:\s*(ALLARME|OK)", text, re.I)
    gravity = re.search(r"GRAVIT[AÀ]:\s*(bassa|media|alta|critica)", text, re.I)
    result["is_alarm"] = bool(verdict and verdict.group(1).upper() == "ALLARME") if verdict else None
    result["severity"] = _SEVERITY_FROM_TEXT.get(gravity.group(1).lower()) if gravity else None
    result["body"] = re.sub(r"^\s*(VERDETTO|GRAVIT[AÀ]):.*$\n?", "", text, flags=re.I | re.M).strip()
    if result["ok"] and result["is_alarm"] is not None:
        try:
            from ai_assistant.apprendimento import registra_proposta

            proposal = {"crea_alert": result["is_alarm"]}
            if result["is_alarm"] and result["severity"]:
                proposal["gravita"] = result["severity"]
            registra_proposta(modulo=AI_MODULE, azione=AI_ACTION_TRIAGE, oggetto_ref=f"event:{event.pk}", proposta=proposal, user=user)
        except Exception:  # noqa: BLE001
            logger.exception("Proposta AI non registrata per l'evento %s", event.pk)
    return result
