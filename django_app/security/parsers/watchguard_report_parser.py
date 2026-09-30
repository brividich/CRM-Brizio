from .base import BaseParser, ParsedRecord, ParsedReport
from .registry import parser_registry
from .watchguard import (
    parse_watchguard_dimension_executive_summary,
    parse_watchguard_epdr_executive_report,
    parse_watchguard_epdr_threat_mail,
    parse_watchguard_executive_dashboard,
    parse_watchguard_firebox_authentication_allowed_csv,
    parse_watchguard_firebox_authentication_denied_csv,
    parse_watchguard_interface_summary_pdf,
    parse_watchguard_sdwan_status_pdf,
    parse_watchguard_threatsync_incident_list,
    parse_watchguard_threatsync_summary,
    parse_watchguard_zero_day_apt_summary,
)
from .watchguard import routing

_VPN_REPORT_TYPES = {"watchguard_firebox_authentication_allowed", "watchguard_firebox_authentication_denied"}

_HANDLERS = {
    routing.AUTH_ALLOWED: parse_watchguard_firebox_authentication_allowed_csv,
    routing.AUTH_DENIED: parse_watchguard_firebox_authentication_denied_csv,
    routing.EXECUTIVE_SUMMARY: parse_watchguard_dimension_executive_summary,
    routing.EXECUTIVE_DASHBOARD: parse_watchguard_executive_dashboard,
    routing.INTERFACE_SUMMARY: parse_watchguard_interface_summary_pdf,
    routing.SDWAN: parse_watchguard_sdwan_status_pdf,
    routing.ZERO_DAY: parse_watchguard_zero_day_apt_summary,
    routing.EPDR_REPORT: parse_watchguard_epdr_executive_report,
    routing.EPDR_THREAT_MAIL: parse_watchguard_epdr_threat_mail,
    routing.THREATSYNC_LIST: parse_watchguard_threatsync_incident_list,
    routing.THREATSYNC_SUMMARY: parse_watchguard_threatsync_summary,
    routing.DIMENSION: parse_watchguard_dimension_executive_summary,
}


class WatchGuardReportParser(BaseParser):
    name = "watchguard_report_parser"

    def can_parse(self, item) -> bool:
        return self._kind(item) is not None or routing.looks_like_watchguard(_provenance(item))

    def parse(self, item) -> ParsedReport:
        source_name = getattr(item, "original_name", "") or getattr(item, "subject", "")
        content = getattr(item, "content", "") or getattr(item, "body", "")
        kind = self._kind(item)
        result = _parse_payload(kind, source_name, content, getattr(item, "received_at", None))
        records = [
            ParsedRecord(
                record_type="watchguard_report_summary",
                payload={
                    "vendor": "watchguard",
                    "report_type": result["report_type"],
                    "dedup_key": result["dedup_key"],
                    "raw_summary": result["raw_summary"],
                    "parse_warnings": result["parse_warnings"],
                },
            )
        ]
        if result["report_type"] in _VPN_REPORT_TYPES:
            # Le righe di accesso vanno allo storico (SecurityVpnAccess), non a eventi generici.
            for row in result["records"]:
                records.append(ParsedRecord(record_type="vpn_access", payload=row))
        for candidate in result["alerts_candidates"]:
            records.append(
                ParsedRecord(
                    record_type="watchguard_alert_candidate",
                    payload={"vendor": "watchguard", "alert_candidate": True, **candidate},
                )
            )
        title = source_name or result["report_type"]
        return ParsedReport(
            report_type=result["report_type"],
            title=title,
            parser_name=self.name,
            records=records,
            metrics=result["metrics"],
            payload=result,
        )

    @staticmethod
    def _kind(item):
        filename = getattr(item, "original_name", "") or ""
        content = getattr(item, "content", "") or getattr(item, "body", "") or ""
        return routing.detect_report(filename, content, getattr(item, "subject", ""))


def _parse_payload(kind, source_name, content, received_at):
    kwargs = {"source_name": source_name, "received_at": received_at}
    handler = _HANDLERS.get(kind)
    if handler:
        return handler(content, **kwargs)
    result = parse_watchguard_dimension_executive_summary(content, **kwargs)
    result["parse_warnings"].append("Report WatchGuard non riconosciuto dal titolo: trattato come riepilogo generico, verificare")
    return result


def _provenance(item):
    """Solo mittente, oggetto, nome file e sorgente: il corpo della mail non prova nulla."""
    source = getattr(item, "source", None)
    return [
        getattr(item, "original_name", ""),
        getattr(item, "subject", ""),
        getattr(item, "sender", ""),
        getattr(source, "name", ""),
        getattr(source, "vendor", ""),
    ]


parser_registry.register(WatchGuardReportParser())
