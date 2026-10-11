"""Soppressione appresa: «dopo 3 disattivazioni, la 4ª non è un alert».

Come funziona, in breve:

1. Ogni alert ha un'**impronta** stabile (``alert_fingerprint``): sorgente + tipo di evento +
   pochi campi del payload che identificano il fatto (vedi ``FINGERPRINT_FIELDS``). Timestamp,
   ID, conteggi e date non entrano: due report dello stesso problema hanno la stessa impronta.
2. Una **disattivazione** è una chiusura manuale come falso positivo, non rilevante, rischio
   accettato, oppure un «silenzia», sempre con motivo (``record_dismissal``). Le chiusure
   automatiche e i «risolto» (il problema è rientrato davvero) non contano.
3. Alla N-esima disattivazione (soglia, default 3) della stessa impronta nella finestra
   configurata nasce una ``SecurityAlertSuppressionRule`` con ``owner="system:learned"`` e
   ambito esatto sull'impronta: audit di configurazione e avviso ai canali scelti.
4. Dalle occorrenze successive il motore registra l'evento come soppresso (``decision_trace``
   con il riferimento alla regola) e aggiorna ``hit_count``/``last_hit_at``: nessun alert.
5. Una riapertura manuale disattiva la regola e azzera il conteggio di quell'impronta.

Guardrail (configurabili, attivi di default): mai per severità critica, CVE in CISA KEV,
minacce/malware/ransomware/botnet; se l'evento è più grave delle disattivazioni l'alert nasce.
Le azioni massive contano una volta sola per impronta (``batch``).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from security.models import (
    SEVERITY_RANK,
    SecurityAlertDismissal,
    SecurityAlertSuppressionRule,
    Severity,
)
from security.services import soc_settings
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

SYSTEM_ACTORS = {"", "system", "auto", "ui"}
EVENT_KIND_LEARNED = "learned_suppression"

# Campi del payload che identificano «lo stesso fatto», per tipo di evento. Solo quelli
# presenti entrano nell'impronta; se non ce n'è nessuno l'alert non è apprendibile (una
# regola su «tutto il tipo» sarebbe troppo larga).
FINGERPRINT_FIELDS = {
    "backup_job": ("job_name", "device_name", "nas_name"),
    "vulnerability_finding": ("cve", "affected_product", "organization"),
    "watchguard_alert_candidate": ("type", "user", "username", "source_ip", "computer", "firebox_name"),
    "vpn_auth_denied": ("user", "username", "source_ip"),
    "vpn_auth_allowed": ("user", "username", "source_ip"),
    "source_silent": ("source_code", "reason"),
    "possible_sender_spoofing": ("claimed_vendor", "sender_domain"),
}
DEFAULT_FINGERPRINT_FIELDS = (
    "type", "computer", "hostname", "device_name", "job_name", "cve", "affected_product", "user", "username", "source_ip",
)
THREAT_KEYWORDS = ("malware", "ransomware", "threat", "minacc", "virus", "trojan", "botnet", "exploit", "intrusion")
# Campi che identificano un soggetto (chi/cosa): senza almeno uno l'impronta coprirebbe un
# intero tipo di evento della sorgente, troppo largo per una soppressione automatica.
SUBJECT_FIELDS = {
    "computer", "hostname", "device_name", "job_name", "nas_name", "cve", "affected_product", "user", "username",
    "source_ip", "firebox_name", "source_code", "claimed_vendor", "sender_domain",
}
CVE_PATTERN = re.compile(r"CVE-\d{4}-\d{4,7}", re.I)
KEV_CATALOG_MAX_AGE_HOURS = 48


@dataclass(frozen=True)
class Fingerprint:
    hash: str
    fields: dict
    event_type: str
    source_id: int | None


def _norm(value):
    return str(value if value is not None else "").strip().casefold()


def event_fingerprint(event):
    """Impronta stabile dell'evento, o None se il payload non ha campi identificativi."""
    if event is None:
        return None
    payload = event.payload or {}
    keys = FINGERPRINT_FIELDS.get(event.event_type, DEFAULT_FINGERPRINT_FIELDS)
    fields = {}
    for key in keys:
        value = payload.get(key)
        if value in (None, "", [], {}) or isinstance(value, (dict, list)):
            continue
        fields[key] = str(value).strip()[:255]
    if not fields or not (set(fields) & SUBJECT_FIELDS):
        return None
    parts = [f"{key}={_norm(fields[key])}" for key in sorted(fields)]
    return Fingerprint(make_hash(event.source_id, event.event_type, *parts), fields, event.event_type, event.source_id)


