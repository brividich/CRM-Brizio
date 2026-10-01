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
    "gergo inutile. Usa esattamente queste quattro sezioni, ciascuna con il titolo in grassetto:\n"
    "**Cosa è successo** (2-3 frasi)\n**Perché è scattato l'alert** (la regola e il valore che l'hanno fatto scattare)\n"
    "**Quanto è urgente** (bassa, media o alta, con il motivo in una frase)\n**Cosa fare adesso** (al massimo 3 passi concreti, elenco puntato).\n"
    "Usa solo i dati del contesto: se un'informazione manca, dillo invece di inventarla. Non ripetere il contesto."
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
