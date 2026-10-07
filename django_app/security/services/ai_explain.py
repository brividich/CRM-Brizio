"""Spiegazioni in linguaggio semplice con l'AI LOCALE (Ollama on-premise, `ai_assistant.chat_with_ollama`).

- Nessun dato esce dall'azienda: l'AI e' quella del portale, sul server interno.
- L'AI spiega e suggerisce, non decide: non cambia stato agli alert, non crea ticket.
- Contesto minimo e strutturato: titolo, severita', regola, valori, report d'origine. Mai il corpo
  delle mail: e' contenuto di terzi e puo' contenere dati personali o testo malevolo.
- Fail-safe: AI spenta o lenta = messaggio chiaro, mai un errore di pagina.
- Ogni richiesta finisce in `SecurityAiInteractionLog` (chi, quando, modello, esito; non il testo).
"""
import hashlib
import json
import logging
import re
import time

from django.conf import settings
from django.core.cache import cache
from django.utils.timezone import localtime

from security.models import SecurityAiInteractionLog, SecurityEventRecord

logger = logging.getLogger(__name__)

CACHE_SECONDS = 7 * 24 * 3600
_TOOL_CITATION = re.compile(r"[ \t]*[(\[]\s*\*?\s*(?:fonte:\s*)?tool:[^)\]\n]*[)\]]", re.IGNORECASE)
DISCLAIMER = "Testo generato dall'AI locale a partire dai dati del Security Center: verificalo prima di agire."
# Campi dell'evento utili a capire l'alert. Tutto il resto (corpo, payload grezzi) resta fuori.
_PAYLOAD_KEYS = (
    "vendor", "report_type", "type", "title", "reason", "severity", "count", "threshold", "value", "metric",
    "user", "source_ip", "computer", "ip", "group", "categories", "job_name", "status", "device_name", "nas_name",
    "cve", "cvss", "affected_product", "exposed_devices", "days_left", "firebox_name", "interface", "detail",
    "claimed_vendor", "sender_domain", "duration_seconds", "malware", "exploits", "no_license", "with_errors",
)
ALERT_INSTRUCTIONS = (
    "Sei un analista della sicurezza IT di una piccola azienda manifatturiera italiana. Spiega l'alert qui sotto "
    "a un responsabile IT che non è uno specialista di sicurezza. Scrivi in italiano semplice, frasi brevi, niente "
    "gergo inutile. Usa esattamente queste cinque sezioni, ciascuna con il titolo in grassetto:\n"
    "**Cosa è successo** (2-3 frasi)\n**Perché è scattato l'alert** (la regola e il valore che l'hanno fatto scattare)\n"
    "**Cosa dice lo storico** (dai Precedenti e dai fatti collegati: quante volte è già successo, come è stato chiuso e "
    "con quale motivo, eventi scartati; se lo storico fa pensare a un falso positivo dillo, ma verifica che i fatti di "
    "oggi siano coerenti con quel motivo)\n"
    "**Quanto è urgente** (bassa, media o alta, con il motivo in una frase)\n**Cosa fare adesso** (al massimo 3 passi concreti, elenco puntato).\n"
    "Usa solo i dati del contesto: se un'informazione manca, dillo invece di inventarla. Non ripetere il contesto.\n"
    "Tieni conto di fatti collegati, precedenti ed eventi scartati: se in passato lo stesso alert è stato chiuso come "
    "falso positivo o con un motivo, dillo e valuta se vale anche ora; se si ripete spesso, suggerisci di cercare la causa. "
    "Per i passi parti dalla procedura standard del contesto, adattandola ai dati."
)
CASE_STEPS_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Dal ticket qui sotto (alert, "
    "attività già fatte o da fare, note, precedenti, procedura standard) proponi i PROSSIMI passi concreti per chiuderlo. "
    "Massimo 5 passi, uno per riga, ogni riga inizia con «- », frasi brevi all'infinito (es. «- Bloccare l'IP sul firewall»). "
    "Non ripetere attività già presenti nel ticket. Niente titoli né spiegazioni oltre ai passi. Se non serve altro, "
    "scrivi una sola riga: «- Chiudere il ticket scrivendo l'esito»."
)
CASE_RESOLUTION_INSTRUCTIONS = (
    "Scrivi in italiano l'esito di chiusura del ticket di sicurezza qui sotto, da registrare per l'audit: 2-4 frasi, "
    "un solo paragrafo, niente elenchi. Dì cosa è successo, cosa è stato fatto (dalle attività completate e dalle note) "
    "e lo stato finale. Usa solo i dati forniti; se mancano informazioni su cosa è stato fatto, scrivilo chiaramente "
    "(es. «nessuna attività registrata»). Non inventare azioni."
)
REVIEW_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Qui sotto c'è il riepilogo dello "
    "storico del Security Center: alert ricorrenti con come sono stati chiusi, falsi positivi, eventi scartati dal motore, "
    "alert e ticket fermi, regole di soppressione. Proponi al massimo 5 azioni, dalla più utile, come elenco numerato. "
    "Per ogni azione: **cosa fare** in grassetto, poi in una frase il dato che la giustifica e l'effetto atteso. "
    "Azioni tipiche: regola di soppressione per un falso positivo che si ripete; risolvere la causa di un problema che "
    "torna; chiudere o riassegnare ticket e alert fermi; rivedere regole di soppressione mai usate o che scartano troppo. "
    "Non proporre nulla senza un dato a sostegno. Usa solo i dati forniti."
)
BRIEF_INSTRUCTIONS = (
    "Sei l'assistente del responsabile IT di una piccola azienda manifatturiera italiana. Dall'elenco qui sotto "
    "(i punti che richiedono attenzione nel Security Center) scrivi una sintesi della giornata in italiano semplice: "
    "UN solo paragrafo di massimo 5 frasi, niente elenchi puntati, niente titoli. Prima la cosa più urgente, poi raggruppa "
    "il resto per area (es. «sui computer: …»); chiudi con una frase su cosa fare per prima cosa. Non citare fonti, "
    "strumenti o etichette tra parentesi. Se l'elenco è vuoto dì che non ci sono problemi aperti. Usa solo i dati forniti, "
    "senza inventare."
)


