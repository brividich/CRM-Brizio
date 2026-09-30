import re
from collections import Counter, defaultdict

from .common import alert_candidate, base_result, finalize_result, normalize_csv_row, parse_datetime, parse_duration_seconds, read_csv_rows, stable_hash, top_counter
from .config import (
    VPN_DENIED_THRESHOLD_PER_IP,
    VPN_LONG_SESSION_SECONDS,
    VPN_MANY_SHORT_RECONNECTS_THRESHOLD,
    VPN_SHORT_SESSION_SECONDS,
)

KIND_VPN, KIND_FIREWALL, KIND_GUEST, KIND_OTHER = "vpn", "firewall", "guest", "other"
_VPN_WORDS = ("vpn", "ssl", "ipsec", "pptp", "l2tp", "ikev2")


def classify_kind(method, reason=""):
    """Tipo di autenticazione. Il report «Authentication» del Firebox NON e' solo VPN: la colonna
    `method` distingue Firewall, VPN, Guest. Contarli tutti come VPN gonfiava gli accessi
    (centinaia di login «Firewall» al minuto di un servizio) e generava alert falsi."""
    text = f"{method} {reason}".lower()
    if any(word in text for word in _VPN_WORDS):
        return KIND_VPN
    if "firewall" in text:
        return KIND_FIREWALL
    if "guest" in text or "portal" in text:
        return KIND_GUEST
    return KIND_OTHER


def parse_watchguard_firebox_authentication_allowed_csv(csv_text, *, source_name=None, received_at=None):
    result = _parse_authentication_csv(csv_text, "allowed", source_name=source_name, received_at=received_at)
    result["report_type"] = "watchguard_firebox_authentication_allowed"
    records = result["records"]
    vpn = [record for record in records if record["kind"] == KIND_VPN]
    result["metrics"]["watchguard_auth_allowed_total"] = len(records)
    result["metrics"]["watchguard_firewall_auth_count"] = sum(1 for record in records if record["kind"] == KIND_FIREWALL)
    result["metrics"]["watchguard_sslvpn_allowed_count"] = len(vpn)
    result["metrics"]["watchguard_sslvpn_denied_count"] = 0
    short_by_user = Counter(record["user"] for record in vpn if 0 < record["duration_seconds"] <= VPN_SHORT_SESSION_SECONDS)
    long_sessions = [record for record in vpn if record["duration_seconds"] > VPN_LONG_SESSION_SECONDS]
    result["metrics"]["watchguard_sslvpn_short_reconnect_count"] = sum(short_by_user.values())
    result["metrics"]["watchguard_sslvpn_long_session_count"] = len(long_sessions)
    for user, count in short_by_user.items():
        if user and count >= VPN_MANY_SHORT_RECONNECTS_THRESHOLD:
            result["alerts_candidates"].append(
                alert_candidate(
                    "watchguard_vpn_many_short_reconnects",
                    "warning",
                    f"Many short SSL VPN reconnects for {user}",
                    "Short reconnect volume is above the configured threshold",
                    user=user,
                    count=count,
                    threshold=VPN_MANY_SHORT_RECONNECTS_THRESHOLD,
                )
            )
    for record in long_sessions[:10]:
        result["alerts_candidates"].append(
            alert_candidate(
                "watchguard_vpn_long_session",
                "warning",
                f"Long SSL VPN session for {record['user']}",
                "Session duration is above the configured long-session threshold",
                user=record["user"],
                source_ip=record["source_ip"],
                duration_seconds=record["duration_seconds"],
                threshold=VPN_LONG_SESSION_SECONDS,
            )
        )
    return _finalize_auth_result(result, csv_text)


def parse_watchguard_firebox_authentication_denied_csv(csv_text, *, source_name=None, received_at=None):
    result = _parse_authentication_csv(csv_text, "denied", source_name=source_name, received_at=received_at)
    result["report_type"] = "watchguard_firebox_authentication_denied"
    records = result["records"]
    result["metrics"]["watchguard_sslvpn_allowed_count"] = 0
    result["metrics"]["watchguard_auth_denied_total"] = len(records)
    result["metrics"]["watchguard_sslvpn_denied_count"] = sum(1 for record in records if record["kind"] == KIND_VPN)
    denied_by_ip = Counter(record["source_ip"] for record in records)
    denied_by_user = Counter(record["user"] for record in records)
    for source_ip, count in denied_by_ip.items():
        if source_ip and count >= VPN_DENIED_THRESHOLD_PER_IP:
            result["alerts_candidates"].append(
                alert_candidate(
                    "watchguard_vpn_repeated_denied",
                    "warning",
                    f"Repeated denied SSL VPN logins from {source_ip}",
                    "Denied login volume from one source IP is above threshold",
                    source_ip=source_ip,
                    count=count,
                    threshold=VPN_DENIED_THRESHOLD_PER_IP,
                )
            )
    for user, count in denied_by_user.items():
        if user and count >= VPN_DENIED_THRESHOLD_PER_IP:
            result["alerts_candidates"].append(
                alert_candidate(
                    "watchguard_vpn_repeated_denied",
                    "warning",
                    f"Repeated denied SSL VPN logins for {user}",
                    "Denied login volume for one user is above threshold",
                    user=user,
                    count=count,
                    threshold=VPN_DENIED_THRESHOLD_PER_IP,
                )
            )
    return _finalize_auth_result(result, csv_text)


