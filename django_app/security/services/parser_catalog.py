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
}
STATUS_BADGES = {"ok": "ok", "error": "critical", "idle": "warning", "disabled": "disabled", "orphan": "critical"}


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
                row = failures.setdefault(name, {"count": 0, "last_at": None, "last_error": ""})
                row["count"] += 1
                if row["last_at"] is None or (when and when > row["last_at"]):
                    row["last_at"] = when
                    row["last_error"] = payload.get("parser_error", "")
            elif payload.get("skip_reason") == SKIP_PARSER_DISABLED:
                name = str(payload.get("skip_detail", "")).rsplit(":", 1)[-1].strip()
                disabled_skips[name] = disabled_skips.get(name, 0) + 1
    return failures, disabled_skips


def parser_overview():
    parsers, configs = _effective_order()
    report_stats = {
        row["parser_name"]: row
        for row in SecurityReport.objects.values("parser_name").annotate(total=Count("id"), last_at=Max("created_at")).order_by()
    }
    failures, disabled_skips = _recent_outcomes()

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
        rows.append(_row(parser.name, config, status, position=position, enabled=enabled, reports=reports, failure=failure, disabled_skips=disabled_skips.get(parser.name, 0)))

    registered = {parser.name for parser in parsers}
    for name, config in sorted(configs.items()):
        if name not in registered:
            rows.append(_row(name, config, "orphan", enabled=config.enabled, reports=report_stats.get(name, {}), failure=failures.get(name, {})))

    return {
        "parser_rows": rows,
        "parser_summary": {
            "total": len(rows),
            "ok": sum(1 for row in rows if row["status"] == "ok"),
            "problems": sum(1 for row in rows if row["status"] in {"error", "orphan"}),
            "missing_config": sum(1 for row in rows if row["registered"] and row["config"] is None),
        },
        "queue_summary": _queue_summary(),
        "unprocessed_items": _unprocessed_items(),
    }


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
            else:
                reason = payload.get("skip_detail") or SKIP_REASON_LABELS.get(payload.get("skip_reason"), "Scartato (motivo non registrato)")
            items.append(
                {
                    "kind": kind,
                    "title": getattr(item, "subject", "") or getattr(item, "original_name", ""),
                    "sender": getattr(item, "sender", ""),
                    "source": getattr(item.source, "name", ""),
                    "at": getattr(item, date_field),
                    "status": item.parse_status,
                    "reason": reason,
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
            for key in ("skip_reason", "skip_detail", "parser_error", "parser_name"):
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


def test_parsers(*, sender="", subject="", body="", filename="", data=None):
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
            }
        )

    chosen = _match_enabled_parser(item)
    result = {"candidates": candidates, "warnings": warnings, "extracted_preview": extracted_preview, "is_file": bool(filename), "filename": filename}
    if not chosen:
        code, detail = skip_reason(item)
        result.update({"chosen": None, "skip_code": code, "skip_detail": detail})
        return result

    result["chosen"] = PARSER_INFO.get(chosen.name, {}).get("label", chosen.name)
    result["chosen_name"] = chosen.name
    try:
        with transaction.atomic():
            parsed = chosen.parse(item)
            transaction.set_rollback(True)
    except Exception as exc:  # noqa: BLE001 - è proprio l'errore che l'operatore deve vedere
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        return result
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
    }
    return result