def _ask(prompt, context, *, action, user=None, object_type="", object_id=""):
    started = time.monotonic()
    model = str(getattr(settings, "OLLAMA_CHAT_MODEL", "") or "")
    status, text, error = "ok", "", ""
    try:
        from ai_assistant.services import chat_with_ollama

        result = chat_with_ollama(prompt, runtime_context=context, timeout=int(getattr(settings, "SECURITY_AI_TIMEOUT_SECONDS", 120) or 120))
        # L'assistente del portale chiede di citare le fonti «tool:*»: qui non servono e sporcano la lettura.
        text = _TOOL_CITATION.sub("", getattr(result, "content", "") or "").strip()
        if not text:
            status, error = "empty", "L'AI non ha restituito testo."
    except Exception as exc:  # noqa: BLE001 - AI spenta, timeout, configurazione
        status, error = "error", str(exc)[:300]
        logger.info("AI locale non disponibile per %s: %s", action, exc)
    try:
        SecurityAiInteractionLog.objects.create(
            user=user if getattr(user, "is_authenticated", False) else None, action=action, provider="ollama", model=model[:160],
            status=status, page="soc", object_type=object_type, object_id=str(object_id)[:80], request_chars=len(prompt) + len(context),
            response_chars=len(text), latency_ms=int((time.monotonic() - started) * 1000), error_message=error,
        )
    except Exception:  # noqa: BLE001 - il registro non deve bloccare la risposta
        logger.exception("Registro AI non scritto")
    return {"ok": status == "ok", "text": text, "error": error, "model": model, "disclaimer": DISCLAIMER}


