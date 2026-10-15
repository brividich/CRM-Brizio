"""Stato reale dei parser per la pagina «Configurazione › Parser».

La pagina elencava solo le righe di ``SecurityParserConfig``: tutte «Attivo», anche se il
parser non aveva mai prodotto un report, falliva a ogni mail o non esisteva più nel codice.
Qui si incrociano registry (cosa esiste), configurazione (cosa è acceso) ed esiti reali
(report prodotti, elementi falliti o scartati).
"""
from django.db import transaction
from django.db.models import Count, Max

from security.models import (
    ParseStatus,
    SecurityMailboxMessage,
    SecurityParserConfig,
    SecurityReport,
    SecuritySourceFile,
    SourceType,
)
from security.parsers import parser_registry
from security.parsers.base import QUALITA_COMPLETA, QUALITA_DA_VERIFICARE, QUALITA_PARZIALE
from security.services.configuration import audit_config_change
from security.services.parser_engine import (
    SKIP_PARSER_DISABLED,
    SKIP_REASON_LABELS,
    SKIP_UNTRUSTED_SENDER,
    _match_enabled_parser,
    run_pending_parsers,
    skip_reason,
)
from security.services.text_extraction import extract_text

DEFAULT_PRIORITY = 100
# Esiti scansionati per contare errori e scarti: basta la storia recente.
RECENT_ITEMS_WINDOW = 500
REPROCESS_LIMIT = 500

PARSER_INFO = {
    "microsoft_defender_vulnerability_notification_email_parser": {
        "label": "Microsoft Defender · vulnerabilità",
        "vendor": "Microsoft",
        "inputs": "Mail",
        "recognizes": "Notifiche «New vulnerabilities notification» con CVE, solo da mittente @microsoft.com.",
    },
    "synology_active_backup_email_parser": {
        "label": "Synology Active Backup",
        "vendor": "Synology",
        "inputs": "Mail",
        "recognizes": "Esiti dei job Active Backup for Business (mail in italiano o inglese).",
    },
    "veeam_backup_email_parser": {
        "label": "Veeam Backup & Replication",
        "vendor": "Veeam",
        "inputs": "Mail",
        "recognizes": "Esiti dei job Veeam («[Success] Backup ...»): stato, orari, dimensioni, durata e macchine virtuali.",
    },
    "watchguard_report_parser": {
        "label": "WatchGuard · tutti i report",
        "vendor": "WatchGuard",
        "inputs": "Mail, PDF, CSV",
        "recognizes": "Dimension, autenticazioni VPN Firebox (CSV), EPDR, ThreatSync, SD-WAN, Zero-Day/APT.",
    },
}

STATUS_LABELS = {
    "ok": "Funziona",
    "error": "In errore",
    "idle": "Mai usato",
    "disabled": "Disattivato",
    "orphan": "Non esiste nel codice",
    "to_check": "Letture da verificare",
}
STATUS_BADGES = {"ok": "ok", "error": "critical", "idle": "warning", "disabled": "disabled", "orphan": "critical", "to_check": "warning"}


def _effective_order():
    """Registry nell'ordine in cui lo valuta ``parser_engine`` (priorità, poi registrazione)."""
    configs = {config.parser_name: config for config in SecurityParserConfig.objects.all()}
    parsers = parser_registry.all()
    parsers.sort(key=lambda parser: configs[parser.name].priority if parser.name in configs else DEFAULT_PRIORITY)
    return parsers, configs


def _recent_outcomes():
    """Per parser: fallimenti (con l'ultimo errore) e scarti perché disattivato."""
    failures, disabled_skips = {}, {}
    for model, date_field in ((SecurityMailboxMessage, "received_at"), (SecuritySourceFile, "uploaded_at")):
        items = model.objects.filter(parse_status__in=[ParseStatus.FAILED, ParseStatus.SKIPPED]).order_by(f"-{date_field}")
        for item in items[:RECENT_ITEMS_WINDOW]:
            payload = item.raw_payload or {}
            when = getattr(item, date_field)
            if item.parse_status == ParseStatus.FAILED:
                name = payload.get("parser_name") or ""
                row = failures.setdefault(name, {"count": 0, "last_at": None, "last_error": "", "last_hint": ""})
                row["count"] += 1
                if row["last_at"] is None or (when and when > row["last_at"]):
                    row["last_at"] = when
                    row["last_error"] = payload.get("parser_error", "")
                    row["last_hint"] = payload.get("parser_error_hint", "")
            elif payload.get("skip_reason") == SKIP_PARSER_DISABLED:
                name = str(payload.get("skip_detail", "")).rsplit(":", 1)[-1].strip()
                disabled_skips[name] = disabled_skips.get(name, 0) + 1
    return failures, disabled_skips


