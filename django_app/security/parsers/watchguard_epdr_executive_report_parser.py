from .base import BaseParser, ParsedReport
from .registry import parser_registry


class WatchGuardEpdrExecutiveReportParser(BaseParser):
    name = "watchguard_epdr_executive_report_parser"

    def can_parse(self, item) -> bool:
        name = getattr(item, "original_name", "").lower()
        return "epdr" in name and name.endswith(".pdf")

    def parse(self, item) -> ParsedReport:
        return ParsedReport(
            report_type="watchguard_epdr_executive_report",
            title=item.original_name,
            parser_name=self.name,
            records=[],
            metrics={"threatsync_low_closed": 0},
            payload={"stub": True, "note": "PDF extraction will be implemented after MVP ingestion is validated."},
        )


parser_registry.register(WatchGuardEpdrExecutiveReportParser())