def alert_context(alert):
    """Contesto strutturato e minimo dell'alert (testo, non JSON grezzo dell'evento)."""
    event = alert.event
    payload = (event.payload if event else {}) or {}
    trace = {**((event.decision_trace if event else {}) or {}), **(alert.decision_trace or {})}
    lines = [
        f"Titolo: {alert.title}",
        f"Severità: {alert.severity}",
        f"Stato: {alert.status}",
        f"Sorgente: {getattr(alert.source, 'name', '')}",
        f"Creato il: {alert.created_at:%d/%m/%Y %H:%M}" if alert.created_at else "",
        f"Ultimo aggiornamento: {alert.updated_at:%d/%m/%Y %H:%M}" if alert.updated_at else "",
        f"Occorrenze: {SecurityEventRecord.objects.filter(dedup_hash=alert.dedup_hash).count()}" if alert.dedup_hash else "",
    ]
    if event:
        lines.append(f"Tipo di evento: {event.event_type}")
        if event.report_id:
            lines.append(f"Report d'origine: {event.report.report_type} del {event.report.report_date:%d/%m/%Y}")
    details = {key: payload[key] for key in _PAYLOAD_KEYS if key in payload and payload[key] not in (None, "", [], {})}
    if details:
        lines.append("Dettagli dell'evento: " + json.dumps(details, ensure_ascii=False, default=str)[:1500])
    rule = {key: trace[key] for key in ("decision", "rule", "rule_code", "rule_name", "metric", "operator", "threshold", "value", "matched_rules", "reason") if key in trace}
    if rule:
        lines.append("Regola che ha deciso: " + json.dumps(rule, ensure_ascii=False, default=str)[:800])
    if trace.get("manual_escalation") or trace.get("learned_rule_id"):
        lines.append(
            "ALLARME MANCATO DAL MOTORE: il motore aveva giudicato l'evento a posto "
            f"(«{trace.get('previous_reason') or trace.get('previous_decision') or 'solo statistica'}»); "
            + ("una persona lo ha promosso ad alert" if trace.get("manual_escalation") else "una regola appresa da una persona lo ha riconosciuto")
            + (f" con questo motivo: {trace.get('reason')}" if trace.get("reason") else "") + "."
        )
    try:
        from security.services.investigation import facts_as_text

        lines.append(facts_as_text(alert)[:2500])
    except Exception:  # noqa: BLE001 - senza fatti collegati l'AI spiega comunque l'alert
        logger.exception("Fatti collegati non disponibili per l'alert %s", alert.pk)
    return "\n".join(line for line in lines if line)


def explain_alert(alert, *, user=None, refresh=False):
    context = alert_context(alert)
    key = "soc:ai:alert:" + hashlib.sha256(f"{alert.pk}:{context}".encode()).hexdigest()[:32]
    if not refresh:
        cached = cache.get(key)
        if cached:
            return {**cached, "cached": True}
    result = _ask(ALERT_INSTRUCTIONS, context, action="alert_explain", user=user, object_type="SecurityAlert", object_id=alert.pk)
    if result["ok"]:
        cache.set(key, result, CACHE_SECONDS)
    return {**result, "cached": False}


def _cached_ask(prefix, instructions, context, *, action, user, object_type, object_id="", seconds=3600, refresh=False):
    key = f"soc:ai:{prefix}:" + hashlib.sha256(f"{object_id}:{context}".encode()).hexdigest()[:32]
    if not refresh:
        cached = cache.get(key)
        if cached:
            return {**cached, "cached": True}
    result = _ask(instructions, context, action=action, user=user, object_type=object_type, object_id=object_id)
    if result["ok"]:
        cache.set(key, result, seconds)
    return {**result, "cached": False}


def case_context(case):
    """Il ticket in poche righe: alert, attivita', note di lavoro, fatti e procedura dell'alert principale."""
    from security.services.cases import case_alerts
    from security.services.investigation import facts_as_text

    alerts = case_alerts(case)
    tasks = list(case.tasks.all())
    lines = [
        f"Ticket #{case.pk}: {case.title}",
        f"Severità: {case.severity} · Stato: {case.status} · Aperto il {case.created_at:%d/%m/%Y}",
    ]
    if case.description:
        lines.append(f"Descrizione: {case.description[:500]}")
    for alert in alerts[:8]:
        lines.append(f"Alert: {alert.title} ({alert.severity}, {alert.status})")
    lines += [f"Attività fatta: {task.title}" for task in tasks if task.done]
    lines += [f"Attività da fare: {task.title}" for task in tasks if not task.done]
    for note in case.notes.order_by("-created_at")[:6]:
        lines.append(f"Nota del {note.created_at:%d/%m}: {note.body[:300]}")
    if alerts:
        try:
            lines.append(facts_as_text(alerts[0])[:2000])
        except Exception:  # noqa: BLE001
            logger.exception("Fatti collegati non disponibili per il ticket %s", case.pk)
    return "\n".join(lines)


