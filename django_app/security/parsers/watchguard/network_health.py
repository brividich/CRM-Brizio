import re

from .common import alert_candidate, base_result, finalize_result, find_period, normalize_csv_row, parse_number, read_csv_rows
from .config import SDWAN_JITTER_WARN_MS, SDWAN_LATENCY_WARN_MS, SDWAN_PACKET_LOSS_HIGH, SDWAN_PACKET_LOSS_WARN


def parse_watchguard_interface_summary(text_or_csv, *, source_name=None, received_at=None):
    return _parse_network_health(text_or_csv, "watchguard_interface_summary", source_name, received_at)


def parse_watchguard_sdwan_status(text_or_csv, *, source_name=None, received_at=None):
    return _parse_network_health(text_or_csv, "watchguard_sdwan_status", source_name, received_at)


def _parse_network_health(text_or_csv, report_type, source_name, received_at):
    result = base_result("csv_or_text", report_type, source_name, received_at)
    text = text_or_csv or ""
    start, end, date = find_period(text, source_name)
    result["period_start"] = start
    result["period_end"] = end
    result["report_date"] = date
    rows, warnings = read_csv_rows(text)
    if rows and not warnings:
        records = [_record_from_row(row) for row in rows]
    else:
        records = _records_from_text(text)
        if not records:
            result["parse_warnings"].extend(warnings or ["No interface or SD-WAN metrics recognized"])
    result["records"] = records
    losses = [record["packet_loss"] for record in records if record["packet_loss"] is not None]
    latencies = [record["latency_ms"] for record in records if record["latency_ms"] is not None]
    jitters = [record["jitter_ms"] for record in records if record["jitter_ms"] is not None]
    dropped = [record["dropped_packets"] for record in records if record["dropped_packets"] is not None]
    result["metrics"].update(
        {
            "watchguard_sdwan_loss_avg": sum(losses) / len(losses) if losses else 0,
            "watchguard_sdwan_latency_avg_ms": sum(latencies) / len(latencies) if latencies else 0,
            "watchguard_sdwan_jitter_avg_ms": sum(jitters) / len(jitters) if jitters else 0,
            "watchguard_dropped_packets_total": sum(dropped) if dropped else 0,
        }
    )
    for record in records:
        _add_network_alerts(result, record)
    return finalize_result(result, text)


def _record_from_row(row):
    normalized = normalize_csv_row(row)
    return {
        "interface": _first(normalized, "interface", "link", "name"),
        "bytes_in": parse_number(_first(normalized, "bytes_in", "in_bytes")),
        "bytes_out": parse_number(_first(normalized, "bytes_out", "out_bytes")),
        "bps": parse_number(_first(normalized, "bps", "throughput")),
        "packets": parse_number(_first(normalized, "packets")),
        "dropped_packets": parse_number(_first(normalized, "dropped_packets", "drops")),
        "packet_loss": parse_number(_first(normalized, "packet_loss", "loss")),
        "latency_ms": parse_number(_first(normalized, "latency", "latency_ms")),
        "jitter_ms": parse_number(_first(normalized, "jitter", "jitter_ms")),
    }


def _records_from_text(text):
    records = []
    for line in text.splitlines():
        if not re.search(r"(loss|latency|jitter|drop|bytes|packets)", line, flags=re.I):
            continue
        name_match = re.match(r"\s*([A-Za-z0-9_.\-/ ]+?)\s*[:,-]", line)
        records.append(
            {
                "interface": name_match.group(1).strip() if name_match else "",
                "bytes_in": _metric(line, "bytes in"),
                "bytes_out": _metric(line, "bytes out"),
                "bps": _metric(line, "bps"),
                "packets": _metric(line, "packets"),
                "dropped_packets": _metric(line, "dropped"),
                "packet_loss": _metric(line, "loss"),
                "latency_ms": _metric(line, "latency"),
                "jitter_ms": _metric(line, "jitter"),
            }
        )
    return records


def _add_network_alerts(result, record):
    label = record.get("interface") or "unknown link"
    loss = record.get("packet_loss") or 0
    if loss >= SDWAN_PACKET_LOSS_HIGH:
        severity = "high"
    elif loss >= SDWAN_PACKET_LOSS_WARN:
        severity = "warning"
    else:
        severity = None
    if severity:
        result["alerts_candidates"].append(alert_candidate("watchguard_sdwan_packet_loss", severity, f"WatchGuard packet loss on {label}", "Packet loss is above threshold", interface=label, value=loss))
    if (record.get("latency_ms") or 0) >= SDWAN_LATENCY_WARN_MS:
        result["alerts_candidates"].append(alert_candidate("watchguard_sdwan_latency", "warning", f"WatchGuard latency on {label}", "Latency is above threshold", interface=label, value=record["latency_ms"]))
    if (record.get("jitter_ms") or 0) >= SDWAN_JITTER_WARN_MS:
        result["alerts_candidates"].append(alert_candidate("watchguard_sdwan_jitter", "warning", f"WatchGuard jitter on {label}", "Jitter is above threshold", interface=label, value=record["jitter_ms"]))
    if (record.get("dropped_packets") or 0) > 0:
        result["alerts_candidates"].append(alert_candidate("watchguard_dropped_packets", "warning", f"WatchGuard dropped packets on {label}", "Dropped packets are present; no baseline available yet", interface=label, value=record["dropped_packets"]))


def _metric(line, label):
    match = re.search(rf"{re.escape(label)}\s*[:=]?\s*(\d+(?:[\.,]\d+)?)", line, flags=re.I)
    if not match and label == "loss":
        match = re.search(r"(\d+(?:[\.,]\d+)?)\s*%\s*(?:packet\s*)?loss", line, flags=re.I)
    if not match and label == "dropped":
        match = re.search(r"dropped\s+packets?\s*[:=]?\s*(\d+(?:[\.,]\d+)?)", line, flags=re.I)
    return parse_number(match.group(1)) if match else None


def _first(row, *names):
    for name in names:
        if row.get(name):
            return row[name]
    return ""