def alert_fingerprint(alert):
    return event_fingerprint(getattr(alert, "event", None))


def enabled():
    return soc_settings.value("soppressione.appresa.attivo")


# --- Guardrail ------------------------------------------------------------------------------

def _payload_cves(payload):
    found = set()
    for value in payload.values():
        if isinstance(value, (list, tuple)):
            value = " ".join(str(v) for v in value)
        if isinstance(value, str):
            found.update(match.upper() for match in CVE_PATTERN.findall(value))
    return found


def _kev_catalog_fresh():
    from security.models import SecurityExternalFeedCache

    since = timezone.now() - timedelta(hours=KEV_CATALOG_MAX_AGE_HOURS)
    return SecurityExternalFeedCache.objects.filter(feed="kev", key="catalog", fetched_at__gte=since).exists()


def _is_kev(event):
    """True se una CVE dell'evento è in CISA KEV **o se non si può escluderlo** (catalogo assente/vecchio)."""
    payload = event.payload or {}
    if payload.get("kev") or payload.get("known_exploited") or payload.get("cisa_kev"):
        return True
    cves = _payload_cves(payload)
    if not cves:
        return False
    try:
        from security.models import SecurityCveRecord

        if SecurityCveRecord.objects.filter(cve_id__in=cves, kev=True).exists():
            return True
        # Fail-closed: senza un catalogo KEV recente non si può dire che la CVE non sia sfruttata.
        return not _kev_catalog_fresh()
    except Exception:  # noqa: BLE001 - catalogo non leggibile: nel dubbio è KEV
        logger.exception("Catalogo KEV non leggibile per %s: trattata come KEV", ", ".join(sorted(cves)))
        return True


def effective_severity(event, alert=None):
    """Severità con cui l'evento diventerebbe alert: la più alta tra evento, alert e regola CVE (CVSS >= 9 = critica)."""
    candidates = [event.severity or Severity.INFO]
    if alert is not None and alert.severity:
        candidates.append(alert.severity)
    payload = event.payload or {}
    if payload.get("severity") in SEVERITY_RANK:
        candidates.append(payload["severity"])
    try:
        if float(payload.get("cvss") or 0) >= 9:
            candidates.append(Severity.CRITICAL)
    except (TypeError, ValueError):
        pass
    return max(candidates, key=lambda s: SEVERITY_RANK.get(s, 0))


def _is_threat(event):
    payload = event.payload or {}
    text = " ".join(_norm(payload.get(key)) for key in ("type", "title", "reason", "category", "threat", "detail"))
    text = f"{_norm(event.event_type)} {text}"
    return any(word in text for word in THREAT_KEYWORDS)


def guardrail_reason(event, *, severity=None):
    """Motivo per cui un evento non può essere soppresso da una regola appresa (o "")."""
    severity = severity or effective_severity(event)
    if soc_settings.value("soppressione.appresa.escludi_critici") and severity == Severity.CRITICAL:
        return "severità critica"
    if _norm(event.event_type) in soc_settings.text_list("soppressione.appresa.tipi_esclusi"):
        return f"tipo di evento escluso ({event.event_type})"
    if soc_settings.value("soppressione.appresa.escludi_minacce") and _is_threat(event):
        return "minaccia / malware rilevato"
    if soc_settings.value("soppressione.appresa.escludi_kev") and _is_kev(event):
        return "CVE sfruttata attivamente (CISA KEV)"
    return ""


def learned_rule_matches(rule, event):
    """Chiamata da ``SecurityAlertSuppressionRule.matches`` per le regole con impronta."""
    if rule.source_id and rule.source_id != event.source_id:
        return False
    if rule.event_type and rule.event_type != event.event_type:
        return False
    fingerprint = event_fingerprint(event)
    if fingerprint is None or fingerprint.hash != rule.fingerprint:
        return False
    if (soc_settings.value("soppressione.appresa.blocca_aggravamento") and rule.max_severity
            and SEVERITY_RANK.get(effective_severity(event), 0) > SEVERITY_RANK.get(rule.max_severity, 0)):
        return False
    return not guardrail_reason(event)


# --- Disattivazioni e apprendimento --------------------------------------------------------

def _window_start(now=None):
    return (now or timezone.now()) - timedelta(days=soc_settings.value("soppressione.appresa.finestra_giorni"))


def counted_dismissals(fingerprint_hash, now=None):
    return SecurityAlertDismissal.objects.filter(
        fingerprint=fingerprint_hash, counted=True, created_at__gte=_window_start(now),
    ).order_by("created_at")