def _steps_from_text(text, existing):
    """Righe «- passo» della risposta, senza doppioni rispetto alle attivita' gia' nel ticket."""
    seen = {title.strip().lower() for title in existing}
    steps = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip("*").strip()
        if len(line) < 4 or line.endswith(":") or line.lower() in seen:
            continue
        seen.add(line.lower())
        steps.append(line[:255])
    return steps[:5]


def propose_case_steps(case, *, user=None, refresh=False):
    context = case_context(case)
    result = _cached_ask("steps", CASE_STEPS_INSTRUCTIONS, context, action="case_next_steps", user=user,
                         object_type="SecurityRemediationTicket", object_id=case.pk, refresh=refresh)
    result["steps"] = _steps_from_text(result.get("text", ""), [task.title for task in case.tasks.all()]) if result["ok"] else []
    return result


def draft_resolution(case, *, user=None, refresh=False):
    context = case_context(case)
    return _cached_ask("resolution", CASE_RESOLUTION_INSTRUCTIONS, context, action="case_resolution_draft", user=user,
                       object_type="SecurityRemediationTicket", object_id=case.pk, refresh=refresh)


def review_history(review_text, *, user=None, refresh=False):
    return _cached_ask("review", REVIEW_INSTRUCTIONS, review_text, action="history_review", user=user, object_type="history", refresh=refresh)


def daily_brief(items, *, user=None, refresh=False):
    """Sintesi del giorno dai punti «da guardare» della Panoramica."""
    context = "\n".join(f"- {item['level_label']} · {item['area']}: {item['title']}. {item.get('detail', '')}" for item in items) or "(nessun punto aperto)"
    key = "soc:ai:brief:" + hashlib.sha256(context.encode()).hexdigest()[:32]
    if not refresh:
        cached = cache.get(key)
        if cached:
            return {**cached, "cached": True}
    result = _ask(BRIEF_INSTRUCTIONS, context, action="daily_brief", user=user, object_type="overview")
    if result["ok"]:
        cache.set(key, result, 3600)
    return {**result, "cached": False}


# --- Controlli AI su incidente e PC ---------------------------------------------------------

INCIDENT_CHECK_INSTRUCTIONS = (
    "Sei il consulente sicurezza e conformità NIS2/GDPR di una piccola azienda manifatturiera italiana. Controlla la "
    "scheda dell'incidente qui sotto e scrivi in italiano semplice, con queste tre sezioni con il titolo in grassetto:\n"
    "**Cosa manca** (campi vuoti o incoerenti che servono per notifiche e audit: impatto, causa, misure, servizi, "
    "valutazione di significatività, date; elenco puntato, al massimo 5 voci; se è tutto completo dillo)\n"
    "**Scadenze** (per ogni notifica dovuta: rispettata, in ritardo o da fare, con la data; se nessuna è dovuta dillo)\n"
    "**Prossimi passi** (al massimo 3, concreti, elenco puntato).\n"
    "Usa solo i dati forniti, non inventare fatti. Non dare pareri legali definitivi: se un punto va verificato col "
    "consulente o col DPO, scrivilo."
)
PC_CHECK_INSTRUCTIONS = (
    "Sei l'analista della sicurezza IT di una piccola azienda manifatturiera italiana. Dalla scheda del dispositivo "
    "qui sotto (backup, alert aperti, vulnerabilità, segnalazioni della protezione endpoint) scrivi in italiano semplice "
    "tre sezioni con il titolo in grassetto:\n**Stato** (2 frasi: com'è messo il dispositivo e perché)\n"
    "**Rischi** (al massimo 3, elenco puntato, dal più serio, ognuno con il dato che lo giustifica)\n"
    "**Cosa fare** (al massimo 3 passi concreti, elenco puntato).\nUsa solo i dati forniti; se mancano dati dillo."
)


