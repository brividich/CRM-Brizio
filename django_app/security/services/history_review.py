"""Analisi dello storico: cosa e' gia' passato dal Security Center e cosa se ne puo' imparare.

Riassume un periodo (default 30 giorni) in sezioni leggibili: alert ricorrenti e come sono finiti,
falsi positivi che si ripetono, eventi scartati dal motore (soppressi o sotto soglia), alert e ticket
fermi, regole di soppressione mai usate, motivi di chiusura scritti dagli operatori.
Il testo prodotto da ``review_as_text`` e' il contesto che l'AI locale usa per proporre azioni:
l'AI propone, chi gestisce decide.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertSuppressionRule, SecurityEventRecord, SecurityRemediationTicket, Status
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.cases import ACTIVE_CASE_STATUSES
from security.services.investigation import PLAYBOOKS, STATUS_LABELS, alert_kind, status_label

CLOSED = {Status.CLOSED, Status.RESOLVED, Status.FALSE_POSITIVE, Status.SUPPRESSED, Status.MUTED}


def _family_key(alert):
    payload = (alert.event.payload if alert.event_id else None) or {}
    return payload.get("type") or alert.title


def _status_text(counts):
    return ", ".join(f"{n} {status_label(status, n)}" for status, n in sorted(counts.items(), key=lambda item: -item[1]))


def build_review(days=30, now=None):
    now = now or timezone.now()
    since = now - timedelta(days=days)
    alerts = list(SecurityAlert.objects.filter(created_at__gte=since).select_related("event", "source").order_by("-created_at")[:2000])

    families = {}
    for alert in alerts:
        family = families.setdefault(_family_key(alert), {"alerts": [], "counts": {}, "reasons": []})
        family["alerts"].append(alert)
        family["counts"][alert.status] = family["counts"].get(alert.status, 0) + 1
        reason = (alert.status_reason or "").strip()
        if reason and alert.status in CLOSED and reason not in family["reasons"] and len(family["reasons"]) < 3:
            family["reasons"].append(reason[:160])

    recurring, false_positives = [], []
    for family in families.values():
        sample = family["alerts"][0]
        total = len(family["alerts"])
        row = {
            "label": PLAYBOOKS[alert_kind(sample)][0],
            "example": sample.title,
            "total": total,
            "status_text": _status_text(family["counts"]),
            "reasons": family["reasons"],
            "open": sum(family["counts"].get(s, 0) for s in ACTIVE_ALERT_STATUSES),
            "false_positive": family["counts"].get(Status.FALSE_POSITIVE, 0),
            "url": reverse("security:alert_detail", args=[sample.pk]),
        }
        if total >= 2:
            recurring.append(row)
        if row["false_positive"] >= 2 and row["false_positive"] * 2 >= total:
            false_positives.append(row)
    recurring.sort(key=lambda row: -row["total"])
    false_positives.sort(key=lambda row: -row["false_positive"])

    stale_alerts = list(
        SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, created_at__lt=now - timedelta(days=7)).order_by("created_at")[:8]
    )
    stale_alerts_total = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, created_at__lt=now - timedelta(days=7)).count()
    active_cases = SecurityRemediationTicket.objects.filter(status__in=ACTIVE_CASE_STATUSES)
    stale_cases = list(active_cases.filter(updated_at__lt=now - timedelta(days=14)).order_by("updated_at")[:8])
    unassigned_cases = active_cases.filter(assignee__isnull=True).count()

    # Eventi scartati: soppressi da una regola o tenuti solo per i KPI (sotto soglia, regola spenta).
    discarded_by_rule, below_threshold = {}, {}
    for event in SecurityEventRecord.objects.filter(occurred_at__gte=since).only("event_type", "suppressed", "decision_trace", "payload")[:20000]:
        trace = event.decision_trace or {}
        decision = trace.get("decision", "")
        if event.suppressed or decision == "suppressed_kpi_only":
            name = trace.get("rule") or "regola senza nome"
            discarded_by_rule[name] = discarded_by_rule.get(name, 0) + 1
        elif decision == "kpi_only" and event.event_type not in ("backup_job", "vulnerability_finding", "kpi_metric"):
            key = f"{event.event_type}: {trace.get('reason') or 'sotto soglia'}"
            below_threshold[key] = below_threshold.get(key, 0) + 1

    # «Mai usata» solo se non ha scartato nulla: ne' secondo il contatore della regola, ne' tra gli eventi del periodo.
    unused_rules = [
        rule for rule in SecurityAlertSuppressionRule.objects.filter(is_active=True)
        if (not rule.last_hit_at or rule.last_hit_at < now - timedelta(days=90)) and rule.name not in discarded_by_rule
    ]
    # Allarmi mancati: eventi che il motore aveva giudicato a posto e una persona ha promosso ad alert.
    from security.models import SecurityAlertActionLog, SecurityEscalationRule

    missed = list(
        SecurityAlertActionLog.objects.filter(action="manual_escalation", created_at__gte=since).select_related("alert").order_by("-created_at")[:10]
    )
    learned_rules = list(SecurityEscalationRule.objects.filter(is_active=True).order_by("-hit_count", "-created_at")[:8])
    closures = [
        {"title": alert.title, "status": status_label(alert.status), "reason": alert.status_reason[:200], "pk": alert.pk}
        for alert in alerts if alert.status in CLOSED and (alert.status_reason or "").strip()
    ][:10]

    return {
        "days": days,
        "since": since,
        "alerts_total": len(alerts),
        "closed_total": sum(1 for alert in alerts if alert.status in CLOSED),
        "false_positive_total": sum(1 for alert in alerts if alert.status == Status.FALSE_POSITIVE),
        "recurring": recurring[:10],
        "false_positives": false_positives[:6],
        "stale_alerts": stale_alerts,
        "stale_alerts_total": stale_alerts_total,
        "stale_cases": stale_cases,
        "unassigned_cases": unassigned_cases,
        "discarded_by_rule": sorted(discarded_by_rule.items(), key=lambda item: -item[1])[:8],
        "discarded_total": sum(discarded_by_rule.values()),
        "below_threshold": sorted(below_threshold.items(), key=lambda item: -item[1])[:8],
        "unused_rules": unused_rules[:8],
        "closures": closures,
        "missed": missed,
        "learned_rules": learned_rules,
    }


def review_as_text(review):
    """Il riepilogo in righe di testo per l'AI: conteggi, titoli, motivi. Mai payload o corpi delle mail."""
    lines = [f"Periodo: ultimi {review['days']} giorni. Alert: {review['alerts_total']}, chiusi {review['closed_total']}, "
             f"falsi positivi {review['false_positive_total']}."]
    for row in review["recurring"]:
        lines.append(f"Ricorrente: «{row['example']}» ({row['label']}) {row['total']} volte: {row['status_text']}"
                     + (f". Motivi di chiusura: {' | '.join(row['reasons'])}" if row["reasons"] else ""))
    for row in review["false_positives"]:
        lines.append(f"Falso positivo ripetuto: «{row['example']}» {row['false_positive']} volte su {row['total']}")
    if review["stale_alerts_total"]:
        lines.append(f"Alert aperti da più di 7 giorni: {review['stale_alerts_total']} (es. " + "; ".join(a.title for a in review["stale_alerts"][:3]) + ")")
    if review["stale_cases"]:
        lines.append(f"Ticket attivi fermi da più di 14 giorni: {len(review['stale_cases'])} (es. " + "; ".join(c.title for c in review["stale_cases"][:3]) + ")")
    if review["unassigned_cases"]:
        lines.append(f"Ticket attivi senza responsabile: {review['unassigned_cases']}")
    for name, count in review["discarded_by_rule"]:
        lines.append(f"Eventi scartati dalla soppressione «{name}»: {count}")
    for name, count in review["below_threshold"]:
        lines.append(f"Eventi senza alert ({name}): {count}")
    for rule in review["unused_rules"]:
        lines.append(f"Regola di soppressione attiva mai usata negli ultimi 90 giorni: «{rule.name}»")
    for log in review.get("missed", [])[:6]:
        lines.append(f"Allarme mancato dal motore, promosso a mano: «{log.alert.title if log.alert else 'alert'}»"
                     + (f" — motivo: {log.details.get('reason')}" if (log.details or {}).get("reason") else ""))
    for rule in review.get("learned_rules", [])[:6]:
        lines.append(f"Regola appresa attiva: «{rule.name}» (scattata {rule.hit_count} volte)")
    for closure in review["closures"][:6]:
        lines.append(f"Chiusura recente: «{closure['title']}» come {closure['status']}: {closure['reason']}")
    return "\n".join(lines)[:6000]