def dismissal_units(dismissals):
    """Unità = alert distinti; un'azione massiva (stesso ``batch``) conta una volta sola."""
    return len({d.batch or f"a{d.alert_id}" for d in dismissals})


def active_learned_rule(fingerprint_hash):
    now = timezone.now()
    for rule in SecurityAlertSuppressionRule.objects.filter(fingerprint=fingerprint_hash, is_active=True):
        if not rule.expires_at or rule.expires_at > now:
            return rule
    return None


def record_dismissal(alert, *, kind, actor, reason, batch="", user=None):
    """Registra una disattivazione manuale e, se si raggiunge la soglia, crea la regola appresa.

    Ritorna la regola creata o None. Non solleva: l'azione sull'alert è già avvenuta e non va
    annullata per un errore dell'apprendimento."""
    if _norm(actor) in SYSTEM_ACTORS or not (reason or "").strip():
        return None
    try:
        fingerprint = alert_fingerprint(alert)
        event = alert.event
        SecurityAlertDismissal.objects.create(
            alert=alert, source=alert.source, event_type=event.event_type if event else "",
            fingerprint=fingerprint.hash if fingerprint else "", fingerprint_fields=fingerprint.fields if fingerprint else {},
            kind=kind, severity=(effective_severity(event, alert) if event else alert.severity), actor=str(actor)[:120],
            reason=reason.strip()[:2000], batch=(batch or "")[:64], by_config_user=_is_config_user(user),
        )
        if fingerprint is None or not enabled():
            return None
        return _maybe_learn(alert, fingerprint)
    except Exception:  # noqa: BLE001 - l'apprendimento non deve mai annullare la disattivazione
        logger.exception("Disattivazione dell'alert %s non registrata per l'apprendimento", alert.pk)
        return None


def _is_config_user(user):
    if not getattr(user, "is_authenticated", False):
        return False
    from security.services.configuration import can_manage_security_config

    return bool(can_manage_security_config(user))


def _maybe_learn(alert, fingerprint):
    threshold = soc_settings.value("soppressione.appresa.soglia")
    with transaction.atomic():
        dismissals = list(counted_dismissals(fingerprint.hash).select_for_update())
        if dismissal_units(dismissals) < threshold or active_learned_rule(fingerprint.hash):
            return None
        if not any(d.by_config_user for d in dismissals):
            # Una regola vale mesi e solo la configurazione la revoca: serve che almeno una
            # delle disattivazioni sia di chi ha il permesso di configurazione del SOC.
            logger.info("Soppressione appresa in attesa: nessuna disattivazione da un responsabile SOC (%s)", fingerprint.hash[:12])
            return None
        max_severity = max((d.severity or Severity.INFO for d in dismissals), key=lambda s: SEVERITY_RANK.get(s, 0))
        blocked = guardrail_reason(alert.event, severity=max_severity) if alert.event else "evento mancante"
        if blocked:
            logger.info("Soppressione appresa non creata per l'impronta %s: %s", fingerprint.hash[:12], blocked)
            return None
        rule = SecurityAlertSuppressionRule.objects.create(
            name=_rule_name(alert, fingerprint),
            source_id=fingerprint.source_id,
            event_type=fingerprint.event_type,
            match_payload=fingerprint.fields,
            scope_type=SecurityAlertSuppressionRule.LEARNED_SCOPE,
            owner=SecurityAlertSuppressionRule.LEARNED_OWNER,
            fingerprint=fingerprint.hash,
            max_severity=max_severity,
            reason=_rule_reason(dismissals),
            is_active=True,
            expires_at=timezone.now() + timedelta(days=soc_settings.value("soppressione.appresa.durata_giorni")),
        )
        SecurityAlertDismissal.objects.filter(pk__in=[d.pk for d in dismissals]).update(learned_rule=rule)
    _audit(rule, None, "create", "reason", "", rule.reason)
    _notify_learned(rule)
    return rule


def _rule_name(alert, fingerprint):
    from security.templatetags.security_i18n import metric_label

    detail = ", ".join(str(value) for value in fingerprint.fields.values())
    return f"Appresa: {metric_label(fingerprint.event_type)} — {detail}"[:160]


def _rule_reason(dismissals):
    lines = ["Creata automaticamente dopo disattivazioni ripetute dello stesso alert:"]
    for d in dismissals:
        when = timezone.localtime(d.created_at).strftime("%d/%m/%Y %H:%M")
        lines.append(f"- {when} · {d.actor} · {d.get_kind_display()} · alert #{d.alert_id}: {d.reason[:200]}")
    return "\n".join(lines)