def _parse_authentication_csv(csv_text, action, *, source_name=None, received_at=None):
    result = base_result("csv", f"watchguard_firebox_authentication_{action}", source_name, received_at)
    rows, warnings = read_csv_rows(csv_text)
    if not _has_access_columns(rows):
        text_rows = _rows_from_text(csv_text)
        if text_rows:
            # Report arrivato come PDF (o testo libero): niente intestazioni CSV, ma le righe
            # di accesso si riconoscono da IP + data. Meglio uno storico approssimato che nulla.
            rows, warnings = text_rows, ["Accessi estratti dal testo del report (non era un CSV): verificare a campione"]
    result["parse_warnings"].extend(warnings)
    users = set()
    source_ips = set()
    by_pair = defaultdict(int)
    required_groups = [("user", "username", "account"), ("source_ip", "ip", "src_ip", "client_ip"), ("login_time", "login", "start_time", "timestamp")]
    headers = {str(key or "").strip().lower().replace(" ", "_") for key in (rows[0].keys() if rows else []) if key is not None}
    for group in required_groups:
        if rows and not any(name in headers for name in group):
            result["parse_warnings"].append(f"CSV missing expected column: {group[0]}")
    for row in rows:
        normalized = normalize_csv_row(row)
        user = _first(normalized, "user", "username", "account")
        source_ip = _first(normalized, "source_ip", "ip", "src_ip", "client_ip")
        login_time = _first(normalized, "login_time", "login", "start_time", "timestamp")
        logout_time = _first(normalized, "logout_time", "logout", "end_time")
        duration = _first(normalized, "duration", "session_duration")
        method = _first(normalized, "method", "auth_method", "connection_type", "type", "auth_type", "connection")
        reason = _first(normalized, "reason", "message", "description")
        kind = classify_kind(method, reason)
        record = {
            "vendor": "watchguard",
            "action": action,
            "user": user,
            "source_ip": source_ip,
            "login_time": login_time,
            "logout_time": logout_time,
            "duration": duration,
            "duration_seconds": parse_duration_seconds(duration),
            "quota": _first(normalized, "quota"),
            "method": method,
            "reason": reason[:300],
            "kind": kind,
            "firebox_name": result["firebox_name"],
            "dedup_key": stable_hash("watchguard", "vpn_auth", action, user, source_ip, login_time, logout_time, duration),
        }
        result["records"].append(record)
        if kind == KIND_VPN:
            if user:
                users.add(user)
            if source_ip:
                source_ips.add(source_ip)
            by_pair[(user, source_ip)] += 1
    result["metrics"]["watchguard_sslvpn_unique_users"] = len(users)
    result["metrics"]["watchguard_sslvpn_unique_source_ips"] = len(source_ips)
    result["metrics"]["watchguard_sslvpn_user_ip_pairs"] = len(by_pair)
    dated = next((r for r in result["records"] if parse_datetime(r.get("login_time")) or parse_datetime(r.get("logout_time"))), None)
    if dated:
        moment = parse_datetime(dated.get("login_time")) or parse_datetime(dated.get("logout_time"))
        result["report_date"] = moment.date().isoformat()
    return result


def _finalize_auth_result(result, csv_text):
    kinds = Counter(record["kind"] for record in result["records"])
    result["raw_summary"] = (
        f"{result['report_type']}: {len(result['records'])} righe "
        f"({', '.join(f'{count} {kind}' for kind, count in kinds.most_common())}), "
        f"{len(result['alerts_candidates'])} alert candidates"
    )
    result["metrics"]["top_users"] = top_counter(Counter(record["user"] for record in result["records"] if record["user"]))
    result["metrics"]["top_source_ips"] = top_counter(Counter(record["source_ip"] for record in result["records"] if record["source_ip"]))
    return finalize_result(result, csv_text)


_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DATETIME = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?|\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}(?::\d{2})?")
_DURATION = re.compile(r"\b\d{1,4}:\d{2}:\d{2}\b")
_NOISE_TOKENS = {"allowed", "denied", "ssl", "vpn", "sslvpn", "mobile", "ipsec", "pptp", "l2tp", "-", "n/a"}


def _has_access_columns(rows):
    return any(
        normalize_csv_row(row).get(name)
        for row in rows[:5]
        for name in ("source_ip", "ip", "src_ip", "client_ip")
    )


def _rows_from_text(text):
    """Righe di accesso da testo libero: una riga con un IPv4 e almeno una data e' un accesso."""
    rows = []
    for line in str(text or "").splitlines():
        ip = _IPV4.search(line)
        stamps = _DATETIME.findall(line)
        if not ip or not stamps:
            continue
        rest = _DATETIME.sub(" ", line.replace(ip.group(0), " "))
        duration = _DURATION.search(rest)
        if duration:
            rest = rest.replace(duration.group(0), " ")
        user = next(
            (tok for tok in rest.split() if any(ch.isalpha() for ch in tok) and tok.lower() not in _NOISE_TOKENS),
            "",
        )
        low = line.lower()
        rows.append({
            "method": "SSLVPN" if ("vpn" in low or "ssl" in low) else ("Firewall" if "firewall" in low else ""),
            "user": user,
            "source_ip": ip.group(0),
            "login_time": stamps[0],
            "logout_time": stamps[1] if len(stamps) > 1 else "",
            "duration": duration.group(0) if duration else "",
        })
    return rows


def _first(row, *names):
    for name in names:
        if row.get(name):
            return row[name]
    return ""
