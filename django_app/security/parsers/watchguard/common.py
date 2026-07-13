import csv
import hashlib
import re
from collections import Counter
from decimal import Decimal
from datetime import datetime
from io import StringIO


def stable_hash(*parts):
    seed = ":".join(_normalize_for_hash(part) for part in parts)
    return hashlib.sha256(seed.encode()).hexdigest()


def base_result(source_type, report_type, source_name=None, received_at=None):
    return {
        "vendor": "watchguard",
        "source_type": source_type,
        "report_type": report_type,
        "source_name": source_name,
        "received_at": received_at.isoformat() if hasattr(received_at, "isoformat") else received_at,
        "report_date": None,
        "period_start": None,
        "period_end": None,
        "organization": None,
        "customer": None,
        "firebox_name": _firebox_from_source_name(source_name),
        "metrics": {},
        "records": [],
        "events": [],
        "incidents": [],
        "alerts_candidates": [],
        "dedup_key": None,
        "normalized_hash": None,
        "parse_warnings": [],
        "raw_summary": "",
    }


def finalize_result(result, content):
    if not str(content or "").strip() and "Report contains no content" not in result["parse_warnings"]:
        result["parse_warnings"].append("Report contains no content")
    result["normalized_hash"] = stable_hash(result["vendor"], result["report_type"], _normalize_content(content))
    result["dedup_key"] = stable_hash(
        result["vendor"],
        result["report_type"],
        result.get("period_start") or result.get("report_date"),
        result.get("period_end"),
        result.get("firebox_name") or result.get("customer") or result.get("organization"),
        result["normalized_hash"],
    )
    if not result["raw_summary"]:
        result["raw_summary"] = (
            f"{result['report_type']}: {len(result['records'])} records, "
            f"{len(result['alerts_candidates'])} alert candidates"
        )
    return result


def parse_number(value):
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text or text.lower() in {"no data", "n/a", "-"}:
        return 0.0
    match = re.search(r"(-?[\d.,]+)\s*([kmb])?", text, flags=re.I)
    if not match:
        return 0.0
    number = float(_normalize_number_text(match.group(1)))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        number *= 1_000
    elif suffix == "m":
        number *= 1_000_000
    elif suffix == "b":
        number *= 1_000_000_000
    return number


def parse_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_duration_seconds(value):
    if not value:
        return 0
    text = str(value).strip()
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return int(float(text))
    except ValueError:
        return 0


def read_csv_rows(csv_text):
    text = (csv_text or "").strip("\ufeff")
    if not text.strip() or text.strip().lower() == "no data":
        return [], ["CSV contains no data"]
    rows = list(csv.DictReader(StringIO(text)))
    return rows, [] if rows else ["CSV header found but no rows parsed"]


def normalize_csv_row(row):
    normalized = {}
    for key, value in (row or {}).items():
        if key is None:
            continue
        normalized[str(key).strip().lower().replace(" ", "_")] = _clean_csv_value(value)
    return normalized


def find_period(text, source_name=None):
    combined = " ".join(part for part in [source_name, text] if part)
    match = re.search(
        r"(\d{4}-\d{2}-\d{2})[T ](\d{2})[_:](\d{2}).{0,20}?to.{0,20}?(\d{4}-\d{2}-\d{2})[T ](\d{2})[_:](\d{2})",
        combined,
        flags=re.I | re.S,
    )
    if match:
        start = f"{match.group(1)} {match.group(2)}:{match.group(3)}:00"
        end = f"{match.group(4)} {match.group(5)}:{match.group(6)}:00"
        return start, end, match.group(1)
    match = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2}).{0,8}(?:-|to).{0,8}(\d{4}-\d{2}-\d{2})?\s*(\d{2}:\d{2})", combined, flags=re.I)
    if match:
        end_date = match.group(3) or match.group(1)
        return f"{match.group(1)} {match.group(2)}:00", f"{end_date} {match.group(4)}:00", match.group(1)
    match = re.search(r"(\d{4}-\d{2}-\d{2})", combined)
    if match:
        return None, None, match.group(1)
    return None, None, None


def metric_from_label(text, label):
    pattern = rf"{re.escape(label)}[^\d]*(\d+(?:[\.,]\d+)?\s*[KMBkmb]?)"
    match = re.search(pattern, text, flags=re.I)
    return parse_number(match.group(1)) if match else 0.0


def alert_candidate(kind, severity, title, reason, **payload):
    key = stable_hash("watchguard", kind, title, severity, payload)
    return {
        "type": kind,
        "severity": severity,
        "title": title,
        "reason": reason,
        "dedup_key": key,
        **payload,
    }


def top_counter(counter, limit=10):
    return [{"value": value, "count": count} for value, count in counter.most_common(limit)]


def concentration_candidates(counter, kind, label, threshold, severity="warning"):
    candidates = []
    for value, count in counter.items():
        if value and count >= threshold:
            candidates.append(
                alert_candidate(
                    kind,
                    severity,
                    f"WatchGuard concentration on {label}: {value}",
                    f"{count} records share the same {label}",
                    subject=value,
                    count=count,
                    threshold=threshold,
                )
            )
    return candidates


def _normalize_for_hash(part):
    if isinstance(part, dict):
        return repr(sorted(part.items())).lower()
    if isinstance(part, list):
        return repr(part).lower()
    if isinstance(part, Decimal):
        return str(float(part))
    return str(part or "").strip().lower()


def _normalize_content(content):
    lines = []
    for line in str(content or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line.strip().lower())
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def _normalize_number_text(text):
    text = str(text).strip().replace(" ", "")
    has_dot = "." in text
    has_comma = "," in text
    if has_dot and has_comma:
        if text.rfind(",") > text.rfind("."):
            return text.replace(".", "").replace(",", ".")
        return text.replace(",", "")
    if has_comma:
        whole, fraction = text.rsplit(",", 1)
        if len(fraction) == 3 and whole.replace("-", "").isdigit():
            return whole.replace(",", "") + fraction
        return whole.replace(",", "") + "." + fraction
    return text


def _clean_csv_value(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if item is not None).strip()
    return str(value).strip()


def _firebox_from_source_name(source_name):
    if not source_name:
        return None
    name = str(source_name)
    for marker in ["_Authentication", "_Zero", "_APT", "_Botnet", "_GAV", "_IPS", "_Access", "_Denied", "_Interface", "_SD-WAN"]:
        if marker.lower() in name.lower():
            return name[: name.lower().find(marker.lower())]
    if "firebox" in name.lower():
        match = re.search(r"firebox[:\s]+([A-Za-z0-9_.-]+)", name, flags=re.I)
        if match:
            return match.group(1)
    return None