def _audit(rule, user, action, field_name="", old="", new=""):
    try:
        from security.services.configuration import audit_config_change

        audit_config_change(user if getattr(user, "pk", None) else None, action, rule, field_name=field_name, old_value=old, new_value=new)
    except Exception:  # noqa: BLE001 - l'audit mancante va visto nei log, ma non annulla l'operazione
        logger.exception("Audit della soppressione appresa %s non scritto", rule.pk)


def _notify_learned(rule):
    from security.models import SecurityNotificationChannel
    from security.services.notifications import _link, deliver_once

    ids = soc_settings.value("soppressione.appresa.canali")
    channels = SecurityNotificationChannel.objects.filter(enabled=True)
    # Senza canali scelti: i canali del SOC che ricevono i nuovi alert.
    channels = channels.filter(pk__in=ids) if ids else channels.filter(notify_on_new_alert=True)
    sent = 0
    body = (
        f"Nuova soppressione appresa: {rule.name}\n"
        f"Valida fino al {timezone.localtime(rule.expires_at).strftime('%d/%m/%Y')}.\n\n{rule.reason}\n\n"
        f"Revoca: {_link('/soc/soppressioni/')}"
    )
    for channel in channels:
        log = deliver_once(channel, event_kind=EVENT_KIND_LEARNED, severity=Severity.INFO, dedup_hash=f"learned:{rule.pk}",
                           subject=f"[SOC] Soppressione appresa: {rule.name}"[:200], body=body)
        sent += bool(log and log.outcome == "sent")
    return sent


# --- Riapertura, revoca, progresso ---------------------------------------------------------

def reset_fingerprint(fingerprint_hash, *, user=None, actor="", reason=""):
    """Riapertura manuale: disattiva le regole apprese dell'impronta e azzera il conteggio."""
    if not fingerprint_hash:
        return 0
    revoked = 0
    for rule in SecurityAlertSuppressionRule.objects.filter(fingerprint=fingerprint_hash, is_active=True):
        revoke_rule(rule, user=user, reason=reason or f"Riapertura manuale da {actor or 'operatore'}")
        revoked += 1
    SecurityAlertDismissal.objects.filter(fingerprint=fingerprint_hash, counted=True).update(counted=False)
    return revoked


def on_manual_reopen(alert, *, actor, reason="", user=None):
    if _norm(actor) in SYSTEM_ACTORS:
        return 0
    fingerprint = alert_fingerprint(alert)
    if fingerprint is None:
        return 0
    try:
        return reset_fingerprint(fingerprint.hash, user=user, actor=actor,
                                 reason=f"Alert #{alert.pk} riaperto a mano da {actor}" + (f": {reason}" if reason else ""))
    except Exception:  # noqa: BLE001
        logger.exception("Reset della soppressione appresa non riuscito per l'alert %s", alert.pk)
        return 0


def revoke_rule(rule, *, user=None, reason):
    if not rule.is_active:
        return False
    rule.is_active = False
    rule.revoked_at = timezone.now()
    rule.revoked_reason = (reason or "").strip()[:2000]
    rule.save(update_fields=["is_active", "revoked_at", "revoked_reason", "updated_at"])
    if rule.fingerprint:
        # Senza azzerare, la prossima disattivazione ricreerebbe subito la regola appena revocata.
        SecurityAlertDismissal.objects.filter(fingerprint=rule.fingerprint, counted=True).update(counted=False)
    _audit(rule, user, "update", "is_active", "True", f"False — {rule.revoked_reason}")
    return True


def dismissal_progress(alert):
    """Stato per il badge «2/3 disattivazioni» nella pagina dell'alert."""
    fingerprint = alert_fingerprint(alert)
    threshold = soc_settings.value("soppressione.appresa.soglia")
    info = {"enabled": enabled(), "threshold": threshold, "count": 0, "learnable": fingerprint is not None,
            "rule": None, "blocked": "", "next_creates_rule": False}
    if fingerprint is None:
        return info
    info["count"] = dismissal_units(list(counted_dismissals(fingerprint.hash)))
    info["rule"] = active_learned_rule(fingerprint.hash)
    if alert.event is not None:
        info["blocked"] = guardrail_reason(alert.event, severity=effective_severity(alert.event, alert))
    info["next_creates_rule"] = bool(info["enabled"] and not info["rule"] and not info["blocked"] and info["count"] == threshold - 1)
    return info