def _recent_quality():
    """Per parser: letture recenti «da verificare» o «parziali» (campi obbligatori mancanti, avvisi).

    Un parser che non va in errore ma legge a metà sembrava «Funziona»: le cifre arrivavano
    a zero o vuote e nessuno se ne accorgeva. ``lettura_qualita`` è scritta da ``parser_engine``.
    """
    quality = {}
    for model, date_field in ((SecurityMailboxMessage, "received_at"), (SecuritySourceFile, "uploaded_at")):
        rows = model.objects.filter(parse_status=ParseStatus.PARSED).order_by(f"-{date_field}").values_list("raw_payload", flat=True)
        for payload in rows[:RECENT_ITEMS_WINDOW]:
            payload = payload or {}
            name = payload.get("parser_name") or ""
            level = payload.get("lettura_qualita") or ""
            if not name or not level:
                continue
            row = quality.setdefault(name, {QUALITA_DA_VERIFICARE: 0, QUALITA_PARZIALE: 0, QUALITA_COMPLETA: 0})
            if level in row:
                row[level] += 1
    return quality


def parser_overview():
    parsers, configs = _effective_order()
    report_stats = {
        row["parser_name"]: row
        for row in SecurityReport.objects.values("parser_name").annotate(total=Count("id"), last_at=Max("created_at")).order_by()
    }
    failures, disabled_skips = _recent_outcomes()
    quality = _recent_quality()

    rows = []
    for position, parser in enumerate(parsers, start=1):
        config = configs.get(parser.name)
        enabled = config.enabled if config else True
        reports = report_stats.get(parser.name, {})
        failure = failures.get(parser.name, {})
        last_ok = reports.get("last_at")
        if not enabled:
            status = "disabled"
        elif failure.get("last_at") and (not last_ok or failure["last_at"] > last_ok):
            status = "error"
        elif reports.get("total"):
            status = "ok"
        else:
            status = "idle"
        row = _row(parser.name, config, status, position=position, enabled=enabled, reports=reports, failure=failure, disabled_skips=disabled_skips.get(parser.name, 0))
        row["quality"] = quality.get(parser.name, {})
        row["to_check"] = row["quality"].get(QUALITA_DA_VERIFICARE, 0)
        if status == "ok" and row["to_check"]:
            row["status"], row["status_label"], row["status_badge"] = "to_check", STATUS_LABELS["to_check"], STATUS_BADGES["to_check"]
        rows.append(row)

    registered = {parser.name for parser in parsers}
    for name, config in sorted(configs.items()):
        if name not in registered:
            rows.append(_row(name, config, "orphan", enabled=config.enabled, reports=report_stats.get(name, {}), failure=failures.get(name, {})))

    return {
        "parser_rows": rows,
        "parser_summary": {
            "total": len(rows),
            "ok": sum(1 for row in rows if row["status"] in {"ok", "to_check"}),
            "problems": sum(1 for row in rows if row["status"] in {"error", "orphan"}),
            "to_check": sum(1 for row in rows if row["status"] == "to_check"),
            "missing_config": sum(1 for row in rows if row["registered"] and row["config"] is None),
        },
        "queue_summary": _queue_summary(),
        "unprocessed_items": _unprocessed_items(),
        "to_check_items": _to_check_items(),
    }


def _to_check_items(limit=10):
    """Ultimi elementi letti ma «da verificare», con l'eventuale proposta dell'AI."""
    items = []
    for model, date_field, kind in ((SecurityMailboxMessage, "received_at", "Mail"), (SecuritySourceFile, "uploaded_at", "File")):
        rows = model.objects.filter(parse_status=ParseStatus.PARSED).select_related("source").order_by(f"-{date_field}")[:RECENT_ITEMS_WINDOW]
        for item in rows:
            payload = item.raw_payload or {}
            if payload.get("lettura_qualita") != QUALITA_DA_VERIFICARE:
                continue
            items.append({
                "kind": kind,
                "title": getattr(item, "subject", "") or getattr(item, "original_name", ""),
                "parser": PARSER_INFO.get(payload.get("parser_name"), {}).get("label", payload.get("parser_name", "")),
                "source": getattr(item.source, "name", ""),
                "at": getattr(item, date_field),
                "ai": payload.get("ai_lettura") or None,
            })
            if len(items) >= limit * 2:
                break
    items.sort(key=lambda row: row["at"].timestamp() if row["at"] else 0, reverse=True)
    return items[:limit]