def incident_context(incident):
    from security.services.incidents import SIGNIFICANCE_LABELS, deadlines

    def fmt(value):
        return localtime(value).strftime("%d/%m/%Y %H:%M") if value else "non indicata"

    lines = [
        f"Incidente {incident.code}: {incident.title}",
        f"Categoria: {incident.get_category_display()} · gravità {incident.severity} · stato {incident.get_status_display()}",
        f"Rilevato (conoscenza): {fmt(incident.detected_at)} · avvenuto: {fmt(incident.occurred_at)} · risolto: {fmt(incident.resolved_at)}",
        f"Significativo NIS2: {'sì' if incident.is_significant else 'no'}"
        + (f" (criteri: {'; '.join(SIGNIFICANCE_LABELS.get(c, c) for c in incident.significance_criteria)})" if incident.significance_criteria else ""),
        f"Dati personali coinvolti: {'sì' if incident.personal_data_breach else 'no'} · sospetto malevolo: {'sì' if incident.suspected_malicious else 'no'} · transfrontaliero: {'sì' if incident.cross_border else 'no'}",
        f"Responsabile: {incident.owner.get_username() if incident.owner_id else 'nessuno'}",
    ]
    for label, value in (("Descrizione", incident.description), ("Servizi coinvolti", incident.affected_services),
                         ("Utenti coinvolti", incident.affected_users_count), ("Impatto", incident.impact_description),
                         ("Causa", incident.root_cause), ("Misure adottate", incident.actions_taken),
                         ("Lezioni apprese", incident.lessons_learned), ("Riferimento CSIRT", incident.csirt_reference)):
        lines.append(f"{label}: {str(value).strip()[:400] if value not in (None, '') else 'VUOTO'}")
    dues = deadlines(incident)
    lines.append("Notifiche dovute:" if dues else "Notifiche dovute: nessuna")
    for d in dues:
        lines.append(f"- {d['label']}: scadenza {fmt(d['due_at'])}, inviata {fmt(d['done_at'])}, stato {d['state_label']}")
    tickets = list(incident.tickets.order_by("-updated_at")[:5])
    if tickets:
        lines.append("Ticket collegati: " + "; ".join(f"#{t.pk} {t.title} ({t.status})" for t in tickets))
    notes = list(incident.logs.filter(action="note").order_by("-created_at")[:5])
    if notes:
        lines.append("Ultime note: " + " | ".join(n.body[:200] for n in notes))
    return "\n".join(lines)


def check_incident(incident, *, user=None, refresh=False):
    context = incident_context(incident)
    return _cached_ask("incident-check", INCIDENT_CHECK_INSTRUCTIONS, context, action="incident_check", user=user,
                       object_type="incident", object_id=incident.pk, seconds=1800, refresh=refresh)


def pc_context(pc):
    lines = [f"Dispositivo: {pc['name']}" + (f" ({pc['asset_type']})" if pc.get("asset_type") else ""),
             f"Giudizio della scheda: {pc['status'][1]}"]
    backup = pc.get("backup")
    if backup:
        lines.append(
            f"Backup: ultimo esito {backup['last_label']} il {localtime(backup['last_at']):%d/%m/%Y %H:%M}; ultimo riuscito "
            + (f"{localtime(backup['last_ok']):%d/%m/%Y %H:%M} ({backup['days_since_ok']} giorni fa)" if backup["last_ok"] else "mai nel periodo")
            + f"; riuscite {backup['ok']} su {backup['runs']}; job {', '.join(backup['jobs'])}"
        )
    else:
        lines.append("Backup: il dispositivo non compare nei report di backup")
    lines.append(f"Alert aperti: {pc['alert_count']}" + (": " + "; ".join(f"{a.title} ({a.severity})" for a in pc["alerts"][:5]) if pc["alerts"] else ""))
    lines.append(f"Vulnerabilità aperte: {pc['vuln_count']}" + (": " + "; ".join(f"{v.cve} {v.affected_product} CVSS {v.cvss}" for v in pc["vulns"][:5]) if pc["vulns"] else ""))
    endpoint = pc.get("endpoint") or []
    lines.append(f"Segnalazioni protezione endpoint: {len(endpoint)}" + (": " + "; ".join(e["signal"].title for e in endpoint[:5]) if endpoint else ""))
    return "\n".join(lines)


def check_pc(pc, *, user=None, refresh=False):
    return _cached_ask("pc-check", PC_CHECK_INSTRUCTIONS, pc_context(pc), action="pc_check", user=user,
                       object_type="device", object_id=pc["name"][:80], seconds=1800, refresh=refresh)
