from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedRecord:
    record_type: str
    payload: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass
class ParsedReport:
    report_type: str
    title: str
    parser_name: str
    records: list[ParsedRecord]
    metrics: dict[str, float] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)


class BaseParser:
    name = "base"
    supported_source_types: tuple[str, ...] = ()

    def can_parse(self, item) -> bool:
        raise NotImplementedError

    def parse(self, item) -> ParsedReport:
        raise NotImplementedError