def _row(name, config, status, *, position=None, enabled, reports, failure, disabled_skips=0):
    info = PARSER_INFO.get(name, {})
    return {
        "name": name,
        "label": info.get("label") or name.replace("_", " "),
        "vendor": info.get("vendor", ""),
        "inputs": info.get("inputs", ""),
        "recognizes": info.get("recognizes") or (config.description if config else ""),
        "config": config,
        "registered": status != "orphan",
        "position": position,
        "priority": config.priority if config else DEFAULT_PRIORITY,
        "enabled": enabled,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "status_badge": STATUS_BADGES[status],
        "reports_total": reports.get("total", 0),
        "last_report_at": reports.get("last_at"),
        "failures_count": failure.get("count", 0),
        "last_failure_at": failure.get("last_at"),
        "last_error": failure.get("last_error", ""),
        "last_hint": failure.get("last_hint", ""),
        "disabled_skips": disabled_skips,
    }


def _queue_summary():
    summary = {}
    for status in (ParseStatus.PENDING, ParseStatus.FAILED, ParseStatus.SKIPPED):
        summary[status.value] = (
            SecurityMailboxMessage.objects.filter(parse_status=status).count()
            + SecuritySourceFile.objects.filter(parse_status=status).count()
        )
    return summary


def _unprocessed_items(limit=10):
    """Ultimi elementi falliti o scartati, con il perché: è da qui che si capisce cosa non va."""
    items = []
    for model, date_field, kind in ((SecurityMailboxMessage, "received_at", "Mail"), (SecuritySourceFile, "uploaded_at", "File")):
        for item in model.objects.filter(parse_status__in=[ParseStatus.FAILED, ParseStatus.SKIPPED]).select_related("source").order_by(f"-{date_field}")[:limit]:
            payload = item.raw_payload or {}
            if item.parse_status == ParseStatus.FAILED:
                reason = f"Errore del parser {payload.get('parser_name') or '?'}: {payload.get('parser_error') or 'nessun dettaglio'}"
                hint = payload.get("parser_error_hint", "")
            else:
                reason = payload.get("skip_detail") or SKIP_REASON_LABELS.get(payload.get("skip_reason"), "Scartato (motivo non registrato)")
                hint = ""
            items.append(
                {
                    "kind": kind,
                    "title": getattr(item, "subject", "") or getattr(item, "original_name", ""),
                    "sender": getattr(item, "sender", ""),
                    "source": getattr(item.source, "name", ""),
                    "at": getattr(item, date_field),
                    "status": item.parse_status,
                    "reason": reason,
                    "hint": hint,
                    "ai": payload.get("ai_lettura") or None,
                }
            )
    items.sort(key=lambda row: row["at"].timestamp() if row["at"] else 0, reverse=True)
    return items[:limit]


def reprocess_items():
    """Rimette in coda falliti e scartati e riesegue parser (e regole).

    Serve dopo aver riattivato un parser o corretto una configurazione: prima gli
    elementi restavano FAILED/SKIPPED per sempre. Le mail da mittente non attendibile
    NON rientrano: sono scartate apposta e hanno già generato l'alert di spoofing.
    """
    from security.services.rule_engine import evaluate_security_rules

    requeued = 0
    for model, date_field in ((SecurityMailboxMessage, "received_at"), (SecuritySourceFile, "uploaded_at")):
        items = model.objects.filter(parse_status__in=[ParseStatus.FAILED, ParseStatus.SKIPPED]).order_by(f"-{date_field}")[:REPROCESS_LIMIT]
        for item in items:
            payload = dict(item.raw_payload or {})
            if payload.get("skip_reason") == SKIP_UNTRUSTED_SENDER:
                continue
            for key in ("skip_reason", "skip_detail", "parser_error", "parser_error_hint", "parser_name"):
                payload.pop(key, None)
            item.raw_payload = payload
            item.parse_status = ParseStatus.PENDING
            item.save(update_fields=["parse_status", "raw_payload"])
            requeued += 1
    parsed = run_pending_parsers()
    evaluate_security_rules()
    return {"requeued": requeued, "parsed": parsed, "still_unprocessed": _queue_summary()}


