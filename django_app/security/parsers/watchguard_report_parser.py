from .base import BaseParser, ParsedRecord, ParsedReport
from .registry import parser_registry
from .watchguard import (
    parse_watchguard_dimension_executive_summary,
    parse_watchguard_epdr_executive_report,
    parse_watchguard_firebox_authentication_allowed_csv,
    parse_watchguard_firebox_authentication_denied_csv,
    parse_watchguard_interface_summary,
    parse_watchguard_sdwan_status,
    parse_watchguard_threatsync_incident_list,
    parse_watchguard_threatsync_summary,
    parse_watchguard_zero_day_apt_summary,
)


class WatchGuardReportParser(BaseParser):
    name = "watchguard_report_parser"

    def can_parse(self, item) -> bool:
        haystack = _item_haystack(item)
        return any(token in haystack for token in ["watchguard", "firebox", "threatsync", "epdr", "dimension", "sd-wan", "sdwan", "zero-day", "zero_day", "authentication"])

    def parse(self, item) -> ParsedReport:
        source_name = getattr(item, "original_name", "") or getattr(item, "subject", "")
        content = getattr(item, "content", "") or getattr(item, "body", "")
        result = _parse_watchguard_payload(source_name, content, getattr(item, "received_at", None))
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


def _parse_watchguard_payload(source_name, content, received_at):
    haystack = f"{source_name}\n{content}".lower()
    kwargs = {"source_name": source_name, "received_at": received_at}
    if "authentication" in haystack and "allowed" in haystack:
        return parse_watchguard_firebox_authentication_allowed_csv(content, **kwargs)
    if "authentication" in haystack and "denied" in haystack:
        return parse_watchguard_firebox_authentication_denied_csv(content, **kwargs)
    if "zero" in haystack and "apt" in haystack:
        return parse_watchguard_zero_day_apt_summary(content, **kwargs)
    if "sd-wan" in haystack or "sdwan" in haystack:
        return parse_watchguard_sdwan_status(content, **kwargs)
    if "interface" in haystack:
        return parse_watchguard_interface_summary(content, **kwargs)
    if "threatsync" in haystack and ("," in content.splitlines()[0] if content.splitlines() else False):
        return parse_watchguard_threatsync_incident_list(content, **kwargs)
    if "threatsync" in haystack:
        return parse_watchguard_threatsync_summary(content, **kwargs)
    if "epdr" in haystack:
        return parse_watchguard_epdr_executive_report(content, **kwargs)
    if "dimension" in haystack or "executive summary" in haystack or "dashboard" in haystack or "botnet detection" in haystack:
        return parse_watchguard_dimension_executive_summary(content, **kwargs)
    result = parse_watchguard_dimension_executive_summary(content, **kwargs)
    result["parse_warnings"].append("WatchGuard source recognized, but report subtype was inferred as Dimension summary")
    return result


def _item_haystack(item):
    parts = [
        getattr(item, "original_name", ""),
        getattr(item, "subject", ""),
        getattr(getattr(item, "source", None), "name", ""),
        getattr(getattr(item, "source", None), "vendor", ""),
        getattr(item, "content", "")[:1000],
        getattr(item, "body", "")[:1000],
    ]
    return "\n".join(str(part or "").lower() for part in parts)


parser_registry.register(WatchGuardReportParser())
