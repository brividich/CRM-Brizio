import csv
from io import StringIO

from .base import BaseParser, ParsedRecord, ParsedReport
from .registry import parser_registry


class WatchGuardFireboxAuthenticationAllowedCsvParser(BaseParser):
    name = "watchguard_firebox_authentication_allowed_csv_parser"

    def can_parse(self, item) -> bool:
        return getattr(item, "original_name", "").lower().endswith(".csv") and "allowed" in getattr(item, "original_name", "").lower()

    def parse(self, item) -> ParsedReport:
        records = []
        for row in csv.DictReader(StringIO(item.content)):
            records.append(
                ParsedRecord(
                    record_type="vpn_auth_allowed",
                    payload={"user": row.get("user"), "ip": row.get("ip"), "action": "allowed", "raw": row},
                    metrics={"vpn_auth_allowed": 1},
                )
            )
        return ParsedReport("watchguard_firebox_auth_allowed", item.original_name, self.name, records, {"vpn_auth_allowed": len(records)})


parser_registry.register(WatchGuardFireboxAuthenticationAllowedCsvParser())
