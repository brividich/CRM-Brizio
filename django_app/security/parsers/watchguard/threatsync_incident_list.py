from collections import Counter

from .common import alert_candidate, base_result, concentration_candidates, finalize_result, normalize_csv_row, parse_datetime, read_csv_rows, stable_hash


def parse_watchguard_threatsync_incident_list(text_or_csv, *, source_name=None, received_at=None):
    result = base_result("csv_or_text", "watchguard_threatsync_incident_list", source_name, received_at)
    rows, warnings = read_csv_rows(text_or_csv or "")
    if warnings:
        result["parse_warnings"].extend(warnings)
    asset_counter = Counter()
    threat_counter = Counter()
    severe_counter = Counter()
    open_high = 0
    open_critical = 0
    for row in rows:
        normalized = normalize_csv_row(row)
        severity = _first(normalized, "severity", "risk").lower()
        status = _first(normalized, "status", "state").lower()
        asset = _first(normalized, "asset", "device", "endpoint", "hostname")
        threat = _first(normalized, "threat", "threat_name", "malware", "name")
        timestamp = _first(normalized, "timestamp", "time", "created", "created_at")
        record = {
            "incident_id": _first(normalized, "incident_id", "id"),
            "severity": severity,
            "status": status,
            "asset": asset,
            "user": _first(normalized, "user", "username"),
            "threat_name": threat,
            "action": _first(normalized, "action", "result"),
            "timestamp": timestamp,
            "dedup_key": stable_hash("watchguard", "threatsync", _first(normalized, "incident_id", "id"), asset, threat, timestamp, severity, status),
        }
        result["incidents"].append(record)
        result["records"].append(record)
        if asset:
            asset_counter[asset] += 1
        if threat:
            threat_counter[threat] += 1
        if severity in {"high", "critical"} and status in {"open", "pending"}:
            if severity == "critical":
                open_critical += 1
            else:
                open_high += 1
            severe_counter[(severity, status)] += 1
    result["metrics"].update(
        {
            "watchguard_threatsync_total_count": len(result["incidents"]),
            "watchguard_threatsync_open_high_count": open_high,
            "watchguard_threatsync_open_critical_count": open_critical,
        }
    )
    for (severity, status), count in severe_counter.items():
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_threatsync_open_severe",
                severity,
                f"WatchGuard ThreatSync {severity} incidents {status}",
                "High/Critical incidents are open or pending",
                incident_severity=severity,
                status=status,
                count=count,
            )
        )
    result["alerts_candidates"].extend(concentration_candidates(asset_counter, "watchguard_threatsync_asset_concentration", "asset", 5, "warning"))
    result["alerts_candidates"].extend(concentration_candidates(threat_counter, "watchguard_threatsync_threat_concentration", "threat", 5, "warning"))
    if result["incidents"]:
        first_ts = parse_datetime(result["incidents"][0].get("timestamp"))
        if first_ts:
            result["report_date"] = first_ts.date().isoformat()
    return finalize_result(result, text_or_csv or "")


def _first(row, *names):
    for name in names:
        if row.get(name):
            return row[name]
    return ""