def delete_orphan_config(config, *, actor=None, request=None):
    """Elimina la configurazione di un parser che non esiste nel codice (mai un parser vivo)."""
    if config.parser_name in {parser.name for parser in parser_registry.all()}:
        return False
    audit_config_change(actor, "delete", config, "parser_name", config.parser_name, "", request=request)
    config.delete()
    return True


def test_parsers(*, sender="", subject="", body="", filename="", data=None, with_ai=False, user=None):
    """Prova a secco: quale parser prenderebbe questo contenuto e cosa ne estrarrebbe.

    Nessun salvataggio: gli oggetti restano in memoria e l'eventuale scrittura di un
    parser viene annullata dal rollback.
    """
    warnings = []
    if filename:
        text, warnings = extract_text(filename, data or b"")
        item = SecuritySourceFile(original_name=filename, content=text, file_type=SourceType.PDF if filename.lower().endswith(".pdf") else SourceType.MANUAL)
        extracted_preview = " ".join(text.split())[:600]
    else:
        item = SecurityMailboxMessage(sender=sender, subject=subject or "", body=body or "")
        extracted_preview = ""

    parsers, configs = _effective_order()
    candidates = []
    for parser in parsers:
        config = configs.get(parser.name)
        try:
            recognizes = bool(parser.can_parse(item))
        except Exception as exc:  # noqa: BLE001
            recognizes, warnings = False, warnings + [f"{parser.name}: errore nel riconoscimento ({str(exc)[:150]})"]
        candidates.append(
            {
                "name": parser.name,
                "label": PARSER_INFO.get(parser.name, {}).get("label", parser.name),
                "enabled": config.enabled if config else True,
                "recognizes": recognizes,
                "impersonation": bool(parser.impersonation_suspect(item)),
                "why": _why(parser, item),
            }
        )

    chosen = _match_enabled_parser(item)
    result = {"candidates": candidates, "warnings": warnings, "extracted_preview": extracted_preview, "is_file": bool(filename), "filename": filename}
    if not chosen:
        code, detail = skip_reason(item)
        result.update({"chosen": None, "skip_code": code, "skip_detail": detail})
        return _with_ai(result, with_ai, item, None, user)

    result["chosen"] = PARSER_INFO.get(chosen.name, {}).get("label", chosen.name)
    result["chosen_name"] = chosen.name
    try:
        with transaction.atomic():
            parsed = chosen.parse(item)
            transaction.set_rollback(True)
    except Exception as exc:  # noqa: BLE001 - è proprio l'errore che l'operatore deve vedere
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        return _with_ai(result, with_ai, item, chosen.name, user)
    record_types = {}
    for record in parsed.records:
        record_types[record.record_type] = record_types.get(record.record_type, 0) + 1
    result["parsed"] = {
        "report_type": parsed.report_type,
        "title": parsed.title,
        "metrics": sorted((name, value) for name, value in parsed.metrics.items() if isinstance(value, (int, float)) and not isinstance(value, bool))[:20],
        "record_types": sorted(record_types.items()),
        "records_total": len(parsed.records),
        "parse_warnings": list((parsed.payload or {}).get("parse_warnings") or [])[:10],
        "alert_candidates": len((parsed.payload or {}).get("alerts_candidates") or (parsed.payload or {}).get("alert_candidates") or []),
        "lettura": (parsed.payload or {}).get("lettura") or {},
    }
    return _with_ai(result, with_ai, item, chosen.name, user)


def _with_ai(result, with_ai, item, parser_name, user):
    """«Chiedi all'AI»: proposta della lettura assistita sullo stesso contenuto (nessun salvataggio)."""
    if not with_ai:
        return result
    from security.services.ai_lettura import proponi_a_secco

    is_file = isinstance(item, SecuritySourceFile)
    result["ai"] = proponi_a_secco(
        subject=item.original_name if is_file else item.subject,
        text=(item.content if is_file else item.body) or "",
        parser_name=parser_name, user=user,
    )
    return result


def _why(parser, item):
    """Perché il parser riconosce (o no) il contenuto: solo spiegazione, mai una decisione."""
    try:
        return list(parser.perche_riconosce(item) or [])[:5]
    except Exception:  # noqa: BLE001 - la spiegazione non deve mai rompere la prova
        return []
